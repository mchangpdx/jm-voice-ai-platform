# Store API router — dashboard data endpoints (스토어 API 라우터 — 대시보드 데이터 엔드포인트)
# Layer 1 RLS enforced: all queries filter by store_id resolved from tenant_id (owner_id)
#
# Business KPI formulas per Harness methodology (Harness 방법론 기반 비즈니스 KPI 공식):
#   MCRR (real)  = busy_successful_calls × avg_ticket           (is_store_busy 실측 데이터 있을 때)
#   MCRR (est.)  = total_calls × MISSED_CALL_RATE × success_rate × avg_ticket  (폴백)
#   LCS          = (sum(duration_sec) ÷ 3600) × store.hourly_wage
#   LCR          = (successful_calls ÷ total_calls) × 100
#   UV           = total_calls × UPSELL_RATE × AVG_UPSELL_AMOUNT
#   MONTHLY_IMPACT = MCRR + LCS + UV

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/api/store", tags=["Store"])

_SUPABASE_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Business KPI constants — fallback defaults when no store_configs row exists
_HOURLY_WAGE         = 20.0   # Default restaurant staff hourly rate USD (기본 직원 시급)
_MISSED_CALL_RATE    = 0.20   # Fallback: 20% estimated miss rate (폴백 추정 부재율)
_UPSELL_RATE         = 0.15   # 15% AI call upsell attempt rate (AI 업셀링 시도율)
_AVG_UPSELL_AMOUNT   = 5.0    # Average additional revenue per upsell (업셀 1건 추가 매출)
_DEFAULT_AVG_TICKET  = 50.0   # Fallback avg ticket when no order data (주문 없을 때 기본 객단가)
_DEFAULT_TIMEZONE    = "America/Los_Angeles"

_VALID_PERIODS = {"today", "week", "month", "all"}


