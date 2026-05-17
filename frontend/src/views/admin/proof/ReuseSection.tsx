// Code reuse layer bars — per-layer reuse % across all verticals.
// (계층별 코드 재사용률 — bar visualization)
import { CODE_REUSE_LAYERS } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

// Color matches reuse strength tier — green ≥90, blue 80–89, amber <80.
function layerColor(pct: number): string {
  if (pct >= 90) return '#16a34a'
  if (pct >= 80) return '#0369a1'
  return '#f59e0b'
}

export default function ReuseSection() {
  return (
    <>
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
    </>
  )
}
