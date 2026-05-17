// Store Overview — orchestrator only. All content lives in overview/* and is
// registered via overviewSections.tsx.
// (Store Overview — orchestrator. 모든 섹션은 overview/* + overviewSections.tsx)
//
// Adding a new dashboard widget:
//   1. Create overview/MyWidget.tsx
//   2. Add an entry to OVERVIEW_SECTIONS
// No changes to this file needed unless you change the period / data contract.

import { useState } from 'react'
import { useAuth } from '../../../core/AuthContext'
import Tier3AlertBadge from '../../../components/Tier3AlertBadge'
import styles from './Overview.module.css'
import { isVisibleFor, OVERVIEW_SECTIONS } from './overviewSections'
import type { Metrics, Period } from './overview/PrimaryKpiSection'

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'Week'  },
  { key: 'month', label: 'Month' },
  { key: 'all',   label: 'All'   },
]

export default function Overview() {
  const { storeName, industry } = useAuth()
  const [period, setPeriod] = useState<Period>('all')
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [loadingMetrics, setLoadingMetrics] = useState(true)

  const handleMetrics = (m: Metrics | null) => {
    setMetrics(m)
    setLoadingMetrics(false)
  }

  const props = {
    period, industry, storeName, metrics, loadingMetrics, onMetrics: handleMetrics,
  }

  // Filter sections by vertical/industry, then render. The panels grid pairs
  // 'panel-left' + 'panel-right' siblings into a 2-col wrapper.
  const visible = OVERVIEW_SECTIONS.filter((s) => isVisibleFor(s, industry))

  const rendered: React.ReactNode[] = []
  for (let i = 0; i < visible.length; i++) {
    const s = visible[i]
    if (s.variant === 'panel-right') continue          // consumed by previous left

    if (s.variant === 'panel-left' && visible[i + 1]?.variant === 'panel-right') {
      const right = visible[i + 1]
      rendered.push(
        <div key={`${s.id}+${right.id}`} className={styles.panels}>
          {s.render(props)}
          {right.render(props)}
        </div>,
      )
      i++ // skip the right we just rendered
      continue
    }

    rendered.push(<div key={s.id}>{s.render(props)}</div>)
  }

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.storeName}>{storeName ?? 'Store'}</h1>
          <p className={styles.pageDesc}>
            AI ROI analytics, persona control, and live call orders — all in one place.
          </p>
        </div>
        {/* TODO: wire up GET /api/store/alerts/tier3 (backend pending) */}
        <Tier3AlertBadge count={0} />
      </div>

      <div className={styles.periodRow}>
        <span className={styles.periodLabel}>Period:</span>
        {PERIODS.map(({ key, label }) => (
          <button
            key={key}
            className={`${styles.periodBtn} ${period === key ? styles.periodBtnActive : ''}`}
            onClick={() => {
              setPeriod(key)
              setLoadingMetrics(true)
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {rendered}
    </div>
  )
}
