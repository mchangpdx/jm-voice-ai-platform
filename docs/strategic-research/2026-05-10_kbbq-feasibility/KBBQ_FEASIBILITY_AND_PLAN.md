# JM KBBQ 신규 매장 도입 — 코드 재사용 분석 + 실행 계획

**작성일**: 2026-05-10
**대상**: JM Tech One Backend / Strategy
**목적**: 장충동(JCD K-Barbecue) 메뉴를 베이스로 가상 매장 **JM KBBQ** (장르: Korean BBQ FSR) 시뮬레이션 도입 시, 기존 JM Cafe 코드의 재사용 가능 범위 + KBBQ 구체 실행 계획 정리

---

## 0. Executive Summary

| 항목 | 값 |
|---|:---:|
| **백엔드 LOC 재사용률** | **81.2%** (12,905 / 15,894 LOC) |
| **백엔드 파일 재사용률** | **95%** (91 / 96 files) |
| **Feature 1:1 재사용** | **79%** (11 / 14 capabilities) |
| **신규 작성 필요 코드** | **5 파일** (~880 LOC, 대부분 YAML/TXT 템플릿) |
| **기존 코드 수정 필요** | **5 파일** (대부분 enum/dispatch 추가, 신규 로직 X) |
| **베이스 라인 KBBQ 라이브 가능 시점** | **5–7 founder-days** |
| **정식 FSR 운영 (open tab + multi-round)** | **+6–10 founder-days** (별도 sprint) |
| **POS** | **Loyverse — 테스트용 ⭕ / 정식 FSR 운영 ❌** |

**한 줄 결론**: JM Cafe의 4계층 아키텍처가 의도대로 작동 — Layer 1–2 (Auth/RLS/Skills/Tools)는 95%+ 재사용, Layer 3 (Knowledge)는 copy-adapt, Layer 4 (Adapters)는 provider-agnostic. KBBQ 도입은 신규 산업 확장이 아니라 **두 번째 vertical 적용이라는 표준 절차의 검증**.

---

## 1. 코드 재사용 감사 (Code Reuse Audit)

### 1.1 Layer별 재사용률

| Layer | LOC | 재사용 LOC | 재사용 % | 비고 |
|---|---:|---:|:---:|---|
| Layer 1 — Core (Auth/RLS/Gemini) | 263 | 263 | **100%** | 완전 vertical-agnostic |
| Layer 2 — Skills (Tools/Scheduler) | 1,484 | 1,410 | **95%** | 모든 tool schema 재사용. catalog/service.py만 yaml 경로 파라미터 |
| Layer 3 — Knowledge (Metrics) | 334 | 310 | **93%** | restaurant.py → kbbq.py 복사 필요 |
| Layer 4 — Adapters (Twilio/SMTP/Loyverse) | 463 | 390 | **84%** | Loyverse webhook 라우팅에 'kbbq' 분기 추가 |
| API Layer (FastAPI routes) | 7,169 | 5,780 | **81%** | realtime_voice 단일매장 하드코드 / voice_websocket 1줄 store name |
| Services Layer (Bridge/Menu/Policy) | 6,149 | 4,920 | **80%** | flows.py vertical 파라미터화 + transactions.py enum 추가 |
| Models | 32 | 32 | **100%** | 완전 generic |
| **합계** | **15,894** | **12,905** | **81.2%** | |

### 1.2 Feature Surface별 재사용

| Capability | Cafe | KBBQ | 재사용 클래스 | 추가 작업 |
|---|:---:|:---:|:---:|:---:|
| Auth & RLS | ✅ | ✅ | 🟢 1:1 | 없음 |
| Voice WebSocket (Retell legacy + Realtime) | ✅ | ✅ | 🟡 DB-driven | 없음 |
| Realtime Voice (Twilio/OpenAI) | ✅ | ✅ | 🟠 phone→store 라우팅 추가 | 낮음 |
| POS Integration (Loyverse) | ✅ | ✅ | 🟢 1:1 | 없음 |
| Menu Sync | ✅ | ✅ | 🟢 1:1 | 없음 |
| Allergen Lookup | ✅ | ✅ | 🟢 1:1 | KBBQ keyword 추가 |
| Order Flow (single-shot) | ✅ | ✅ | 🟡 단일 transaction OK (시뮬) | 없음 |
| Order Flow (multi-round all-you-can-eat) | ❌ | 🟡 옵션 | 🟠 신규 lane | Phase 5 별도 |
| Reservation Flow | ✅ | ✅ | 🟢 1:1 | 없음 |
| Payment Bridge (pay-link) | ✅ | ✅ | 🟢 1:1 | 없음 |
| Payment Bridge (open tab dine-in) | ❌ | 🟡 옵션 | 🟠 신규 lane | Phase 6 별도 |
| Email/SMS Channels | ✅ | ✅ | 🟢 1:1 | 없음 |
| System Prompt Assembly | ✅ | ✅ | 🟢 template-driven | KBBQ template 4개 |
| State Machine | ✅ | ✅ | 🟢 1:1 | 없음 |
| 5-Language Support | ✅ | ✅ | 🟢 1:1 | KBBQ는 KO+EN만 |
| Modifier Decomposition (FIX-B) | ✅ | ✅ | 🟢 1:1 | 없음 |

