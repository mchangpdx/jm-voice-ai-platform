// Supporting KPI row — LCR / Upselling / Total AI Revenue / Avg Ticket / Total Calls.
// Reads metrics prop fed by PrimaryKpiSection's fetch (single source).
// (2행 보조 KPI — PrimaryKpiSection 한 번의 fetch 결과를 props로 받음)
import { getVerticalMeta } from '../../../../core/verticalLabels'
import Skeleton from '../../../../components/Skeleton/Skeleton'
import styles from '../Overview.module.css'
import type { Metrics } from './PrimaryKpiSection'

const fmt = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function SupportingKpiSection({
  metrics,
  industry,
  loading,
}: {
  metrics: Metrics | null
  industry: string | null
  loading: boolean
}) {
  const meta = getVerticalMeta(industry ?? 'restaurant')
  const m = metrics

  return (
    <div className={styles.kpiRowSm}>
      <div className={styles.kpiCardSm}>
        <div className={styles.kpiSmLabel}>{meta.conversionLabel} (LCR)</div>
        <div className={styles.kpiSmValue} style={{ color: '#6366f1' }}>
          {loading ? <Skeleton w={80} h={20} /> : `${m?.lcr.toFixed(1) ?? 0}%`}
        </div>
        <div className={styles.kpiSmSub}>
          {loading ? '' : `${m?.successful_calls ?? 0} orders / ${m?.total_calls ?? 0} calls`}
        </div>
      </div>

      <div className={styles.kpiCardSm}>
        <div className={styles.kpiSmLabel}>Upselling Value (UV)</div>
        <div className={styles.kpiSmValue} style={{ color: '#f59e0b' }}>
          {loading ? <Skeleton w={80} h={20} /> : fmt(m?.upselling_value ?? 0)}
        </div>
        <div className={styles.kpiSmSub}>15% upsell rate × $5/success</div>
      </div>

      <div className={styles.kpiCardSm}>
        <div className={styles.kpiSmLabel}>Total AI Revenue</div>
        <div className={styles.kpiSmValue} style={{ color: '#16a34a' }}>
          {loading ? <Skeleton w={80} h={20} /> : fmt(m?.total_ai_revenue ?? 0)}
        </div>
        <div className={styles.kpiSmSub}>Paid orders processed by AI</div>
      </div>

      <div className={styles.kpiCardSm}>
        <div className={styles.kpiSmLabel}>{meta.avgValueLabel}</div>
        <div className={styles.kpiSmValue} style={{ color: '#0369a1' }}>
          {loading ? <Skeleton w={80} h={20} /> : fmt(m?.avg_ticket ?? 0)}
        </div>
        <div className={styles.kpiSmSub}>Per paid order value</div>
      </div>

      <div className={styles.kpiCardSm}>
        <div className={styles.kpiSmLabel}>Total Calls Handled</div>
        <div className={styles.kpiSmValue} style={{ color: '#334155' }}>
          {loading ? <Skeleton w={70} h={20} /> : (m?.total_calls ?? 0).toLocaleString()}
        </div>
        <div className={styles.kpiSmSub}>AI-answered this period</div>
      </div>
    </div>
  )
}
