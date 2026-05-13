// Admin Onboarding Wizard — 6-step container (managed via React state).
// (Admin 매장 온보딩 위저드 — 6단계 컨테이너)
//
// Route: /admin/onboarding/new
// Spec: docs/handoff-frontend-onboarding-wizard.md  (Frozen contract §2)
//
// Phase 1 (this PR): Steps 1-3 wired to mock client.
// Phase 2 (next PR): Steps 4-6 wired once backend Phase 4-5 endpoints land.
// (Phase 1: Step 1-3 mock 연결, Phase 2: 백엔드 endpoint 완료 후 4-6 연결)
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import WizardStepper, { type StepDef } from './components/WizardStepper'
import Step1_SourceUpload from './steps/Step1_SourceUpload'
import Step2_AIPreview from './steps/Step2_AIPreview'
import Step3_EditItems from './steps/Step3_EditItems'
import Step4_ModifierReview from './steps/Step4_ModifierReview'
import Step5_POSSync from './steps/Step5_POSSync'
import Step6_TestCall from './steps/Step6_TestCall'
import type { RawMenuExtraction, NormalizedMenuItem } from './types'
import styles from './OnboardingWizard.module.css'

const STEPS: StepDef[] = [
  { key: 1, label: '1. Source (소스)' },
  { key: 2, label: '2. AI Preview (미리보기)' },
  { key: 3, label: '3. Edit Items (편집)' },
  { key: 4, label: '4. Modifiers (옵션)' },
  { key: 5, label: '5. POS Sync (동기화)' },
  { key: 6, label: '6. Test Call (테스트 콜)' },
]

export default function OnboardingWizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState<number>(1)
  const [raw, setRaw] = useState<RawMenuExtraction | null>(null)
  const [normalized, setNormalized] = useState<NormalizedMenuItem[] | null>(null)

  const go = (n: number) => setStep(n)

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>
            New Store Onboarding <span className={styles.titleSub}>(신규 매장 온보딩)</span>
          </h1>
          <p className={styles.subtitle}>
            Provide a menu source — AI extracts items, you review, and we activate the voice agent.
            <br />
            <span className={styles.subtitleKo}>
              메뉴 소스를 제공하면 AI가 아이템을 추출하고, 검토 후 보이스 에이전트가 활성화됩니다.
            </span>
          </p>
        </div>
        <button
          type="button"
          className={styles.exitBtn}
          onClick={() => navigate('/admin/architecture-proof')}
          aria-label="Exit onboarding wizard"
        >
          ✕ Exit
        </button>
      </header>

      <WizardStepper steps={STEPS} current={step} />

      <main className={styles.stepBody}>
        {step === 1 && (
          <Step1_SourceUpload
            onExtracted={(r) => { setRaw(r); go(2) }}
          />
        )}
        {step === 2 && raw && (
          <Step2_AIPreview
            raw={raw}
            onBack={() => go(1)}
            onContinue={() => go(3)}
          />
        )}
        {step === 3 && raw && (
          <Step3_EditItems
            raw={raw}
            onBack={() => go(2)}
            onNormalized={(items) => { setNormalized(items); go(4) }}
          />
        )}
        {step === 4 && (
          <Step4_ModifierReview
            raw={raw}
            normalized={normalized}
            onBack={() => go(3)}
            onContinue={() => go(5)}
          />
        )}
        {step === 5 && (
          <Step5_POSSync
            onBack={() => go(4)}
            onContinue={() => go(6)}
          />
        )}
        {step === 6 && (
          <Step6_TestCall
            onDone={() => navigate('/admin/architecture-proof')}
          />
        )}
      </main>
    </div>
  )
}