**1:1 재사용 11개 / 확장 필요 3개 / 옵션 2개 = 79% 1:1, 21% 확장 (그중 2개는 정식 FSR용 옵션)**

### 1.3 하드코드된 "cafe" 잔재 — 단 2건

| 위치 | 영향 | 수정안 |
|---|:---:|---|
| `realtime_voice.py:103` `JM_CAFE_STORE_ID = "7c425fcb-..."` | 🔴 단일매장 라우팅 — KBBQ 라이브 차단 | `phone_routing` 테이블 lookup으로 대체 |
| `voice_websocket.py:1316` `"Thanks for calling JM Cafe..."` | 🟡 매장명 하드코드 — UX 영향 | `f"Thanks for calling {store['name']}..."` |

나머지 25건의 "cafe" 매치는 모두 system prompt/docstring **예시 텍스트** — 새 매장에 그대로 배포해도 무해 (LLM 입장에서 일반 예시).

### 1.4 Vertical 등록 지점 — 단 1줄

```python
# backend/app/services/bridge/transactions.py:22
_VERTICALS = {"restaurant", "home_services", "beauty", "auto_repair"}
#  → {"restaurant", "kbbq", "home_services", "beauty", "auto_repair"}
```

`bridge/flows.py`의 `vertical="restaurant"` 5곳도 store record에서 읽도록 파라미터화 (호출부만 수정, 알고리즘 무변경).

---

## 2. JM KBBQ 메뉴 — 장충동 PDF 기반 (77 아이템)

### 2.1 카테고리 + 가격대 요약

| 카테고리 | 개수 | 가격대 | 룰 |
|---|:---:|:---:|---|
| Appetizers (A1-A13) | 13 | $5.00–$23.95 | 떡볶이류 +Ramen/+Cheese add-on |
| Shareable Plate (S1-S4) | 4 | $19.95–$45.95 | Soondae S/M variant |
| BBQ Combo Set (A/B) | 2 | $85 / $105 | No substitute |
| BBQ Beef A La Carte (B1-B7) | 7 | $29.95–$45.95 | Min 2 order |
| BBQ Pork A La Carte (B8-B13) | 6 | $27.95–$30.95 | Min 2 order |
| BBQ Chicken/Squid A La Carte (B14-B15) | 2 | $25.95–$27.95 | Min 2 order |
| Hot Pot 전골류 (H1-H7) | 7 | $45.95 | For 2 People |
| Entrees 식사류 (E1-E31) | 31 | $14.95–$27.95 | Rice + 반찬 무한 리필 |
| Side Order | 7 | $2.50–$5.00 | Corn cheese, egg, rice cake |
| **합계** | **77** | | |

### 2.2 브랜딩 변경 (장충동 → JM KBBQ)

| 원본 | JM KBBQ | 비고 |
|---|---|---|
| 장충동 JCD K-Barbecue | **JM Korean BBQ** (영문 정식) / **JM KBBQ** (단축) | 매장 이름 |
| 장충동 족발 (S1) | JM 족발 / Jokbal | "장충동" prefix 제거 |
| 장충동 보쌈 (S2) | JM 보쌈 / Bossam | 동일 |
| 메뉴 한국어 표기 | 그대로 유지 | Galbi/Bulgogi/Samgyeopsal 등 음역 |

### 2.3 다언어 정책 (메모리 `feedback_multilingual_policy.md` 적용)

> **KBBQ vertical = KO + EN 만** (JA/ZH/ES 제외 — Cafe와 다름)

```yaml
# 메뉴 항목 예시 (cafe와 달리 2-language)
- id: galbi_marinated
  en: Galbi (Marinated Beef Short Rib)
  ko: 양념갈비
  category: bbq_beef
  base_price: 45.95
```

