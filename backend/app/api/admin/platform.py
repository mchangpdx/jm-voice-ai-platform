"""Platform Admin API — read-only views across all agencies + stores.
(플랫폼 관리자 API — 모든 에이전시·매장에 대한 읽기 전용 뷰)

Phase 1: GET endpoints only. Mutations (POST/PATCH/DELETE) land in Phase 2.

Authorization model:
  JWT → decode email claim
    → email == ADMIN_EMAIL  → allow (service_role for RLS bypass)
    → otherwise              → 403

NOTE: Until Supabase app_metadata.role = 'admin' is provisioned, this uses an
email-based shortcut. Replace with metadata check in Phase 2.
(현재는 email 매칭으로 admin 판별 — Phase 2에서 app_metadata.role로 교체 예정)
"""
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from jose import JWTError, jwt

from app.core.audit import audit_log
from app.core.auth import _get_public_key
from app.core.config import settings

router = APIRouter(prefix="/api/admin", tags=["Admin Platform"])

ADMIN_EMAIL = "admin@test.com"

_SUPABASE_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


# ── Auth dependency ──────────────────────────────────────────────────────────


async def _decode_admin_jwt(authorization: str | None) -> dict[str, Any]:
    """Validate JWT, require admin, return decoded payload.
    (JWT 검증 + admin 권한 체크, payload 반환)
    """
    if authorization is None:
        raise HTTPException(401, "Authorization header is missing")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Authorization header must be 'Bearer <token>'")

    raw = parts[1]
    try:
        header = jwt.get_unverified_header(raw)
    except JWTError:
        raise HTTPException(401, "Invalid token")

    alg = header.get("alg", "ES256")
    try:
        if alg == "HS256":
            payload = jwt.decode(
                raw, settings.supabase_service_role_key, algorithms=["HS256"]
            )
        else:
            kid = header.get("kid", "")
            key = await _get_public_key(kid)
            if not key:
                raise HTTPException(401, "Unknown token signing key")
            payload = jwt.decode(
                raw, key, algorithms=[alg], options={"verify_aud": False}
            )
    except JWTError:
        raise HTTPException(401, "Invalid token")

    email = (payload.get("email") or "").lower()
    if email != ADMIN_EMAIL:
        raise HTTPException(403, "Admin role required")
    if not payload.get("sub"):
        raise HTTPException(401, "Token missing 'sub' claim")
    return payload


async def require_admin(authorization: str = Header(None)) -> str:
    """Returns user_id only — for read-only endpoints that don't audit-log.
    (감사 로그가 필요 없는 read endpoint용 — user_id만 반환)
    """
    payload = await _decode_admin_jwt(authorization)
    return payload["sub"]


async def admin_context(
    request: Request,
    authorization: str = Header(None),
) -> dict[str, str | None]:
    """Returns {user_id, email, ip, user_agent} for mutations that audit-log.
    (감사 로그 기록용 — user_id/email/ip/UA 포함)
    """
    payload = await _decode_admin_jwt(authorization)
    return {
        "user_id":    payload["sub"],
        "email":      (payload.get("email") or "").lower(),
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _fetch_one(
    c: httpx.AsyncClient, table: str, row_id: str, select: str = "*"
) -> dict[str, Any] | None:
    r = await c.get(
        f"{_REST}/{table}",
        headers=_SUPABASE_HEADERS,
        params={"id": f"eq.{row_id}", "select": select, "limit": "1"},
    )
    rows = r.json() if isinstance(r.json(), list) else []
    return rows[0] if rows else None


async def _resolve_user_by_email(
    c: httpx.AsyncClient, email: str
) -> dict[str, Any] | None:
    """Lookup auth.users by email. Returns user dict or None.
    (email로 auth.users 조회)
    """
    # Supabase admin users list — filter by email is not supported, so paginate.
    # For typical admin scale (< 1000 users) this is fine; switch to SQL view later.
    target = email.lower()
    page = 1
    while True:
        r = await c.get(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=_SUPABASE_HEADERS,
            params={"page": str(page), "per_page": "200"},
        )
        users = r.json().get("users", []) if r.status_code == 200 else []
        for u in users:
            if (u.get("email") or "").lower() == target:
                return u
        if len(users) < 200:
            return None
        page += 1
        if page > 20:  # hard cap — 4000 users
            return None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/agencies")
async def list_agencies(_: str = Depends(require_admin)) -> list[dict[str, Any]]:
    """List every agency with owner email + store count.
    (전체 에이전시 + 오너 email + 산하 매장 수 반환)
    """
    async with httpx.AsyncClient(timeout=15) as c:
        ar = await c.get(
            f"{_REST}/agencies",
            headers=_SUPABASE_HEADERS,
            params={"select": "id,name,owner_id,created_at"},
        )
        agencies = ar.json() if isinstance(ar.json(), list) else []

        sr = await c.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"select": "id,agency_id"},
        )
        stores = sr.json() if isinstance(sr.json(), list) else []
        counts: dict[str, int] = {}
        for s in stores:
            aid = s.get("agency_id")
            if aid:
                counts[aid] = counts.get(aid, 0) + 1

        owner_ids = [a["owner_id"] for a in agencies if a.get("owner_id")]
        emails: dict[str, str] = {}
        for oid in owner_ids:
            ur = await c.get(
                f"{settings.supabase_url}/auth/v1/admin/users/{oid}",
                headers=_SUPABASE_HEADERS,
            )
            if ur.status_code == 200:
                emails[oid] = ur.json().get("email", "")

    return [
        {
            "id": a["id"],
            "name": a["name"],
            "owner_id": a["owner_id"],
            "owner_email": emails.get(a["owner_id"], ""),
            "store_count": counts.get(a["id"], 0),
            "created_at": a.get("created_at"),
        }
        for a in agencies
    ]


