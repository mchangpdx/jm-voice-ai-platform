// Call History — paginated call log with filters and expandable detail rows
// (필터 + 페이징 + 상세 확장 통화 내역 페이지)
import { Fragment, useEffect, useState } from 'react'
import api from '../../../core/api'
import styles from './CallHistory.module.css'

type Period = 'today' | 'week' | 'month' | 'all'
type StatusFilter = 'all' | 'Successful' | 'Unsuccessful'

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

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'Week'  },
  { key: 'month', label: 'Month' },
  { key: 'all',   label: 'All'   },
]

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all',           label: 'All'          },
  { key: 'Successful',    label: 'Successful'   },
  { key: 'Unsuccessful',  label: 'Unsuccessful' },
]

const PAGE_LIMIT = 20

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

export default function CallHistory() {
  const [period, setPeriod]       = useState<Period>('all')
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

    api.get(`/store/call-logs?${params}`)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false))
  }, [period, statusFilter, page])

  // Reset to page 1 when filters change (필터 변경 시 첫 페이지로 초기화)
  useEffect(() => { setPage(1) }, [period, statusFilter])

  const items   = data?.items ?? []
  const total   = data?.total ?? 0
  const pages   = data?.pages ?? 1
  const success = items.filter((c) => c.call_status === 'Successful').length
  const totalDur = items.reduce((s, c) => s + c.duration, 0)
  const totalCost = items.reduce((s, c) => s + c.cost, 0)

  function toggleExpand(id: string) {
    setExpanded((prev) => (prev === id ? null : id))
  }

  function sentimentClass(s: string | null) {
    if (s === 'Positive') return styles.sentimentPositive
    if (s === 'Negative') return styles.sentimentNegative
    return styles.sentimentNeutral
  }

  return (
    <div className={styles.page}>
      {/* Header (헤더) */}
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Call History</h1>
        <p className={styles.pageDesc}>
          AI-handled call logs — status, sentiment, duration, and transcript details.
        </p>
      </div>

      {/* Filters (필터) */}
      <div className={styles.filtersRow}>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Period:</span>
          {PERIODS.map(({ key, label }) => (
            <button
              key={key}
              className={`${styles.filterBtn} ${period === key ? styles.filterBtnActive : ''}`}
              onClick={() => setPeriod(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Status:</span>
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

      {/* Stats strip (요약 통계) */}
      {!loading && data && (
        <div className={styles.statsStrip}>
          <div className={styles.stat}>
            <span className={styles.statLabel}>Total Calls</span>
            <span className={styles.statValue}>{total.toLocaleString()}</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statLabel}>Successful</span>
            <span className={styles.statValue} style={{ color: '#16a34a' }}>
              {statusFilter === 'all' ? total > 0 ? `${((success / items.length) * 100).toFixed(0)}%` : '—' : items.length}
            </span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statLabel}>Avg Duration</span>
            <span className={styles.statValue}>
              {items.length > 0 ? fmtDuration(Math.round(totalDur / items.length)) : '—'}
            </span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statLabel}>Total Cost (page)</span>
            <span className={styles.statValue}>${totalCost.toFixed(2)}</span>
          </div>
        </div>
      )}

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
              <th>SUMMARY</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr className={styles.emptyRow}>
                <td colSpan={8}>Loading call history...</td>
              </tr>
            ) : items.length === 0 ? (
              <tr className={styles.emptyRow}>
                <td colSpan={8}>No calls found for this period</td>
              </tr>
            ) : (
              items.map((c) => (
                <Fragment key={c.call_id}>
                  <tr
                    className={expandedId === c.call_id ? styles.expanded : ''}
                    onClick={() => toggleExpand(c.call_id)}
                  >
                    <td className={styles.cellDate}>{fmtDate(c.start_time)}</td>
                    <td className={styles.cellPhone}>{c.customer_phone ?? '—'}</td>
                    <td className={styles.cellDuration}>{fmtDuration(c.duration)}</td>
                    <td>
                      <span className={`${styles.statusBadge} ${c.call_status === 'Successful' ? styles.statusSuccess : styles.statusFail}`}>
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
                    <td className={styles.cellCost}>${c.cost.toFixed(2)}</td>
                    <td className={styles.cellSummary}>{c.summary ?? '—'}</td>
                  </tr>

                  {expandedId === c.call_id && (
                    <tr className={styles.expandedRow}>
                      <td colSpan={8}>
                        <div className={styles.expandedContent}>
                          <div className={styles.expandedSection}>
                            <div className={styles.expandedSectionTitle}>Call Summary</div>
                            <p className={styles.summaryText}>{c.summary ?? 'No summary available.'}</p>
                          </div>
                          <div className={styles.expandedSection}>
                            <div className={styles.expandedSectionTitle}>Recording</div>
                            {c.recording_url
                              ? (
                                // HTML5 audio player — plays inline regardless of
                                // Content-Disposition: attachment from CDN
                                // (CDN의 Content-Disposition: attachment 무시하고 인라인 재생)
                                <audio
                                  controls
                                  src={c.recording_url}
                                  className={styles.audioPlayer}
                                  onClick={(e) => e.stopPropagation()}
                                  preload="none"
                                >
                                  Your browser does not support audio playback.
                                </audio>
                              )
                              : <span className={styles.noRecording}>No recording available</span>
                            }
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination (페이지네이션) */}
        {!loading && total > 0 && (
          <div className={styles.pagination}>
            <span className={styles.paginationInfo}>
              Showing {(page - 1) * PAGE_LIMIT + 1}–{Math.min(page * PAGE_LIMIT, total)} of {total} calls
            </span>
            <div className={styles.paginationBtns}>
              <button
                className={styles.pageBtn}
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
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
              <button
                className={styles.pageBtn}
                disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
