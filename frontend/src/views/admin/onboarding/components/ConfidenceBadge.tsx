// AI-extraction confidence badge (0.0–1.0 → 0-100% with traffic-light color)
// (AI 추출 신뢰도 뱃지 — 초록 0.95+, 노랑 0.70-0.94, 빨강 <0.70)
import styles from './ConfidenceBadge.module.css'

interface Props {
  confidence: number    // 0.0 - 1.0
}

export default function ConfidenceBadge({ confidence }: Props) {
  const pct = Math.round(confidence * 100)
  const level =
    confidence >= 0.95 ? 'high' :
    confidence >= 0.70 ? 'mid' : 'low'
  const icon = level === 'high' ? '✓' : level === 'mid' ? '⚠' : '❗'
  const a11y =
    level === 'high' ? 'High confidence' :
    level === 'mid' ? 'Medium confidence — review' :
    'Low confidence — operator review required'
  return (
    <span
      className={`${styles.badge} ${styles[level]}`}
      title={a11y}
      aria-label={`${a11y} (${pct}%)`}
    >
      <span className={styles.icon} aria-hidden="true">{icon}</span>
      <span className={styles.pct}>{pct}%</span>
    </span>
  )
}