음성 응대 시:
- 한국 손님 → "양념갈비 두 인분 주문하시겠어요?"
- 영어 손님 → "Two orders of marinated short rib?"
- Galbi/Bulgogi/Samgyeopsal/Bibimbap/Tteokbokki/Soondae/Banchan은 **고유명사로 음역 유지**

---

## 3. KBBQ 구체 실행 계획 (Day 1 산출물 명세)

### 3.1 메뉴 (Menu) — `templates/kbbq/menu.yaml`

**구조** (cafe pattern 그대로 + KO/EN dual):

```yaml
vertical: kbbq
default_lang: en
supported_langs: [en, ko]

categories:
  - id: appetizer
    en: Appetizers
    ko: 안주
  - id: shareable
    en: Shareable Plate
    ko: 공유 메뉴
  - id: bbq_combo
    en: BBQ Combo
    ko: BBQ 콤보
  - id: bbq_beef
    en: BBQ Beef A La Carte
    ko: 소고기 단품
  - id: bbq_pork
    en: BBQ Pork A La Carte
    ko: 돼지고기 단품
  - id: bbq_other
    en: BBQ Chicken / Squid
    ko: 닭/오징어 단품
  - id: hot_pot
    en: Korean Style Hot Pot
    ko: 전골류
  - id: entree
    en: Entrees
    ko: 식사류
  - id: side
    en: Sides
    ko: 사이드

items:
  # ─── BBQ Beef (B1-B7) — Min 2 order rule
  - id: galbi_saeng
    en: Saeng Galbi (Plain Beef Short Rib)
    ko: 생갈비
    category: bbq_beef
    base_price: 45.95
    base_allergens: []
    base_dietary: [gluten_free, dairy_free, nut_free]
    modifier_groups: [meat_doneness, bbq_party_size, wrap_extras, banchan_refill_info]
    rules: [bbq_min_two_orders]
  # ... (B2-B7 동일 패턴)

  # ─── Hot Pot (H1-H7) — For 2 People rule
  - id: budae_jeongol
    en: Budae Jeongol (Spicy Army Stew Hot Pot)
    ko: 부대전골
    category: hot_pot
    base_price: 45.95
    serves: 2  # ← KBBQ 신규 메타필드 (info, runtime 사용 안함)
    base_allergens: [soy, wheat, gluten, dairy, pork]
    base_dietary: []
    modifier_groups: [spice_level, add_on_starch, banchan_refill_info]

  # ─── Add-on variants (Tteokbokki / Budae jjigae / Squid stir-fry)
  - id: tteokbokki
    en: Tteokbokki (Spicy Rice Cake)
    ko: 떡볶이
    category: appetizer
    base_price: 14.95
    base_allergens: [soy, wheat, gluten]
    base_dietary: [vegetarian]
    modifier_groups: [spice_level, add_on_starch]
    add_on_options:
      - {id: ramen,  delta: 5.00}
      - {id: cheese, delta: 5.00, allergen_add: [dairy]}
```

**총 LOC**: ~600줄 (cafe menu.yaml 371줄 대비 ~1.6배 — 카테고리 9개 × 평균 8.5 아이템).

### 3.2 Modifier — `templates/kbbq/modifier_groups.yaml`

**12 그룹** (cafe 8 + KBBQ 신규 4):

| Group ID | 종류 | Required | Min/Max | 적용 대상 |
|---|---|:---:|:---:|---|
| `meat_doneness` | 신규 | ✅ | 1/1 | BBQ Beef Saeng/Deung/Jumullleok |
| `spice_level` | 신규 | optional | 0/1 | 매운 메뉴 8개 |
| `bbq_party_size` | 신규 | ✅ | 1/1 | BBQ A La Carte 15개 |
| `pork_cut_thickness` | 신규 | ✅ | 1/1 | 삼겹살/대패삼겹살 |
| `add_on_starch` | 신규 (cafe `syrup` 패턴 변형) | optional | 0/2 | 떡볶이/오징어볶음/부대찌개 |
| `egg_style` | 신규 | optional | 0/1 | Bibimbap/Dolsot/Manduguk |
| `wrap_extras` | 신규 | optional | 0/3 | BBQ 전체 |
| `rice_swap` | 신규 | optional | 0/1 | Bibimbap/Entrees |
| `banchan_refill_info` | info-only | — | — | 모든 BBQ/Entree (info) |
| `combo_no_sub_rule` | hard-rule | — | — | BBQ Combo A/B (system prompt) |
| `gratuity_party_rule` | auto-rule | — | — | 6명 이상 (auto +18%) |
| `dietary_filter` | info | — | — | 메뉴 검색 메타데이터 |

