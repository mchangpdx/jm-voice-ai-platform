// Call History — paginated call log with filters and expandable detail rows
// (필터 + 페이징 + 상세 확장 통화 내역 페이지)
import { useEffect, useState } from 'react'
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

// Sliding right-side drawer for call detail (우측 슬라이딩 통화 상세 패널)
// ESC key + backdrop click closes. Audio playback inline.
// TODO (backend pending): wire transcript (color-coded Agent 딥블루 / Caller 앰버),
// items + modifiers, CRM context block, and state machine timeline.
function CallDetailDrawer({
  call,
  onClose,
}: {
  call: CallLogItem | null
  onClose: () => void
}) {
  useEffect(() => {
    if (!call) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [call, onClose])

  if (!call) return null

  return (
    <div className={styles.drawerBackdrop} onClick={onClose}>
      <aside
        className={styles.drawer}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Call detail"
      >
        <header className={styles.drawerHeader}>
          <div>
            <div className={styles.drawerPhone}>{call.customer_phone ?? 'Unknown caller'}</div>
            <div className={styles.drawerTime}>{fmtDate(call.start_time)}</div>
          </div>
          <button className={styles.drawerClose} onClick={onClose} aria-label="Close">×</button>
        </header>

        <div className={styles.drawerBody}>
          <div className={styles.drawerStatsRow}>
            <div className={styles.drawerStat}>
              <span>Duration</span><strong>{fmtDuration(call.duration)}</strong>
            </div>
            <div className={styles.drawerStat}>
              <span>Status</span><strong>{call.call_status}</strong>
            </div>
            <div className={styles.drawerStat}>
              <span>Sentiment</span><strong>{call.sentiment ?? '—'}</strong>
            </div>
            <div className={styles.drawerStat}>
              <span>Cost</span><strong>${call.cost.toFixed(2)}</strong>
            </div>
          </div>

          <section className={styles.drawerSection}>
            <h3 className={styles.drawerSectionTitle}>Call Summary</h3>
            <p className={styles.drawerText}>{call.summary ?? 'No summary available.'}</p>
          </section>

          <section className={styles.drawerSection}>
            <h3 className={styles.drawerSectionTitle}>Recording</h3>
            {call.recording_url
              ? (
                <audio
                  controls
                  src={call.recording_url}
                  className={styles.audioPlayer}
                  preload="none"
                >
                  Your browser does not support audio playback.
                </audio>
              )
              : <p className={styles.drawerMuted}>No recording available</p>
            }
          </section>

          <section className={styles.drawerSection}>
            <h3 className={styles.drawerSectionTitle}>Transcript</h3>
            <p className={styles.drawerMuted}>
              Full color-coded transcript (Agent / Caller dialogue) — coming soon (backend pending).
            </p>
          </section>

          <section className={styles.drawerSection}>
            <h3 className={styles.drawerSectionTitle}>Order &amp; CRM</h3>
            <p className={styles.drawerMuted}>
              Items, modifiers, CRM context, and state machine timeline — coming soon (backend pending).
            </p>
          </section>
        </div>
      </aside>
    </div>
  )
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

  // Build CSV from currently visible page (현재 페이지 items로 CSV 생성)
  function exportCsv() {
    if (items.length === 0) return
    const headers = ['Date', 'Caller', 'Duration (s)', 'Status', 'Sentiment', 'Busy', 'Cost', 'Summary']
    const escape = (v: string | number | null | undefined): string => {
      const s = v == null ? '' : String(v)
      return `"${s.replace(/"/g, '""')}"`
    }
    const rows = items.map((c) => [
      escape(c.start_time),
      escape(c.customer_phone),
      escape(c.duration),
      escape(c.call_status),
      escape(c.sentiment),
      escape(c.is_store_busy ? 'Peak' : ''),
      escape(c.cost.toFixed(2)),
      escape(c.summary),
    ].join(','))
    const csv = [headers.map(escape).join(','), ...rows].join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `call-history-${period}-${statusFilter}-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
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
        <button
          className={styles.exportBtn}
          onClick={exportCsv}
          disabled={loading || items.length === 0}
          title="Download current page as CSV"
        >
          📥 Export CSV
        </button>
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
                <tr
                  key={c.call_id}
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

      {/* Sliding right drawer for call detail (우측 슬라이딩 통화 상세) */}
      <CallDetailDrawer
        call={items.find((c) => c.call_id === expandedId) ?? null}
        onClose={() => setExpanded(null)}
      />
    </div>
  )
}