def _period_start(period: str, store_tz: str = _DEFAULT_TIMEZONE) -> str | None:
    """Return ISO 8601 UTC timestamp for the start of the requested period.
    'today' uses store's local timezone so midnight is correct for that location.
    Returns None for 'all'. (기간 시작 UTC 타임스탬프 반환; 'today'는 스토어 로컬 자정 기준)
    """
    now_utc = datetime.now(timezone.utc)

    if period == "today":
        tz = ZoneInfo(store_tz)
        now_local = now_utc.astimezone(tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(timezone.utc)
    elif period == "week":
        start_utc = now_utc - timedelta(days=7)
    elif period == "month":
        start_utc = now_utc - timedelta(days=30)
    else:
        return None

    return start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _resolve_store(client: httpx.AsyncClient, owner_id: str) -> dict:
    """Lookup store by owner_id — enforces single-store tenant isolation.
    (owner_id로 스토어 조회 — 단일 스토어 테넌트 격리 적용)
    """
    resp = await client.get(
        f"{_REST}/stores",
        headers=_SUPABASE_HEADERS,
        params={"owner_id": f"eq.{owner_id}", "select": "id,name,agency_id,industry"},
    )
    stores = resp.json()
    if not stores:
        raise HTTPException(status_code=404, detail="Store not found for this user")
    return stores[0]


# ── Schemas ───────────────────────────────────────────────────────────────────


class StoreInfo(BaseModel):
    id: str
    name: str
    role: str = "STORE"
    industry: str | None = None


class StoreMetrics(BaseModel):
    # Business ROI KPIs (비즈니스 ROI KPI)
    mcrr: float               # Missed Call Recovery Revenue
    lcs: float                # Labor Cost Savings
    lcr: float                # Lead Conversion Rate %
    upselling_value: float    # Upselling Value
    monthly_impact: float     # Total Economic Impact = MCRR + LCS + UV
    # Supporting data (지원 데이터)
    total_calls: int
    successful_calls: int
    total_ai_revenue: float
    avg_ticket: float
    success_rate: float
    # Configuration context (설정 컨텍스트 — 어떤 값 기준으로 계산했는지 프론트엔드에 전달)
    hourly_wage: float         # Rate used for LCS calculation
    missed_call_rate: float    # Real rate or 20.0 fallback
    using_real_busy_data: bool # True = is_store_busy actual data, False = fallback estimate


class OrderItem(BaseModel):
    name: str
    quantity: int


class RecentOrder(BaseModel):
    id: int
    customer_phone: Optional[str]
    customer_email: Optional[str]
    total_amount: float
    status: str
    created_at: str
    items: list[Any]


class CallLogItem(BaseModel):
    call_id: str
    start_time: str
    customer_phone: Optional[str]
    duration: int
    sentiment: Optional[str]
    call_status: str
    cost: float
    recording_url: Optional[str]
    summary: Optional[str]
    is_store_busy: bool


class CallLogsResponse(BaseModel):
    items: list[CallLogItem]
    total: int
    page: int
    pages: int
    limit: int


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/me", response_model=StoreInfo)
async def get_store_me(tenant_id: str = Depends(get_tenant_id)) -> StoreInfo:
    """Return the authenticated store owner's store info.
    (인증된 스토어 오너의 스토어 정보 반환)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
    return StoreInfo(id=store["id"], name=store["name"], industry=store.get("industry"))


@router.get("/metrics", response_model=StoreMetrics)
async def get_store_metrics(
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> StoreMetrics:
    """Return Harness-methodology Business KPIs for the overview dashboard.

    KPIs: MCRR, LCS, LCR, UV, Monthly Impact (비즈니스 ROI KPI 반환)
    period: today | week | month | all
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
        )

    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        # Fetch store_configs: hourly_wage + timezone (스토어별 시급 및 타임존 조회)
        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id": f"eq.{store_id}",
                "select": "hourly_wage,timezone,is_override_busy,override_until",
            },
        )
        cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []
        cfg = cfg_list[0] if cfg_list else {}
        hourly_wage = float(cfg.get("hourly_wage") or _HOURLY_WAGE)
        store_tz    = cfg.get("timezone") or _DEFAULT_TIMEZONE

        since = _period_start(period, store_tz)

        # Fetch call_logs with is_store_busy for real missed-call detection.
        # Paginate in 1000-row pages to work around Supabase PostgREST max_rows cap.
        # (Supabase max_rows 1000 제한 우회를 위해 1000건씩 페이지네이션)
        call_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "call_status,duration,is_store_busy",
        }
        if since:
            call_params["start_time"] = f"gte.{since}"

        call_logs: list[Any] = []
        offset = 0
        while True:
            page_resp = await client.get(
                f"{_REST}/call_logs",
                headers=_SUPABASE_HEADERS,
                params={**call_params, "limit": "1000", "offset": str(offset)},
            )
            page = page_resp.json() if isinstance(page_resp.json(), list) else []
            call_logs.extend(page)
            if len(page) < 1000:
                break
            offset += 1000

        # Fetch orders filtered by period (기간 필터 적용된 orders 조회)
        order_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "total_amount,status",
            "limit": "10000",
        }
        if since:
            order_params["created_at"] = f"gte.{since}"

        order_resp = await client.get(f"{_REST}/orders", headers=_SUPABASE_HEADERS, params=order_params)
        orders = order_resp.json() if isinstance(order_resp.json(), list) else []

    # ── Aggregate call metrics (통화 지표 집계) ──────────────────────────────
    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_duration_sec = sum(int(c.get("duration") or 0) for c in call_logs)
    success_rate     = (successful_calls / total_calls * 100) if total_calls > 0 else 0.0

    # ── Aggregate order metrics (주문 지표 집계) ─────────────────────────────
    paid_orders   = [o for o in orders if o.get("status") == "paid"]
    total_revenue = sum(float(o.get("total_amount") or 0) for o in paid_orders)
    avg_ticket    = (total_revenue / len(paid_orders)) if paid_orders else _DEFAULT_AVG_TICKET

    # ── LCS: Labor Cost Savings = AI call HOURS × store hourly wage
    # duration is seconds → ÷3600 to convert to hours (초 단위 → ÷3600 = 시간 단위)
    lcs = round((total_duration_sec / 3600) * hourly_wage, 2)

    # ── MCRR: real data if is_store_busy exists, else 20% fallback
    # (is_store_busy 데이터 있으면 실측값, 없으면 20% 추정 폴백)
    busy_calls       = [c for c in call_logs if c.get("is_store_busy") is True]
    busy_successful  = sum(1 for c in busy_calls if c.get("call_status") == "Successful")
    using_real       = len(busy_calls) > 0

    if using_real:
        mcrr             = round(busy_successful * avg_ticket, 2)
        missed_call_rate = round(len(busy_calls) / total_calls * 100, 1) if total_calls > 0 else 0.0
    else:
        mcrr             = round(total_calls * _MISSED_CALL_RATE * (success_rate / 100) * avg_ticket, 2)
        missed_call_rate = _MISSED_CALL_RATE * 100  # 20.0

    # ── UV: Upselling Value (업셀링 수익)
    uv = round(total_calls * _UPSELL_RATE * _AVG_UPSELL_AMOUNT, 2)

    monthly_impact = round(mcrr + lcs + uv, 2)

    return StoreMetrics(
        mcrr=mcrr,
        lcs=lcs,
        lcr=round(success_rate, 1),
        upselling_value=uv,
        monthly_impact=monthly_impact,
        total_calls=total_calls,
        successful_calls=successful_calls,
        total_ai_revenue=round(total_revenue, 2),
        avg_ticket=round(avg_ticket, 2),
        success_rate=round(success_rate, 1),
        hourly_wage=round(hourly_wage, 2),
        missed_call_rate=missed_call_rate,
        using_real_busy_data=using_real,
    )


