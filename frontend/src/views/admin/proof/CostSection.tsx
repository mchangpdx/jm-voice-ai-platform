// Add-vertical cost chart — founder-days to onboard each vertical.
// Embeds a $ savings annotation derived from the cafe baseline.
// (vertical 추가 시간 차트 + 기준 대비 절감 금액 환산)
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { VERTICAL_ADD_COSTS } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

const FOUNDER_DAY_USD = 1200   // assumed engineering opportunity cost / founder-day

export default function CostSection() {
  const data = VERTICAL_ADD_COSTS.map((c) => ({
    vertical: c.vertical, days: c.days, mode: c.mode, loc: c.loc,
  }))
  const baseline = data.find((d) => d.mode.startsWith('baseline'))?.days ?? 25
  const subsequent = data.filter((d) => !d.mode.startsWith('baseline'))
  const avgAdd = subsequent.reduce((s, d) => s + d.days, 0) / Math.max(1, subsequent.length)
  const savingsPerVertical = Math.round((baseline - avgAdd) * FOUNDER_DAY_USD)

  return (
    <>
      <p className={styles.sectionSub}>
        Time to onboard a new vertical, measured in founder-days. KBBQ shipped in 0.5 days —
        <strong> 98% faster than the cafe baseline</strong>.
      </p>

      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 20, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis dataKey="vertical" tick={{ fontSize: 11, fill: '#64748b' }} tickLine={false} axisLine={false} interval={0} />
          <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}d`} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: 'none', borderRadius: 8, fontSize: 12, color: '#fff' }}
            formatter={((v: unknown) => [`${v} founder-days`, 'Add time']) as never}
          />
          <Bar dataKey="days" radius={[4, 4, 0, 0]}>
            {data.map((c) => (
              <Cell key={c.vertical} fill={c.mode.startsWith('baseline') ? '#94a3b8' : '#16a34a'} />
            ))}
            <LabelList
              dataKey="days"
              position="top"
              formatter={((v: unknown) => `${v}d`) as never}
              style={{ fontSize: 11, fontWeight: 600, fill: '#0f172a' }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className={styles.savingsCallout}>
        <div>
          <div className={styles.savingsValue}>${savingsPerVertical.toLocaleString()}</div>
          <div className={styles.savingsLabel}>Engineering cost saved per added vertical</div>
        </div>
        <div className={styles.savingsNote}>
          Baseline {baseline}d → avg add {avgAdd.toFixed(1)}d, at ${FOUNDER_DAY_USD.toLocaleString()}/founder-day.
        </div>
      </div>

      <p className={styles.chartFootnote}>
        Grey bar = cafe baseline (built from scratch). Green bars = subsequent verticals built on top
        of the shared 4-layer foundation.
      </p>
    </>
  )
}
