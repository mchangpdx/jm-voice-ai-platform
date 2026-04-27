# Store settings API — hourly wage, timezone, busy schedule, override
# (스토어 설정 API — 시급, 타임존, 바쁜 시간대 스케줄, 긴급 오버라이드)

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import get_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/api/store", tags=["Settings"])

_SUPABASE_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
_REST = f"{settings.supabase_url}/rest/v1"

_DEFAULT_HOURLY_WAGE = 20.00
_DEFAULT_TIMEZONE    = "America/Los_Angeles"


async def _resolve_store(client: httpx.AsyncClient, owner_id: str) -> dict:
    resp = await client.get(
        f"{_REST}/stores",
        headers=_SUPABASE_HEADERS,
        params={"owner_id": f"eq.{owner_id}", "select": "id,name"},
    )
    stores = resp.json()
    if not stores:
        raise HTTPException(status_code=404, detail="Store not found")
    return stores[0]


# ── Schemas ───────────────────────────────────────────────────────────────────

class StoreSettings(BaseModel):
    hourly_wage:      float  = _DEFAULT_HOURLY_WAGE
    timezone:         str    = _DEFAULT_TIMEZONE
    is_override_busy: bool   = False
    override_until:   Optional[str] = None
    busy_schedules:   list["BusySchedule"] = []


class StoreSettingsPatch(BaseModel):
    hourly_wage: Optional[float] = Field(None, gt=0, le=1000)
    timezone:    Optional[str]   = None


class BusySchedule(BaseModel):
    id:           Optional[str] = None
    day_of_week:  int            # 0=Sun … 6=Sat
    start_time:   str            # "HH:MM"
    end_time:     str            # "HH:MM"


