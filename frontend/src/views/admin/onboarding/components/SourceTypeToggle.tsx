// Source-type segmented toggle for Step 1
// (Step 1 소스 타입 5개 선택 토글: Loyverse / URL / Photo / CSV / Manual)
import type { SourceType } from '../types'
import styles from './SourceTypeToggle.module.css'

interface Option {
  value: SourceType
  label: string
  icon: string
  hint: string
}

const OPTIONS: Option[] = [
  { value: 'loyverse', label: 'Loyverse token (API 키)', icon: '🔑', hint: 'Paste your Loyverse API token' },
  { value: 'url',      label: 'Website URL (메뉴 URL)',  icon: '🔗', hint: 'Public menu page link' },
  { value: 'image',    label: 'Menu photos (사진)',       icon: '📷', hint: 'Drag & drop JPG/PNG' },
  { value: 'csv',      label: 'CSV file (CSV 파일)',      icon: '📄', hint: 'Spreadsheet export' },
  { value: 'manual',   label: 'Manual entry (수동 입력)', icon: '✏️', hint: 'Type items by hand' },
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
            <span className={styles.icon} aria-hidden="true">{o.icon}</span>
            <span className={styles.label}>{o.label}</span>
            <span className={styles.hint}>{o.hint}</span>
          </button>
        )
      })}
    </div>
  )
}
