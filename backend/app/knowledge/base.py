"""Layer 3 Knowledge — shared VerticalMetrics contract across all industry verticals.
(Layer 3 지식층 — 모든 산업 수직에 공통 사용되는 VerticalMetrics 계약)
"""
from typing import TypedDict


class VerticalMetrics(TypedDict):
    # Industry-agnostic numeric KPIs (산업 공통 수치 KPI)
    monthly_impact: float
    labor_savings: float
    conversion_rate: float       # LCR (restaurant) | JBR (home_services)
    upsell_value: float          # UV  (restaurant) | LRR (home_services)
    primary_revenue: float       # PHRC (restaurant) | FTR (home_services)
    avg_value: float             # avg_ticket (restaurant) | avg_job_value (home_services)
    total_calls: int
    successful_calls: int
    using_real_busy_data: bool

    # Rendering metadata — frontend resolves labels from these (프론트엔드 레이블 해석용 메타데이터)
    industry: str                       # 'restaurant' | 'home_services'
    primary_revenue_label: str          # "Peak Hour Revenue" | "Field Time Revenue"
    conversion_label: str               # "Lead Conversion Rate" | "Job Booking Rate"
    avg_value_label: str                # "Avg Ticket" | "Avg Job Value"
    store_id: str
    store_name: str
