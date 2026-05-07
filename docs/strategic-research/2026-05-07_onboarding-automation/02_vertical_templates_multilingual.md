# Vertical Templates + Multilingual Policy

**Date**: 2026-05-07
**Goal**: 5 vertical (Cafe / KBBQ / Sushi / Chinese / Mexican) template 구조 + 다국어 정책 설계.

---

## 1. 다국어 정책 매트릭스 (사용자 명시)

| Vertical | 기본 (default) | 추가 언어 | Total | 적용 매장 |
|---|---|---|---|---|
| **Cafe** (multi-cultural urban) | EN | ES, KO, JA, ZH | **5** | JM Cafe (PDX fast-casual — 다양한 고객층) |
| **Korean Restaurant** (KBBQ / Chicken / etc) | EN | KO | **2** | JM BBQ (Beaverton AYCE) |
| **Japanese Restaurant** (Sushi / etc) | EN | JA | **2** | JM Sushi (SE Portland) |
| **Chinese Restaurant** | EN | ZH | **2** | (Phase 2+) |
| **Mexican Restaurant** | EN | ES | **2** | (Phase 2+) |
| **Generic Fast-Casual** | EN | (per matrix) | 1-2 | fallback |

### 정책 근거
- **Cafe = 다국어 wedge 핵심**: PDX fast-casual 카페는 인종/문화 다양 — 5개 언어 모두 native speaker 고객 발생. JM Cafe는 platform demo 매장으로 5 언어 모두 검증됨 (Phase 5에서 영어 + 한국어 + 일본어 + 스페인어 + 중국어 모두 라이브 통과).
- **타 vertical = 1 native + EN fallback**: 한식당 고객은 한국어 + 영어, 일식당은 일본어 + 영어 — 운영 단순화 + 영업 메시지 명확.
- **Maple 비교**: Maple = EN/ES/CN/TL (4 언어), KO 0/10 / JA 미지원. JM의 KO + JA 지원은 unfair advantage 직접 검증.

---

## 2. Template 디렉토리 구조 (제안)

```
backend/app/templates/
├── _base/
│   ├── system_prompt_invariants.txt      # 모든 vertical 공통 — I1/I2/I3/I4 invariants
│   ├── allergen_taxonomy.yaml            # FDA-9 + alias 매핑
│   └── modifier_base_rules.yaml          # Required/Optional/Min/Max 패턴
│
├── cafe/
│   ├── menu.yaml                         # 18 items × 5 langs
│   ├── modifier_groups.yaml              # 8 groups
│   ├── allergen_rules.yaml               # menu name → allergen 자동 추론
│   ├── system_prompt_base.txt            # Cafe vertical 흐름 (espresso/pastry/etc)
│   ├── multilang_aliases.yaml            # EN/ES/KO/JA/ZH
│   └── store_persona_template.yaml       # store_name/hours/address placeholder
│
├── kbbq/
│   ├── menu.yaml                         # AYCE tier + 단품 (cuts/banchan)
│   ├── modifier_groups.yaml              # cut(thin/thick) + spice + banchan refill + ssam
│   ├── allergen_rules.yaml               # 참기름(sesame), 콩(soy), 마늘소스(soy+gluten)
│   ├── system_prompt_base.txt            # 한국어 native + AYCE 흐름
│   └── multilang_aliases.yaml            # EN/KO
│
├── sushi/
│   ├── menu.yaml                         # 롤/사시미/오마카세 코스
│   ├── modifier_groups.yaml              # 와사비 옵션 + 추가 요청
│   ├── allergen_rules.yaml               # 생선/조개/대두/wheat (간장)
│   ├── system_prompt_base.txt            # 일본어 + 영어
│   └── multilang_aliases.yaml            # EN/JA
│
├── chinese/                              # Phase 2+
│   └── ...                               # EN/ZH
│
└── mexican/                              # Phase 2+
    └── ...                               # EN/ES
```

### 파일 형식 — YAML 권장 이유
- **사람 읽기**: 매장 운영자 + 영업 측 직접 검토 가능
- **Python parsing 단순**: `pyyaml` 표준
- **Diff 가독성**: git diff에서 변경 명확
- **JSON 대체 가능**: 영업 측이 GUI 로 편집 시 JSON 출력

---

## 3. Cafe Template — 핵심 파일 예시

### `cafe/menu.yaml`

```yaml
vertical: cafe
default_lang: en
supported_langs: [en, es, ko, ja, zh]
items:
  - id: latte
    en: Cafe Latte
    es: Café con leche
    ko: 카페 라떼
    ja: カフェラテ
    zh: 拿铁
    base_price: 5.50
    sizes: [small, medium, large]
    size_deltas: {small: 0.00, medium: 0.50, large: 1.00}
    base_allergens: [dairy]
    base_dietary: [vegetarian, gluten_free, nut_free]
    modifier_groups: [size, temperature, milk, shots, syrup, strength, foam]
    
  - id: almond_croissant
    en: Almond Croissant
    es: Croissant de almendra
    ko: 아몬드 크루아상
    ja: アーモンドクロワッサン
    zh: 杏仁牛角面包
    base_price: 5.50
    base_allergens: [gluten, wheat, dairy, egg, nuts]
    base_dietary: [vegetarian]
    modifier_groups: []
  
  # ... 18 items total
```

