// Source-type segmented toggle for Step 1
// (Step 1 소스 타입 5개 선택 토글)
import type { SourceType } from '../types'
import styles from './SourceTypeToggle.module.css'

interface Option {
  value: SourceType
  label: string
  icon: string
  hint: string
  recommended?: boolean
}

const OPTIONS: Option[] = [
  { value: 'loyverse', label: 'Loyverse token', icon: '🔑', hint: 'Auto-sync from your POS', recommended: true },
  { value: 'url',      label: 'Website URL',   icon: '🔗', hint: 'Crawl a public menu page' },
  { value: 'image',    label: 'Photos or PDF', icon: '📷', hint: 'Drop menu images' },
  { value: 'csv',      label: 'CSV file',      icon: '📄', hint: 'Upload a spreadsheet' },
  { value: 'manual',   label: 'Manual entry',  icon: '✏️', hint: 'Type items by hand' },
]

interface Props {
  value: SourceType
  onChange: (v: SourceType) => void
}

export default function SourceTypeToggle({ value, onChange }: Props) {
  return (
    <div className={styles.grid} role="radiogroup" aria-label="Menu source type">
      {OPTIONS.map((o) => {
        const active = o.value === value
        return (
          <button
            type="button"
            key={o.value}
            role="radio"
            aria-checked={active}
            className={`${styles.option} ${active ? styles.active : ''}`}
            onClick={() => onChange(o.value)}
          >
            {o.recommended && <span className={styles.recommendedTag}>Recommended</span>}
            <span className={styles.icon} aria-hidden="true">{o.icon}</span>
            <span className={styles.label}>{o.label}</span>
            <span className={styles.hint}>{o.hint}</span>
          </button>
        )
      })}
    </div>
  )
}
