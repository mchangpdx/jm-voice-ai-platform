// System Health — operational dashboard for platform admin.
// (시스템 헬스 — 플랫폼 운영자용 대시보드)
//
// Three panels:
//  1. Sync Freeze — POS webhook freeze state per store
//  2. Call Volume — 1h / 24h / 7d totals + error rate
//  3. API Errors — recent 4xx/5xx from in-memory ring buffer
import { useEffect, useState } from 'react'
import api from '../../core/api'
import styles from './SystemHealth.module.css'

interface FreezeStatus {
  global_frozen: boolean
  active: Record<string, { expires_at: string }>
}
interface WebhooksHealth {
  sync_freeze: FreezeStatus
  globally_frozen: boolean
  active_freeze_count: number
}

interface CallWindow {
  total: number
  failed: number
  error_rate: number
}
interface CallsHealth {
  '1h':  CallWindow
  '24h': CallWindow
  '7d':  CallWindow
}

interface ApiErrorEntry {
  ts:     number
  method: string
  path:   string
  status: number
  client: string | null
}
interface ApiErrorsHealth {
  summary: {
    window_seconds: number
    total_4xx:      number
    total_5xx:      number
    by_status:      Record<string, number>
    top_endpoints:  { endpoint: string; count: number }[]
  }
  recent: ApiErrorEntry[]
}

const REFRESH_MS = 30_000

const fmtTime = (ts: number) => {
  try {
    return new Date(ts * 1000).toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return '—' }
}

const errorRatePct = (r: number) => (r * 100).toFixed(2) + '%'

const statusColorClass = (status: number) => {
  if (status >= 500) return styles.status5xx
  if (status >= 400) return styles.status4xx
  return styles.status2xx
}

const rateColorClass = (rate: number) => {
  if (rate >= 0.05) return styles.rateBad
  if (rate >= 0.01) return styles.rateWarn
  return styles.rateOk
}

