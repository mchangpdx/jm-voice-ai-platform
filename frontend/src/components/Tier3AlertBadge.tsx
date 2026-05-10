// Tier-3 Allergen Alert Badge — top-of-screen pill, links to filtered call history
// (Tier-3 알레르기 알림 배지 — 화면 상단 pill, 필터된 통화 이력으로 링크)
import { Link } from 'react-router-dom'
import styles from './Tier3AlertBadge.module.css'

interface Props {
  count: number
  href?: string
}

export default function Tier3AlertBadge({
  count,
  href = '/fsr/store/call-history?filter=tier3',
}: Props) {
  if (count <= 0) return null

  const label = count === 1 ? '1 allergen alert' : `${count} allergen alerts`

  return (
    <Link to={href} className={styles.badge} aria-label={`${label} — view details`}>
      <span className={styles.icon} aria-hidden>🚨</span>
      <span className={styles.label}>{label}</span>
      <span className={styles.arrow} aria-hidden>›</span>
    </Link>
  )
}