@router.get("/orders", response_model=list[RecentOrder])
async def get_recent_orders(
    limit: int = 10,
    tenant_id: str = Depends(get_tenant_id),
) -> list[RecentOrder]:
    """Return the most recent orders for the Live Call Orders table.
    (Live Call Orders 테이블용 최신 주문 목록 반환)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        resp = await client.get(
            f"{_REST}/orders",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id": f"eq.{store_id}",
                "select": "id,customer_phone,customer_email,total_amount,status,created_at,items",
                "order": "created_at.desc",
                "limit": limit,
            },
        )
        orders = resp.json()

    if not isinstance(orders, list):
        return []

    return [
        RecentOrder(
            id=o["id"],
            customer_phone=o.get("customer_phone"),
            customer_email=o.get("customer_email"),
            total_amount=float(o.get("total_amount", 0)),
            status=o.get("status", "pending"),
            created_at=o.get("created_at", ""),
            items=o.get("items", []),
        )
        for o in orders
    ]


_VALID_STATUSES   = {"Successful", "Unsuccessful"}
_VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}


@router.get("/call-logs", response_model=CallLogsResponse)
async def get_call_logs(
    period: str = "all",
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    sentiment: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
) -> CallLogsResponse:
    """Return paginated call history with optional filters.
    (페이징 + 필터 지원 통화 내역 반환)
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
        )

    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, tenant_id)
        store_id = store["id"]

        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "timezone"},
        )
        cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []
        store_tz = (cfg_list[0].get("timezone") if cfg_list else None) or _DEFAULT_TIMEZONE

        since = _period_start(period, store_tz)

        params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "call_id,start_time,customer_phone,duration,sentiment,call_status,cost,recording_url,summary,is_store_busy",
            "order": "start_time.desc",
            "limit": "1000",
        }
        if since:
            params["start_time"] = f"gte.{since}"
        if status and status in _VALID_STATUSES:
            params["call_status"] = f"eq.{status}"
        if sentiment and sentiment in _VALID_SENTIMENTS:
            params["sentiment"] = f"eq.{sentiment}"

        # Paginate to fetch all matching logs past Supabase 1000-row cap.
        # (Supabase max_rows 우회 페이지네이션)
        all_logs: list[Any] = []
        db_offset = 0
        while True:
            batch_resp = await client.get(
                f"{_REST}/call_logs",
                headers=_SUPABASE_HEADERS,
                params={**params, "limit": "1000", "offset": str(db_offset)},
            )
            batch = batch_resp.json() if isinstance(batch_resp.json(), list) else []
            all_logs.extend(batch)
            if len(batch) < 1000:
                break
            db_offset += 1000

    total = len(all_logs)
    pages = math.ceil(total / limit) if total > 0 else 1
    offset = (page - 1) * limit
    page_logs = all_logs[offset : offset + limit]

    return CallLogsResponse(
        items=[
            CallLogItem(
                call_id=c["call_id"],
                start_time=c.get("start_time", ""),
                customer_phone=c.get("customer_phone"),
                duration=int(c.get("duration") or 0),
                sentiment=c.get("sentiment"),
                call_status=c.get("call_status", ""),
                cost=float(c.get("cost") or 0),
                recording_url=c.get("recording_url"),
                summary=c.get("summary"),
                is_store_busy=bool(c.get("is_store_busy")),
            )
            for c in page_logs
        ],
        total=total,
        page=page,
        pages=pages,
        limit=limit,
    )
