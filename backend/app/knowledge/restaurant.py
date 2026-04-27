"""Layer 3 Knowledge — Restaurant vertical KPI calculator.
Mirrors store.py logic exactly; intentionally duplicated to keep store.py stable.
(store.py 로직을 그대로 복제 — 기존 71개 테스트를 깨지 않기 위해 의도적 중복)

KPIs:
  PHRC = busy_successful × avg_ticket              (Peak Hour Revenue Capture)
  LCS  = (Σduration_sec ÷ 3600) × hourly_wage     (Labor Cost Savings)
  LCR  = (successful ÷ total) × 100               (Lead Conversion Rate)
  UV   = total_calls × 0.15 × $5                  (Upselling Value)
"""
from app.knowledge.base import VerticalMetrics

_UPSELL_RATE         = 0.15
_AVG_UPSELL_AMOUNT   = 5.0
_MISSED_CALL_RATE    = 0.20
_DEFAULT_AVG_TICKET  = 50.0


def calculate(
    store_id: str,
    store_name: str,
    call_logs: list[dict],
    orders: list[dict],
    hourly_wage: float,
) -> VerticalMetrics:
    """Return VerticalMetrics for a restaurant store. (레스토랑 스토어 VerticalMetrics 반환)"""
    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_duration_s = sum(int(c.get("duration") or 0) for c in call_logs)
    success_rate     = (successful_calls / total_calls * 100) if total_calls > 0 else 0.0

    paid_orders  = [o for o in orders if o.get("status") == "paid"]
    total_rev    = sum(float(o.get("total_amount") or 0) for o in paid_orders)
    avg_ticket   = (total_rev / len(paid_orders)) if paid_orders else _DEFAULT_AVG_TICKET

    lcs = round((total_duration_s / 3600) * hourly_wage, 2)
    uv  = round(total_calls * _UPSELL_RATE * _AVG_UPSELL_AMOUNT, 2)

    busy_calls      = [c for c in call_logs if c.get("is_store_busy") is True]
    busy_successful = sum(1 for c in busy_calls if c.get("call_status") == "Successful")
    using_real      = len(busy_calls) > 0

    if using_real:
        phrc = round(busy_successful * avg_ticket, 2)
    else:
        phrc = round(total_calls * _MISSED_CALL_RATE * (success_rate / 100) * avg_ticket, 2)

    monthly_impact = round(phrc + lcs + uv, 2)

    return VerticalMetrics(
        monthly_impact=monthly_impact,
        labor_savings=lcs,
        conversion_rate=round(success_rate, 1),
        upsell_value=uv,
        primary_revenue=phrc,
        avg_value=round(avg_ticket, 2),
        total_calls=total_calls,
        successful_calls=successful_calls,
        using_real_busy_data=using_real,
        industry="restaurant",
        primary_revenue_label="Peak Hour Revenue",
        conversion_label="Lead Conversion Rate",
        avg_value_label="Avg Ticket",
        store_id=store_id,
        store_name=store_name,
    )
