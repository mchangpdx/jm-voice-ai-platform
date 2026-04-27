// Agency Overview — aggregated KPIs + per-store card grid
// (에이전시 개요 — 전체 집계 KPI + 스토어별 카드 그리드)
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import styles from './Overview.module.css'

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
  primary_revenue_label: string
  conversion_label: string
  avg_value_label: string
}

interface OverviewData {
  agency_name: string
  period: string
  totals: {
    total_calls: number
    total_monthly_impact: number
    store_count: number
  }
  stores: StoreMetrics[]
}

const fmt = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`

export default function AgencyOverview() {
  const [period, setPeriod] = useState<Period>('month')
  const [data, setData] = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    api
      .get(`/agency/overview?period=${period}`)
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [period])

  const avgConversion =
    data && data.stores.length > 0
      ? data.stores.reduce((s, m) => s + m.conversion_rate, 0) / data.stores.length
      : 0

  const attentionStores = data?.stores.filter((s) => s.conversion_rate < 50) ?? []

  return (
    <div className={styles.page}>
      {/* Page header (페이지 헤더) */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Agency Overall Performance</h1>
          <p className={styles.subtitle}>Aggregated across all managed stores.</p>
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
      ) : (
        <>
          {/* Summary badges (집계 배지) */}
          <div className={styles.summaryRow}>
            <div className={styles.badge}>
              <div className={styles.badgeValue}>{data?.totals.total_calls.toLocaleString() ?? '—'}</div>
              <div className={styles.badgeLabel}>Total Calls</div>
            </div>
            <div className={styles.badge}>
              <div className={styles.badgeValue}>{fmt(data?.totals.total_monthly_impact ?? 0)}</div>
              <div className={styles.badgeLabel}>Total Impact</div>
            </div>
            <div className={styles.badge}>
              <div className={styles.badgeValue}>{data?.totals.store_count ?? '—'}</div>
              <div className={styles.badgeLabel}>Stores</div>
            </div>
            <div className={styles.badge}>
              <div className={styles.badgeValue}>{avgConversion.toFixed(1)}%</div>
              <div className={styles.badgeLabel}>Avg Conversion</div>
            </div>
          </div>

          {/* Store card grid (스토어 카드 그리드) */}
          <h2 className={styles.sectionTitle}>STORE PERFORMANCE</h2>
          <div className={styles.cardGrid}>
            {(data?.stores ?? []).map((s) => {
              const meta = getVerticalMeta(s.industry)
              return (
                <div key={s.store_id} className={styles.storeCard}>
                  <div className={styles.cardHeader}>
                    <span className={styles.cardIcon}>{meta.icon}</span>
                    <div>
                      <div className={styles.cardStoreName}>{s.store_name}</div>
                      <div className={styles.cardIndustry}>{meta.industryLabel}</div>
                    </div>
                  </div>

                  <div className={styles.cardKpis}>
                    <div className={styles.kpiRow}>
                      <span className={styles.kpiLabel}>{s.primary_revenue_label}</span>
                      <span className={styles.kpiValue}>{fmt(s.primary_revenue)}</span>
                    </div>
                    <div className={styles.kpiRow}>
                      <span className={styles.kpiLabel}>Labor Savings</span>
                      <span className={styles.kpiValue}>{fmt(s.labor_savings)}</span>
                    </div>
                    <div className={styles.kpiRow}>
                      <span className={styles.kpiLabel}>{s.conversion_label}</span>
                      <span className={`${styles.kpiValue} ${s.conversion_rate < 50 ? styles.kpiWarn : ''}`}>
                        {s.conversion_rate.toFixed(1)}%
                      </span>
                    </div>
                    <div className={styles.kpiRow}>
                      <span className={styles.kpiLabel}>Total Calls</span>
                      <span className={styles.kpiValue}>{s.total_calls.toLocaleString()}</span>
                    </div>
                  </div>

                  <div className={styles.cardImpact}>
                    <span className={styles.impactLabel}>Monthly Impact</span>
                    <span className={styles.impactValue}>{fmt(s.monthly_impact)}</span>
                  </div>

                  <button
                    className={styles.viewBtn}
                    onClick={() => navigate(`/agency/store/${s.store_id}`)}
                  >
                    View Store →
                  </button>
                </div>
              )
            })}
          </div>

          {/* Needs attention (주의 필요 스토어) */}
          {attentionStores.length > 0 && (
            <div className={styles.attentionBox}>
              <div className={styles.attentionTitle}>⚠ Needs Attention</div>
              <div className={styles.attentionSub}>
                Stores with conversion rate below 50%
              </div>
              {attentionStores.map((s) => (
                <div key={s.store_id} className={styles.attentionRow}>
                  <span>{getVerticalMeta(s.industry).icon} {s.store_name}</span>
                  <span className={styles.kpiWarn}>{s.conversion_rate.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
