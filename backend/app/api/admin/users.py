"""Phase 2-B — Admin Users & Roles management.
(플랫폼 관리자용 사용자 + 역할 관리)

Endpoints:
    GET    /api/admin/users                 — list users + role + ownership + last_sign_in
    PATCH  /api/admin/users/{user_id}/role  — change role (blocks last-admin demotion)
    DELETE /api/admin/users/{user_id}       — disable user (blocks if owns active resource)

All mutations write to `audit_logs` via app.core.audit.audit_log.
Authorization piggybacks on platform.py's `admin_context` dependency, which
already enforces `app_metadata.role == 'admin'` (Phase 2-E).
"""
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.admin.platform import admin_context
from app.core.audit import audit_log
from app.core.config import settings

router = APIRouter(prefix="/api/admin/users", tags=["Admin Users"])

_VALID_ROLES = {"STORE", "AGENCY", "ADMIN"}

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"
_AUTH_ADMIN = f"{settings.supabase_url}/auth/v1/admin/users"


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _paginate_users(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Walk Supabase admin users API until exhausted. Caps at 20 pages × 200 = 4000.
    (Supabase admin users 페이지네이션 — 최대 4000명)
    """
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        r = await client.get(
            _AUTH_ADMIN,
            headers=_SUPABASE_HEADERS,
            params={"page": str(page), "per_page": "200"},
        )
        if r.status_code != 200:
            break
        batch = r.json().get("users", []) if isinstance(r.json(), dict) else []
        out.extend(batch)
        if len(batch) < 200:
            break
        page += 1
        if page > 20:
            break
    return out


async def _count_other_admins(
    client: httpx.AsyncClient, exclude_user_id: str
) -> int:
    """Count users with app_metadata.role=='admin', excluding one user_id.
    (지정된 user 제외, app_metadata.role=='admin'인 사용자 수)
    """
    users = await _paginate_users(client)
    return sum(
        1
        for u in users
        if u.get("id") != exclude_user_id
        and ((u.get("app_metadata") or {}).get("role") or "").lower() == "admin"
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("")
async def list_users(
    role:   str | None = Query(None, description="filter by role: STORE|AGENCY|ADMIN"),
    search: str | None = Query(None, description="case-insensitive email substring"),
    limit:  int  = Query(100, ge=1, le=500),
    offset: int  = Query(0, ge=0),
    _:      dict = Depends(admin_context),
) -> dict[str, Any]:
    """List Supabase auth users enriched with role + owned resources.

    Returns {items, total} where items are paginated post-filter and total is
    the full match count. Role comes from app_metadata.role (lowercase 'admin'
    surfaces as 'ADMIN' for the UI; missing role defaults to 'STORE').
    (Supabase 사용자 + role + 소유 자원 결합)
    """
    role_filter = (role or "").upper().strip() or None
    if role_filter and role_filter not in _VALID_ROLES:
        raise HTTPException(422, f"role must be one of {sorted(_VALID_ROLES)}")
    search_lower = (search or "").strip().lower() or None

    async with httpx.AsyncClient(timeout=20) as c:
        users = await _paginate_users(c)

        ar = await c.get(
            f"{_REST}/agencies",
            headers=_SUPABASE_HEADERS,
            params={"select": "id,name,owner_id,is_active"},
        )
        agencies = ar.json() if isinstance(ar.json(), list) else []

        sr = await c.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"select": "id,name,owner_id,is_active"},
        )
        stores = sr.json() if isinstance(sr.json(), list) else []

    # owner_id → owned resources
    agencies_by_owner: dict[str, list[dict[str, Any]]] = {}
    for a in agencies:
        if a.get("owner_id"):
            agencies_by_owner.setdefault(a["owner_id"], []).append(a)
    stores_by_owner: dict[str, list[dict[str, Any]]] = {}
    for s in stores:
        if s.get("owner_id"):
            stores_by_owner.setdefault(s["owner_id"], []).append(s)

    def _derive_role(u: dict[str, Any]) -> str:
        meta_role = ((u.get("app_metadata") or {}).get("role") or "").lower()
        if meta_role == "admin":
            return "ADMIN"
        if agencies_by_owner.get(u.get("id", "")):
            return "AGENCY"
        return "STORE"

    enriched: list[dict[str, Any]] = []
    for u in users:
        uid = u.get("id") or ""
        derived = _derive_role(u)
        if role_filter and derived != role_filter:
            continue
        email = (u.get("email") or "").lower()
        if search_lower and search_lower not in email:
            continue
        enriched.append({
            "id":              uid,
            "email":           u.get("email"),
            "role":            derived,
            "last_sign_in_at": u.get("last_sign_in_at"),
            "created_at":      u.get("created_at"),
            "is_disabled":     bool(u.get("banned_until")),
            "owned_agencies":  [
                {"id": a["id"], "name": a["name"], "is_active": a.get("is_active", True)}
                for a in agencies_by_owner.get(uid, [])
            ],
            "owned_stores":    [
                {"id": s["id"], "name": s["name"], "is_active": s.get("is_active", True)}
                for s in stores_by_owner.get(uid, [])
            ],
        })

    total = len(enriched)
    page  = enriched[offset: offset + limit]
    return {"items": page, "total": total, "limit": limit, "offset": offset}


@router.patch("/{user_id}/role")
async def set_user_role(
    user_id: str,
    body: dict[str, Any] = Body(...),
    ctx:  dict = Depends(admin_context),
) -> dict[str, Any]:
    """Set app_metadata.role on a Supabase user. Blocks demotion of the last ADMIN.
    (사용자 역할 변경 — 마지막 ADMIN 강등 차단)
    """
    new_role = (body.get("role") or "").upper().strip()
    if new_role not in _VALID_ROLES:
        raise HTTPException(422, f"role must be one of {sorted(_VALID_ROLES)}")

    async with httpx.AsyncClient(timeout=15) as c:
        # Look up the target user first — also gives us the before snapshot
        ur = await c.get(f"{_AUTH_ADMIN}/{user_id}", headers=_SUPABASE_HEADERS)
        if ur.status_code != 200:
            raise HTTPException(404, "User not found")
        target = ur.json()
        before_role = ((target.get("app_metadata") or {}).get("role") or "").lower()

        # Last-admin guard — only when DEMOTING (admin → non-admin)
        if before_role == "admin" and new_role != "ADMIN":
            others = await _count_other_admins(c, exclude_user_id=user_id)
            if others == 0:
                raise HTTPException(
                    409, "Cannot demote the last platform admin."
                )

        # Persist: app_metadata.role uses lowercase 'admin'; non-admins clear the claim
        # (관리자 외 역할은 STORE/AGENCY로 store 소유 여부에서 파생 — claim 비움)
        new_meta_role = "admin" if new_role == "ADMIN" else None
        pr = await c.put(
            f"{_AUTH_ADMIN}/{user_id}",
            headers=_SUPABASE_HEADERS,
            json={"app_metadata": {"role": new_meta_role}},
        )
        if pr.status_code >= 300:
            raise HTTPException(pr.status_code, f"Supabase: {pr.text[:200]}")
        after = pr.json()

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="user.role_change",
        target_type="user",
        target_id=user_id,
        before={"role": before_role.upper() or "STORE", "email": target.get("email")},
        after={"role": new_role, "email": after.get("email")},
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return {
        "id":    user_id,
        "email": after.get("email"),
        "role":  new_role,
    }


@router.delete("/{user_id}")
async def disable_user(
    user_id: str,
    ctx: dict = Depends(admin_context),
) -> dict[str, Any]:
    """Disable a user (Supabase ban_duration). Rejects if they own active resources.
    (사용자 비활성화 — 활성 자원 소유자는 409, 먼저 이관 필요)
    """
    if user_id == ctx["user_id"]:
        raise HTTPException(400, "Refusing to disable the currently logged-in admin.")

    async with httpx.AsyncClient(timeout=15) as c:
        ur = await c.get(f"{_AUTH_ADMIN}/{user_id}", headers=_SUPABASE_HEADERS)
        if ur.status_code != 200:
            raise HTTPException(404, "User not found")
        target = ur.json()

        # Block if user still owns any active agency or store
        ar = await c.get(
            f"{_REST}/agencies",
            headers=_SUPABASE_HEADERS,
            params={"owner_id": f"eq.{user_id}", "is_active": "eq.true", "select": "id"},
        )
        active_agencies = ar.json() if isinstance(ar.json(), list) else []
        sr = await c.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"owner_id": f"eq.{user_id}", "is_active": "eq.true", "select": "id"},
        )
        active_stores = sr.json() if isinstance(sr.json(), list) else []
        if active_agencies or active_stores:
            raise HTTPException(
                409,
                "User still owns active agencies or stores. Transfer them first.",
            )

        # Disable via Supabase: ban_duration='876000h' ≈ 100 years.
        # (Supabase admin API: ban_duration 문자열로 ban_until 자동 계산)
        pr = await c.put(
            f"{_AUTH_ADMIN}/{user_id}",
            headers=_SUPABASE_HEADERS,
            json={"ban_duration": "876000h"},
        )
        if pr.status_code >= 300:
            raise HTTPException(pr.status_code, f"Supabase: {pr.text[:200]}")

    await audit_log(
        actor_user_id=ctx["user_id"],
        actor_email=ctx["email"],
        action="user.disable",
        target_type="user",
        target_id=user_id,
        before={"email": target.get("email"), "banned_until": target.get("banned_until")},
        after={"email": target.get("email"), "banned_until": "9999"},
        ip_address=ctx["ip_address"],
        user_agent=ctx["user_agent"],
    )
    return {"ok": True, "user_id": user_id}
