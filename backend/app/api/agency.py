"""Agency API — multi-store dashboard endpoints for agency owners.
(에이전시 API — 에이전시 오너의 멀티스토어 대시보드 엔드포인트)

Authorization flow:
  JWT → tenant_id
    → agencies WHERE owner_id = tenant_id  → agency (403 if not found)
    → stores WHERE agency_id = agency.id   → store list

Layer 3 dispatch:
  store.industry == 'restaurant'   → knowledge.restaurant.calculate()
  store.industry == 'home_services'→ knowledge.home_services.calculate()
  store.industry == 'beauty'        → knowledge.beauty.calculate()
  store.industry == 'auto_repair'   → knowledge.auto_repair.calculate()
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_tenant_id
from app.core.config import settings
import app.knowledge.home_services as hs_knowledge
import app.knowledge.restaurant as rest_knowledge
import app.knowledge.beauty as beauty_knowledge
import app.knowledge.auto_repair as auto_knowledge
from app.api.analytics import build_analytics_response

router = APIRouter(prefix="/api/agency", tags=["Agency"])

_SUPABASE_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

_VALID_PERIODS   = {"today", "week", "month", "all"}
_DEFAULT_TIMEZONE = "America/Los_Angeles"
_DEFAULT_WAGE     = 20.0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _period_start(period: str, store_tz: str = _DEFAULT_TIMEZONE) -> str | None:
    """Return ISO 8601 UTC timestamp for period start. (기간 시작 UTC 타임스탬프 반환)"""
    now_utc = datetime.now(timezone.utc)
    if period == "today":
        tz = ZoneInfo(store_tz)
        local = now_utc.astimezone(tz)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    elif period == "week":
        start = now_utc - timedelta(days=7)
    elif period == "month":
        start = now_utc - timedelta(days=30)
    else:
        return None
    return start.strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _resolve_agency(client: httpx.AsyncClient, owner_id: str) -> dict:
    """Lookup agency by owner_id. Raises 403 if not an agency user.
    (owner_id로 에이전시 조회. 에이전시 사용자가 아니면 403)
    """
    resp = await client.get(
        f"{_REST}/agencies",
        headers=_SUPABASE_HEADERS,
        params={"owner_id": f"eq.{owner_id}", "select": "id,name"},
    )
    agencies = resp.json() if isinstance(resp.json(), list) else []
    if not agencies:
        raise HTTPException(status_code=403, detail="Not an agency account")
    return agencies[0]


async def _fetch_call_logs(
    client: httpx.AsyncClient,
    store_id: str,
    since: str | None,
) -> list[dict]:
    """Fetch all call_logs with pagination. (페이지네이션으로 전체 call_logs 조회)"""
    params: dict[str, Any] = {
        "store_id": f"eq.{store_id}",
        "select": "call_id,call_status,duration,is_store_busy",
    }
    if since:
        params["start_time"] = f"gte.{since}"

    logs: list[dict] = []
    offset = 0
    while True:
        resp = await client.get(
            f"{_REST}/call_logs",
            headers=_SUPABASE_HEADERS,
            params={**params, "limit": "1000", "offset": str(offset)},
        )
        page = resp.json() if isinstance(resp.json(), list) else []
        logs.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return logs


async def _compute_store_metrics(
    client: httpx.AsyncClient,
    store: dict,
    period: str,
) -> dict:
    """Fetch data + dispatch to correct Layer 3 vertical module.
    (데이터 조회 후 올바른 Layer 3 수직 모듈로 분기)

    GET call order (tests depend on this exact sequence):
      1. store_configs
      2. call_logs (paginated, 1 GET per page in tests)
      3. orders (restaurant) | jobs (home_services)
    """
    store_id   = store["id"]
    store_name = store["name"]
    industry   = store.get("industry", "restaurant")

    # 1. store_configs → hourly_wage + timezone
    cfg_resp = await client.get(
        f"{_REST}/store_configs",
        headers=_SUPABASE_HEADERS,
        params={"store_id": f"eq.{store_id}", "select": "hourly_wage,timezone"},
    )
    cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []
    cfg = cfg_list[0] if cfg_list else {}
    hourly_wage = float(cfg.get("hourly_wage") or _DEFAULT_WAGE)
    store_tz    = cfg.get("timezone") or _DEFAULT_TIMEZONE
    since       = _period_start(period, store_tz)

    # 2. call_logs
    call_logs = await _fetch_call_logs(client, store_id, since)

    # 3. industry-specific data + Layer 3 dispatch
    if industry == "home_services":
        job_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "call_log_id,job_value,status",
        }
        if since:
            job_params["created_at"] = f"gte.{since}"
        job_resp = await client.get(
            f"{_REST}/jobs",
            headers=_SUPABASE_HEADERS,
            params=job_params,
        )
        jobs = job_resp.json() if isinstance(job_resp.json(), list) else []
        metrics = hs_knowledge.calculate(store_id, store_name, call_logs, jobs, hourly_wage)
    elif industry == "beauty":
        appt_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "call_log_id,price,status",
        }
        if since:
            appt_params["scheduled_at"] = f"gte.{since}"
        appt_resp = await client.get(
            f"{_REST}/appointments",
            headers=_SUPABASE_HEADERS,
            params=appt_params,
        )
        appointments = appt_resp.json() if isinstance(appt_resp.json(), list) else []
        metrics = beauty_knowledge.calculate(store_id, store_name, call_logs, appointments, hourly_wage)
    elif industry == "auto_repair":
        so_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "call_log_id,estimate,final_price,status",
        }
        if since:
            so_params["created_at"] = f"gte.{since}"
        so_resp = await client.get(
            f"{_REST}/service_orders",
            headers=_SUPABASE_HEADERS,
            params=so_params,
        )
        service_orders = so_resp.json() if isinstance(so_resp.json(), list) else []
        metrics = auto_knowledge.calculate(store_id, store_name, call_logs, service_orders, hourly_wage)
    else:
        order_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select": "total_amount,status",
        }
        if since:
            order_params["created_at"] = f"gte.{since}"
        order_resp = await client.get(
            f"{_REST}/orders",
            headers=_SUPABASE_HEADERS,
            params=order_params,
        )
        orders = order_resp.json() if isinstance(order_resp.json(), list) else []
        metrics = rest_knowledge.calculate(store_id, store_name, call_logs, orders, hourly_wage)

    return dict(metrics)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/me")
async def get_agency_me(tenant_id: str = Depends(get_tenant_id)) -> dict:
    """Return agency info for the authenticated agency owner. (에이전시 오너 정보 반환)"""
    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)
    return {"id": agency["id"], "name": agency["name"]}


@router.get("/stores")
async def get_agency_stores(tenant_id: str = Depends(get_tenant_id)) -> list[dict]:
    """List all stores managed by this agency. (에이전시 관리 스토어 목록 반환)"""
    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)
        resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"agency_id": f"eq.{agency['id']}", "select": "id,name,industry"},
        )
    stores = resp.json() if isinstance(resp.json(), list) else []
    return stores


@router.get("/overview")
async def get_agency_overview(
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Aggregated KPIs across all agency stores, with per-store VerticalMetrics.
    (에이전시 전체 집계 KPI + 스토어별 VerticalMetrics 반환)
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
        )

    async with httpx.AsyncClient() as client:
        # 1. Resolve agency
        agency = await _resolve_agency(client, tenant_id)

        # 2. Get all stores
        stores_resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"agency_id": f"eq.{agency['id']}", "select": "id,name,industry"},
        )
        stores = stores_resp.json() if isinstance(stores_resp.json(), list) else []

        # 3. Compute metrics per store sequentially (순차 계산 — mock GET 순서 보장)
        store_metrics: list[dict] = []
        for store in stores:
            m = await _compute_store_metrics(client, store, period)
            store_metrics.append(m)

    total_calls  = sum(m["total_calls"]    for m in store_metrics)
    total_impact = sum(m["monthly_impact"] for m in store_metrics)

    return {
        "agency_name": agency["name"],
        "period": period,
        "totals": {
            "total_calls":        total_calls,
            "total_monthly_impact": round(total_impact, 2),
            "store_count":        len(stores),
        },
        "stores": store_metrics,
    }


_VALID_STATUSES   = {"Successful", "Unsuccessful"}
_VALID_ANALYTICS  = {"week", "month", "all"}


@router.get("/store/{store_id}/analytics")
async def get_agency_store_analytics(
    store_id: str,
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Analytics charts data for a single store in agency context.
    (에이전시 컨텍스트의 단일 스토어 분석 차트 데이터 반환)
    period: week | month | all
    """
    if period not in _VALID_ANALYTICS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_ANALYTICS)}",
        )

    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)

        check_resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "id":        f"eq.{store_id}",
                "agency_id": f"eq.{agency['id']}",
                "select":    "id,name,industry",
            },
        )
        stores = check_resp.json() if isinstance(check_resp.json(), list) else []
        if not stores:
            raise HTTPException(status_code=403, detail="Store not accessible by this agency")

        cfg_resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={"store_id": f"eq.{store_id}", "select": "timezone"},
        )
        cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []
        store_tz = (cfg_list[0].get("timezone") if cfg_list else None) or _DEFAULT_TIMEZONE
        since    = _period_start(period, store_tz)

        call_params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select":   "call_status,duration,sentiment,start_time",
        }
        if since:
            call_params["start_time"] = f"gte.{since}"

        call_logs: list[dict] = []
        offset = 0
        while True:
            resp = await client.get(
                f"{_REST}/call_logs",
                headers=_SUPABASE_HEADERS,
                params={**call_params, "limit": "1000", "offset": str(offset)},
            )
            batch = resp.json() if isinstance(resp.json(), list) else []
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

        orders: list[dict] = []
        offset = 0
        while True:
            resp = await client.get(
                f"{_REST}/orders",
                headers=_SUPABASE_HEADERS,
                params={**order_params, "limit": "1000", "offset": str(offset)},
            )
            batch = resp.json() if isinstance(resp.json(), list) else []
            orders.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000

    result = build_analytics_response(call_logs, orders, store_tz)
    return result.model_dump()


