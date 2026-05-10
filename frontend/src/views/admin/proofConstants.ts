// Architecture-proof page constants (per FRONTEND_HANDOFF_SPEC 2026-05-10)
// (아키텍처 입증 페이지 상수 — backend handoff spec과 1:1 일치)

export type StoreMode = 'real' | 'sim'

export interface StoreModeBadge {
  mode: StoreMode
  since: string | null
}

// JM Cafe is the only real store; all others run on synthetic 60-day data
// (JM Cafe만 실 매장. 나머지는 60일 합성 데이터로 동일 아키텍처 입증)
export const STORE_MODE_BADGES: Record<string, StoreModeBadge> = {
  '7c425fcb-91c7-4eb7-982a-591c094ba9c9': { mode: 'real', since: '2026-04-25' },
}

export function getStoreMode(storeId: string): StoreModeBadge {
  return STORE_MODE_BADGES[storeId] ?? { mode: 'sim', since: null }
}

export interface CodeReuseLayer {
  name:      string
  reuse:     number  // percent
  locReused: number
  locTotal:  number
}

export const CODE_REUSE_LAYERS: CodeReuseLayer[] = [
  { name: 'Layer 1 — Auth / RLS / Gemini / OpenAI',          reuse: 100, locReused:  263, locTotal:  263 },
  { name: 'Layer 2 — Universal Skills (Tools/Schemas)',      reuse:  95, locReused: 1410, locTotal: 1484 },
  { name: 'Layer 3 — Knowledge Adapters',                    reuse:  93, locReused:  310, locTotal:  334 },
  { name: 'Layer 4 — External Adapters (POS/SMS/Email)',     reuse:  84, locReused:  390, locTotal:  463 },
  { name: 'API Layer (FastAPI routes)',                      reuse:  81, locReused: 5780, locTotal: 7169 },
  { name: 'Services Layer (Bridge / Menu)',                  reuse:  80, locReused: 4920, locTotal: 6149 },
]

export interface VerticalAddCost {
  vertical: string
  days:     number
  mode:     string
  loc:      string
}

export const VERTICAL_ADD_COSTS: VerticalAddCost[] = [
  { vertical: 'cafe',          days: 25.0, mode: 'baseline (real)', loc: 'all'                          },
  { vertical: 'beauty',        days:  1.5, mode: 'sim',             loc: '~120'                         },
  { vertical: 'auto_repair',   days:  1.5, mode: 'sim',             loc: '~120'                         },
  { vertical: 'home_services', days:  1.5, mode: 'sim',             loc: '~120'                         },
  { vertical: 'kbbq',          days:  0.5, mode: 'sim',             loc: '1,137 (templates + adapter)'  },
]

export const LIVE_DEMO_PHONE      = '+1 (503) 994-1265'
export const LIVE_DEMO_TEL_HREF   = 'tel:+15039941265'
export const LIVE_DEMO_STORE_NAME = 'JM Cafe'
