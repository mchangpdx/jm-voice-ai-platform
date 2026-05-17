// Section Registry — Store Overview composition.
// Adding a new dashboard tile = 1 entry in OVERVIEW_SECTIONS + 1 component file.
// (Store Overview 섹션 레지스트리 — 새 위젯 = 1줄 + 1파일)
//
// `variant`:
//   'standalone'  — full-width row
//   'panel-left'  — first cell of a 2-col panels grid (next 'panel-right' pairs)
//   'panel-right' — second cell of the pair; skipped if previous wasn't 'panel-left'
//
// `visibleFor`:
//   'all'         — show for every industry/vertical
//   string[]      — show only when the store's industry is in this list
//
// Future: when backend.vertical_kind ships everywhere, switch to that.
import type { ReactElement } from 'react'

import PrimaryKpiSection, { type Metrics, type Period } from './overview/PrimaryKpiSection'
import SupportingKpiSection from './overview/SupportingKpiSection'
import PersonaEditorSection from './overview/PersonaEditorSection'
import LiveOrdersSection from './overview/LiveOrdersSection'
import RecentCallsSection from './overview/RecentCallsSection'

export interface OverviewSectionProps {
  period:         Period
  industry:       string | null
  storeName:      string | null
  metrics:        Metrics | null
  loadingMetrics: boolean
  onMetrics:      (m: Metrics | null) => void
}

export interface OverviewSection {
  id:         string
  title:      string                            // accessibility / future TOC
  variant:    'standalone' | 'panel-left' | 'panel-right'
  visibleFor: 'all' | string[]                  // industry whitelist or 'all'
  render:     (props: OverviewSectionProps) => ReactElement
}

export const OVERVIEW_SECTIONS: OverviewSection[] = [
  {
    id: 'kpi-primary', title: 'Primary KPIs', variant: 'standalone', visibleFor: 'all',
    render: (p) => (
      <PrimaryKpiSection period={p.period} industry={p.industry} onMetrics={p.onMetrics} />
    ),
  },
  {
    id: 'kpi-supporting', title: 'Supporting KPIs', variant: 'standalone', visibleFor: 'all',
    render: (p) => (
      <SupportingKpiSection metrics={p.metrics} industry={p.industry} loading={p.loadingMetrics} />
    ),
  },
  {
    id: 'persona', title: 'AI Persona', variant: 'panel-left', visibleFor: 'all',
    render: (p) => <PersonaEditorSection storeName={p.storeName} />,
  },
  {
    id: 'orders', title: 'Live Orders', variant: 'panel-right',
    // Order-flow verticals only. Beauty / home_services / auto_repair use appointments instead;
    // a future AppointmentsSection will register here for those verticals.
    visibleFor: ['restaurant', 'cafe', 'pizza', 'kbbq', 'sushi', 'chinese', 'mexican'],
    render: () => <LiveOrdersSection />,
  },
  {
    id: 'calls', title: 'Recent Calls', variant: 'standalone', visibleFor: 'all',
    render: () => <RecentCallsSection />,
  },
]

export function isVisibleFor(section: OverviewSection, industry: string | null): boolean {
  if (section.visibleFor === 'all') return true
  const key = (industry ?? '').toLowerCase()
  return section.visibleFor.includes(key)
}
