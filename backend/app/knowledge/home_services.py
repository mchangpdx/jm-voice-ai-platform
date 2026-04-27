"""Layer 3 Knowledge — Home Services vertical KPI calculator.
(홈 서비스 수직 KPI 계산기 — Thumbtack/Angi 플랫폼 모델 기반)

KPIs:
  FTR = field_calls_booked × avg_job_value          (Field Time Revenue)
  LCS = (Σduration_sec ÷ 3600) × hourly_rate       (Labor Cost Savings)
  JBR = (booked_jobs ÷ total_calls) × 100           (Job Booking Rate)
  LRR = total_calls × 0.30 × avg_job_value × 0.10  (Lead Response Revenue)

field_call = call where is_store_busy=True (contractor was on-site when call arrived)
field_calls_booked = field calls linked to a job with status IN ('booked','completed')
"""
from app.knowledge.base import VerticalMetrics

_LEAD_RESPONSE_RATE    = 0.30   # 30% of all calls produce a lead (리드 전환율)
_LEAD_REVENUE_FACTOR   = 0.10   # 10% of avg_job_value per lead (리드당 수익 비율)
_DEFAULT_AVG_JOB_VALUE = 400.0  # Fallback when no job data (기본 평균 작업 단가)
_BOOKED_STATUSES       = {"booked", "completed"}


def calculate(
    store_id: str,
    store_name: str,
    call_logs: list[dict],
    jobs: list[dict],
    hourly_wage: float,
) -> VerticalMetrics:
    """Return VerticalMetrics for a home_services store. (홈서비스 스토어 VerticalMetrics 반환)"""
    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_duration_s = sum(int(c.get("duration") or 0) for c in call_logs)

    # Jobs booked/completed — derive avg_job_value (예약/완료 작업으로 평균 단가 산출)
    booked_jobs   = [j for j in jobs if j.get("status") in _BOOKED_STATUSES]
    total_job_rev = sum(float(j.get("job_value") or 0) for j in booked_jobs)
    avg_job_value = (total_job_rev / len(booked_jobs)) if booked_jobs else _DEFAULT_AVG_JOB_VALUE

    # Field calls: contractor was on-site (is_store_busy=True reused as is_field_call)
    field_call_ids = {
        c.get("call_id")
        for c in call_logs
        if c.get("is_store_busy") is True
    }
    using_real = len(field_call_ids) > 0

    # FTR: field jobs that were booked (현장 통화 → 예약 성사된 작업 수익)
    field_booked_jobs = [
        j for j in booked_jobs if j.get("call_log_id") in field_call_ids
    ]
    ftr = round(len(field_booked_jobs) * avg_job_value, 2)

    lcs = round((total_duration_s / 3600) * hourly_wage, 2)

    # JBR: booked jobs ÷ total calls (예약 성사율)
    jbr = round((len(booked_jobs) / total_calls * 100) if total_calls > 0 else 0.0, 1)

    # LRR: lead response revenue estimate (리드 응답 수익 추정)
    lrr = round(total_calls * _LEAD_RESPONSE_RATE * avg_job_value * _LEAD_REVENUE_FACTOR, 2)

    monthly_impact = round(ftr + lcs + lrr, 2)

    return VerticalMetrics(
        monthly_impact=monthly_impact,
        labor_savings=lcs,
        conversion_rate=jbr,
        upsell_value=lrr,
        primary_revenue=ftr,
        avg_value=round(avg_job_value, 2),
        total_calls=total_calls,
        successful_calls=successful_calls,
        using_real_busy_data=using_real,
        industry="home_services",
        primary_revenue_label="Field Time Revenue",
        conversion_label="Job Booking Rate",
        avg_value_label="Avg Job Value",
        store_id=store_id,
        store_name=store_name,
    )
