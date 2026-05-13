// Onboarding wizard shared types — mirror backend contract
// (온보딩 위저드 공유 타입 — 백엔드 contract와 1:1 매칭)
// Spec: docs/handoff-frontend-onboarding-wizard.md §2 (Frozen until 2026-05-15)

export type SourceType = 'loyverse' | 'url' | 'pdf' | 'image' | 'csv' | 'manual'

export type VerticalGuess =
  | 'pizza' | 'cafe' | 'kbbq' | 'sushi' | 'mexican' | 'general' | null

export interface ManualItemInput {
  name: string
  price: number
  category?: string
}

export interface ExtractPayload {
  api_key?: string
  url?: string
  image_paths?: string[]
  file_path?: string
  items?: ManualItemInput[]
}

export interface ExtractRequest {
  source_type: SourceType
  payload: ExtractPayload
}

export interface RawMenuItem {
  name: string
  price: number
  category: string | null
  description: string | null
  size_hint: string | null
  pos_item_id: string | null
  pos_variant_id: string | null
  sku: string | null
  stock_quantity: number | null
  detected_allergens: string[] | null
  confidence: number          // 0.0 - 1.0
}

export interface RawMenuExtraction {
  source: 'loyverse' | 'url' | 'image' | 'csv' | 'manual'
  items: RawMenuItem[]
  detected_modifiers: string[]
  vertical_guess: VerticalGuess
  warnings: string[]
}

export interface NormalizedVariant {
  size_hint: string | null
  price: number
  pos_variant_id: string | null
  sku: string | null
  stock_quantity: number | null
}

export interface NormalizedMenuItem {
  name: string
  category: string | null
  description: string | null
  pos_item_id: string | null
  detected_allergens: string[] | null
  confidence: number
  variants: NormalizedVariant[]
}

export interface PreviewYamlRequest {
  items: NormalizedMenuItem[]
  vertical: string
}

export interface PreviewYamlResponse {
  menu_yaml: Record<string, unknown>
}

export interface FinalizeRequest {
  store_name: string
  phone_number: string
  manager_phone: string
  menu_yaml: Record<string, unknown>
  loyverse_api_key?: string
}

export interface FinalizeResponse {
  store_id: string
  voice_agent_url: string
  test_call_number: string
}