export default function SystemHealth() {
  const [webhooks,  setWebhooks]  = useState<WebhooksHealth | null>(null)
  const [calls,     setCalls]     = useState<CallsHealth | null>(null)
  const [apiErrors, setApiErrors] = useState<ApiErrorsHealth | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchAll = () =>
    Promise.allSettled([
      api.get('/admin/health/webhooks').then((r) => setWebhooks(r.data)),
      api.get('/admin/health/calls').then((r) => setCalls(r.data)),
      api.get('/admin/health/api-errors?window_seconds=3600&limit=50')
        .then((r) => setApiErrors(r.data)),
    ]).finally(() => {
      setLoading(false)
      setLastRefresh(new Date())
    })

  useEffect(() => {
    fetchAll()
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const id = window.setInterval(fetchAll, REFRESH_MS)
    return () => window.clearInterval(id)
  }, [autoRefresh])

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>System Health</h1>
          <p className={styles.subtitle}>
            Sync freeze state, call volume, and API error rate. Refreshes every 30s.
          </p>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.lastRefresh}>
            Updated {lastRefresh.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
          <label className={styles.autoToggle}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh
          </label>
          <button className={styles.refreshBtn} onClick={fetchAll} disabled={loading}>
            ↺ Refresh
          </button>
        </div>
      </div>

      {/* ── Panel 1: Sync Freeze ────────────────────────────────────────── */}
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <span className={styles.panelIcon}>❄</span>
          <h2 className={styles.panelTitle}>POS Sync Freeze</h2>
          {webhooks?.globally_frozen ? (
            <span className={`${styles.pill} ${styles.pillBad}`}>● Globally frozen</span>
          ) : webhooks && webhooks.active_freeze_count > 0 ? (
            <span className={`${styles.pill} ${styles.pillWarn}`}>
              {webhooks.active_freeze_count} store(s) frozen
            </span>
          ) : (
            <span className={`${styles.pill} ${styles.pillOk}`}>● Healthy</span>
          )}
        </div>
        {!webhooks ? (
          <div className={styles.empty}>Loading…</div>
        ) : webhooks.active_freeze_count === 0 ? (
          <div className={styles.emptyOk}>
            No freezes active. POS webhooks are processed normally.
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>SCOPE</th>
                <th>EXPIRES AT</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(webhooks.sync_freeze.active).map(([scope, info]) => (
                <tr key={scope}>
                  <td className={styles.mono}>{scope === '*' ? 'ALL STORES' : scope}</td>
                  <td className={styles.mono}>{info.expires_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Panel 2: Call Volume ────────────────────────────────────────── */}
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <span className={styles.panelIcon}>📞</span>
          <h2 className={styles.panelTitle}>Voice Agent Calls</h2>
        </div>
        {!calls ? (
          <div className={styles.empty}>Loading…</div>
        ) : (
          <div className={styles.kpiRow}>
            {(['1h', '24h', '7d'] as const).map((w) => {
              const c = calls[w]
              return (
                <div key={w} className={styles.kpiCard}>
                  <div className={styles.kpiLabel}>Last {w}</div>
                  <div className={styles.kpiValue}>{c.total.toLocaleString()}</div>
                  <div className={styles.kpiSub}>
                    <span className={rateColorClass(c.error_rate)}>
                      {errorRatePct(c.error_rate)} failed
                    </span>
                    <span className={styles.kpiSubMute}>
                      {' '}({c.failed.toLocaleString()})
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* ── Panel 3: API Errors ─────────────────────────────────────────── */}
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <span className={styles.panelIcon}>⚠</span>
          <h2 className={styles.panelTitle}>API Errors (last 1h)</h2>
          {apiErrors && (apiErrors.summary.total_5xx > 0) ? (
            <span className={`${styles.pill} ${styles.pillBad}`}>
              {apiErrors.summary.total_5xx} 5xx
            </span>
          ) : apiErrors && (apiErrors.summary.total_4xx > 0) ? (
            <span className={`${styles.pill} ${styles.pillWarn}`}>
              {apiErrors.summary.total_4xx} 4xx
            </span>
          ) : (
            <span className={`${styles.pill} ${styles.pillOk}`}>● No errors</span>
          )}
        </div>
        {!apiErrors ? (
          <div className={styles.empty}>Loading…</div>
        ) : apiErrors.recent.length === 0 ? (
          <div className={styles.emptyOk}>No errors in the last hour.</div>
        ) : (
          <>
            <div className={styles.summaryRow}>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>4xx</span>
                <span className={styles.summaryValue}>
                  {apiErrors.summary.total_4xx}
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>5xx</span>
                <span className={`${styles.summaryValue} ${styles.status5xx}`}>
                  {apiErrors.summary.total_5xx}
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>By Status</span>
                <span className={styles.summaryValue}>
                  {Object.entries(apiErrors.summary.by_status)
                    .map(([s, n]) => `${s}:${n}`)
                    .join('  ')}
                </span>
              </div>
            </div>

            {apiErrors.summary.top_endpoints.length > 0 && (
              <>
                <h3 className={styles.subhead}>Top Endpoints</h3>
                <div className={styles.topList}>
                  {apiErrors.summary.top_endpoints.map((e) => (
                    <div key={e.endpoint} className={styles.topRow}>
                      <span className={styles.mono}>{e.endpoint}</span>
                      <span className={styles.topCount}>{e.count}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            <h3 className={styles.subhead}>Recent Errors</h3>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>TIME</th>
                  <th>STATUS</th>
                  <th>METHOD</th>
                  <th>PATH</th>
                  <th>CLIENT</th>
                </tr>
              </thead>
              <tbody>
                {apiErrors.recent.map((e, i) => (
                  <tr key={i}>
                    <td className={styles.mono}>{fmtTime(e.ts)}</td>
                    <td>
                      <span className={`${styles.statusBadge} ${statusColorClass(e.status)}`}>
                        {e.status}
                      </span>
                    </td>
                    <td className={styles.mono}>{e.method}</td>
                    <td className={styles.mono}>{e.path}</td>
                    <td className={styles.mono}>{e.client ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  )
}
