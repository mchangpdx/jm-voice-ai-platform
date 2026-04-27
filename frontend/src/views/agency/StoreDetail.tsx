// Agency Store Detail — full tabbed store dashboard in agency context
// (에이전시 컨텍스트의 스토어 전체 탭 대시보드)
import { Fragment, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import Analytics from '../fsr/store/Analytics'
import styles from './StoreDetail.module.css'

type Period = 'today' | 'week' | 'month' | 'all'
type Tab    = 'overview' | 'calls' | 'analytics'
type StatusFilter = 'all' | 'Successful' | 'Unsuccessful'

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

interface CallLogItem {
  call_id: string
  start_time: string
  customer_phone: string | null
  duration: number
  sentiment: string | null
  call_status: string
  cost: number
  recording_url: string | null
  summary: string | null
  is_store_busy: boolean
}

interface CallLogsResponse {
  items: CallLogItem[]
  total: number
  page: number
  pages: number
  limit: number
}

const fmt = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function fmtDuration(sec: number) {
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'Week'  },
  { key: 'month', label: 'Month' },
  { key: 'all',   label: 'All'   },
]

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all',          label: 'All'          },
  { key: 'Successful',   label: 'Successful'   },
  { key: 'Unsuccessful', label: 'Unsuccessful' },
]

const PAGE_LIMIT = 20

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ storeId, period }: { storeId: string; period: Period }) {
  const [data, setData]       = useState<StoreMetrics | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api
      .get(`/agency/store/${storeId}/metrics?period=${period}`)
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [storeId, period])

  if (loading) return <div className={styles.loading}>Loading…</div>
  if (!data)   return <div className={styles.loading}>No data available.</div>

  return (
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

      {/* Monthly impact banner (월간 임팩트 배너) */}
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
  )
}

// ── Call History tab ──────────────────────────────────────────────────────────

