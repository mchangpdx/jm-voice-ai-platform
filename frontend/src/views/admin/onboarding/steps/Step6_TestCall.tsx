// Step 6 — Test Call (placeholder). Will trigger Twilio outbound call once
// backend Phase 5 endpoint is ready, then stream live transcript via WS.
// (Step 6 — 백엔드 Phase 5 outbound trigger 완료 전 placeholder)
import styles from './StepPlaceholder.module.css'

interface Props {
  onDone: () => void
}

export default function Step6_TestCall({ onDone }: Props) {
  return (
    <div className={styles.wrap}>
      <div className={styles.pendingBadge}>Backend pending (백엔드 준비 중)</div>
      <h2 className={styles.heading}>
        Test call <span className={styles.headingKo}>(테스트 통화)</span>
      </h2>
      <p className={styles.sub}>
        Trigger a Twilio outbound call to verify the voice agent end-to-end.
        <br />
        <span className={styles.subKo}>
          백엔드 Phase 5 완료 후 "Twilio test call now" 버튼 + 실시간 통화 로그 표시
        </span>
      </p>

      <div className={styles.actions}>
        <button type="button" className={styles.primary} onClick={onDone}>
          Finish & exit → (완료)
        </button>
      </div>
    </div>
  )
}
