# Reservations API router (예약 관리 API 라우터)
# Supports: list with date/status filter, status update
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/api/store", tags=["Reservations"])

_REST = f"{settings.supabase_url}/rest/v1"
_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}

_VALID_PERIODS  = {"today", "week", "month", "all"}
_VALID_STATUSES = {"pending", "confirmed", "seated", "cancelled", "no_show"}
_DEFAULT_TZ     = "America/Los_Angeles"


def _period_start(period: str, store_tz: str = _DEFAULT_TZ) -> str | None:
    """Return ISO 8601 UTC start for the given period. (기간 시작 UTC 반환)"""
    now = datetime.now(timezone.utc)
    if period == "today":
        tz          = ZoneInfo(store_tz)
        local_today = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start       = local_today.astimezone(timezone.utc)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return None
    return start.strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _resolve_store(client: httpx.AsyncClient, owner_id: str) -> dict:
    resp   = await client.get(
        f"{_REST}/stores",
        headers=_HEADERS,
        params={"owner_id": f"eq.{owner_id}", "select": "id,name"},
    )
    stores = resp.json()
    if not stores:
        raise HTTPException(status_code=404, detail="Store not found")
    return stores[0]


# ── Schemas ───────────────────────────────────────────────────────────────────

class ReservationItem(BaseModel):
    id: int
    call_log_id: Optional[str]
    customer_name: Optional[str]
    customer_phone: Optional[str]
    party_size: int
    reservation_time: str
    status: str
    notes: Optional[str]
    created_at: str


class ReservationsResponse(BaseModel):
    items: list[ReservationItem]
    total: int
    page: int
    pages: int
    limit: int
    total_covers: int          # sum of party_size for displayed items
    status_counts: dict[str, int]  # per-status totals across ALL matching rows


class ReservationStatusUpdate(BaseModel):
    status: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/reservations", response_model=ReservationsResponse)
async def get_reservations(
    period: str = "month",
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    tenant_id: str = Depends(get_tenant_id),
) -> ReservationsResponse:
    """Return paginated reservations with optional period + status filter.
    (기간/상태 필터 지원 예약 목록 반환)
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
        )
    if status and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )

    async with httpx.AsyncClient() as client:
        store    = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "timezone"},
        )
        cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []
        store_tz = (cfg_list[0].get("timezone") if cfg_list else None) or _DEFAULT_TZ

        since    = _period_start(period, store_tz)

        params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select":   "id,call_log_id,customer_name,customer_phone,party_size,reservation_time,status,notes,created_at",
            "order":    "reservation_time.asc",
            "limit":    "2000",
        }
        if since:
            params["reservation_time"] = f"gte.{since}"
        if status:
            params["status"] = f"eq.{status}"

        resp     = await client.get(f"{_REST}/reservations", headers=_HEADERS, params=params)
        all_rows = resp.json() if isinstance(resp.json(), list) else []

    # Build per-status counts across full result set
    status_counts: dict[str, int] = {}
    for row in all_rows:
        s = row.get("status", "pending")
        status_counts[s] = status_counts.get(s, 0) + 1

    total  = len(all_rows)
    pages  = math.ceil(total / limit) if total > 0 else 1
    offset = (page - 1) * limit
    page_rows = all_rows[offset : offset + limit]

    return ReservationsResponse(
        items=[
            ReservationItem(
                id=r["id"],
                call_log_id=r.get("call_log_id"),
                customer_name=r.get("customer_name"),
                customer_phone=r.get("customer_phone"),
                party_size=int(r.get("party_size") or 1),
                reservation_time=r.get("reservation_time", ""),
                status=r.get("status", "pending"),
                notes=r.get("notes"),
                created_at=r.get("created_at", ""),
            )
            for r in page_rows
        ],
        total=total,
        page=page,
        pages=pages,
        limit=limit,
        total_covers=sum(int(r.get("party_size") or 1) for r in page_rows),
        status_counts=status_counts,
    )


@router.patch("/reservations/{reservation_id}", response_model=ReservationItem)
async def update_reservation_status(
    reservation_id: int,
    body: ReservationStatusUpdate,
    tenant_id: str = Depends(get_tenant_id),
) -> ReservationItem:
    """Update reservation status (e.g. pending → confirmed → seated).
    (예약 상태 업데이트: pending → confirmed → seated 등)
    """
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )

    async with httpx.AsyncClient() as client:
        store    = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        resp = await client.patch(
            f"{_REST}/reservations",
            headers={**_HEADERS, "Prefer": "return=representation"},
            params={
                "id":       f"eq.{reservation_id}",
                "store_id": f"eq.{store_id}",
            },
            json={"status": body.status},
        )
        rows = resp.json() if isinstance(resp.json(), list) else []

    if not rows:
        raise HTTPException(status_code=404, detail="Reservation not found")

    r = rows[0]
    return ReservationItem(
        id=r["id"],
        call_log_id=r.get("call_log_id"),
        customer_name=r.get("customer_name"),
        customer_phone=r.get("customer_phone"),
        party_size=int(r.get("party_size") or 1),
        reservation_time=r.get("reservation_time", ""),
        status=r.get("status", "pending"),
        notes=r.get("notes"),
        created_at=r.get("created_at", ""),
    )