### `cafe/modifier_groups.yaml`

```yaml
groups:
  size:
    required: true
    min: 1
    max: 1
    options:
      - {id: small, en: "12oz", price_delta: 0.00}
      - {id: medium, en: "16oz", price_delta: 0.50}
      - {id: large, en: "20oz", price_delta: 1.00}
  
  milk:
    required: false  # optional for non-milk drinks
    min: 0
    max: 1
    options:
      - {id: whole, en: "Whole milk", price_delta: 0.00, allergen_add: [dairy]}
      - {id: oat, en: "Oat milk", price_delta: 0.75, allergen_add: [gluten, wheat], allergen_remove: [dairy]}
      - {id: almond, en: "Almond milk", price_delta: 0.75, allergen_add: [nuts], allergen_remove: [dairy]}
      - {id: soy, en: "Soy milk", price_delta: 0.75, allergen_add: [soy], allergen_remove: [dairy]}
      - {id: coconut, en: "Coconut milk", price_delta: 0.75, allergen_remove: [dairy]}
  
  # ... 8 groups
```

### `cafe/allergen_rules.yaml`

```yaml
# Auto-inference rules — used by AI helper during onboarding
patterns:
  - keywords: [croissant, bagel, muffin, scone, cake, cookie, bread, sandwich, toast]
    add_allergens: [gluten, wheat]
  - keywords: [almond, hazelnut, walnut, pecan, pistachio, cashew]
    add_allergens: [nuts]
  - keywords: [milk, cream, cheese, butter, yogurt, latte, cappuccino, mocha, frappé]
    add_allergens: [dairy]
  - keywords: [egg, omelet, frittata]
    add_allergens: [egg]
  - keywords: [oat, oatmeal, granola]
    add_allergens: [gluten, wheat]
```

### `cafe/system_prompt_base.txt` (excerpt)

```
You are Aria, the AI assistant for {{store_name}}, a fast-casual cafe.
Business hours: {{business_hours}}.

Today's menu:
{{menu_listing}}

Available modifiers:
{{modifier_listing}}

Languages: respond in the customer's spoken language. Supported: 
English, Spanish, Korean, Japanese, Chinese.

For allergen questions, ALWAYS call allergen_lookup tool — never answer 
from your own knowledge. (See I1-I4 invariants in _base.)

CROSS-CALL HISTORY ('last order', 'yesterday', 'previous order') = 
DO NOT call recall_order. Reply: 'I can only see orders from this 
current call — want to place a new one?' and stop.

# ... rest of cafe-specific rules
```

---

## 4. KBBQ Template — 핵심 차이점

### `kbbq/menu.yaml` (excerpt)

```yaml
vertical: kbbq
default_lang: en
supported_langs: [en, ko]
items:
  - id: ayce_premium
    en: AYCE Premium (All You Can Eat)
    ko: 무한리필 프리미엄
    base_price: 39.99      # per person
    pricing_model: per_person
    age_pricing:           # AYCE-specific
      adult: 39.99
      child_5_12: 19.99
      under_5: 0.00
    includes:              # AYCE included items
      - 갈비 (Galbi)
      - 불고기 (Bulgogi)
      - 삼겹살 (Pork Belly)
      - 차돌박이 (Brisket)
    modifier_groups: [party_size, banchan_refill, spice_level]
    
  - id: galbi
    en: Galbi (Marinated Short Rib)
    ko: 양념갈비
    base_price: 28.99
    base_allergens: [soy, gluten, wheat, sesame]   # 간장 + 참기름
    pricing_model: per_serving
    modifier_groups: [cut, doneness, spice, ssam]
```

### `kbbq/modifier_groups.yaml` (한식 specific)

```yaml
groups:
  cut:
    required: false
    options:
      - {id: thin, en: "Thin sliced", ko: "얇게", price_delta: 0.00}
      - {id: thick, en: "Thick cut", ko: "두껍게", price_delta: 0.00}
  
  spice:
    required: false
    options:
      - {id: mild, en: "Mild", ko: "순한맛", price_delta: 0.00}
      - {id: medium, en: "Medium spicy", ko: "중간 매운맛", price_delta: 0.00}
      - {id: spicy, en: "Spicy", ko: "매운맛", price_delta: 0.00}
      - {id: extra_spicy, en: "Extra spicy", ko: "아주 매운맛", price_delta: 0.00}
  
  banchan_refill:
    required: false
    options:
      - {id: yes, en: "Refill banchan", ko: "반찬 리필", price_delta: 0.00}
  
  ssam:
    required: false
    options:
      - {id: lettuce, en: "Lettuce wrap", ko: "상추쌈", price_delta: 0.00}
      - {id: perilla, en: "Perilla leaf", ko: "깻잎", price_delta: 0.00}
```