class BusyScheduleCreate(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time:  str                         # "HH:MM"
    end_time:    str


class BusyOverrideRequest(BaseModel):
    active:           bool
    duration_minutes: Optional[int] = Field(None, gt=0, le=480)  # max 8 hours


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg_to_settings(cfg: dict, schedules: list[dict]) -> StoreSettings:
    return StoreSettings(
        hourly_wage=float(cfg.get("hourly_wage") or _DEFAULT_HOURLY_WAGE),
        timezone=cfg.get("timezone") or _DEFAULT_TIMEZONE,
        is_override_busy=bool(cfg.get("is_override_busy", False)),
        override_until=cfg.get("override_until"),
        busy_schedules=[
            BusySchedule(
                id=s["id"],
                day_of_week=s["day_of_week"],
                start_time=s["start_time"][:5],  # "HH:MM:SS" → "HH:MM"
                end_time=s["end_time"][:5],
            )
            for s in schedules
        ],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=StoreSettings)
async def get_store_settings(tenant_id: str = Depends(get_tenant_id)) -> StoreSettings:
    """Return store_configs and busy_schedules for the Settings page.
    (Settings 페이지용 스토어 설정 및 바쁜 시간대 스케줄 반환)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "*"},
        )
        cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []

        sched_resp = await client.get(
            f"{_REST}/busy_schedules",
            headers=_SUPABASE_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "*", "order": "day_of_week.asc,start_time.asc"},
        )
        schedules = sched_resp.json() if isinstance(sched_resp.json(), list) else []

    cfg = cfg_list[0] if cfg_list else {}
    return _cfg_to_settings(cfg, schedules)


@router.patch("/settings", response_model=StoreSettings)
async def patch_store_settings(
    body: StoreSettingsPatch,
    tenant_id: str = Depends(get_tenant_id),
) -> StoreSettings:
    """Update store_configs fields (hourly_wage, timezone).
    (store_configs 필드 업데이트 — 시급, 타임존)
    """
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "id"},
        )
        existing = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []

        if existing:
            patch_resp = await client.patch(
                f"{_REST}/store_configs",
                headers=_SUPABASE_HEADERS,
                params={"store_id": f"eq.{store_id}"},
                json=updates,
            )
            updated_list = patch_resp.json() if isinstance(patch_resp.json(), list) else []
            cfg = updated_list[0] if updated_list else {}
        else:
            # Upsert if no config row exists yet (설정 행이 없으면 신규 생성)
            post_resp = await client.post(
                f"{_REST}/store_configs",
                headers=_SUPABASE_HEADERS,
                json={"store_id": store_id, **updates},
            )
            cfg_list = post_resp.json() if isinstance(post_resp.json(), list) else []
            cfg = cfg_list[0] if cfg_list else {}

    return _cfg_to_settings(cfg, [])


@router.post("/busy-schedule", response_model=BusySchedule, status_code=201)
async def create_busy_schedule(
    body: BusyScheduleCreate,
    tenant_id: str = Depends(get_tenant_id),
) -> BusySchedule:
    """Add a weekly busy schedule entry for this store.
    (스토어 주간 바쁜 시간대 스케줄 추가)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        resp = await client.post(
            f"{_REST}/busy_schedules",
            headers=_SUPABASE_HEADERS,
            json={
                "store_id": store_id,
                "day_of_week": body.day_of_week,
                "start_time": f"{body.start_time}:00",
                "end_time": f"{body.end_time}:00",
            },
        )
        created = resp.json() if isinstance(resp.json(), list) else []
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create schedule")

    s = created[0]
    return BusySchedule(
        id=s["id"],
        day_of_week=s["day_of_week"],
        start_time=s["start_time"][:5],
        end_time=s["end_time"][:5],
    )


@router.delete("/busy-schedule/{schedule_id}", status_code=204)
async def delete_busy_schedule(
    schedule_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> None:
    """Delete a busy schedule entry — verifies ownership before deleting.
    (소유권 확인 후 바쁜 시간대 스케줄 삭제)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        # Verify schedule belongs to this store before deleting (소유권 확인)
        check_resp = await client.get(
            f"{_REST}/busy_schedules",
            headers=_SUPABASE_HEADERS,
            params={"id": f"eq.{schedule_id}", "store_id": f"eq.{store_id}", "select": "id"},
        )
        owned = check_resp.json() if isinstance(check_resp.json(), list) else []
        if not owned:
            raise HTTPException(status_code=404, detail="Schedule not found")

        await client.delete(
            f"{_REST}/busy_schedules",
            headers=_SUPABASE_HEADERS,
            params={"id": f"eq.{schedule_id}"},
        )


@router.post("/busy-override", response_model=StoreSettings)
async def set_busy_override(
    body: BusyOverrideRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> StoreSettings:
    """Activate or deactivate emergency busy override.
    duration_minutes: if provided, auto-expires; if None, stays until manually turned off.
    (긴급 바쁨 오버라이드 활성/비활성화; duration_minutes 없으면 수동 해제까지 유지)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "id"},
        )
        existing = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []

        if body.active:
            override_until = None
            if body.duration_minutes:
                until_dt = datetime.now(timezone.utc) + timedelta(minutes=body.duration_minutes)
                override_until = until_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            patch_data = {"is_override_busy": True, "override_until": override_until}
        else:
            patch_data = {"is_override_busy": False, "override_until": None}

        if existing:
            patch_resp = await client.patch(
                f"{_REST}/store_configs",
                headers=_SUPABASE_HEADERS,
                params={"store_id": f"eq.{store_id}"},
                json=patch_data,
            )
            updated_list = patch_resp.json() if isinstance(patch_resp.json(), list) else []
            cfg = updated_list[0] if updated_list else {}
        else:
            post_resp = await client.post(
                f"{_REST}/store_configs",
                headers=_SUPABASE_HEADERS,
                json={"store_id": store_id, **patch_data},
            )
            cfg_list = post_resp.json() if isinstance(post_resp.json(), list) else []
            cfg = cfg_list[0] if cfg_list else {}

    return _cfg_to_settings(cfg, [])
