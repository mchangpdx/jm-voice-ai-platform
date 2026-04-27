# Analytics API router — aggregated call + revenue trend data for charts
# (분석 API 라우터 — 차트용 통화/매출 집계 데이터)
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/api/store", tags=["Analytics"])

_REST = f"{settings.supabase_url}/rest/v1"
_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}

_VALID_PERIODS = {"week", "month", "all"}
_DEFAULT_TZ    = "America/Los_Angeles"


def _period_start(period: str, store_tz: str = _DEFAULT_TZ) -> str | None:
    now = datetime.now(timezone.utc)
    if period == "week":
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

class DailyCallPoint(BaseModel):
    date: str           # YYYY-MM-DD in store local time
    successful: int
    unsuccessful: int
    total: int


class HourlyPoint(BaseModel):
    hour: int           # 0-23 local store time
    count: int


class DailyRevenuePoint(BaseModel):
    date: str           # YYYY-MM-DD
    revenue: float
    orders: int


class AnalyticsSummary(BaseModel):
    peak_hour: int              # local hour with most calls
    peak_hour_label: str        # e.g. "7 PM"
    peak_day: str               # e.g. "Saturday"
    avg_daily_calls: float
    total_call_minutes: float
    busiest_period: str         # "Lunch" | "Dinner" | "Morning"


class AnalyticsResponse(BaseModel):
    daily_calls: list[DailyCallPoint]
    hourly_distribution: list[HourlyPoint]
    daily_revenue: list[DailyRevenuePoint]
    sentiment_breakdown: dict[str, int]
    day_of_week_distribution: list[dict]  # [{"day": "Mon", "count": 45}, ...]
    summary: AnalyticsSummary


# ── Shared computation (에이전시/스토어 공통 분석 계산) ──────────────────────

_DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build_analytics_response(
    call_logs: list[Any],
    orders: list[Any],
    store_tz: str = _DEFAULT_TZ,
) -> AnalyticsResponse:
    """Pure analytics computation — shared by /store/analytics and /agency/store/{id}/analytics.
    (스토어 및 에이전시 엔드포인트가 공유하는 분석 계산 함수)
    """
    tz = ZoneInfo(store_tz)

    daily_succ:   defaultdict[str, int] = defaultdict(int)
    daily_unsucc: defaultdict[str, int] = defaultdict(int)
    hourly:       defaultdict[int, int] = defaultdict(int)
    dow:          defaultdict[str, int] = defaultdict(int)
    sentiment:    defaultdict[str, int] = defaultdict(int)
    total_dur_sec = 0

    for c in call_logs:
        raw = c.get("start_time", "")
        try:
            dt_utc   = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(tz)
        except Exception:
            continue

        date_str   = dt_local.strftime("%Y-%m-%d")
        hour_local = dt_local.hour
        day_name   = dt_local.strftime("%a")

        if c.get("call_status") == "Successful":
            daily_succ[date_str] += 1
        else:
            daily_unsucc[date_str] += 1

        hourly[hour_local] += 1
        dow[day_name]      += 1
        total_dur_sec      += int(c.get("duration") or 0)

        s = c.get("sentiment")
        if s in ("Positive", "Neutral", "Negative"):
            sentiment[s] += 1

    all_dates  = sorted(set(daily_succ) | set(daily_unsucc))
    daily_calls = [
        DailyCallPoint(
            date=d,
            successful=daily_succ[d],
            unsuccessful=daily_unsucc[d],
            total=daily_succ[d] + daily_unsucc[d],
        )
        for d in all_dates
    ]

    hourly_distribution = [HourlyPoint(hour=h, count=hourly.get(h, 0)) for h in range(24)]
    dow_dist = [{"day": d, "count": dow.get(d, 0)} for d in _DOW_ORDER]

    # Revenue aggregation (매출 집계)
    daily_rev:    defaultdict[str, float] = defaultdict(float)
    daily_orders: defaultdict[str, int]   = defaultdict(int)

    for o in orders:
        raw = o.get("created_at", "")
        try:
            dt_utc   = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(tz)
            date_str = dt_local.strftime("%Y-%m-%d")
        except Exception:
            continue
        daily_rev[date_str]    += float(o.get("total_amount") or 0)
        daily_orders[date_str] += 1

    rev_dates = sorted(set(daily_rev))
    daily_revenue = [
        DailyRevenuePoint(date=d, revenue=round(daily_rev[d], 2), orders=daily_orders[d])
        for d in rev_dates
    ]

    # Summary (요약 인사이트)
    total_calls = len(call_logs)
    days_count  = len(all_dates) or 1
    avg_daily   = round(total_calls / days_count, 1)
    peak_hour   = max(range(24), key=lambda h: hourly.get(h, 0)) if hourly else 12
    peak_day    = max(_DOW_ORDER, key=lambda d: dow.get(d, 0)) if dow else "Saturday"

    if peak_hour == 0:     peak_label = "12 AM"
    elif peak_hour < 12:   peak_label = f"{peak_hour} AM"
    elif peak_hour == 12:  peak_label = "12 PM"
    else:                  peak_label = f"{peak_hour - 12} PM"

    if   6  <= peak_hour < 11: busiest = "Morning"
    elif 11 <= peak_hour < 15: busiest = "Lunch"
    elif 15 <= peak_hour < 17: busiest = "Afternoon"
    else:                       busiest = "Dinner"

    return AnalyticsResponse(
        daily_calls=daily_calls,
        hourly_distribution=hourly_distribution,
        daily_revenue=daily_revenue,
        sentiment_breakdown=dict(sentiment),
        day_of_week_distribution=dow_dist,
        summary=AnalyticsSummary(
            peak_hour=peak_hour,
            peak_hour_label=peak_label,
            peak_day=peak_day,
            avg_daily_calls=avg_daily,
            total_call_minutes=round(total_dur_sec / 60, 1),
            busiest_period=busiest,
        ),
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> AnalyticsResponse:
    """Return aggregated analytics data for charts and insights.
    (차트 및 인사이트용 집계 분석 데이터 반환)
    period: week | month | all
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
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

        call_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select":   "call_status,duration,sentiment,start_time",
        }
        if since:
            call_params["start_time"] = f"gte.{since}"

        call_logs: list[Any] = []
        offset = 0
        while True:
            page_resp = await client.get(
                f"{_REST}/call_logs",
                headers=_HEADERS,
                params={**call_params, "limit": "1000", "offset": str(offset)},
            )
            batch = page_resp.json() if isinstance(page_resp.json(), list) else []
            call_logs.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000

        order_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select":   "total_amount,status,created_at",
            "status":   "eq.paid",
        }
        if since:
            order_params["created_at"] = f"gte.{since}"

        orders: list[Any] = []
        offset = 0
        while True:
            page_resp = await client.get(
                f"{_REST}/orders",
                headers=_HEADERS,
                params={**order_params, "limit": "1000", "offset": str(offset)},
            )
            batch = page_resp.json() if isinstance(page_resp.json(), list) else []
            orders.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000

    return build_analytics_response(call_logs, orders, store_tz)
