// Live demo CTA — large tap-to-call CTA + language list + privacy note.
// On mobile, tapping the number triggers the dialer; desktop hides the
// pulse to reduce noise during recorded demos.
// (라이브 데모 CTA — 큰 tap-to-call 버튼 + 지원 언어 + 안내)
import { LIVE_DEMO_PHONE, LIVE_DEMO_STORE_NAME, LIVE_DEMO_TEL_HREF } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

const LANGUAGES = ['English', 'Spanish', 'Korean', 'Japanese', 'Chinese']

export default function LiveDemoCta() {
  return (
    <div className={styles.ctaCard}>
      <div className={styles.ctaPulse} aria-hidden>
        <span className={styles.pulseDot} />
        <span>Live now</span>
      </div>
      <h3 className={styles.ctaTitle}>Try it live</h3>
      <p className={styles.ctaText}>
        Call <strong>{LIVE_DEMO_STORE_NAME}</strong>'s AI voice agent. Answers in 5 languages,
        24/7. Place a real order, ask about hours, request a reservation — it's the production system.
      </p>

      <a href={LIVE_DEMO_TEL_HREF} className={styles.ctaCallBtn}>
        <span className={styles.ctaCallIcon} aria-hidden>📞</span>
        <span className={styles.ctaCallLabel}>Tap to call</span>
        <span className={styles.ctaCallPhone}>{LIVE_DEMO_PHONE}</span>
      </a>

      <div className={styles.ctaLangRow}>
        {LANGUAGES.map((l) => (
          <span key={l} className={styles.ctaLangChip}>{l}</span>
        ))}
      </div>

      <p className={styles.ctaNote}>
        Calls are recorded for QA and surfaced in <code>/admin/audit-log</code>. No PII is shared
        outside the JM platform. All other verticals shown above use simulated 60-day data.
      </p>
    </div>
  )
}
