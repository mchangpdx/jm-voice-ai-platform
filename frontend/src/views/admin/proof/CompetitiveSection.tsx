// Competitive comparison — JM vs Maple / Yelp / Slang.ai across 10 criteria.
// Score table per memory rule (item scores + total). Color-coded heatmap.
// (경쟁사 비교 — 항목별 + 합계 score, color heatmap)
import { COMPETITIVE_COMPETITORS, COMPETITIVE_CRITERIA } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

// Heatmap color — green ≥8, blue 6–7, amber 4–5, red <4.
function scoreColor(s: number): string {
  if (s >= 8) return '#dcfce7'
  if (s >= 6) return '#dbeafe'
  if (s >= 4) return '#fef3c7'
  return '#fee2e2'
}
function scoreTextColor(s: number): string {
  if (s >= 8) return '#15803d'
  if (s >= 6) return '#1d4ed8'
  if (s >= 4) return '#92400e'
  return '#b91c1c'
}

export default function CompetitiveSection() {
  const totals = COMPETITIVE_COMPETITORS.map((c) => ({
    id: c.id,
    name: c.name,
    color: c.color,
    total: COMPETITIVE_CRITERIA.reduce((s, cr) => s + (c.scores[cr.key] ?? 0), 0),
    max:   COMPETITIVE_CRITERIA.length * 10,
  }))
  const winner = [...totals].sort((a, b) => b.total - a.total)[0]

  return (
    <>
      <p className={styles.sectionSub}>
        Side-by-side scoring vs the three nearest competitors in SMB voice. Each criterion is 0–10;
        column total shows the headline gap. <strong>{winner.name} leads</strong> with{' '}
        <strong>{winner.total}/{winner.max}</strong>.
      </p>

      <div className={styles.tableWrap}>
        <table className={styles.compTable}>
          <thead>
            <tr>
              <th className={styles.compCriterionHeader}>CRITERION</th>
              {COMPETITIVE_COMPETITORS.map((c) => (
                <th key={c.id} className={styles.compScoreHeader} style={{ color: c.color }}>
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPETITIVE_CRITERIA.map((cr) => (
              <tr key={cr.key}>
                <td className={styles.compCriterionCell}>{cr.label}</td>
                {COMPETITIVE_COMPETITORS.map((c) => {
                  const s = c.scores[cr.key] ?? 0
                  return (
                    <td key={c.id} className={styles.compScoreCell}>
                      <span
                        className={styles.compScorePill}
                        style={{ background: scoreColor(s), color: scoreTextColor(s) }}
                      >
                        {s}
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
            <tr className={styles.compTotalRow}>
              <td className={styles.compCriterionCell}><strong>TOTAL</strong></td>
              {totals.map((t) => (
                <td key={t.id} className={styles.compScoreCell}>
                  <span className={styles.compTotalNum} style={{ color: t.color }}>
                    {t.total}<span className={styles.compTotalMax}>/{t.max}</span>
                  </span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <p className={styles.chartFootnote}>
        Sources: Maple competitive baseline (2026-05-02 deep-dive), Yelp Agent + Slang.ai public pricing
        and feature pages. Self-rated scores cited from public reviews where available.
      </p>
    </>
  )
}
