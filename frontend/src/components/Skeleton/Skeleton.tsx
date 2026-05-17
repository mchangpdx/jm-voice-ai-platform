// Skeleton primitive — shimmer block for loading states.
// (Skeleton 기본 컴포넌트 — 로딩 시 shimmer 블록)
//
// Usage:
//   <Skeleton h={20} />                  default full-width row
//   <Skeleton w={80} h={32} />           fixed width tile
//   <Skeleton h={120} radius={12} />     card-shaped placeholder
import styles from './Skeleton.module.css'

interface Props {
  w?:      number | string
  h?:      number | string
  radius?: number | string
  className?: string
}

export default function Skeleton({ w, h = 14, radius = 6, className }: Props) {
  return (
    <div
      className={`${styles.skeleton} ${className ?? ''}`}
      style={{ width: w, height: h, borderRadius: radius }}
      aria-hidden="true"
    />
  )
}

// Common composite — table row pretending to be N cells.
export function SkeletonRow({ cells = 5 }: { cells?: number }) {
  return (
    <div className={styles.row}>
      {Array.from({ length: cells }).map((_, i) => (
        <Skeleton key={i} h={14} />
      ))}
    </div>
  )
}
