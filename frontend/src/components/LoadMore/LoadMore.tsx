// LoadMore — incremental row reveal for client-side paginated lists.
// (LoadMore — 클라이언트 사이드 페이지네이션 — 누적 row 표시)
//
// Renders one of three states:
//   - "Showing N of M  [Load more]"  when more rows are hidden
//   - "✓ All N loaded"                when all rows are shown
//   - nothing                          when total <= 0 (caller's empty state)
import styles from './LoadMore.module.css'

interface Props {
  shown:       number
  total:       number
  pageSize?:   number       // default reveal increment, info only
  onLoadMore:  () => void
  loading?:    boolean      // optional spinner / disable while parent refetches
}

export default function LoadMore({
  shown, total, pageSize = 50, onLoadMore, loading = false,
}: Props) {
  if (total <= 0) return null

  if (shown >= total) {
    return (
      <div className={styles.bar}>
        <span className={styles.allLoaded}>✓ All {total.toLocaleString()} loaded</span>
      </div>
    )
  }

  return (
    <div className={styles.bar}>
      <span className={styles.info}>
        Showing <strong>{shown.toLocaleString()}</strong> of {total.toLocaleString()}
      </span>
      <button
        type="button"
        className={styles.btn}
        onClick={onLoadMore}
        disabled={loading}
        aria-label={`Load ${Math.min(pageSize, total - shown)} more`}
      >
        {loading ? 'Loading…' : `Load ${Math.min(pageSize, total - shown)} more`}
      </button>
    </div>
  )
}
