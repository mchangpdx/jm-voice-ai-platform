"""Layer 3 Knowledge — Auto Repair vertical KPI calculator.
(자동차 수리 수직 KPI 계산기 — 정비소/오토샵 플랫폼 모델 기반)

KPIs:
  SAR = busy_approved_orders × avg_ticket         (Service Appointment Revenue)
  LCS = (Σduration_sec ÷ 3600) × hourly_wage      (Labor Cost Savings)
  ECR = (approved_orders ÷ total_calls) × 100     (Estimate Conversion Rate)
  LRR = total_calls × 0.25 × avg_ticket × 0.08   (Lead Recovery Revenue)
  Monthly Impact = SAR + LCS + LRR

busy_call = call where is_store_busy=True (technician was working when call arrived)
approved_statuses = {"approved", "in_progress", "completed"}
approved_orders = service_orders where status IN approved_statuses
busy_approved_orders = approved_orders whose call_log_id is in busy_call_ids
avg_ticket: derive from approved_orders using final_price if > 0, else estimate;
            fallback = $450.0
"""
from app.knowledge.base import VerticalMetrics

_APPROVED_STATUSES   = {"approved", "in_progress", "completed"}
_LEAD_RESPONSE_RATE  = 0.25
_LEAD_REVENUE_FACTOR = 0.08
_DEFAULT_AVG_TICKET  = 450.0


def calculate(
    store_id: str,
    store_name: str,
    call_logs: list[dict],
    service_orders: list[dict],
    hourly_wage: float,
) -> VerticalMetrics:
    """Return VerticalMetrics for an auto repair store. (자동차 수리 스토어 VerticalMetrics 반환)"""
    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_duration_s = sum(int(c.get("duration") or 0) for c in call_logs)

    # 승인된 수리 주문으로 평균 수리 단가 산출 (final_price 우선, 없으면 estimate 사용)
    approved_orders = [o for o in service_orders if o.get("status") in _APPROVED_STATUSES]
    ticket_values = []
    for o in approved_orders:
        final = float(o.get("final_price") or 0)
        if final > 0:
            ticket_values.append(final)
        else:
            est = float(o.get("estimate") or 0)
            if est > 0:
                ticket_values.append(est)
    avg_ticket = (sum(ticket_values) / len(ticket_values)) if ticket_values else _DEFAULT_AVG_TICKET

    # 정비사 바쁜 통화 → busy_call_ids (is_store_busy=True 재활용)
    busy_call_ids = {
        c.get("call_id")
        for c in call_logs
        if c.get("is_store_busy") is True
    }
    using_real = len(busy_call_ids) > 0

    # 바쁜 통화에서 승인된 수리 주문만 SAR 계산에 사용
    busy_approved_orders = [
        o for o in approved_orders if o.get("call_log_id") in busy_call_ids
    ]

    sar = round(len(busy_approved_orders) * avg_ticket, 2)
    lcs = round((total_duration_s / 3600) * hourly_wage, 2)
    ecr = round((len(approved_orders) / total_calls * 100) if total_calls > 0 else 0.0, 1)
    lrr = round(total_calls * _LEAD_RESPONSE_RATE * avg_ticket * _LEAD_REVENUE_FACTOR, 2)
    monthly_impact = round(sar + lcs + lrr, 2)

    return VerticalMetrics(
        monthly_impact=monthly_impact,
        labor_savings=lcs,
        conversion_rate=ecr,
        upsell_value=lrr,
        primary_revenue=sar,
        avg_value=round(avg_ticket, 2),
        total_calls=total_calls,
        successful_calls=successful_calls,
        using_real_busy_data=using_real,
        industry="auto_repair",
        primary_revenue_label="Service Appointment Revenue",
        conversion_label="Estimate Conversion Rate",
        avg_value_label="Avg Repair Ticket",
        store_id=store_id,
        store_name=store_name,
    )
