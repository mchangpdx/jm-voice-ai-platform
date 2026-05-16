// Wizard progress header — step indicators with active/completed states
// (위저드 진행도 헤더 — 단계 진행 표시)
import styles from './WizardStepper.module.css'

export interface StepDef {
  key: number
  label: string         // English only, e.g. "Source"
}

interface Props {
  steps: StepDef[]
  current: number       // 1-based
}

export default function WizardStepper({ steps, current }: Props) {
  return (
    <ol className={styles.stepper} aria-label="Onboarding progress">
      {steps.map((s, i) => {
        const state =
          s.key < current ? 'completed' :
          s.key === current ? 'active' : 'pending'
        const isLast = i === steps.length - 1
        return (
          <li key={s.key} className={`${styles.step} ${styles[state]}`}>
            <div className={styles.stepInner}>
              <span className={styles.bubble} aria-hidden="true">
                {state === 'completed' ? '✓' : s.key}
              </span>
              <span className={styles.label}>{s.label}</span>
            </div>
            {!isLast && <span className={styles.connector} aria-hidden="true" />}
          </li>
        )
      })}
    </ol>
  )
}