**Cafe에서 재사용**: `dietary_filter`, `banchan_refill_info` (개념만), 나머지 새로.

**핵심 옵션 정의**:

```yaml
groups:
  meat_doneness:
    required: true
    min: 1
    max: 1
    applies_to_categories: [bbq_beef]
    options:
      - {id: rare,        en: "Rare",        ko: "레어",      price_delta: 0.00}
      - {id: medium_rare, en: "Medium-rare", ko: "미디엄 레어", price_delta: 0.00}
      - {id: medium,      en: "Medium",      ko: "미디엄",    price_delta: 0.00}
      - {id: medium_well, en: "Medium-well", ko: "미디엄 웰",  price_delta: 0.00}
      - {id: well_done,   en: "Well-done",   ko: "웰던",      price_delta: 0.00}

  spice_level:
    required: false
    min: 0
    max: 1
    applies_to_categories: [appetizer, hot_pot, entree]
    options:
      - {id: mild,    en: "Mild",        ko: "순한맛",    price_delta: 0.00}
      - {id: medium,  en: "Medium",      ko: "보통맛",    price_delta: 0.00}
      - {id: hot,     en: "Hot",         ko: "매운맛",    price_delta: 0.00}
      - {id: extra,   en: "Extra hot",   ko: "아주 매운맛", price_delta: 0.00}

  bbq_party_size:
    required: true
    min: 1
    max: 1
    applies_to_categories: [bbq_beef, bbq_pork, bbq_other]
    options:
      - {id: two,     en: "2 portions (min)", ko: "2인분(최소)", price_delta: 0.00, default: true}
      - {id: three,   en: "3 portions",       ko: "3인분",       price_delta: 0.00}
      - {id: four,    en: "4 portions",       ko: "4인분",       price_delta: 0.00}
      - {id: five_plus, en: "5+ portions",    ko: "5인분 이상",  price_delta: 0.00}

  add_on_starch:
    required: false
    min: 0
    max: 2
    applies_to_items: [tteokbokki, no_spicy_tteokbokki, ojingeo_bokkeum, budae_jjigae, ramen_extras]
    options:
      - {id: add_ramen,     en: "+Ramen",         ko: "+라면",       price_delta: 5.00, allergen_add: [wheat, gluten]}
      - {id: add_cheese,    en: "+Cheese",        ko: "+치즈",       price_delta: 5.00, allergen_add: [dairy]}
      - {id: add_udon,      en: "+Udon",          ko: "+우동",       price_delta: 5.00, allergen_add: [wheat, gluten]}
      - {id: add_rice_cake, en: "+Rice cake",     ko: "+떡 추가",     price_delta: 2.50, allergen_add: [gluten]}

  wrap_extras:
    required: false
    min: 0
    max: 3
    applies_to_categories: [bbq_beef, bbq_pork, bbq_other]
    options:
      - {id: extra_lettuce,    en: "+Lettuce wrap",       ko: "+상추 추가",     price_delta: 5.00}
      - {id: extra_mozzarella, en: "+Mozzarella cheese",  ko: "+모짜렐라 추가",  price_delta: 5.00, allergen_add: [dairy]}
      - {id: extra_side_set,   en: "+Side dish set",      ko: "+반찬 세트 추가", price_delta: 5.00}
```

### 3.3 Variant — Loyverse 200-combo 한계 내 fit

**원칙**: variants는 **단일 attribute** (size 등)만, 다중 옵션은 **modifier**로 처리.

| 메뉴 | Variant 종류 | 조합 수 |
|---|---|:---:|
| 순대 (S3) | size [Small/Medium] | 2 |
| 순대 콤비네이션 (S4) | size [Small/Medium] | 2 |
| 보쌈 (S2/E5) | size [Shareable/Single] | 2 |
| 족발 (S1/E4) | size [Shareable/Single] | 2 |
| 떡볶이 (A5) | add-on [Plain/+R/+C/+R+C] | 4 |
| 안매운 떡볶이 (A6) | 동일 | 4 |
| 부대찌개 (E16) | add-on [Plain/+R] | 2 |
| 오징어볶음 (E21) | add-on [Plain/+U/+R] | 3 |
| **나머지 69개** | variant 없음 | 1 each |

**총 variant 조합**: 2+2+2+2+4+4+2+3 + 69 = **90개 (200 한도 충분)**

