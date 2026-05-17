// Architecture Proof page — investor-facing 4-layer reuse demonstration.
// (아키텍처 입증 페이지 — 4계층 재사용성 투자자 시연용)
//
// Route: /admin/marketing/architecture-proof  (ADMIN role only — route guard)
// Data:  GET /api/agency/overview?period=month
//
// Composition: orchestrator only. All section content lives in proof/* and
// is registered via proofSections.tsx. Adding a new dimension = 1 entry +
// one component file. No edits to this file needed.
import { useEffect, useState } from 'react'
import api from '../../core/api'
import Toc from './proof/Toc'
import { PROOF_SECTIONS, type StoreMetrics } from './proofSections'
import styles from './ArchitectureProof.module.css'

interface OverviewData {
  agency_name: string
  period:      string
  totals: {
    total_calls:          number
    total_monthly_impact: number
    store_count:          number
  }
  stores: StoreMetrics[]
}

export default function ArchitectureProof() {
  // Route-level RequireRole allow={['ADMIN']} already gates this page.
  // (라우트 가드만으로 충분, 컴포넌트 내부 role 체크 제거)
  const [data, setData]       = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get('/agency/overview?period=month')
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const stores = data?.stores ?? []
  const props  = { stores, loading }

  return (
    <div className={styles.page}>
      <Toc sections={PROOF_SECTIONS} />

      <div className={styles.content}>
        {PROOF_SECTIONS.map((section) => {
          const shellClass =
            section.variant === 'hero' ? styles.heroShell
            : section.variant === 'cta' ? styles.ctaShell
            : styles.section

          return (
            <section key={section.id} id={section.id} className={shellClass}>
              {section.variant === 'panel' && (
                <h2 className={styles.sectionTitle}>
                  <span className={styles.sectionEmoji} aria-hidden>{section.emoji}</span>
                  {section.title}
                </h2>
              )}
              {section.render(props)}
            </section>
          )
        })}
      </div>
    </div>
  )
}
