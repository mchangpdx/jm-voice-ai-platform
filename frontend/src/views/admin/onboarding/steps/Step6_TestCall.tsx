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
      <span className={styles.pendingBadgeSuccess}>Almost done</span>
      <h2 className={styles.heading}>Place a test call</h2>
      <p className={styles.sub}>
        We will ring a Twilio number you control so you can verify the voice
        agent end-to-end. Once you confirm, the agent goes live for real customers.
      </p>

      <div className={styles.actions}>
        <button type="button" className={styles.primary} onClick={onDone}>
          Finish onboarding →
        </button>
      </div>
    </div>
  )
}
