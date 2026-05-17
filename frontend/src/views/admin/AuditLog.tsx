// Audit Log — every admin mutation in chronological order.
// (감사 로그 — 모든 admin mutation 시간순)
import { useEffect, useState } from 'react'
import api from '../../core/api'
import styles from './AuditLog.module.css'

interface AuditEntry {
  id: string
  actor_user_id: string
  actor_email: string | null
  action: string
  target_type: string | null
  target_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

const PAGE_SIZE = 50

type ActionScope = '' | 'agency.' | 'store.' | 'user.'
type TargetType  = '' | 'agency' | 'store' | 'user'
type RangeKey    = 'all' | '24h' | '7d' | '30d'

const ACTION_CHIPS: { key: ActionScope; label: string }[] = [
  { key: '',         label: 'All actions' },
  { key: 'agency.',  label: 'agency.*' },
  { key: 'store.',   label: 'store.*' },
  { key: 'user.',    label: 'user.*' },
]

const TARGET_CHIPS: { key: TargetType; label: string }[] = [
  { key: '',         label: 'All targets' },
  { key: 'agency',   label: 'agency' },
  { key: 'store',    label: 'store' },
  { key: 'user',     label: 'user' },
]

const RANGE_CHIPS: { key: RangeKey; label: string; hours: number | null }[] = [
  { key: 'all', label: 'All time', hours: null },
  { key: '24h', label: 'Last 24h', hours: 24 },
  { key: '7d',  label: 'Last 7d',  hours: 24 * 7 },
  { key: '30d', label: 'Last 30d', hours: 24 * 30 },
]

const sinceIso = (hours: number | null): string | null =>
  hours == null
    ? null
    : new Date(Date.now() - hours * 3600_000).toISOString()

const fmtTime = (iso: string) => {
  try {
    return new Date(iso).toLocaleString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return iso }
}

const actionBadge = (action: string) => {
  if (action.endsWith('.delete')) return styles.badgeDelete
  if (action.endsWith('.create')) return styles.badgeCreate
  if (action.endsWith('.transfer')) return styles.badgeTransfer
  return styles.badgeUpdate
}

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [offset, setOffset] = useState(0)
  const [actionFilter, setActionFilter] = useState<ActionScope>('')
  const [targetTypeFilter, setTargetTypeFilter] = useState<TargetType>('')
  const [rangeFilter, setRangeFilter] = useState<RangeKey>('all')
  const [expanded, setExpanded] = useState<string>('')
  const [hasMore, setHasMore] = useState(false)

  const buildParams = (forOffset: number): string => {
    const params = new URLSearchParams()
    params.set('limit', String(PAGE_SIZE))
    params.set('offset', String(forOffset))
    if (actionFilter) params.set('action', actionFilter)
    if (targetTypeFilter) params.set('target_type', targetTypeFilter)
    const rangeMeta = RANGE_CHIPS.find((c) => c.key === rangeFilter)
    const since = sinceIso(rangeMeta?.hours ?? null)
    if (since) params.set('since', since)
    return params.toString()
  }