@router.get("/store/{store_id}/call-logs")
async def get_agency_store_call_logs(
    store_id: str,
    period: str = "all",
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Paginated call logs for a single store in agency context.
    (에이전시 컨텍스트의 단일 스토어 통화 내역 — 페이징 + 기간 필터 지원)
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
        )

    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)

        check_resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "id":        f"eq.{store_id}",
                "agency_id": f"eq.{agency['id']}",
                "select":    "id,name,industry",
            },
        )
        stores = check_resp.json() if isinstance(check_resp.json(), list) else []
        if not stores:
            raise HTTPException(status_code=403, detail="Store not accessible by this agency")

        since = _period_start(period)

        params: dict[str, Any] = {
            "store_id": f"eq.{store_id}",
            "select":   "call_id,start_time,customer_phone,duration,sentiment,call_status,cost,recording_url,summary,is_store_busy",
            "order":    "start_time.desc",
        }
        if since:
            params["start_time"] = f"gte.{since}"
        if status and status in _VALID_STATUSES:
            params["call_status"] = f"eq.{status}"

        all_logs: list[dict] = []
        offset = 0
        while True:
            resp = await client.get(
                f"{_REST}/call_logs",
                headers=_SUPABASE_HEADERS,
                params={**params, "limit": "1000", "offset": str(offset)},
            )
            batch = resp.json() if isinstance(resp.json(), list) else []
            all_logs.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000

    total  = len(all_logs)
    pages  = math.ceil(total / limit) if total > 0 else 1
    start  = (page - 1) * limit
    items  = all_logs[start: start + limit]

    return {
        "items": [
            {
                "call_id":        c["call_id"],
                "start_time":     c.get("start_time", ""),
                "customer_phone": c.get("customer_phone"),
                "duration":       int(c.get("duration") or 0),
                "sentiment":      c.get("sentiment"),
                "call_status":    c.get("call_status", ""),
                "cost":           float(c.get("cost") or 0),
                "recording_url":  c.get("recording_url"),
                "summary":        c.get("summary"),
                "is_store_busy":  bool(c.get("is_store_busy")),
            }
            for c in items
        ],
        "total": total,
        "page":  page,
        "pages": pages,
        "limit": limit,
    }


@router.get("/store/{store_id}/metrics")
async def get_agency_store_metrics(
    store_id: str,
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Per-store KPIs in agency context. Enforces cross-agency 403 protection.
    (에이전시 컨텍스트의 단일 스토어 KPI. 크로스-에이전시 403 보호 적용)
    """
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}",
        )

    async with httpx.AsyncClient() as client:
        # 1. Resolve agency
        agency = await _resolve_agency(client, tenant_id)

        # 2. Access check: store must belong to THIS agency (크로스-에이전시 접근 차단)
        check_resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "id":        f"eq.{store_id}",
                "agency_id": f"eq.{agency['id']}",
                "select":    "id,name,industry",
            },
        )
        stores = check_resp.json() if isinstance(check_resp.json(), list) else []
        if not stores:
            raise HTTPException(status_code=403, detail="Store not accessible by this agency")

        # 3. Compute metrics
        metrics = await _compute_store_metrics(client, stores[0], period)

    return metrics
