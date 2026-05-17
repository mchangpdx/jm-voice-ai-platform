// Hero KPI section — three top-line numbers with count-up animation.
// (히어로 3대 KPI — 카운트업 애니메이션 적용)
import { CODE_REUSE_LAYERS, VERTICAL_ADD_COSTS } from '../proofConstants'
import { useCountUp } from './useCountUp'
import styles from '../ArchitectureProof.module.css'

export default function HeroKpi() {
  const verticals = VERTICAL_ADD_COSTS.length
  const reuseSum   = CODE_REUSE_LAYERS.reduce((s, l) => s + l.locReused, 0)
  const totalSum   = CODE_REUSE_LAYERS.reduce((s, l) => s + l.locTotal, 0)
  const reusePct   = totalSum > 0 ? (reuseSum / totalSum) * 100 : 0
  const fastestDays = Math.min(...VERTICAL_ADD_COSTS.filter((c) => c.mode !== 'baseline (real)').map((c) => c.days))

  const vCount = useCountUp(verticals)
  const rCount = useCountUp(reusePct, 1100, 0)
  const dCount = useCountUp(fastestDays, 900, 1)

  return (
    <header className={styles.hero}>
      <div className={styles.heroIntro}>
        <h1 className={styles.heroTitle}>
          {verticals} verticals live in <span className={styles.heroEmph}>{fastestDays}-day</span> increments
        </h1>
        <p className={styles.heroSub}>
          Built once on a 4-layer architecture, deployed across every SMB vertical we touch.
        </p>
      </div>

      <div className={styles.heroKpiGrid} role="group" aria-label="Headline metrics">
        <div className={styles.heroKpi}>
          <div className={styles.heroKpiNum}>{vCount}</div>
          <div className={styles.heroKpiLabel}>Verticals shipped</div>
          <div className={styles.heroKpiSub}>Cafe · KBBQ · Beauty · Auto Repair · Home Services</div>
        </div>
        <div className={styles.heroKpi}>
          <div className={styles.heroKpiNum}>{rCount.toFixed(0)}<span className={styles.heroKpiUnit}>%</span></div>
          <div className={styles.heroKpiLabel}>Backend code reuse</div>
          <div className={styles.heroKpiSub}>{reuseSum.toLocaleString()} of {totalSum.toLocaleString()} lines shared</div>
        </div>
        <div className={styles.heroKpi}>
          <div className={styles.heroKpiNum}>{dCount.toFixed(1)}<span className={styles.heroKpiUnit}>d</span></div>
          <div className={styles.heroKpiLabel}>Fastest vertical add</div>
          <div className={styles.heroKpiSub}>98% faster than the cafe baseline (25 founder-days)</div>
        </div>
      </div>
    </header>
  )
}
