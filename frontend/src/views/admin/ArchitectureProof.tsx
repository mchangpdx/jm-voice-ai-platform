// Architecture Proof page — investor-facing demonstration of 4-layer reuse
// (아키텍처 입증 페이지 — 4계층 재사용성 투자자 시연용)
//
// Route: /admin/architecture-proof  (AGENCY role only)
// Data: GET /api/agency/overview?period=month — 5 verticals roll-up
//
// Per FRONTEND_HANDOFF_SPEC 2026-05-10 §F-C.
import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, LabelList,
} from 'recharts'
import api from '../../core/api'
import { useAuth } from '../../core/AuthContext'
import { getVerticalMeta } from '../../core/verticalLabels'
import {
  CODE_REUSE_LAYERS,
  VERTICAL_ADD_COSTS,
  getStoreMode,
  LIVE_DEMO_PHONE,
  LIVE_DEMO_TEL_HREF,
  LIVE_DEMO_STORE_NAME,
} from './proofConstants'
import styles from './ArchitectureProof.module.css'

interface StoreMetrics {
  store_id:              string
  store_name:            string
  industry:              string
  monthly_impact:        number
  labor_savings:         number
  conversion_rate:       number
  primary_revenue:       number
  avg_value:             number
  total_calls:           number
  successful_calls:      number
  primary_revenue_label: string
  conversion_label:      string
  avg_value_label:       string
}

interface OverviewData {
  agency_name: string
  period:      string
  totals: {
    total_calls:          number
    total_monthly_impact: number
    store_count:          number
  }
  stores: StoreMetrics[]
}

