// Agency Store Detail — per-store KPI view in agency context
// (에이전시 컨텍스트의 단일 스토어 KPI 뷰)
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import styles from './StoreDetail.module.css'

type Period = 'today' | 'week' | 'month' | 'all'

interface StoreMetrics {
  store_id: string
  store_name: string
  industry: string
  monthly_impact: number
  labor_savings: number
  conversion_rate: number
  upsell_value: number
  primary_revenue: number
  avg_value: number
  total_calls: number
  successful_calls: number
  using_real_busy_data: boolean
  primary_revenue_label: string
  conversion_label: string
  avg_value_label: string
}

const fmt = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`

export default function AgencyStoreDetail() {
  const { storeId } = useParams<{ storeId: string }>()
  const [period, setPeriod] = useState<Period>('month')
  const [data, setData] = useState<StoreMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    if (!storeId) return
    setLoading(true)
    api
      .get(`/agency/store/${storeId}/metrics?period=${period}`)
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [storeId, period])

  const meta = data ? getVerticalMeta(data.industry) : null

  return (
    <div className={styles.page}>
      {/* Breadcrumb + period (브레드크럼 + 기간 선택) */}
      <div className={styles.header}>
        <div>
          <button className={styles.backBtn} onClick={() => navigate('/agency/overview')}>
            ← All Stores
          </button>
          <h1 className={styles.title}>
            {meta?.icon} {data?.store_name ?? '…'}
          </h1>
          <p className={styles.subtitle}>{meta?.industryLabel ?? ''}</p>
        </div>
        <div className={styles.periodTabs}>
          {(['today', 'week', 'month', 'all'] as Period[]).map((p) => (
            <button
              key={p}
              className={`${styles.periodBtn} ${period === p ? styles.periodBtnActive : ''}`}
              onClick={() => setPeriod(p)}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Loading…</div>
      ) : data ? (
        <>
          {/* KPI cards (KPI 카드) */}
          <div className={styles.kpiGrid}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>{data.primary_revenue_label}</div>
              <div className={styles.kpiValue}>{fmt(data.primary_revenue)}</div>
              <div className={styles.kpiSub}>
                {data.using_real_busy_data ? 'Based on real busy data' : 'Estimated'}
              </div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Labor Savings</div>
              <div className={styles.kpiValue}>{fmt(data.labor_savings)}</div>
              <div className={styles.kpiSub}>AI call handling time</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>{data.conversion_label}</div>
              <div className={`${styles.kpiValue} ${data.conversion_rate < 50 ? styles.warn : ''}`}>
                {data.conversion_rate.toFixed(1)}%
              </div>
              <div className={styles.kpiSub}>
                {data.successful_calls} / {data.total_calls} calls
              </div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>{data.avg_value_label}</div>
              <div className={styles.kpiValue}>{fmt(data.avg_value)}</div>
              <div className={styles.kpiSub}>Per transaction</div>
            </div>
          </div>

          {/* Monthly impact highlight (월간 임팩트 하이라이트) */}
          <div className={styles.impactBanner}>
            <div>
              <div className={styles.impactTitle}>Monthly Impact</div>
              <div className={styles.impactSub}>
                {data.primary_revenue_label} + Labor Savings + Upside
              </div>
            </div>
            <div className={styles.impactAmount}>{fmt(data.monthly_impact)}</div>
          </div>

          {/* Call volume stats (통화량 통계) */}
          <div className={styles.statsRow}>
            <div className={styles.statItem}>
              <div className={styles.statValue}>{data.total_calls.toLocaleString()}</div>
              <div className={styles.statLabel}>Total Calls</div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statValue}>{data.successful_calls.toLocaleString()}</div>
              <div className={styles.statLabel}>Successful</div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statValue}>{fmt(data.upsell_value)}</div>
              <div className={styles.statLabel}>
                {data.industry === 'home_services' ? 'Lead Revenue' : 'Upsell Value'}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className={styles.loading}>No data available.</div>
      )}
    </div>
  )
}
