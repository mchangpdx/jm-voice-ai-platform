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
  const [actionFilter, setActionFilter] = useState('')
  const [targetTypeFilter, setTargetTypeFilter] = useState('')
  const [expanded, setExpanded] = useState<string>('')
  const [hasMore, setHasMore] = useState(false)

  const load = (resetOffset = false) => {
    setLoading(true)
    const nextOffset = resetOffset ? 0 : offset
    const params = new URLSearchParams()
    params.set('limit', String(PAGE_SIZE))
    params.set('offset', String(nextOffset))
    if (actionFilter) params.set('action', actionFilter)
    if (targetTypeFilter) params.set('target_type', targetTypeFilter)
    api
      .get(`/admin/audit-logs?${params.toString()}`)
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
  }, [actionFilter, targetTypeFilter])

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
        <label className={styles.filterLabel}>
          Action
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className={styles.select}
          >
            <option value="">All</option>
            <option value="agency.">agency.*</option>
            <option value="store.">store.*</option>
            <option value="user.">user.*</option>
          </select>
        </label>

        <label className={styles.filterLabel}>
          Target
          <select
            value={targetTypeFilter}
            onChange={(e) => setTargetTypeFilter(e.target.value)}
            className={styles.select}
          >
            <option value="">All</option>
            <option value="agency">agency</option>
            <option value="store">store</option>
            <option value="user">user</option>
          </select>
        </label>

        <button className={styles.refreshBtn} onClick={() => load(true)} disabled={loading}>
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
                  const params = new URLSearchParams()
                  params.set('limit', String(PAGE_SIZE))
                  params.set('offset', String(next))
                  if (actionFilter) params.set('action', actionFilter)
                  if (targetTypeFilter) params.set('target_type', targetTypeFilter)
                  api
                    .get(`/admin/audit-logs?${params.toString()}`)
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
