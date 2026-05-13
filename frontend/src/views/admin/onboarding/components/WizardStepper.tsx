// Wizard progress header — 6 step indicators with active/completed states
// (위저드 진행도 헤더 — 6단계 진행 표시)
import styles from './WizardStepper.module.css'

export interface StepDef {
  key: number
  label: string         // "Source Upload (소스 업로드)"
}

interface Props {
  steps: StepDef[]
  current: number       // 1-based
}

export default function WizardStepper({ steps, current }: Props) {
  return (
    <ol className={styles.stepper} aria-label="Onboarding progress">
      {steps.map((s) => {
        const state =
          s.key < current ? 'completed' :
          s.key === current ? 'active' : 'pending'
        return (
          <li key={s.key} className={`${styles.step} ${styles[state]}`}>
            <span className={styles.bubble}>
              {state === 'completed' ? '✓' : s.key}
            </span>
            <span className={styles.label}>{s.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