const fmtCompact = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`

// Bar color per reuse percentage — green ≥ 90, blue 80-89, amber < 80
function layerColor(pct: number): string {
  if (pct >= 90) return '#16a34a'
  if (pct >= 80) return '#0369a1'
  return '#f59e0b'
}

export default function ArchitectureProof() {
  const { role } = useAuth()
  const [data, setData]       = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (role !== 'AGENCY') return
    api
      .get('/agency/overview?period=month')
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [role])

  // Guard runs AFTER all hooks (React rules-of-hooks compliance)
  if (role !== 'AGENCY') return <Navigate to="/" replace />

  const stores       = data?.stores ?? []
  const totalReuseLoc = CODE_REUSE_LAYERS.reduce((s, l) => s + l.locReused, 0)
  const totalLoc      = CODE_REUSE_LAYERS.reduce((s, l) => s + l.locTotal,  0)
  const overallReuse  = totalLoc > 0 ? (totalReuseLoc / totalLoc) * 100 : 0

  const costChartData = VERTICAL_ADD_COSTS.map((c) => ({
    vertical: c.vertical,
    days:     c.days,
    mode:     c.mode,
    loc:      c.loc,
  }))

  return (
    <div className={styles.page}>

      {/* ── Hero banner ─────────────────────────────────────────────────── */}
      <header className={styles.hero}>
        <h1 className={styles.heroTitle}>
          5 verticals live in <span className={styles.heroEmph}>0.5 founder-days</span> per vertical
        </h1>
        <p className={styles.heroSub}>
          {overallReuse.toFixed(0)}% backend code reuse. Built once, runs everywhere.
        </p>
      </header>

      {/* ── Section 1 — Vertical Performance Roll-up ────────────────────── */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>1 — Vertical Performance Roll-up</h2>
        <p className={styles.sectionSub}>
          All five verticals running on the same 4-layer architecture. JM Cafe is live; the rest run on
          synthetic 60-day data for proof-of-concept demonstration.
        </p>

        {loading ? (
          <div className={styles.empty}>Loading verticals…</div>
        ) : stores.length === 0 ? (
          <div className={styles.empty}>No vertical data available.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.rollupTable}>
              <thead>
                <tr>
                  <th>VERTICAL</th>
                  <th>MODE</th>
                  <th className={styles.numCol}>CALLS</th>
                  <th className={styles.numCol}>AVG TICKET</th>
                  <th className={styles.numCol}>CONVERSION</th>
                  <th className={styles.numCol}>MONTHLY IMPACT</th>
                </tr>
              </thead>
              <tbody>
                {stores.map((s) => {
                  const meta = getVerticalMeta(s.industry)
                  const mode = getStoreMode(s.store_id)
                  return (
                    <tr key={s.store_id}>
                      <td>
                        <span className={styles.vIcon}>{meta.icon}</span>
                        <span className={styles.vName}>{s.store_name}</span>
                        <span className={styles.vLabel}>· {meta.industryLabel}</span>
                      </td>
                      <td>
                        {mode.mode === 'real' ? (
                          <span className={styles.modeRealBadge} title={`Live since ${mode.since}`}>
                            ✓ Real
                          </span>
                        ) : (
                          <span className={styles.modeSimBadge} title="Synthetic 60-day window">
                            Sim
                          </span>
                        )}
                      </td>
                      <td className={styles.numCol}>{s.total_calls.toLocaleString()}</td>
                      <td className={styles.numCol}>{fmtCompact(s.avg_value)}</td>
                      <td className={styles.numCol}>{s.conversion_rate.toFixed(1)}%</td>
                      <td className={`${styles.numCol} ${styles.impactCell}`}>
                        {fmtCompact(s.monthly_impact)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Section 2 — Code Reuse Visualization ────────────────────────── */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>2 — Code Reuse Visualization</h2>
        <p className={styles.sectionSub}>
          Per-layer reuse measured in lines of code shared across all five verticals. Higher = more
          leverage from each new vertical onboarded.
        </p>

        <div className={styles.layerList}>
          {CODE_REUSE_LAYERS.map((l) => (
            <div key={l.name} className={styles.layerRow}>
              <div className={styles.layerLabel}>{l.name}</div>
              <div className={styles.layerBarTrack}>
                <div
                  className={styles.layerBarFill}
                  style={{ width: `${l.reuse}%`, background: layerColor(l.reuse) }}
                />
                <span className={styles.layerPct}>{l.reuse}%</span>
              </div>
              <div className={styles.layerLoc}>
                {l.locReused.toLocaleString()} / {l.locTotal.toLocaleString()} LOC
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Section 3 — Add-Vertical Cost Chart ─────────────────────────── */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>3 — Add-Vertical Cost</h2>
        <p className={styles.sectionSub}>
          Time to onboard a new vertical, measured in founder-days. KBBQ shipped in 0.5 days —
          <strong> 98% faster than the cafe baseline</strong>.
        </p>

        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={costChartData} margin={{ top: 20, right: 24, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis dataKey="vertical" tick={{ fontSize: 12, fill: '#64748b' }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}d`} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: 'none', borderRadius: 8, fontSize: 12, color: '#fff' }}
              formatter={((v: unknown) => [`${v} founder-days`, 'Add time']) as never}
            />
            <Bar dataKey="days" radius={[4, 4, 0, 0]}>
              {costChartData.map((c) => (
                <Cell key={c.vertical} fill={c.vertical === 'cafe' ? '#94a3b8' : '#16a34a'} />
              ))}
              <LabelList
                dataKey="days"
                position="top"
                formatter={((v: unknown) => `${v}d`) as never}
                style={{ fontSize: 12, fontWeight: 600, fill: '#0f172a' }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        <p className={styles.chartFootnote}>
          Grey bar = cafe baseline (built from scratch). Green bars = subsequent verticals built on top
          of the shared 4-layer foundation.
        </p>
      </section>

      {/* ── Section 4 — Live Demo CTA ───────────────────────────────────── */}
      <section className={styles.ctaSection}>
        <div className={styles.ctaCard}>
          <div className={styles.ctaPulse} aria-hidden>
            <span className={styles.pulseDot} />
            <span>Live now</span>
          </div>
          <h2 className={styles.ctaTitle}>📞 Try it live</h2>
          <p className={styles.ctaText}>
            Call{' '}
            <a href={LIVE_DEMO_TEL_HREF} className={styles.ctaPhone}>
              {LIVE_DEMO_PHONE}
            </a>
            {' '}— {LIVE_DEMO_STORE_NAME} AI agent answers in 5 languages.
          </p>
          <p className={styles.ctaNote}>
            All other verticals shown above use simulated 60-day data to demonstrate the same architecture in production.
          </p>
        </div>
      </section>

    </div>
  )
}
