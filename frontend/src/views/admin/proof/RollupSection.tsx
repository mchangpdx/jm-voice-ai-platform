// Vertical Roll-up — same 4-layer architecture, all five verticals' performance.
// (5 vertical 성과 roll-up 표 — 행 클릭 시 store detail navigate)
import { useNavigate } from 'react-router-dom'
import { getVerticalMeta } from '../../../core/verticalLabels'
import { getStoreMode } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

interface StoreMetrics {
  store_id:        string
  store_name:      string
  industry:        string
  monthly_impact:  number
  conversion_rate: number
  avg_value:       number
  total_calls:     number
}

const fmtCompact = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`

export default function RollupSection({ stores, loading }: { stores: StoreMetrics[]; loading: boolean }) {
  const navigate = useNavigate()

  if (loading) return <div className={styles.empty}>Loading verticals…</div>
  if (stores.length === 0) return <div className={styles.empty}>No vertical data available.</div>

  return (
    <>
      <p className={styles.sectionSub}>
        All five verticals running on the same 4-layer architecture. JM Cafe is live; the rest run on
        synthetic 60-day data for proof-of-concept demonstration. Tap a row to drill into store detail.
      </p>

      {/* Desktop / tablet — table */}
      <div className={`${styles.tableWrap} ${styles.hideOnPhone}`}>
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
                <tr
                  key={s.store_id}
                  onClick={() => navigate(`/agency/store/${s.store_id}`)}
                  className={styles.rowClickable}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') navigate(`/agency/store/${s.store_id}`)
                  }}
                >
                  <td>
                    <span className={styles.vIcon}>{meta.icon}</span>
                    <span className={styles.vName}>{s.store_name}</span>
                    <span className={styles.vLabel}>· {meta.industryLabel}</span>
                  </td>
                  <td>
                    {mode.mode === 'real' ? (
                      <span className={styles.modeRealBadge} title={`Live since ${mode.since}`}>✓ Real</span>
                    ) : (
                      <span className={styles.modeSimBadge} title="Synthetic 60-day window">Sim</span>
                    )}
                  </td>
                  <td className={styles.numCol}>{s.total_calls.toLocaleString()}</td>
                  <td className={styles.numCol}>{fmtCompact(s.avg_value)}</td>
                  <td className={styles.numCol}>{s.conversion_rate.toFixed(1)}%</td>
                  <td className={`${styles.numCol} ${styles.impactCell}`}>{fmtCompact(s.monthly_impact)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile — card stack */}
      <div className={`${styles.cardStack} ${styles.showOnPhone}`}>
        {stores.map((s) => {
          const meta = getVerticalMeta(s.industry)
          const mode = getStoreMode(s.store_id)
          return (
            <button
              key={s.store_id}
              type="button"
              className={styles.storeCard}
              onClick={() => navigate(`/agency/store/${s.store_id}`)}
            >
              <div className={styles.storeCardHeader}>
                <div>
                  <span className={styles.vIcon}>{meta.icon}</span>
                  <span className={styles.vName}>{s.store_name}</span>
                </div>
                {mode.mode === 'real'
                  ? <span className={styles.modeRealBadge}>✓ Real</span>
                  : <span className={styles.modeSimBadge}>Sim</span>}
              </div>
              <div className={styles.vLabel} style={{ marginBottom: 10 }}>{meta.industryLabel}</div>
              <div className={styles.storeCardKpiGrid}>
                <div><span>Calls</span><strong>{s.total_calls.toLocaleString()}</strong></div>
                <div><span>Avg ticket</span><strong>{fmtCompact(s.avg_value)}</strong></div>
                <div><span>Conversion</span><strong>{s.conversion_rate.toFixed(1)}%</strong></div>
                <div><span>Impact</span><strong className={styles.impactCell}>{fmtCompact(s.monthly_impact)}</strong></div>
              </div>
            </button>
          )
        })}
      </div>
    </>
  )
}