@router.get("/stores")
async def list_stores(
    agency_id: str | None = Query(None),
    _: str = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List every store across all agencies (optional ?agency_id=… filter).
    (전체 매장 cross-agency 조회, ?agency_id= 필터 옵션)
    """
    params: dict[str, Any] = {
        "select": "id,name,industry,agency_id,created_at,phone,is_active,pos_provider"
    }
    if agency_id:
        params["agency_id"] = f"eq.{agency_id}"

    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_REST}/stores", headers=_SUPABASE_HEADERS, params=params)
        stores = r.json() if isinstance(r.json(), list) else []

        agency_names: dict[str, str] = {}
        if stores:
            ar = await c.get(
                f"{_REST}/agencies",
                headers=_SUPABASE_HEADERS,
                params={"select": "id,name"},
            )
            for a in ar.json() if isinstance(ar.json(), list) else []:
                agency_names[a["id"]] = a["name"]

    return [
        {
            **s,
            "agency_name": agency_names.get(s.get("agency_id"), ""),
        }
        for s in stores
    ]


@router.get("/overview")
async def admin_overview(_: str = Depends(require_admin)) -> dict[str, Any]:
    """Platform-wide totals — agency count, store count, total calls (30d).
    (플랫폼 전체 집계 — 에이전시·매장 수, 30일 총 통화수)
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    async with httpx.AsyncClient(timeout=15) as c:
        ar = await c.get(
            f"{_REST}/agencies", headers=_SUPABASE_HEADERS, params={"select": "id"}
        )
        sr = await c.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"select": "id,industry"},
        )
        # Total calls in last 30d — exact count via prefer header
        cr = await c.get(
            f"{_REST}/call_logs",
            headers={**_SUPABASE_HEADERS, "Prefer": "count=exact"},
            params={"select": "call_id", "start_time": f"gte.{since}", "limit": "1"},
        )
        call_count = 0
        cr_range = cr.headers.get("content-range", "")
        if "/" in cr_range:
            try:
                call_count = int(cr_range.split("/")[-1])
            except ValueError:
                pass

    agencies = ar.json() if isinstance(ar.json(), list) else []
    stores = sr.json() if isinstance(sr.json(), list) else []
    by_vertical: dict[str, int] = {}
    for s in stores:
        v = s.get("industry") or "unknown"
        by_vertical[v] = by_vertical.get(v, 0) + 1

    return {
        "agency_count": len(agencies),
        "store_count": len(stores),
        "calls_30d": call_count,
        "stores_by_vertical": by_vertical,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2-A: Admin CRUD (mutations) + Phase 2-D: Audit log hooks
# ─────────────────────────────────────────────────────────────────────────────


@router.patch("/agencies/{agency_id}")
async def update_agency(
    agency_id: str,
    body: dict[str, Any] = Body(...),
    ctx: dict[str, Any] = Depends(admin_context),
) -> dict[str, Any]:
    """Update agency name and/or owner (by email).
    (에이전시 name / owner 변경)
    """
    update: dict[str, Any] = {}
    new_owner_email: str | None = None

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "name must be non-empty")
        update["name"] = name

    if "owner_email" in body:
        new_owner_email = (body.get("owner_email") or "").strip().lower()
        if not new_owner_email:
            raise HTTPException(422, "owner_email must be non-empty")

    if not update and new_owner_email is None:
        raise HTTPException(400, "No mutable fields provided")

    async with httpx.AsyncClient(timeout=15) as c:
        before = await _fetch_one(c, "agencies", agency_id, "id,name,owner_id,is_active")
        if not before:
            raise HTTPException(404, "Agency not found")

        if new_owner_email:
            user = await _resolve_user_by_email(c, new_owner_email)
            if not user:
                raise HTTPException(
                    422, f"User '{new_owner_email}' not found in auth.users"
                )
            update["owner_id"] = user["id"]

        r = await c.patch(
            f"{_REST}/agencies",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{agency_id}"},
            json=update,
        )
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Supabase: {r.text[:200]}")
        rows = r.json() if isinstance(r.json(), list) else []
        after = rows[0] if rows else None

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="agency.update",
        target_type="agency",
        target_id=agency_id,
        before=before,
        after=after,
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return after or {}


