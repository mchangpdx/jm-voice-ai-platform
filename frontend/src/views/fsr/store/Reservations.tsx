// Reservations — AI-captured reservation management with status workflow
// (AI가 수집한 예약 관리 페이지 — 상태 워크플로우 포함)
import { useEffect, useState, useCallback } from 'react'
import api from '../../../core/api'
import styles from './Reservations.module.css'

type Period       = 'today' | 'week' | 'month' | 'all'
type StatusFilter = 'all' | 'pending' | 'confirmed' | 'seated' | 'cancelled'

interface ReservationItem {
  id: number
  call_log_id: string | null
  customer_name: string | null
  customer_phone: string | null
  party_size: number
  reservation_time: string
  status: string
  notes: string | null
  created_at: string
}

interface ReservationsResponse {
  items: ReservationItem[]
  total: number
  page: number
  pages: number
  limit: number
  total_covers: number
  status_counts: Record<string, number>
}

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today'  },
  { key: 'week',  label: 'Week'   },
  { key: 'month', label: 'Month'  },
  { key: 'all',   label: 'All'    },
]

const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: 'all',       label: 'All'       },
  { key: 'confirmed', label: 'Confirmed' },
  { key: 'pending',   label: 'Pending'   },
  { key: 'seated',    label: 'Seated'    },
  { key: 'cancelled', label: 'Cancelled' },
]

const PAGE_LIMIT = 20

function fmtDateShort(iso: string) {
  try {
    return new Date(iso).toLocaleString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
      timeZone: 'America/Los_Angeles',
    })
  } catch { return iso }
}

function isUpcoming(iso: string) {
  return new Date(iso) > new Date()
}

function badgeClass(status: string) {
  const map: Record<string, string> = {
    confirmed: styles.badgeConfirmed,
    pending:   styles.badgePending,
    seated:    styles.badgeSeated,
    cancelled: styles.badgeCancelled,
    no_show:   styles.badgeNoShow,
  }
  return `${styles.badge} ${map[status] ?? styles.badgePending}`
}

