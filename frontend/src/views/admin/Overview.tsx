// Admin Overview — platform-wide KPIs + vertical breakdown + traffic chart.
// (관리자 개요 — 플랫폼 전체 KPI + vertical 분포 + 통화량 차트)
import { useEffect, useState } from 'react'
import {
  PieChart, Pie, Cell, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import Skeleton from '../../components/Skeleton/Skeleton'
import styles from './Overview.module.css'

interface Overview {
  agency_count: number
  store_count: number
  calls_30d: number
  stores_by_vertical: Record<string, number>
}

interface CallWindow  { total: number; failed: number; error_rate: number }
interface CallsHealth { '1h': CallWindow; '24h': CallWindow; '7d': CallWindow }

// Donut palette — hex matches tokens.css semantic colors. recharts writes the
// value into the SVG fill attribute, which does not interpolate CSS vars.
// Keep this list in sync if tokens.css palette changes.
const CHART_COLORS = [
  '#6366f1', // --color-brand
  '#16a34a', // --color-success
  '#f59e0b', // --color-warn
  '#0369a1', // --color-info
  '#dc2626', // --color-danger
  '#4338ca', // --color-brand-dark
  '#15803d', // --color-success-dark
  '#b45309', // --color-warn-dark
  '#94a3b8', // --color-text-muted (fallback for overflow)
]

export default function AdminOverview() {
  const [data, setData] = useState<Overview | null>(null)
  const [calls, setCalls] = useState<CallsHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorStatus, setErrorStatus] = useState<number | null>(null)

  useEffect(() => {
    Promise.allSettled([
      api.get('/admin/overview')
        .then((r) => setData(r.data))
        .catch((err) => setErrorStatus(err?.response?.status ?? 0)),
      api.get('/admin/health/calls')
        .then((r) => setCalls(r.data))
        .catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  const verticalEntries = Object.entries(data?.stores_by_vertical ?? {}).sort(
    (a, b) => b[1] - a[1],
  )

  const verticalChartData = verticalEntries.map(([vertical, count]) => ({
    name:  getVerticalMeta(vertical).industryLabel,
    value: count,
    key:   vertical,
  }))

  const callsChartData = calls
    ? (['1h', '24h', '7d'] as const).map((w) => ({
        window:     `Last ${w}`,
        successful: calls[w].total - calls[w].failed,
        failed:     calls[w].failed,
      }))
    : []

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
        <>
          <div className={styles.kpiRow}>
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className={styles.kpiCard}>
                <Skeleton w={60} h={11} />
                <div style={{ height: 12 }} />
                <Skeleton w={120} h={28} />
                <div style={{ height: 8 }} />
                <Skeleton w={160} h={11} />
              </div>
            ))}
          </div>
          <div className={styles.chartGrid}>
            <div className={styles.section}><Skeleton h={260} radius={8} /></div>
            <div className={styles.section}><Skeleton h={260} radius={8} /></div>
          </div>
        </>
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

          <div className={styles.chartGrid}>
            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>Stores by Vertical</h2>
              {verticalChartData.length === 0 ? (
                <div className={styles.empty}>No stores yet.</div>
              ) : (
                <>
                  <div className={styles.chartWrap}>
                    <ResponsiveContainer width="100%" height={240}>
                      <PieChart>
                        <Pie
                          data={verticalChartData}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={55}
                          outerRadius={95}
                          paddingAngle={2}
                        >
                          {verticalChartData.map((_, i) => (
                            <Cell
                              key={i}
                              fill={CHART_COLORS[i % CHART_COLORS.length]}
                            />
                          ))}
                        </Pie>
                        <Tooltip
                          formatter={(v) => [`${v as number} stores`, 'Count']}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <ul className={styles.legendList}>
                    {verticalChartData.map((d, i) => {
                      const meta = getVerticalMeta(d.key)
                      const pct =
                        data && data.store_count > 0
                          ? Math.round((d.value / data.store_count) * 100)
                          : 0
                      return (
                        <li key={d.key} className={styles.legendItem}>
                          <span
                            className={styles.legendSwatch}
                            style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
                          />
                          <span className={styles.legendIcon}>{meta.icon}</span>
                          <span className={styles.legendName}>{d.name}</span>
                          <span className={styles.legendCount}>
                            {d.value} · {pct}%
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </>
              )}
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>Call Volume (Successful vs Failed)</h2>
              {!calls ? (
                <Skeleton h={240} radius={8} />
              ) : (
                <div className={styles.chartWrap}>
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={callsChartData}>
                      <XAxis dataKey="window" stroke="#94a3b8" fontSize={12} />
                      <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
                      <Tooltip
                        formatter={(v) => (v as number).toLocaleString()}
                        cursor={{ fill: 'rgba(99, 102, 241, 0.06)' }}
                      />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="successful" stackId="a" fill="#16a34a" name="Successful" />
                      <Bar dataKey="failed"     stackId="a" fill="#dc2626" name="Failed" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
