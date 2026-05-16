// Agency Overview — aggregated KPIs + per-store card grid
// (에이전시 개요 — 전체 집계 KPI + 스토어별 카드 그리드)
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import { getStoreMode } from '../admin/proofConstants'
import StoreViewToggle, {
  StoreViewMode,
  loadStoreView,
  saveStoreView,
} from '../../components/store-view/StoreViewToggle'
import styles from './Overview.module.css'

const VIEW_STORAGE_KEY = 'jm_agency_store_view'

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
  const [errorStatus, setErrorStatus] = useState<number | null>(null)
  const [view, setView] = useState<StoreViewMode>(() => loadStoreView(VIEW_STORAGE_KEY))
  const navigate = useNavigate()

  const onViewChange = (next: StoreViewMode) => {
    setView(next)
    saveStoreView(VIEW_STORAGE_KEY, next)
  }

  useEffect(() => {
    setLoading(true)
    setErrorStatus(null)
    api
      .get(`/agency/overview?period=${period}`)
      .then((r) => { setData(r.data); setErrorStatus(null) })
      .catch((err) => {
        const status = err?.response?.status ?? 0
        setErrorStatus(status)
      })
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

      {errorStatus === 403 ? (
        <div className={styles.errorCard}>
          <div className={styles.errorTitle}>⚠ No agency profile linked to your account</div>
          <div className={styles.errorBody}>
            Your account is authenticated but has no <code>agencies.owner_id</code> mapping.
            Ask the platform admin to link this email to an agency in Admin → Agencies.
          </div>
        </div>
      ) : errorStatus && errorStatus !== 0 ? (
        <div className={styles.errorCard}>
          <div className={styles.errorTitle}>⚠ Failed to load agency data ({errorStatus})</div>
          <div className={styles.errorBody}>Please retry or contact support if this persists.</div>
        </div>
      ) : loading ? (
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

          {/* Section header with view toggle (섹션 헤더 + 뷰 토글) */}
          <div className={styles.sectionHeaderRow}>
            <h2 className={styles.sectionTitle}>STORE PERFORMANCE</h2>
            <StoreViewToggle value={view} onChange={onViewChange} />
          </div>

          {view === 'cards' && (
            <div className={styles.cardGrid}>
              {(data?.stores ?? []).map((s) => {
                const meta = getVerticalMeta(s.industry)
                const mode = getStoreMode(s.store_id)
                return (
                  <div key={s.store_id} className={styles.storeCard}>
                    <div className={styles.cardHeader}>
                      <span className={styles.cardIcon}>{meta.icon}</span>
                      <div className={styles.cardHeaderText}>
                        <div className={styles.cardStoreName}>{s.store_name}</div>
                        <div className={styles.cardIndustry}>{meta.industryLabel}</div>
                      </div>
                      {mode.mode === 'real' ? (
                        <span className={styles.modeRealBadge} title={`Live since ${mode.since}`}>
                          ✓ Real
                        </span>
                      ) : (
                        <span className={styles.modeSimBadge} title="Synthetic 60-day window">
                          Sim
                        </span>
                      )}
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
          )}

          {view === 'list' && (
            <div className={styles.listWrap}>
              <table className={styles.listTable}>
                <thead>
                  <tr>
                    <th>STORE</th>
                    <th>MODE</th>
                    <th className={styles.numCol}>REVENUE</th>
                    <th className={styles.numCol}>LABOR SAVINGS</th>
                    <th className={styles.numCol}>CONVERSION</th>
                    <th className={styles.numCol}>CALLS</th>
                    <th className={styles.numCol}>IMPACT</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {(data?.stores ?? []).map((s) => {
                    const meta = getVerticalMeta(s.industry)
                    const mode = getStoreMode(s.store_id)
                    return (
                      <tr key={s.store_id} className={styles.listRow}>
                        <td>
                          <span className={styles.listIcon}>{meta.icon}</span>
                          <span className={styles.listName}>{s.store_name}</span>
                          <span className={styles.listIndustry}>· {meta.industryLabel}</span>
                        </td>
                        <td>
                          {mode.mode === 'real' ? (
                            <span className={styles.modeRealBadge}>✓ Real</span>
                          ) : (
                            <span className={styles.modeSimBadge}>Sim</span>
                          )}
                        </td>
                        <td className={styles.numCol}>{fmt(s.primary_revenue)}</td>
                        <td className={styles.numCol}>{fmt(s.labor_savings)}</td>
                        <td className={`${styles.numCol} ${s.conversion_rate < 50 ? styles.kpiWarn : ''}`}>
                          {s.conversion_rate.toFixed(1)}%
                        </td>
                        <td className={styles.numCol}>{s.total_calls.toLocaleString()}</td>
                        <td className={`${styles.numCol} ${styles.listImpact}`}>{fmt(s.monthly_impact)}</td>
                        <td>
                          <button
                            className={styles.listBtn}
                            onClick={() => navigate(`/agency/store/${s.store_id}`)}
                          >
                            View →
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {view === 'compact' && (
            <div className={styles.compactList}>
              {(data?.stores ?? []).map((s) => {
                const meta = getVerticalMeta(s.industry)
                const warn = s.conversion_rate < 50
                return (
                  <button
                    key={s.store_id}
                    className={styles.compactRow}
                    onClick={() => navigate(`/agency/store/${s.store_id}`)}
                  >
                    <span className={`${styles.compactDot} ${warn ? styles.dotWarn : styles.dotOk}`} />
                    <span className={styles.compactIcon}>{meta.icon}</span>
                    <span className={styles.compactName}>{s.store_name}</span>
                    <span className={styles.compactMeta}>{fmt(s.monthly_impact)} impact</span>
                    <span className={styles.compactCallsMeta}>
                      {s.total_calls.toLocaleString()} calls · {s.conversion_rate.toFixed(0)}%
                    </span>
                    <span className={styles.compactArrow}>→</span>
                  </button>
                )
              })}
            </div>
          )}

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
