// Admin Overview — platform-wide KPIs + vertical breakdown.
// (관리자 개요 — 플랫폼 전체 KPI + vertical 분포)
import { useEffect, useState } from 'react'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import styles from './Overview.module.css'

interface Overview {
  agency_count: number
  store_count: number
  calls_30d: number
  stores_by_vertical: Record<string, number>
}

export default function AdminOverview() {
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorStatus, setErrorStatus] = useState<number | null>(null)

  useEffect(() => {
    api
      .get('/admin/overview')
      .then((r) => setData(r.data))
      .catch((err) => setErrorStatus(err?.response?.status ?? 0))
      .finally(() => setLoading(false))
  }, [])

  const verticalEntries = Object.entries(data?.stores_by_vertical ?? {}).sort(
    (a, b) => b[1] - a[1],
  )

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Platform Overview</h1>
          <p className={styles.subtitle}>Global state of the JM Voice AI platform.</p>
        </div>
      </div>

      {errorStatus === 403 ? (
        <div className={styles.errorCard}>
          <div className={styles.errorTitle}>⚠ Admin role required</div>
          <div className={styles.errorBody}>This account lacks platform admin permission.</div>
        </div>
      ) : loading ? (
        <div className={styles.loading}>Loading…</div>
      ) : (
        <>
          <div className={styles.kpiRow}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Agencies</div>
              <div className={styles.kpiValue}>{data?.agency_count ?? '—'}</div>
              <div className={styles.kpiSub}>Active customer organizations</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Stores</div>
              <div className={styles.kpiValue}>{data?.store_count ?? '—'}</div>
              <div className={styles.kpiSub}>Across all agencies</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Calls (30d)</div>
              <div className={styles.kpiValue}>
                {(data?.calls_30d ?? 0).toLocaleString()}
              </div>
              <div className={styles.kpiSub}>Voice agent calls in the last 30 days</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Verticals</div>
              <div className={styles.kpiValue}>{verticalEntries.length}</div>
              <div className={styles.kpiSub}>Distinct industries deployed</div>
            </div>
          </div>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Stores by Vertical</h2>
            <div className={styles.verticalList}>
              {verticalEntries.map(([vertical, count]) => {
                const meta = getVerticalMeta(vertical)
                const pct =
                  data && data.store_count > 0
                    ? Math.round((count / data.store_count) * 100)
                    : 0
                return (
                  <div key={vertical} className={styles.verticalRow}>
                    <span className={styles.verticalIcon}>{meta.icon}</span>
                    <span className={styles.verticalName}>{meta.industryLabel}</span>
                    <div className={styles.verticalBarTrack}>
                      <div
                        className={styles.verticalBarFill}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className={styles.verticalCount}>
                      {count} <span className={styles.verticalPct}>· {pct}%</span>
                    </span>
                  </div>
                )
              })}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