  const load = (resetOffset = false) => {
    setLoading(true)
    const nextOffset = resetOffset ? 0 : offset
    api
      .get(`/admin/audit-logs?${buildParams(nextOffset)}`)
      .then((r) => {
        const data = r.data as AuditEntry[]
        if (resetOffset) {
          setEntries(data)
          setOffset(0)
        } else {
          setEntries((prev) => [...prev, ...data])
        }
        setHasMore(data.length === PAGE_SIZE)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionFilter, targetTypeFilter, rangeFilter])

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Audit Log</h1>
          <p className={styles.subtitle}>
            Every admin mutation — who, what, when, before/after.
          </p>
        </div>
        <div className={styles.policyChips}>
          <span className={styles.chipImmutable} title="UPDATE/DELETE rejected at the DB trigger level. Service role cannot rewrite history.">
            🔒 Append-only
          </span>
          <span className={styles.chipRetention} title="Rows past 90 days are auto-purged daily by the backend retention loop.">
            🗑 90-day retention
          </span>
        </div>
      </div>

      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <div className={styles.filterGroupLabel}>Action</div>
          <div className={styles.chipRow} role="radiogroup" aria-label="Action filter">
            {ACTION_CHIPS.map((c) => (
              <button
                key={c.key || 'all'}
                type="button"
                role="radio"
                aria-checked={actionFilter === c.key}
                className={`${styles.chip} ${actionFilter === c.key ? styles.chipActive : ''}`}
                onClick={() => setActionFilter(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <div className={styles.filterGroup}>
          <div className={styles.filterGroupLabel}>Target</div>
          <div className={styles.chipRow} role="radiogroup" aria-label="Target filter">
            {TARGET_CHIPS.map((c) => (
              <button
                key={c.key || 'all'}
                type="button"
                role="radio"
                aria-checked={targetTypeFilter === c.key}
                className={`${styles.chip} ${targetTypeFilter === c.key ? styles.chipActive : ''}`}
                onClick={() => setTargetTypeFilter(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <div className={styles.filterGroup}>
          <div className={styles.filterGroupLabel}>Range</div>
          <div className={styles.chipRow} role="radiogroup" aria-label="Time range filter">
            {RANGE_CHIPS.map((c) => (
              <button
                key={c.key}
                type="button"
                role="radio"
                aria-checked={rangeFilter === c.key}
                className={`${styles.chip} ${rangeFilter === c.key ? styles.chipActive : ''}`}
                onClick={() => setRangeFilter(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <button
          className={styles.refreshBtn}
          onClick={() => load(true)}
          disabled={loading}
          aria-label="Refresh"
        >
          {loading ? '…' : '↺ Refresh'}
        </button>
      </div>

      {loading && entries.length === 0 ? (
        <div className={styles.empty}>Loading…</div>
      ) : entries.length === 0 ? (
        <div className={styles.empty}>No audit log entries.</div>
      ) : (
        <>
          <div className={styles.timeline}>
            {entries.map((e) => {
              const isOpen = expanded === e.id
              return (
                <div key={e.id} className={styles.entry}>
                  <div
                    className={styles.entryHead}
                    onClick={() => setExpanded(isOpen ? '' : e.id)}
                  >
                    <span className={`${styles.badge} ${actionBadge(e.action)}`}>
                      {e.action}
                    </span>
                    <span className={styles.actor}>{e.actor_email ?? e.actor_user_id.slice(0, 8)}</span>
                    <span className={styles.target}>
                      {e.target_type ?? '—'}
                      {e.target_id ? ` · ${e.target_id.slice(0, 8)}…` : ''}
                    </span>
                    <span className={styles.time}>{fmtTime(e.created_at)}</span>
                    <span className={styles.toggle}>{isOpen ? '▾' : '▸'}</span>
                  </div>
                  {isOpen && (
                    <div className={styles.entryBody}>
                      <div className={styles.kv}>
                        <strong>IP:</strong> <code>{e.ip_address ?? '—'}</code>
                      </div>
                      <div className={styles.diffGrid}>
                        <div>
                          <div className={styles.diffLabel}>BEFORE</div>
                          <pre className={styles.json}>
                            {e.before ? JSON.stringify(e.before, null, 2) : 'null'}
                          </pre>
                        </div>
                        <div>
                          <div className={styles.diffLabel}>AFTER</div>
                          <pre className={styles.json}>
                            {e.after ? JSON.stringify(e.after, null, 2) : 'null'}
                          </pre>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {hasMore && (
            <div className={styles.loadMoreWrap}>
              <button
                className={styles.loadMore}
                disabled={loading}
                onClick={() => {
                  const next = offset + PAGE_SIZE
                  setOffset(next)
                  setLoading(true)
                  api
                    .get(`/admin/audit-logs?${buildParams(next)}`)
                    .then((r) => {
                      const data = r.data as AuditEntry[]
                      setEntries((prev) => [...prev, ...data])
                      setHasMore(data.length === PAGE_SIZE)
                    })
                    .catch(() => {})
                    .finally(() => setLoading(false))
                }}
              >
                {loading ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