> ⚠️ **Loyverse 200-combo 한계**는 *per-item*. 한 아이템당 최대 200 조합. 이 분포는 모두 한 자릿수라 안전.

### 3.4 Allergen 룰 — `templates/kbbq/allergen_rules.yaml`

**Cafe 패턴 + KBBQ keyword 추가**:

```yaml
patterns:
  # ─── Cafe에서 재사용 가능 (FDA-9 표준)
  - keywords: [milk, cheese, cream, yogurt, dairy, mozzarella, butter]
    add_allergens: [dairy]
    confidence: 0.92

  - keywords: [soy, soybean, soy sauce, doenjang, dwenjang, ssamjang]
    add_allergens: [soy]
    confidence: 0.95

  - keywords: [wheat, flour, ramen, udon, noodle, mandoo, dumpling, pancake, pajeon]
    add_allergens: [wheat, gluten]
    confidence: 0.95

  - keywords: [egg, gyeran, omelet, fried egg]
    add_allergens: [egg]
    confidence: 0.95

  # ─── KBBQ 신규 keyword
  - keywords: [shrimp, saewoo, mussel, honghap, clam, oyster]
    add_allergens: [shellfish]
    confidence: 0.95

  - keywords: [squid, ojingeo, octopus, cuttlefish]
    add_allergens: [shellfish]   # FDA-9: mollusks → shellfish category
    confidence: 0.93

  - keywords: [godeungeo, mackerel, anchovy, salmon, tuna, fish cake, odeng]
    add_allergens: [fish]
    confidence: 0.95

  - keywords: [sesame, tahini, sesame oil, perilla seed]
    add_allergens: [sesame]
    confidence: 0.95

  # ─── KBBQ-specific patterns (한글 + 영문 동시 매칭)
  - keywords: [bossam, jokbal, samgyupsal, samgyeopsal, daepae, moksal,
               hanjeongsal, pork belly, pork shoulder, pork jowl, 보쌈, 족발,
               삼겹살, 대패삼겹살, 목살, 항정살, 돼지]
    add_allergens: [pork]   # informational — not FDA-9 but cultural/religious
    confidence: 0.97
    reason: "Pork dish — relevant for halal/kosher/religious dietary needs"

  - keywords: [galbi, bulgogi, chadol, deung shim, jumullleok, brisket,
               ribeye, short rib, 갈비, 불고기, 차돌, 등심, 주물럭, 소고기]
    add_allergens: []
    add_dietary: [beef]
    confidence: 0.97

  - keywords: [kimchi, 김치]
    add_allergens: [shellfish, fish]   # 김치 발효 시 멸치액젓/새우젓 (대부분 매장 사용)
    add_dietary: [fermented]
    confidence: 0.85
    reason: "Most kimchi recipes contain anchovy/shrimp paste — verify with operator"

  - keywords: [soondae, blood sausage, 순대]
    add_allergens: [pork, wheat, gluten]   # 순대 = 돼지피 + 당면 + 보리
    confidence: 0.92

  - keywords: [japchae, glass noodle, dangmyeon]
    add_allergens: [soy]   # 잡채 = 간장 양념
    confidence: 0.93

  - keywords: [tteok, rice cake, 떡]
    add_allergens: []
    add_dietary: [gluten_free_base]
    confidence: 0.90
    reason: "Pure rice cake is gluten-free, but check sauce (gochujang has wheat in some brands)"

# ─── Dietary inference (cafe 패턴 그대로)
dietary_inference:
  - if_absent: [dairy]
    suggest: [dairy_free]
  - if_absent: [pork, beef, fish, shellfish]
    suggest: [vegetarian]
    confidence: 0.50   # operator 확인 필요 (다른 동물 단백질 가능)

# ─── Operator hints
operator_hints:
  - text: "김치 = 발효 식품. 대부분 매장의 김치는 새우젓/멸치액젓 포함 → shellfish/fish allergen 표시 권장. 비건 김치 별도 운영 시만 dietary 분리."
  - text: "Gochujang 일부 브랜드는 wheat 포함. 매장 사용 브랜드 확인 후 wheat allergen flag."
  - text: "Pork (돼지) allergen은 FDA-9 X but halal/kosher/이슬람/유대 손님 대응 필수 — 메뉴 사전 표시 권장."
  - text: "BBQ 직화 그릴 cross-contamination — 모든 grilled 메뉴는 'shared grill' 라벨 추천."
```

### 3.5 Gratuity (18% / 6+명) — Voice agent 자동 처리

**Loyverse 한계**: auto-gratuity 내장 X. 두 가지 전략 비교:

