// Section Registry — adding a new proof dimension is one entry in this array.
// Each entry: id (anchor + TOC key) + title + emoji + render(props).
// (섹션 레지스트리 — 새 입증 차원 추가 = 이 배열에 1줄 추가)
import type { ReactElement } from 'react'

import HeroKpi from './proof/HeroKpi'
import RollupSection from './proof/RollupSection'
import ReuseSection from './proof/ReuseSection'
import CostSection from './proof/CostSection'
import ArchitectureSection from './proof/ArchitectureSection'
import CompetitiveSection from './proof/CompetitiveSection'
import RoiCalculator from './proof/RoiCalculator'
import LiveDemoCta from './proof/LiveDemoCta'

export interface StoreMetrics {
  store_id:        string
  store_name:      string
  industry:        string
  monthly_impact:  number
  conversion_rate: number
  avg_value:       number
  total_calls:     number
}

export interface ProofSectionProps {
  stores:  StoreMetrics[]
  loading: boolean
}

export interface ProofSection {
  id:      string                                       // anchor id + TOC key
  title:   string                                       // sidebar label + section h2
  emoji:   string                                       // visual marker
  variant: 'hero' | 'panel' | 'cta'                     // CSS shell choice
  render:  (props: ProofSectionProps) => ReactElement
}

export const PROOF_SECTIONS: ProofSection[] = [
  { id: 'kpi',          title: 'Headline KPIs',         emoji: '🎯', variant: 'hero',  render: () => <HeroKpi /> },
  { id: 'rollup',       title: 'Vertical Roll-up',      emoji: '📊', variant: 'panel', render: (p) => <RollupSection stores={p.stores} loading={p.loading} /> },
  { id: 'reuse',        title: 'Code Reuse',            emoji: '🧬', variant: 'panel', render: () => <ReuseSection /> },
  { id: 'cost',         title: 'Add-Vertical Cost',     emoji: '⏱',  variant: 'panel', render: () => <CostSection /> },
  { id: 'architecture', title: '4-Layer Architecture',  emoji: '🏛',  variant: 'panel', render: () => <ArchitectureSection /> },
  { id: 'competitive',  title: 'vs Competitors',        emoji: '⚔',  variant: 'panel', render: () => <CompetitiveSection /> },
  { id: 'roi',          title: 'ROI Calculator',        emoji: '🧮', variant: 'panel', render: () => <RoiCalculator /> },
  { id: 'cta',          title: 'Try It Live',           emoji: '📞', variant: 'cta',   render: () => <LiveDemoCta /> },
]