@router.post("/agencies")
async def create_agency(
    body: dict[str, Any] = Body(...),
    ctx: dict[str, Any] = Depends(admin_context),
) -> dict[str, Any]:
    """Create a new agency. Body: {name, owner_email}.
    (신규 에이전시 생성 — owner_email은 auth.users에 존재해야 함)
    """
    name = (body.get("name") or "").strip()
    owner_email = (body.get("owner_email") or "").strip().lower()
    if not name or not owner_email:
        raise HTTPException(422, "name and owner_email are required")

    async with httpx.AsyncClient(timeout=15) as c:
        # Resolve owner
        user = await _resolve_user_by_email(c, owner_email)
        if not user:
            raise HTTPException(422, f"User '{owner_email}' not found in auth.users")

        # Reject duplicate name (case-insensitive on db side is preferred; for now exact match)
        dup = await c.get(
            f"{_REST}/agencies",
            headers=_SUPABASE_HEADERS,
            params={"name": f"eq.{name}", "select": "id", "limit": "1"},
        )
        if dup.status_code == 200 and dup.json():
            raise HTTPException(409, f"Agency '{name}' already exists")

        r = await c.post(
            f"{_REST}/agencies",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            json={"name": name, "owner_id": user["id"], "is_active": True},
        )
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Supabase: {r.text[:200]}")
        rows = r.json() if isinstance(r.json(), list) else []
        after = rows[0] if rows else None

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="agency.create",
        target_type="agency",
        target_id=(after or {}).get("id"),
        before=None,
        after=after,
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return after or {}


@router.delete("/agencies/{agency_id}")
async def delete_agency(
    agency_id: str,
    ctx: dict[str, Any] = Depends(admin_context),
) -> dict[str, Any]:
    """Soft delete an agency (is_active=false). Rejects if any active stores remain.
    (에이전시 soft delete — 활성 매장이 있으면 409)
    """
    async with httpx.AsyncClient(timeout=15) as c:
        before = await _fetch_one(c, "agencies", agency_id, "id,name,is_active")
        if not before:
            raise HTTPException(404, "Agency not found")

        # Reject if any active stores under this agency
        sr = await c.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "agency_id":  f"eq.{agency_id}",
                "is_active":  "eq.true",
                "select":     "id",
                "limit":      "1",
            },
        )
        active_stores = sr.json() if isinstance(sr.json(), list) else []
        if active_stores:
            raise HTTPException(
                409,
                "Agency has active stores. Transfer or disable them first.",
            )

        r = await c.patch(
            f"{_REST}/agencies",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{agency_id}"},
            json={"is_active": False},
        )
        rows = r.json() if isinstance(r.json(), list) else []
        after = rows[0] if rows else None

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="agency.delete",
        target_type="agency",
        target_id=agency_id,
        before=before,
        after=after,
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return {"ok": True, "agency_id": agency_id}