| 전략 | 구현 | 장점 | 단점 |
|---|---|---|---|
| **A. Voice agent → menu_item 라인 추가** | Loyverse에 "Service Charge (18%)" menu_item 등록. `create_order` 시 party_size ≥ 6 → items_json에 자동 라인 append | POS 호환 100%, 영수증에 명시 | menu_item ID 매장당 별도 등록 필요 |
| **B. bridge_transactions 메타 + 영수증 후처리** | `metadata.gratuity_pct` 컬럼 추가. 영수증 생성 시 별도 라인 합산 | DB만 변경, POS 무관 | Loyverse 영수증과 voice agent 영수증 불일치 |

> **권장: A (Voice agent + Loyverse menu_item 라인)**
>
> - cafe와 동일한 패턴 (effective_price 계산 시 모든 라인이 menu_item으로 통일)
> - 영수증·POS·payment-link 모두 일관
> - 단점은 "Service Charge 18%" 1개 menu_item만 1회 등록

**구현 코드 (Day 5 라이브 검증 시)**:

```python
# backend/app/services/bridge/flows.py — create_order 내부
GRATUITY_THRESHOLD_PARTY = 6
GRATUITY_PCT = 0.18
GRATUITY_MENU_ITEM_ID = "kbbq-service-charge-18"  # Loyverse 등록

if party_size and party_size >= GRATUITY_THRESHOLD_PARTY:
    subtotal_cents = sum(line["price_cents"] * line["quantity"] for line in items)
    gratuity_cents = round(subtotal_cents * GRATUITY_PCT)
    items.append({
        "menu_item_id": GRATUITY_MENU_ITEM_ID,
        "name": f"Service Charge (18% — party of {party_size})",
        "price_cents": gratuity_cents,
        "quantity": 1,
        "is_auto_gratuity": True,
    })
```

System prompt 룰:
```
GRATUITY RULE: If the caller mentions party of 6 or more, automatically add
18% service charge to the bill. Inform the caller: "For parties of 6 or more
we add an automatic 18% service charge — your total will be $X.XX."
```

---

## 4. KBBQ 도입 일정 — 5–7 founder-days

### Day 1 (오늘, 2026-05-10): Templates + Vertical 등록 (0.5d)

**산출물**:
- ✅ `backend/app/templates/kbbq/menu.yaml` (~600 LOC)
- ✅ `backend/app/templates/kbbq/modifier_groups.yaml` (~200 LOC)
- ✅ `backend/app/templates/kbbq/allergen_rules.yaml` (~120 LOC)
- ✅ `backend/app/templates/kbbq/system_prompt_base.txt` (~150 LOC)
- ✅ `backend/app/knowledge/kbbq.py` (copy of restaurant.py + 가격대 조정)
- ✅ `_VERTICALS = {..., "kbbq", ...}` (transactions.py:22)
- ✅ pytest 검증 (catalog/menu/allergen 단위)

### Day 2 (2026-05-11): DB Seed + Loyverse 연결 (1d)

**산출물**:
- ✅ Supabase: `stores` 신규 row (JM KBBQ, vertical=kbbq, owner_id=신규)
- ✅ `menu_items` + `modifier_groups` + `modifier_options` import (yaml → SQL seed)
- ✅ Loyverse 신규 매장 생성 (또는 cafe와 분리된 별도 token)
- ✅ Loyverse 메뉴 등록 (77 items + 90 variants + 12 modifier groups)
- ✅ "Service Charge 18%" Loyverse menu_item 별도 등록
- ✅ POS sync 엔드포인트 → menu_cache 채움

### Day 3 (2026-05-12): System Prompt + Hard-Code 제거 (1d)

**산출물**:
- ✅ `voice_websocket.py:1316` "JM Cafe" 하드코드 → `store["name"]`
- ✅ KBBQ system prompt assembly (menu_section + modifier_section + FSR rules)
- ✅ allergen lookup KBBQ keywords unit test
- ✅ `bridge/flows.py` `vertical="restaurant"` 5곳 → `vertical=store["vertical"]`

### Day 4 (2026-05-13): Phone Routing + Twilio (1d)

**산출물**:
- ✅ `realtime_voice.py:103` `JM_CAFE_STORE_ID` 하드코드 → `phone_routing` 테이블 lookup
- ✅ Supabase: `phone_routing` 테이블 신규 (phone, store_id, vertical)
- ✅ Twilio 신규 번호 매입 ($1/mo) 또는 cafe 번호 reuse 결정
- ✅ Twilio webhook → store 라우팅 검증 (cross-store leak 0)

