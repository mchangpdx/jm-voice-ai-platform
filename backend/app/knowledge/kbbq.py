"""Layer 3 Knowledge — KBBQ vertical KPI calculator.
(Layer 3 지식층 — KBBQ vertical KPI 계산기)

Mirrors restaurant.py logic; tunes constants for Korean BBQ FSR economics:
  - Higher avg_ticket default ($75 vs $50): BBQ Combos $85-$105, A La Carte
    minimum 2 portions × $27-$45 each.
  - Lower upsell rate (12% vs 15%): KBBQ tickets are larger by default,
    less room for $5 incremental upsell.
  - Higher avg upsell amount ($8 vs $5): KBBQ upsells are typically a
    soju bottle ($12), additional banchan set ($5), or +Ramen/+Cheese ($5).

KPIs (same labels as restaurant for dashboard consistency):
  PHRC = busy_successful × avg_ticket              (Peak Hour Revenue Capture)
  LCS  = (Σduration_sec ÷ 3600) × hourly_wage     (Labor Cost Savings)
  LCR  = (successful ÷ total) × 100               (Lead Conversion Rate)
  UV   = total_calls × 0.12 × $8                  (Upselling Value, KBBQ-tuned)
"""
from app.knowledge.base import VerticalMetrics

_UPSELL_RATE         = 0.12   # KBBQ-tuned: lower than cafe (large ticket → less upsell room)
_AVG_UPSELL_AMOUNT   = 8.0    # KBBQ-tuned: soju/banchan/+Ramen avg vs cafe syrup/shot
_MISSED_CALL_RATE    = 0.20
_DEFAULT_AVG_TICKET  = 75.0   # KBBQ-tuned: BBQ Combos $85-$105, A La Carte 2-portion floor


def calculate(
    store_id: str,
    store_name: str,
    call_logs: list[dict],
    orders: list[dict],
    hourly_wage: float,
) -> VerticalMetrics:
    """Return VerticalMetrics for a KBBQ store. (KBBQ 스토어 VerticalMetrics 반환)"""
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
        industry="kbbq",
        primary_revenue_label="Peak Hour Revenue",
        conversion_label="Lead Conversion Rate",
        avg_value_label="Avg Ticket",
        store_id=store_id,
        store_name=store_name,
    )
