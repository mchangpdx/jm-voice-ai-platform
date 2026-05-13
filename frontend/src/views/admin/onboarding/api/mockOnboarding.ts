// Mock onboarding API — used while backend endpoints are pending.
// (백엔드 endpoint 준비 전까지 사용. 동일한 contract shape으로 응답)
// Fixture mirrors backend test: test_jm_pizza_live_data_folds_34_rows_to_24_items
// (JM Pizza Loyverse 2026-05-12 live data: 34 rows → 24 normalized items)

import type {
  ExtractRequest, RawMenuExtraction, RawMenuItem,
  NormalizedMenuItem, PreviewYamlRequest, PreviewYamlResponse,
  FinalizeRequest, FinalizeResponse,
} from '../types'

const PIZZA_NAMES = [
  'White Pizza', 'Sausage Pizza', 'Pepperoni Pizza', 'Cheese Pizza',
  'Vegan Garden', 'Veggie Supreme', 'Hawaiian',
  'Spicy Meat & Veggie', 'Meat Lover', 'Big Joe',
]
const STANDALONE_NAMES = [
  'Soda', 'Chocolate Chip Cookie', 'Brownie', 'Buffalo Wings',
  'Breadsticks', 'Garlic Knots', 'Caprese Salad', 'House Salad',
  'Caesar Salad', 'Gluten-Free Slice', 'Vegan Slice',
  'Daily Special Slice', 'Pepperoni Slice', 'Cheese Slice',
]

// Deterministic-ish confidence so UI demos cover all three badge colors
function pizzaConfidence(i: number): number {
  if (i === 4) return 0.62       // Vegan Garden → red (manual review)
  if (i === 7) return 0.81       // Spicy Meat & Veggie → yellow
  return 0.97
}
function standaloneConfidence(j: number): number {
  if (j === 9) return 0.55       // Gluten-Free Slice → red
  if (j === 6 || j === 7) return 0.78  // salads → yellow
  return 0.96
}

function pizzaAllergens(name: string): string[] | null {
  const a: string[] = ['gluten', 'dairy']
  if (name.includes('Meat') || name === 'Pepperoni Pizza' || name === 'Sausage Pizza' || name === 'Hawaiian' || name === 'Big Joe') {
    a.push('pork')
  }
  return a
}
function standaloneAllergens(name: string): string[] | null {
  if (name === 'Soda') return null
  if (name.includes('Cookie') || name === 'Brownie' || name.includes('Bread') || name.includes('Knot') || name.includes('Slice')) return ['gluten', 'dairy']
  if (name === 'Buffalo Wings') return ['dairy']
  if (name.includes('Salad')) return ['dairy']
  return null
}

function buildRawItems(): RawMenuItem[] {
  const items: RawMenuItem[] = []
  PIZZA_NAMES.forEach((name, i) => {
    const allergens = pizzaAllergens(name)
    const c = pizzaConfidence(i)
    items.push({
      name, price: 18.0, category: 'Pizza', description: null,
      size_hint: '14 inch (Small)', pos_item_id: `P${i}`,
      pos_variant_id: `V${i}-S`, sku: null, stock_quantity: null,
      detected_allergens: allergens, confidence: c,
    })
    items.push({
      name, price: 26.0, category: 'Pizza', description: null,
      size_hint: '18 inch (Large)', pos_item_id: `P${i}`,
      pos_variant_id: `V${i}-L`, sku: null, stock_quantity: null,
      detected_allergens: allergens, confidence: c,
    })
  })
  STANDALONE_NAMES.forEach((name, j) => {
    items.push({
      name, price: 5.0,
      category: name.includes('Slice') ? 'Pizza' : (name.includes('Salad') ? 'Salad' : 'Sides'),
      description: null, size_hint: null,
      pos_item_id: `S${j}`, pos_variant_id: `S${j}-V`,
      sku: null, stock_quantity: null,
      detected_allergens: standaloneAllergens(name),
      confidence: standaloneConfidence(j),
    })
  })
  return items
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function mockExtract(req: ExtractRequest): Promise<RawMenuExtraction> {
  await delay(1500)
  // Always return the JM Pizza fixture regardless of source_type — demo only
  const source = req.source_type === 'pdf' ? 'image' : req.source_type
  return {
    source,
    items: buildRawItems(),
    detected_modifiers: ['size', 'crust', 'toppings'],
    vertical_guess: 'pizza',
    warnings: req.source_type === 'image'
      ? ['2 items had low OCR confidence — please review (OCR 신뢰도 낮음 — 검토 필요)']
      : [],
  }
}

export async function mockNormalize(raw: RawMenuExtraction): Promise<NormalizedMenuItem[]> {
  await delay(50)
  // Group by (name, pos_item_id) like backend normalizer
  const groups = new Map<string, NormalizedMenuItem>()
  for (const r of raw.items) {
    const key = `${r.name}::${r.pos_item_id ?? ''}`
    let g = groups.get(key)
    if (!g) {
      g = {
        name: r.name,
        category: r.category,
        description: r.description,
        pos_item_id: r.pos_item_id,
        detected_allergens: r.detected_allergens,
        confidence: r.confidence,
        variants: [],
      }
      groups.set(key, g)
    } else {
      g.confidence = Math.min(g.confidence, r.confidence)
    }
    g.variants.push({
      size_hint: r.size_hint, price: r.price,
      pos_variant_id: r.pos_variant_id, sku: r.sku,
      stock_quantity: r.stock_quantity,
    })
  }
  const items = Array.from(groups.values())
  for (const it of items) it.variants.sort((a, b) => a.price - b.price)
  return items
}

export async function mockPreviewYaml(req: PreviewYamlRequest): Promise<PreviewYamlResponse> {
  await delay(200)
  return {
    menu_yaml: {
      vertical: req.vertical,
      items: req.items.map((i) => ({
        name: i.name,
        category: i.category,
        variants: i.variants.map((v) => ({ size: v.size_hint, price: v.price })),
        allergens: i.detected_allergens ?? [],
      })),
    },
  }
}

export async function mockFinalize(_req: FinalizeRequest): Promise<FinalizeResponse> {
  await delay(5000)
  return {
    store_id: 'mock-store-id-0001',
    voice_agent_url: 'https://voice.jmtechone.com/agent/mock',
    test_call_number: '+1-555-DEMO-CALL',
  }
}