### Day 5 (2026-05-14): 라이브 검증 통화 (1d)

**시나리오 6개**:
1. "갈비 2인분 well-done 주문" (KO, BBQ A La Carte min 2 + doneness)
2. "Spicy pork bulgogi for 4 portions" (EN, party_size + spice)
3. "감자탕전골 for 2 people" (KO, hot pot for-2 룰)
4. "I'm allergic to peanuts and shrimp" (EN, Tier-3 alert + shellfish 매칭)
5. "BBQ Combo A 한 세트 + 추가 사이드는 가능?" (KO, combo no-sub 룰)
6. "8명 예약하고 싶어요" (KO, auto-gratuity 18%)

**검증 항목**:
- ✅ KO 음역 (Galbi/Bulgogi/Samgyeopsal) 자연스러운지
- ✅ Cafe vs KBBQ multi-store RLS 격리 (cross-tenant leak 0)
- ✅ Loyverse 주문 생성 + 영수증 발송
- ✅ FIX-A keepalive (1006 disconnect 0%)
- ✅ FIX-B 모디파이어 분해 (well-done/spicy + party_size)

### Day 6-7 (2026-05-15~16): M2 Baseline + 분석 (선택)

- 24-48h passive baseline 운영
- Cafe vs KBBQ 비교 분석 (turn 길이, fallback 빈도, modifier mismatch)
- P0-F Onboarding Wizard 견적 calibration (Frontend Track A 의존성)

---

## 5. 정식 FSR 운영 추가 작업 (별도 sprint, 6–10d)

베이스 라인 KBBQ 라이브 후, 실제 매장 도입 전 필요한 추가 기능:

### Phase 5 — Multi-Round Order Accumulation (3-5d)

**문제**: BBQ 식사는 라운드별 추가 주문 (첫 주문 → 추가 고기 → 술 → 식사) 패턴. Cafe는 단일 transaction 가정.

**해결**:
- `bridge_transactions` 컬럼 추가: `round_number` (default 1), `parent_tx_id` (FK self)
- `flows.py.create_order` 에 `accumulate_mode=true` 옵션 → 기존 transaction 검색 후 items_json append
- State machine: `pending → pending_round_2 → pending_round_3 → paid`

### Phase 6 — Open Tab Dine-In Payment (3-5d)

**문제**: KBBQ는 식사 종료 시점에 청구 (cafe pay-link과 다름).

**해결**:
- 새 `payment_lane = "open_tab"` 도입
- 주문 즉시 `fired_unpaid` 상태로 주방 송신, 청구는 식사 종료 시
- POS 단말기 결제 webhook → bridge_transactions state 업데이트
- Twilio reservation 흐름과 통합 (table_number 인코딩)

---

## 6. Loyverse FSR 한계 — 테스트용 OK / 정식 X

| FSR 요건 | Loyverse | KBBQ 시뮬 | KBBQ 정식 |
|---|:---:|:---:|:---:|
| Modifiers + 가격 추가 | ✅ | OK | OK |
| Variants (200 combo) | ✅ | OK | OK |
| Open ticket / 분할 / 합치기 | ✅ | OK | OK |
| KDS (kitchen display) | ✅ | OK | OK |
| Dining options 커스텀 | ✅ | OK | OK |
| Table mapping (floor plan) | ❌ | Workaround (ticket name) | **부족** |
| Reservation | ❌ | Voice agent에서 관리 | **부족** |
| Auto gratuity (18% 6+명) | ❌ | Voice agent service item | OK (workaround) |
| Course/round ordering | ⚠️ | Open ticket 사용 | **부족** |
| Required modifier 강제 | ⚠️ | Voice agent 책임 | **부족** |
| BBQ 2-min 강제 | ❌ | Voice agent 책임 | **부족** |

**결론**: 시뮬 매장으로는 ⭕, 실제 PDX 5+ 테이블 운영은 Quantic 또는 다른 FSR-native POS로 마이그 권장.

---

## 7. Risk + 권장 우선순위

### High Risk

1. **Phone routing 하드코드** (`realtime_voice.py:103`) — KBBQ 라이브 차단. Day 4 필수.
2. **Loyverse 200-combo 한계** — 한 아이템에 매핑 폭증 시 위험. 현재 분포는 안전하지만 향후 신규 add-on 추가 시 모니터링.
3. **김치 allergen mis-flag** — 매장 김치 레시피 모르면 shellfish/fish 표시 누락 위험. Operator hint로 1차 대응.

