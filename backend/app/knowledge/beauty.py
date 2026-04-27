"""Layer 3 Knowledge — Beauty vertical KPI calculator.
(뷰티 수직 KPI 계산기 — 살롱/스파 플랫폼 모델 기반)

KPIs:
  BCR = busy_booked_appts × avg_service_price          (Booking Capture Revenue)
  LCS = (Σduration_sec ÷ 3600) × hourly_wage           (Labor Cost Savings)
  AFR = (completed_appts ÷ total_calls) × 100           (Appointment Fill Rate)
  NRR = no_show_count × avg_service_price × 0.30        (No-show Recovery Revenue)
  Monthly Impact = BCR + LCS + NRR

busy_call = call where is_store_busy=True (stylist was busy when call arrived)
busy_booked_appts = appointments whose call_log_id is in busy_call_ids AND status == "completed"
no_show_count = appointments where status == "no_show"
avg_service_price: derive from appointments with price > 0; fallback = $95.0
completed_appts = appointments where status == "completed"
"""
from app.knowledge.base import VerticalMetrics

_DEFAULT_AVG_SERVICE_PRICE = 95.0
_NO_SHOW_RECOVERY_FACTOR   = 0.30
_COMPLETED_STATUS          = "completed"
_NO_SHOW_STATUS            = "no_show"


def calculate(
    store_id: str,
    store_name: str,
    call_logs: list[dict],
    appointments: list[dict],
    hourly_wage: float,
) -> VerticalMetrics:
    """Return VerticalMetrics for a beauty store. (뷰티 스토어 VerticalMetrics 반환)"""
    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_duration_s = sum(int(c.get("duration") or 0) for c in call_logs)

    # 시술 가격 있는 예약으로 평균 서비스 단가 산출
    priced_appts  = [a for a in appointments if float(a.get("price") or 0) > 0]
    total_price   = sum(float(a.get("price") or 0) for a in priced_appts)
    avg_service_price = (total_price / len(priced_appts)) if priced_appts else _DEFAULT_AVG_SERVICE_PRICE

    # 스타일리스트 바쁜 통화 → busy_call_ids (is_store_busy=True 재활용)
    busy_call_ids = {
        c.get("call_id")
        for c in call_logs
        if c.get("is_store_busy") is True
    }
    using_real = len(busy_call_ids) > 0

    # 완료/노쇼 예약 분류, BCR은 바쁜 통화에서 완료된 예약만 산정
    completed_appts  = [a for a in appointments if a.get("status") == _COMPLETED_STATUS]
    no_show_appts    = [a for a in appointments if a.get("status") == _NO_SHOW_STATUS]
    busy_booked_appts = [
        a for a in completed_appts if a.get("call_log_id") in busy_call_ids
    ]

    bcr = round(len(busy_booked_appts) * avg_service_price, 2)
    lcs = round((total_duration_s / 3600) * hourly_wage, 2)
    afr = round((len(completed_appts) / total_calls * 100) if total_calls > 0 else 0.0, 1)
    nrr = round(len(no_show_appts) * avg_service_price * _NO_SHOW_RECOVERY_FACTOR, 2)
    monthly_impact = round(bcr + lcs + nrr, 2)

    return VerticalMetrics(
        monthly_impact=monthly_impact,
        labor_savings=lcs,
        conversion_rate=afr,
        upsell_value=nrr,
        primary_revenue=bcr,
        avg_value=round(avg_service_price, 2),
        total_calls=total_calls,
        successful_calls=successful_calls,
        using_real_busy_data=using_real,
        industry="beauty",
        primary_revenue_label="Booking Capture Revenue",
        conversion_label="Appointment Fill Rate",
        avg_value_label="Avg Service Value",
        store_id=store_id,
        store_name=store_name,
    )
