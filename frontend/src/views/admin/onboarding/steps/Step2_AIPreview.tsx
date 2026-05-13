// Step 2 — AI Preview: read-only confidence-coded table of raw items.
// (Step 2 — AI 추출 결과 읽기 전용 미리보기: 신뢰도 색상 시각화)
//
// Vertical badge + warnings banner above the table.
// Low-confidence rows highlighted to draw operator attention.
import { useMemo } from 'react'
import ConfidenceBadge from '../components/ConfidenceBadge'
import type { RawMenuExtraction } from '../types'
import styles from './Step2_AIPreview.module.css'

interface Props {
  raw: RawMenuExtraction
  onBack: () => void
  onContinue: () => void
}

export default function Step2_AIPreview({ raw, onBack, onContinue }: Props) {
  const summary = useMemo(() => {
    const total = raw.items.length
    const low = raw.items.filter((i) => i.confidence < 0.70).length
    const mid = raw.items.filter((i) => i.confidence >= 0.70 && i.confidence < 0.95).length
    const high = total - low - mid
    return { total, low, mid, high }
  }, [raw.items])

  return (
    <div className={styles.wrap}>
      <header className={styles.head}>
        <div>
          <h2 className={styles.heading}>
            AI Preview <span className={styles.headingKo}>(AI 추출 미리보기)</span>
          </h2>
          <p className={styles.sub}>
            Review the extracted items. Confidence scores guide where you should focus.
            <br />
            <span className={styles.subKo}>
              추출된 항목을 확인하세요. 신뢰도 점수로 우선 검토 대상을 안내합니다.
            </span>
          </p>
        </div>
        <div className={styles.verticalBox}>
          <div className={styles.verticalLabel}>Detected vertical (감지된 업종)</div>
          <div className={styles.verticalValue}>
            {raw.vertical_guess ?? '— unknown —'}
          </div>
        </div>
      </header>

      {raw.warnings.length > 0 && (
        <div className={styles.warnings} role="alert">
          <strong>⚠ Warnings:</strong>
          <ul>
            {raw.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      <div className={styles.summaryRow}>
        <div className={styles.statCard}>
          <div className={styles.statValue}>{summary.total}</div>
          <div className={styles.statLabel}>Total items (총 항목)</div>
        </div>
        <div className={`${styles.statCard} ${styles.statHigh}`}>
          <div className={styles.statValue}>{summary.high}</div>
          <div className={styles.statLabel}>High confidence (높음 ≥95%)</div>
        </div>
        <div className={`${styles.statCard} ${styles.statMid}`}>
          <div className={styles.statValue}>{summary.mid}</div>
          <div className={styles.statLabel}>Review (검토 70-94%)</div>
        </div>
        <div className={`${styles.statCard} ${styles.statLow}`}>
          <div className={styles.statValue}>{summary.low}</div>
          <div className={styles.statLabel}>Manual fix (수정 &lt;70%)</div>
        </div>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name (이름)</th>
              <th>Size (사이즈)</th>
              <th>Price</th>
              <th>Category</th>
              <th>Allergens (알레르겐)</th>
              <th style={{ textAlign: 'right' }}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {raw.items.map((it, idx) => {
              const lowRow = it.confidence < 0.70
              return (
                <tr key={idx} className={lowRow ? styles.lowRow : ''}>
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
            })}
          </tbody>
        </table>
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>
          ← Back (뒤로)
        </button>
        <button type="button" className={styles.primary} onClick={onContinue}>
          Continue → Edit (편집하기)
        </button>
      </div>
    </div>
  )
}
