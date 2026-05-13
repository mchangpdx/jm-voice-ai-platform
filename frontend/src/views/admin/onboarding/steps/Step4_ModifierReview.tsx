// Step 4 — Modifier Review (placeholder until backend Phase 3 modifier_groups
// extractor lands). Shows detected modifiers from RawMenuExtraction +
// normalized item count so operator gets useful context now.
// (Step 4 — 백엔드 Phase 3 modifier_groups 완료 전 placeholder)
import type { RawMenuExtraction, NormalizedMenuItem } from '../types'
import styles from './StepPlaceholder.module.css'

interface Props {
  raw: RawMenuExtraction | null
  normalized: NormalizedMenuItem[] | null
  onBack: () => void
  onContinue: () => void
}

export default function Step4_ModifierReview({ raw, normalized, onBack, onContinue }: Props) {
  return (
    <div className={styles.wrap}>
      <div className={styles.pendingBadge}>Backend pending (백엔드 준비 중)</div>
      <h2 className={styles.heading}>
        Modifier review <span className={styles.headingKo}>(옵션 그룹 검토)</span>
      </h2>
      <p className={styles.sub}>
        Variants folded: <strong>{raw?.items.length ?? 0}</strong> rows →
        {' '}<strong>{normalized?.length ?? 0}</strong> normalized items.
        <br />
        Detected modifiers: <strong>{(raw?.detected_modifiers ?? []).join(', ') || '—'}</strong>
        <br />
        <span className={styles.subKo}>
          Phase 3 modifier_groups extractor 완료 후 옵션 그룹 ON/OFF + 옵션 편집 UI 활성화
        </span>
      </p>

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>← Back (뒤로)</button>
        <button type="button" className={styles.primary} onClick={onContinue}>
          Skip to POS Sync → (다음)
        </button>
      </div>
    </div>
  )
}