@router.patch("/stores/{store_id}")
async def update_store(
    store_id: str,
    body: dict[str, Any] = Body(...),
    ctx: dict[str, Any] = Depends(admin_context),
) -> dict[str, Any]:
    """Update store name and/or is_active toggle.
    (매장 name / is_active 변경)
    """
    update: dict[str, Any] = {}
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "name must be non-empty")
        update["name"] = name
    if "is_active" in body:
        update["is_active"] = bool(body["is_active"])

    if not update:
        raise HTTPException(400, "No mutable fields provided")

    async with httpx.AsyncClient(timeout=15) as c:
        before = await _fetch_one(c, "stores", store_id, "id,name,is_active,agency_id")
        if not before:
            raise HTTPException(404, "Store not found")

        r = await c.patch(
            f"{_REST}/stores",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{store_id}"},
            json=update,
        )
        rows = r.json() if isinstance(r.json(), list) else []
        after = rows[0] if rows else None

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="store.update",
        target_type="store",
        target_id=store_id,
        before=before,
        after=after,
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return after or {}


@router.delete("/stores/{store_id}")
async def delete_store(
    store_id: str,
    ctx: dict[str, Any] = Depends(admin_context),
) -> dict[str, Any]:
    """Soft delete a store (is_active=false).
    (매장 soft delete)
    """
    async with httpx.AsyncClient(timeout=15) as c:
        before = await _fetch_one(c, "stores", store_id, "id,name,is_active,agency_id")
        if not before:
            raise HTTPException(404, "Store not found")

        r = await c.patch(
            f"{_REST}/stores",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{store_id}"},
            json={"is_active": False},
        )
        rows = r.json() if isinstance(r.json(), list) else []
        after = rows[0] if rows else None

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="store.delete",
        target_type="store",
        target_id=store_id,
        before=before,
        after=after,
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return {"ok": True, "store_id": store_id}


@router.post("/stores/{store_id}/transfer")
async def transfer_store(
    store_id: str,
    body: dict[str, Any] = Body(...),
    ctx: dict[str, Any] = Depends(admin_context),
) -> dict[str, Any]:
    """Reassign a store to a different agency.
    (매장을 다른 에이전시로 이관)
    """
    new_agency_id = (body.get("new_agency_id") or "").strip()
    if not new_agency_id:
        raise HTTPException(422, "new_agency_id is required")

    async with httpx.AsyncClient(timeout=15) as c:
        before = await _fetch_one(
            c, "stores", store_id, "id,name,agency_id,is_active"
        )
        if not before:
            raise HTTPException(404, "Store not found")
        if before.get("agency_id") == new_agency_id:
            raise HTTPException(400, "Store is already in the target agency")

        target_agency = await _fetch_one(
            c, "agencies", new_agency_id, "id,name,is_active"
        )
        if not target_agency:
            raise HTTPException(422, "Target agency not found")
        if target_agency.get("is_active") is False:
            raise HTTPException(422, "Target agency is inactive")

        r = await c.patch(
            f"{_REST}/stores",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{store_id}"},
            json={"agency_id": new_agency_id},
        )
        rows = r.json() if isinstance(r.json(), list) else []
        after = rows[0] if rows else None

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="store.transfer",
        target_type="store",
        target_id=store_id,
        before={"agency_id": before.get("agency_id")},
        after={"agency_id": new_agency_id},
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return after or {}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2-D: Audit log GET
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/audit-logs")
async def list_audit_logs(
    actor:       str | None = Query(None, description="filter by actor_user_id"),
    action:      str | None = Query(None, description="filter by action prefix, e.g. 'agency.'"),
    target_type: str | None = Query(None, description="'agency'|'store'|'user'"),
    target_id:   str | None = Query(None),
    since:       str | None = Query(None, description="ISO 8601 timestamp"),
    limit:       int = Query(50, ge=1, le=500),
    offset:      int = Query(0, ge=0),
    _:           str = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Read audit log entries with filters + pagination.
    (감사 로그 필터+페이지네이션 조회)
    """
    params: dict[str, Any] = {
        "select":   "id,actor_user_id,actor_email,action,target_type,target_id,before,after,ip_address,created_at",
        "order":    "created_at.desc",
        "limit":    str(limit),
        "offset":   str(offset),
    }
    if actor:
        params["actor_user_id"] = f"eq.{actor}"
    if action:
        params["action"] = f"like.{action}*"
    if target_type:
        params["target_type"] = f"eq.{target_type}"
    if target_id:
        params["target_id"] = f"eq.{target_id}"
    if since:
        params["created_at"] = f"gte.{since}"

    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_REST}/audit_logs", headers=_SUPABASE_HEADERS, params=params)
        if r.status_code == 404 or (
            r.status_code == 400 and "does not exist" in r.text.lower()
        ):
            # Table not provisioned yet — return empty rather than crash.
            return []
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Supabase: {r.text[:200]}")
        return r.json() if isinstance(r.json(), list) else []
