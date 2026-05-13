// Step 5 — POS Sync (placeholder). Will trigger Loyverse direct push or
// CSV export once backend Phase 4-5 db_seeder is ready.
// (Step 5 — Phase 4-5 db_seeder 완료 전 placeholder)
import styles from './StepPlaceholder.module.css'

interface Props {
  onBack: () => void
  onContinue: () => void
}

export default function Step5_POSSync({ onBack, onContinue }: Props) {
  return (
    <div className={styles.wrap}>
      <div className={styles.pendingBadge}>Backend pending (백엔드 준비 중)</div>
      <h2 className={styles.heading}>
        POS sync <span className={styles.headingKo}>(POS 동기화)</span>
      </h2>
      <p className={styles.sub}>
        Push categories → modifier_groups → options → items to Loyverse, or export to CSV.
        <br />
        <span className={styles.subKo}>
          백엔드 Phase 4-5 (db_seeder) 완료 후 진행도 표시 + 라이브 푸시 활성화
        </span>
      </p>

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>← Back (뒤로)</button>
        <button type="button" className={styles.primary} onClick={onContinue}>
          Skip to Test Call → (다음)
        </button>
      </div>
    </div>
  )
}