function CallHistoryTab({ storeId, period }: { storeId: string; period: Period }) {
  const [statusFilter, setStatus] = useState<StatusFilter>('all')
  const [page, setPage]           = useState(1)
  const [data, setData]           = useState<CallLogsResponse | null>(null)
  const [loading, setLoading]     = useState(true)
  const [expandedId, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams({
      period,
      page: String(page),
      limit: String(PAGE_LIMIT),
    })
    if (statusFilter !== 'all') params.set('status', statusFilter)

    api
      .get(`/agency/store/${storeId}/call-logs?${params}`)
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [storeId, period, statusFilter, page])

  useEffect(() => { setPage(1) }, [period, statusFilter])

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const pages = data?.pages ?? 1

  function sentimentClass(s: string | null) {
    if (s === 'Positive') return styles.sentimentPos
    if (s === 'Negative') return styles.sentimentNeg
    return styles.sentimentNeu
  }

  function statusClass(s: string) {
    if (s === 'Successful')   return styles.statusSuccess
    if (s === 'Unsuccessful') return styles.statusFail
    return styles.statusVoice
  }

  return (
    <>
      {/* Filters (필터) */}
      <div className={styles.callFilters}>
        <span className={styles.filterLabel}>Status:</span>
        <div className={styles.filterBtns}>
          {STATUS_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              className={`${styles.filterBtn} ${statusFilter === key ? styles.filterBtnActive : ''}`}
              onClick={() => setStatus(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Table (테이블) */}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>DATE / TIME</th>
              <th>CALLER</th>
              <th>DURATION</th>
              <th>STATUS</th>
              <th>SENTIMENT</th>
              <th>BUSY?</th>
              <th>COST</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr className={styles.emptyRow}>
                <td colSpan={7}>Loading call history…</td>
              </tr>
            ) : items.length === 0 ? (
              <tr className={styles.emptyRow}>
                <td colSpan={7}>No calls found for this period</td>
              </tr>
            ) : (
              items.map((c) => (
                <Fragment key={c.call_id}>
                  <tr
                    style={{ cursor: 'pointer' }}
                    onClick={() => setExpanded((prev) => (prev === c.call_id ? null : c.call_id))}
                  >
                    <td>{fmtDate(c.start_time)}</td>
                    <td style={{ color: '#64748b', fontSize: '12px' }}>{c.customer_phone ?? '—'}</td>
                    <td>{fmtDuration(c.duration)}</td>
                    <td>
                      <span className={`${styles.statusBadge} ${statusClass(c.call_status)}`}>
                        {c.call_status}
                      </span>
                    </td>
                    <td>
                      <span className={`${styles.sentimentBadge} ${sentimentClass(c.sentiment)}`}>
                        {c.sentiment ?? '—'}
                      </span>
                    </td>
                    <td>
                      {c.is_store_busy
                        ? <><span className={styles.busyDot} />Peak</>
                        : <span style={{ color: '#94a3b8' }}>—</span>
                      }
                    </td>
                    <td style={{ color: '#64748b', fontSize: '12px' }}>${c.cost.toFixed(2)}</td>
                  </tr>

                  {expandedId === c.call_id && (
                    <tr>
                      <td colSpan={7} style={{ background: '#f8fafc', padding: '12px 16px' }}>
                        <div style={{ fontSize: '13px', color: '#374151' }}>
                          <strong>Summary:</strong>{' '}
                          {c.summary ?? 'No summary available.'}
                        </div>
                        {c.recording_url && (
                          <audio
                            controls
                            src={c.recording_url}
                            style={{ marginTop: 8, display: 'block', height: 32 }}
                            onClick={(e) => e.stopPropagation()}
                            preload="none"
                          />
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination (페이지네이션) */}
        {!loading && total > PAGE_LIMIT && (
          <div className={styles.pagination}>
            <span>
              Showing {(page - 1) * PAGE_LIMIT + 1}–{Math.min(page * PAGE_LIMIT, total)} of {total}
            </span>
            <div className={styles.paginationBtns}>
              <button className={styles.pageBtn} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                ← Prev
              </button>
              {Array.from({ length: Math.min(pages, 5) }, (_, i) => {
                const p = page <= 3 ? i + 1 : page - 2 + i
                if (p < 1 || p > pages) return null
                return (
                  <button
                    key={p}
                    className={`${styles.pageBtn} ${p === page ? styles.pageBtnActive : ''}`}
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </button>
                )
              })}
              <button className={styles.pageBtn} disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AgencyStoreDetail() {
  const { storeId } = useParams<{ storeId: string }>()
  const [period, setPeriod]   = useState<Period>('month')
  const [tab, setTab]         = useState<Tab>('overview')
  const [storeName, setName]  = useState<string>('')
  const [industry, setIndustry] = useState<string>('')
  const navigate = useNavigate()

  // Fetch store info once to populate header (헤더 표시용 스토어 정보 1회 조회)
  useEffect(() => {
    if (!storeId) return
    api
      .get(`/agency/store/${storeId}/metrics?period=month`)
      .then((r) => {
        setName(r.data.store_name ?? '')
        setIndustry(r.data.industry ?? '')
      })
      .catch(() => {})
  }, [storeId])

  const meta = industry ? getVerticalMeta(industry) : null

  if (!storeId) return null

  const TABS: { key: Tab; label: string }[] = [
    { key: 'overview',   label: '📊 Overview'     },
    { key: 'calls',      label: '📞 Call History'  },
    { key: 'analytics',  label: '📈 Analytics'     },
  ]

  return (
    <div className={styles.page}>
      {/* Header (헤더 — breadcrumb + title + period tabs) */}
      <div className={styles.header}>
        <div>
          <button className={styles.backBtn} onClick={() => navigate('/agency/overview')}>
            ← All Stores
          </button>
          <h1 className={styles.title}>
            {meta?.icon} {storeName || '…'}
          </h1>
          <p className={styles.subtitle}>{meta?.industryLabel ?? ''}</p>
        </div>
        {/* Period tabs only for Overview and Call History (Analytics has its own) */}
        {tab !== 'analytics' && (
          <div className={styles.periodTabs}>
            {PERIODS.map(({ key, label }) => (
              <button
                key={key}
                className={`${styles.periodBtn} ${period === key ? styles.periodBtnActive : ''}`}
                onClick={() => setPeriod(key)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab navigation (탭 내비게이션) */}
      <nav className={styles.tabNav}>
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            className={`${styles.tabBtn} ${tab === key ? styles.tabBtnActive : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Tab content (탭 콘텐츠) */}
      {tab === 'overview' && <OverviewTab storeId={storeId} period={period} />}
      {tab === 'calls'    && <CallHistoryTab storeId={storeId} period={period} />}
      {tab === 'analytics' && (
        <Analytics apiEndpoint={`/agency/store/${storeId}/analytics`} />
      )}
    </div>
  )
}