### `kbbq/system_prompt_base.txt` 핵심 차이

- 한국어 native — invariants 한국어 + 영어 병기
- AYCE 흐름: party_size 먼저 + 시간 제한 (보통 90분) + age pricing
- "spicy = 한국식 매운맛 ≠ 일반 매운맛" — 봇이 customer expectation 매니지

---

## 5. Modifier 시스템 DB Schema (Phase 7-A 신규)

```sql
-- backend/scripts/migrate_modifier_system.sql (Phase 7-A)

CREATE TABLE modifier_groups (
    id              SERIAL PRIMARY KEY,
    store_id        UUID NOT NULL REFERENCES stores(id),
    code            TEXT NOT NULL,              -- 'size','milk','spice'
    display_name    TEXT NOT NULL,              -- 'Size', 'Milk type'
    is_required     BOOLEAN NOT NULL DEFAULT false,
    min_select      INT NOT NULL DEFAULT 0,
    max_select      INT NOT NULL DEFAULT 1,
    sort_order      INT NOT NULL DEFAULT 0,
    UNIQUE(store_id, code)
);

CREATE TABLE modifier_options (
    id              SERIAL PRIMARY KEY,
    group_id        INT NOT NULL REFERENCES modifier_groups(id),
    code            TEXT NOT NULL,              -- 'oat','large','spicy'
    display_name    TEXT NOT NULL,
    price_delta     DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    allergen_add    TEXT[] DEFAULT '{}',        -- e.g. {gluten,wheat}
    allergen_remove TEXT[] DEFAULT '{}',        -- e.g. {dairy}
    sort_order      INT NOT NULL DEFAULT 0,
    UNIQUE(group_id, code)
);

CREATE TABLE menu_item_modifier_groups (
    menu_item_id    INT NOT NULL REFERENCES menu_items(id),
    group_id        INT NOT NULL REFERENCES modifier_groups(id),
    PRIMARY KEY (menu_item_id, group_id)
);

-- Multilingual aliases (lookup performance via lang_code index)
CREATE TABLE menu_item_aliases (
    menu_item_id    INT NOT NULL REFERENCES menu_items(id),
    lang_code       VARCHAR(2) NOT NULL,        -- 'en','es','ko','ja','zh'
    alias           TEXT NOT NULL,
    is_primary      BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (menu_item_id, lang_code, alias)
);
CREATE INDEX idx_menu_aliases_lang ON menu_item_aliases(lang_code);

-- RLS policies (mandatory per CLAUDE.md)
ALTER TABLE modifier_groups ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON modifier_groups
    USING (store_id IN (SELECT id FROM stores WHERE tenant_id = current_setting('app.tenant_id')::uuid));
-- ... similar for modifier_options, menu_item_modifier_groups, menu_item_aliases
```

---

## 6. 코드 재사용률 측정 — 4 Layer

| Layer | Cafe → KBBQ | Cafe → Sushi | KBBQ → Chinese |
|---|:---:|:---:|:---:|
| Layer 1 (RLS/auth/config) | **100%** | **100%** | **100%** |
| Layer 2 (skills/슬롯/dispatcher) | **95%** | **95%** | **95%** |
| Layer 3 (knowledge/KPI) | **100%** (restaurant industry 같음) | **100%** | **100%** |
| Layer 4 (POS adapter — Loyverse 등) | **100%** | **100%** | **100%** |
| **Vertical-specific** (template) | 0% (새로 만듦) | 0% | 60% (cut/spice 패턴 유사) |
| Voice 흐름 | 90% (메뉴 lookup, modifier, 알러젠 동일) | 85% | 90% |
| 다국어 prompt | 60% (새 언어 추가) | 40% (스페인/중국어 빼고 일본어) | 80% (KO 패턴 → ZH 적용) |
| **종합 재사용률** | **~85%** | **~80%** | **~90%** |

→ JM Cafe → JM BBQ onboarding **2-3주** (template 추출 동시 진행), JM BBQ → JM Sushi **1-2주** (template framework 검증), 이후 매 vertical **1주**.

---

## 7. AI 추론 도우미 — Onboarding 자동화

### `backend/app/services/onboarding/ai_helper.py` (Phase 7-A 신규)

