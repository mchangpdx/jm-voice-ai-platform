// Shared 3-way view toggle for store collections (Cards / List / Compact).
// Persists choice to localStorage under the provided storageKey.
// (매장 컬렉션용 3-way 뷰 토글 — Cards/List/Compact, localStorage 영구화)
import styles from './StoreViewToggle.module.css'

export type StoreViewMode = 'cards' | 'list' | 'compact'

const MODES: { mode: StoreViewMode; label: string; icon: string }[] = [
  { mode: 'cards',   label: 'Cards',   icon: '▦' },
  { mode: 'list',    label: 'List',    icon: '☰' },
  { mode: 'compact', label: 'Compact', icon: '≡' },
]

export function loadStoreView(key: string, fallback: StoreViewMode = 'cards'): StoreViewMode {
  if (typeof window === 'undefined') return fallback
  const raw = window.localStorage.getItem(key)
  if (raw === 'cards' || raw === 'list' || raw === 'compact') return raw
  return fallback
}

export function saveStoreView(key: string, value: StoreViewMode) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, value)
}

export default function StoreViewToggle({
  value,
  onChange,
}: {
  value: StoreViewMode
  onChange: (next: StoreViewMode) => void
}) {
  return (
    <div className={styles.toggle} role="tablist" aria-label="Store view">
      {MODES.map(({ mode, label, icon }) => (
        <button
          key={mode}
          role="tab"
          aria-selected={value === mode}
          className={`${styles.btn} ${value === mode ? styles.btnActive : ''}`}
          onClick={() => onChange(mode)}
          title={label}
        >
          <span className={styles.icon} aria-hidden>{icon}</span>
          <span className={styles.label}>{label}</span>
        </button>
      ))}
    </div>
  )
}