export default function Reservations() {
  const [period,   setPeriod]   = useState<Period>('month')
  const [statusF,  setStatus]   = useState<StatusFilter>('all')
  const [page,     setPage]     = useState(1)
  const [data,     setData]     = useState<ReservationsResponse | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [updating, setUpdating] = useState<number | null>(null)

  const fetchData = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ period, page: String(page), limit: String(PAGE_LIMIT) })
    if (statusF !== 'all') params.set('status', statusF)
    api.get(`/store/reservations?${params}`)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false))
  }, [period, statusF, page])

  useEffect(() => { fetchData() }, [fetchData])

  // Reset to page 1 when filters change (필터 변경 시 1페이지로 초기화)
  useEffect(() => { setPage(1) }, [period, statusF])

  async function updateStatus(id: number, newStatus: string) {
    setUpdating(id)
    try {
      await api.patch(`/store/reservations/${id}`, { status: newStatus })
      fetchData()
    } finally {
      setUpdating(null)
    }
  }

  const items   = data?.items ?? []
  const total   = data?.total ?? 0
  const pages   = data?.pages ?? 1
  const counts  = data?.status_counts ?? {}

  return (
    <div className={styles.page}>
      {/* Header (헤더) */}
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Reservations</h1>
        <p className={styles.pageDesc}>AI-captured reservations — confirm, seat, and track your guests.</p>
      </div>

      {/* Summary cards (요약 카드) */}
      {!loading && data && (
        <div className={styles.summaryRow}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Total</div>
            <div className={styles.summaryValue}>{total}</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Confirmed</div>
            <div className={`${styles.summaryValue} ${styles.confirmed}`}>{counts.confirmed ?? 0}</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Pending</div>
            <div className={`${styles.summaryValue} ${styles.pending}`}>{counts.pending ?? 0}</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Seated</div>
            <div className={`${styles.summaryValue} ${styles.seated}`}>{counts.seated ?? 0}</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Total Covers</div>
            <div className={styles.summaryValue}>{data?.total_covers ?? 0}</div>
          </div>
        </div>
      )}

      {/* Filters (필터) */}
      <div className={styles.filtersRow}>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Period:</span>
          {PERIODS.map(({ key, label }) => (
            <button
              key={key}
              className={`${styles.filterBtn} ${period === key ? styles.filterBtnActive : ''}`}
              onClick={() => setPeriod(key)}
            >{label}</button>
          ))}
        </div>

        <div className={styles.statusTabs}>
          {STATUS_TABS.map(({ key, label }) => (
            <button
              key={key}
              className={`${styles.statusTab} ${statusF === key ? `${styles.statusTabActive} ${styles[key]}` : ''}`}
              onClick={() => setStatus(key)}
            >
              {label}
              {key !== 'all' && counts[key] != null && (
                <span className={styles.tabCount}>{counts[key]}</span>
              )}
              {key === 'all' && (
                <span className={styles.tabCount}>{total}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Table (테이블) */}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>DATE &amp; TIME</th>
              <th>GUEST</th>
              <th>PHONE</th>
              <th>PARTY</th>
              <th>STATUS</th>
              <th>NOTES / SOURCE</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr className={styles.emptyRow}><td colSpan={7}>Loading reservations...</td></tr>
            ) : items.length === 0 ? (
              <tr className={styles.emptyRow}><td colSpan={7}>No reservations found for this period</td></tr>
            ) : items.map((r) => (
              <tr key={r.id}>
                <td className={styles.cellTime}>
                  {isUpcoming(r.reservation_time) && (
                    <span style={{ fontSize: 10, background: '#dcfce7', color: '#15803d', padding: '1px 5px', borderRadius: 4, marginRight: 5, fontWeight: 600 }}>
                      UPCOMING
                    </span>
                  )}
                  {fmtDateShort(r.reservation_time)}
                </td>
                <td className={styles.cellName}>{r.customer_name ?? '—'}</td>
                <td className={styles.cellPhone}>{r.customer_phone ?? '—'}</td>
                <td className={styles.cellParty}>
                  <span style={{ fontSize: 14 }}>👥</span> {r.party_size}
                </td>
                <td><span className={badgeClass(r.status)}>{r.status}</span></td>
                <td className={styles.cellNotes}>{r.notes ?? '—'}</td>
                <td>
                  <div className={styles.actions}>
                    {r.status === 'pending' && (
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnConfirm}`}
                        disabled={updating === r.id}
                        onClick={() => updateStatus(r.id, 'confirmed')}
                      >Confirm</button>
                    )}
                    {(r.status === 'pending' || r.status === 'confirmed') && (
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnSeated}`}
                        disabled={updating === r.id}
                        onClick={() => updateStatus(r.id, 'seated')}
                      >Seated</button>
                    )}
                    {r.status !== 'cancelled' && r.status !== 'seated' && (
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnCancel}`}
                        disabled={updating === r.id}
                        onClick={() => updateStatus(r.id, 'cancelled')}
                      >Cancel</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination (페이지네이션) */}
        {!loading && total > PAGE_LIMIT && (
          <div className={styles.pagination}>
            <span className={styles.paginationInfo}>
              Showing {(page - 1) * PAGE_LIMIT + 1}–{Math.min(page * PAGE_LIMIT, total)} of {total}
            </span>
            <div className={styles.paginationBtns}>
              <button className={styles.pageBtn} disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
              {Array.from({ length: Math.min(pages, 5) }, (_, i) => {
                const p = page <= 3 ? i + 1 : page - 2 + i
                if (p < 1 || p > pages) return null
                return (
                  <button key={p}
                    className={`${styles.pageBtn} ${p === page ? styles.pageBtnActive : ''}`}
                    onClick={() => setPage(p)}
                  >{p}</button>
                )
              })}
              <button className={styles.pageBtn} disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