```python
import anthropic

async def infer_allergens(menu_item_name: str, vertical: str) -> dict:
    """
    LLM-based allergen inference using FDA-9 + vertical-specific rules.
    
    Examples:
      ('Almond Croissant', 'cafe') → 
        {allergens: [gluten,wheat,dairy,egg,nuts], confidence: 0.95}
      ('Galbi', 'kbbq') → 
        {allergens: [soy,gluten,wheat,sesame], confidence: 0.90,
         reason: 'Marinated with soy sauce + sesame oil'}
    """
    rules = load_template(f"templates/{vertical}/allergen_rules.yaml")
    prompt = f"""
    Menu: {menu_item_name}
    Vertical: {vertical}
    Pattern rules: {rules}
    
    Return JSON: {{allergens: [...], confidence: 0-1, reason: '...'}}
    Be conservative — when unsure, mark as 'uncertain' not absent.
    """
    response = await anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_json(response.content)


async def generate_aliases(menu_item: str, target_langs: list[str]) -> dict:
    """
    'Cafe Latte' + ['ko','ja','es','zh'] →
      {ko: '카페 라떼', ja: 'カフェラテ', es: 'Café con leche', zh: '拿铁'}
    """
    prompt = f"""
    Menu item: {menu_item}
    Target languages: {target_langs}
    Return common transliteration / native term used in restaurant menus.
    Use JSON format: {{lang_code: alias}}.
    """
    # ... LLM call


async def parse_menu_pdf(pdf_path: str, vertical: str) -> list[dict]:
    """
    Operator uploads menu PDF/image → 
      OCR + structure extraction → 
      menu items list + suggested modifiers + allergen pre-fill
    """
    # 1. OCR via Claude vision or pytesseract
    # 2. Structure: 카테고리 추출 → items per category
    # 3. Per item: name, price, suggested modifiers (from vertical template)
    # 4. Operator reviews + corrects via Admin UI
```

### ROI 매장당 — 30시간 → 4시간

| 작업 | 수동 | 자동화 (AI helper + template) |
|---|---|---|
| 메뉴 입력 | 8h | 5min POS sync + 30min review |
| Modifier 매핑 | 6h | 30min template apply |
| 알러젠 매핑 | 4h | 30min AI infer + review |
| 다국어 alias | 4h | 15min LLM generate + review |
| System prompt customize | 4h | 30min template + 매장 페르소나 |
| 라이브 검증 | 8h | 2h regression + 1 통화 |
| **합계** | **34h** | **4h** |
| **절감** | — | **30h / 매장 (88% 감소)** |

---

## 8. Multilingual 시스템 프롬프트 디자인

### 핵심 원칙
- **Single base prompt + lang-aware sections**: 한 개 prompt가 5 언어 모두 처리
- **`{{lang_section}}` placeholder**: vertical/store 설정에 따라 활성 언어 섹션만 inject
- **Lost-in-middle 회피**: 다국어 instructions는 `{{language_policy}}` block 한 곳에만

### 예시 (`_base/system_prompt_invariants.txt` excerpt)

```
=== LANGUAGE POLICY ===
{{language_policy_block}}
=========================

# language_policy_block injected per store:
# Cafe (5 lang): 
#   "Detect customer language from their first utterance and respond in 
#    that language. Supported: English, Spanish (Español), Korean (한국어), 
#    Japanese (日本語), Chinese (中文). Default: English. NEVER mix 
#    languages within a single response."
#
# KBBQ (2 lang):
#   "Respond in the customer's language. Supported: English, Korean (한국어). 
#    Default: English. NEVER mix languages within a single response."
```

### Per-store override (DB stores 컬럼)
- `stores.languages` TEXT[] — 운영자가 vertical default 변경 가능
- 예: 일반 Cafe vertical은 5 lang, 그러나 노스팟의 작은 카페는 EN+ES만 활성화 가능

---

## 9. 결정 + 다음 단계 추천

### Phase 7-A 작업 (JM BBQ 어댑터 만들면서 동시 진행)

**Week 1**:
1. `backend/app/templates/cafe/` 디렉토리 + 파일 생성 — JM Cafe 역공학
2. JM Cafe 새 메뉴 SQL 적용 (01번 문서 참조)
3. Modifier system DB schema + RLS migration
4. Loyverse modifier sync 확장 (현재 메뉴만 → modifier groups + options 추가)

**Week 2-3**:
5. JM BBQ 어댑터 — KBBQ template 추출하면서 첫 매장 onboarding
6. AYCE pricing model + party_size + 시간 제한 흐름 구현
7. 한국어 native 시스템 프롬프트 검증 (Tier 3 invariant 한국어로)
8. 라이브 검증 통화 (영문 + 한국어)

**Week 4 (검증)**:
9. JM Sushi 어댑터 — sushi template 추출
10. 시간 측정: "30시간 → X시간" 실측 (목표 4-6시간)
11. AI 추론 도우미 prototype (allergen + alias)

### Phase 8 (Admin UI Wizard) — 상세는 03번 문서 참조