### Medium Risk

4. **Multi-round 주문 누락** — Day 5 시나리오는 단일 transaction 가정. 실제 KBBQ 다중 주문은 새 transaction으로 처리 (Phase 5 별도).
5. **한국어 음역 일관성** — Galbi vs Kalbi vs 양념갈비 — 메뉴 ID는 *galbi_marinated* 영어 단일, system prompt에서 음역 규정.

### Low Risk

6. **Knowledge `kbbq.py` 가격 상수** — KPI 계산용, 라이브 차단은 안 함.
7. **Twilio 신규 번호 비용** — $1/mo 무시 가능.

---

## 8. 권장 다음 행동

### 즉시 (오늘, 2026-05-10 EOD까지)

| 단계 | 작업 | 파일 / 출력 |
|---|---|---|
| 1 | KBBQ menu.yaml 작성 | `backend/app/templates/kbbq/menu.yaml` |
| 2 | KBBQ modifier_groups.yaml 작성 | `backend/app/templates/kbbq/modifier_groups.yaml` |
| 3 | KBBQ allergen_rules.yaml 작성 | `backend/app/templates/kbbq/allergen_rules.yaml` |
| 4 | KBBQ system_prompt_base.txt 작성 | `backend/app/templates/kbbq/system_prompt_base.txt` |
| 5 | `_VERTICALS`에 "kbbq" 추가 | `backend/app/services/bridge/transactions.py:22` |
| 6 | `knowledge/kbbq.py` 신규 (restaurant.py 복사 + 가격 조정) | `backend/app/knowledge/kbbq.py` |
| 7 | pytest 검증 | catalog/menu/allergen 단위 테스트 |
| 8 | Day 1 commit + push | 단일 commit + Telegram 알림 |

### Day 2 (내일, 2026-05-11)

- DB seed (yaml → menu_items SQL)
- Loyverse 신규 매장 등록 + 메뉴 import
- Service Charge 18% Loyverse menu_item 등록

### Day 3-5 (2026-05-12~14)

- Hard-code 제거 (voice_websocket store name + flows.py vertical 파라미터)
- Phone routing 테이블 + Twilio 매핑
- 라이브 검증 6 시나리오

### Day 6-7 (2026-05-15~16, 선택)

- Cafe vs KBBQ 비교 분석
- P0-F Onboarding Wizard 견적 calibration

---

## 부록 A — 신규 작성 파일 LOC 추정

| 파일 | 타입 | LOC | 예상 작성시간 |
|---|---|---:|:---:|
| `templates/kbbq/menu.yaml` | YAML | 600 | 1.5h |
| `templates/kbbq/modifier_groups.yaml` | YAML | 200 | 0.5h |
| `templates/kbbq/allergen_rules.yaml` | YAML | 120 | 0.3h |
| `templates/kbbq/system_prompt_base.txt` | TXT | 150 | 1h |
| `knowledge/kbbq.py` | Python (copy + tune) | 67 | 0.3h |
| **합계** | | **1,137** | **3.6h** |

기존 코드 수정 (3 파일):
- `transactions.py:22` — 1 line
- `voice_websocket.py:1316` — 1 line  
- `realtime_voice.py:103+` — 8-12 lines (phone_routing lookup)
- `flows.py` — 5 locations × 1 line each

**총 코드 수정**: ~20 LOC

---

## 부록 B — 사용자 의사 결정 요청 4가지 (Day 1 시작 전)

다음 4가지를 confirm 받은 후 Day 1 yaml 작성 시작:

1. **매장명**: `JM Korean BBQ` (정식 영문) / `JM KBBQ` (단축) — 어느 쪽?
2. **POS**: Loyverse 두 번째 매장 (cafe와 같은 인스턴스 / 별도 토큰)? 아니면 신규 별도 Loyverse 계정?
3. **메뉴 가격**: 장충동 PDF 그대로 적용 OK? 또는 PDX 시장가 조정?
4. **Twilio**: 신규 번호 매입 ($1/mo)? 또는 cafe `+1-503-994-1265` reuse하고 매장 라우팅 분기?

---

**한 줄 결론**: Cafe→KBBQ 추가는 **81% LOC 재사용 + 5 신규 파일 + 20 LOC 수정**으로 **5–7 founder-days 내 시뮬 라이브** 가능. 정식 FSR 운영은 별도 sprint (multi-round + open tab, 6–10d). Loyverse는 시뮬 OK, 실제 5+ 테이블 매장은 Quantic 권장.
