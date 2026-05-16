// Step 2 — AI Preview: read-only confidence-coded table of raw items.
// (Step 2 — AI 추출 결과 미리보기)
//
// Operator features:
//   - Click any summary card to filter (all / high / mid / low)
//   - Search by item name
//   - Sticky bottom CTA bar
// UI copy: English only per [[feedback-ui-language-english-only]].
import { useMemo, useState } from 'react'
import ConfidenceBadge from '../components/ConfidenceBadge'
import type { RawMenuExtraction, RawMenuItem } from '../types'
import styles from './Step2_AIPreview.module.css'

type Filter = 'all' | 'high' | 'mid' | 'low'

interface Props {
  raw: RawMenuExtraction
  onBack: () => void
  onContinue: () => void
}

export default function Step2_AIPreview({ raw, onBack, onContinue }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')

  const summary = useMemo(() => {
    const total = raw.items.length
    const low = raw.items.filter((i) => i.confidence < 0.70).length
    const mid = raw.items.filter((i) => i.confidence >= 0.70 && i.confidence < 0.95).length
    const high = total - low - mid
    return { total, low, mid, high }
  }, [raw.items])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return raw.items.filter((it) => {
      if (q && !it.name.toLowerCase().includes(q)) return false
      if (filter === 'high' && it.confidence < 0.95) return false
      if (filter === 'mid'  && !(it.confidence >= 0.70 && it.confidence < 0.95)) return false
      if (filter === 'low'  && it.confidence >= 0.70) return false
      return true
    })
  }, [raw.items, filter, query])

  return (
    <div className={styles.wrap}>
      <header className={styles.head}>
        <div>
          <h2 className={styles.heading}>Here is what we found</h2>
          <p className={styles.sub}>
            Review the extracted items. Items with low confidence are highlighted —
            you can fix them in the next step.
          </p>
        </div>
        {raw.vertical_guess && (
          <div className={styles.verticalBox}>
            <div className={styles.verticalLabel}>Detected vertical</div>
            <div className={styles.verticalValue}>{raw.vertical_guess}</div>
          </div>
        )}
      </header>

      {raw.warnings.length > 0 && (
        <div className={styles.warnings} role="alert">
          <span className={styles.warningIcon}>⚠</span>
          <div>
            <strong>Heads up</strong>
            <ul>{raw.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </div>
        </div>
      )}

      <div className={styles.summaryRow} role="tablist" aria-label="Filter by confidence">
        <SummaryCard
          label="Total items" value={summary.total}
          active={filter === 'all'} onClick={() => setFilter('all')}
        />
        <SummaryCard
          label="High (≥95%)" value={summary.high} tone="high"
          active={filter === 'high'} onClick={() => setFilter('high')}
        />
        <SummaryCard
          label="Review (70–94%)" value={summary.mid} tone="mid"
          active={filter === 'mid'} onClick={() => setFilter('mid')}
        />
        <SummaryCard
          label="Needs fix (<70%)" value={summary.low} tone="low"
          active={filter === 'low'} onClick={() => setFilter('low')}
        />
      </div>

      <div className={styles.toolbar}>
        <input
          type="search"
          className={styles.search}
          placeholder="Search items by name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className={styles.resultCount}>
          Showing {visible.length} of {raw.items.length}
        </span>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Item</th>
              <th>Size</th>
              <th>Price</th>
              <th>Category</th>
              <th>Allergens</th>
              <th style={{ textAlign: 'right' }}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={6} className={styles.empty}>
                  No items match this filter.
                </td>
              </tr>
            ) : visible.map((it, idx) => <Row key={idx} it={it} />)}
          </tbody>
        </table>
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>
          ← Back
        </button>
        <button type="button" className={styles.primary} onClick={onContinue}>
          Continue to edit →
        </button>
      </div>
    </div>
  )
}

function Row({ it }: { it: RawMenuItem }) {
  const lowRow = it.confidence < 0.70
  return (
    <tr className={lowRow ? styles.lowRow : ''}>
      <td className={styles.nameCell}>{it.name}</td>
      <td className={styles.dim}>{it.size_hint ?? '—'}</td>
      <td>${it.price.toFixed(2)}</td>
      <td className={styles.dim}>{it.category ?? '—'}</td>
      <td className={styles.dim}>
        {it.detected_allergens && it.detected_allergens.length > 0
          ? it.detected_allergens.join(', ')
          : '—'}
      </td>
      <td style={{ textAlign: 'right' }}>
        <ConfidenceBadge confidence={it.confidence} />
      </td>
    </tr>
  )
}

interface SummaryCardProps {
  label: string
  value: number
  tone?: 'high' | 'mid' | 'low'
  active: boolean
  onClick: () => void
}
function SummaryCard({ label, value, tone, active, onClick }: SummaryCardProps) {
  const toneClass = tone ? styles[`stat_${tone}`] : ''
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      className={`${styles.statCard} ${toneClass} ${active ? styles.statActive : ''}`}
      onClick={onClick}
    >
      <div className={styles.statValue}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
    </button>
  )
}
