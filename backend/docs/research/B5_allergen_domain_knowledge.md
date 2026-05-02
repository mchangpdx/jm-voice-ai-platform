# B5 Allergen Q&A — Domain Knowledge + Maple 전수조사

**Date**: 2026-05-02
**Purpose**: B5 implementation 시작 전 도메인 학습 + 경쟁사 분석으로 spec 보강
**Status**: Pre-implementation research; spec at `backend/docs/specs/B5_allergen_qa.md`

---

## Part I — 도메인 지식 (Restaurant Allergen Q&A)

### 1. FDA "Big 9" Allergens (US 법적 기준)

2021년 sesame가 9번째로 추가되어 현재 FDA가 인정하는 major food allergens은 9종:

| # | Allergen | EN | KO 비고 |
|---|---|---|---|
| 1 | Milk | dairy | 우유/유제품 (버터, 치즈, 요거트, 크림) |
| 2 | Eggs | egg | 계란 (마요네즈, 일부 면 포함) |
| 3 | Fish | fish | 생선 (anchovy, salmon, tuna 등) |
| 4 | Crustacean Shellfish | shellfish | 갑각류 (새우, 게, 랍스터) — mollusk(굴/조개)는 별개 |
| 5 | Tree Nuts | nuts | 견과류 (아몬드, 호두, 캐슈, 피칸 등) |
| 6 | Peanuts | peanuts | 땅콩 (legume이지만 분리 표기) |
| 7 | Wheat | gluten | 밀 (gluten의 주 source) |
| 8 | Soybeans | soy | 대두 (간장, 두부, edamame) |
| 9 | Sesame | sesame | 참깨 (2021 추가) |

**B5 spec 결정**: spec v1은 peanuts를 nuts로 통합 (operator 입장에서 구분 모호 + UI 단순화). v2에서 peanuts 별도 가능. 그 외 8종 그대로 채택.

### 2. Dietary Categories (legal 아닌 customer-facing)

법적 정의는 없으나 customer 표현에서 자주 등장:

| Tag | 의미 | 주의 |
|---|---|---|
| vegan | 동물성 일체 배제 | dairy + egg + fish + shellfish + honey 모두 |
| vegetarian | 육류/생선 배제 (dairy/egg 허용) | lacto-ovo가 통상 |
| gluten_free | wheat, barley, rye 배제 | celiac은 trace도 위험 |
| dairy_free | milk products 배제 | lactose-intolerant + dairy-allergy 구분 별개 |
| nut_free | tree nuts + peanuts 배제 | 동일 시설 처리도 risk |
| kosher | Jewish 율법 | dairy-meat 분리, certified만 인정 |
| halal | Islamic 율법 | certified slaughter 필요 |

### 3. 법적 / 규제 환경 (2026 기준)

#### Federal (FDA)
- **FALCPA 2004**: 포장 식품 (packaged) 의무 — pre-packaged 라벨링.
- **FASTER Act 2021**: sesame를 9번째 major allergen에 추가, 2023.01.01 발효.
- **FDA Food Code 2022**: 식당 unpackaged food도 written notification 권고. **단 federal law/regulation 아니라 guidance** — state/local이 채택 여부 결정.

#### State (California — 2026.07.01 발효)
- 20+ locations 체인 식당은 메뉴별 9 major allergens written notification 필수.
- JM의 일반 SMB target은 20-loc 미만이라 직접 의무는 아님. 단 California 입점 시 chain 정의 확장 모니터링 필요.

#### Liability (모든 주)
- 잘못된 allergen 정보 발화 → personal injury / wrongful death 소송 가능.
- **AI bot의 misinformation은 식당 책임으로 귀속** — vendor 면책 조항 통상 약함.
- Insurance: General Liability + Product Liability + Cyber Liability 전부 필요.

### 4. Cross-Contamination 위험 (가장 underestimated 영역)

**핵심 사실**:
- Allergens는 단백질 — "cook off" 불가. 끓여도/구워도 단백질 항원성 유지.
- 같은 fryer, 같은 cutting board, 같은 grill = trace contamination 가능.
- Celiac 환자는 20ppm trace gluten으로도 villi 손상.
- Anaphylaxis는 µg 단위로 발생 가능 (peanut, shellfish 특히).

**B5 spec 함의**:
- "free of X" 발화는 operator-curated DATA가 명시적으로 absent를 confirm한 경우만 허용 (HonestUnknown invariant).
- v1에서는 cross-contamination 정보 미지원 (operator data 없음). 모든 allergen 응답에 implicit risk 존재 — 사용자 manager 전환 가능성 항상 열어둠.
- v2에서 `cross_contam_risk: ["nuts_facility", "shared_fryer"]` 류 별도 컬럼 추가 가능.

### 5. 음성 AI에서의 위험 패턴 (Hostie 2024 audit)

> **"70%+의 AI restaurant bot이 real-time kitchen data 없이 dietary safety claim을 발화한다."**

위험 패턴:
1. Generic LLM이 ingredient name으로만 추론 ("croissant — French pastry, contains butter")
2. 학습 시점 데이터 사용 (today 변경 menu 미반영)
3. Supplier 변경 (예: vegan butter → dairy butter) 미감지
4. Cross-contamination 무지
5. Manager 전환 실패 / 지연

### 6. 권장 아키텍처 (Hostie Three-Tier Framework)

업계 권장 구조:

| Tier | Confidence | Action |
|---|---|---|
| **Tier 1** | ≥90% (curated DB exact match) | 직접 답변 + 안전 disclaimer |
| **Tier 2** | 70-89% (partial match / fuzzy) | qualified response — "let me have the team double-check" |
| **Tier 3** | <70% (no data / multi-allergen / EpiPen language) | 즉시 manager handoff |

**자동 handoff trigger 키워드**:
- "EpiPen", "anaphylaxis", "life-threatening", "severe", "hospital"
- 3+ allergens 동시 mention
- "cross-contamination", "shared fryer", "same kitchen"
- "celiac", "deathly", "react badly"

**B5 v1 매핑**:
- Tier 1 = `allergen_present` / `allergen_absent` / `dietary_match` (curated data 기반)
- Tier 2 = `dietary_no_match` (data 없음, 정직한 미확인 + manager offer)
- Tier 3 = `allergen_unknown` + 향후 EpiPen 키워드 detection (v2)

### 7. 응답 언어 패턴 (trust-building)

**해야 할 것**:
- "I understand how important this is for your safety..."
- "Per our kitchen records, [item] is dairy-free"
- "Let me transfer you to a manager who can verify directly with the kitchen"

**하지 말 것**:
- "I think it's gluten-free" (uncertainty 노출)
- "Probably no nuts" (확률 표현 금지)
- "Should be safe for vegans" (조건부 안전 주장)
- "Most of our items are dairy-free" (개별 확인 회피)

---

## Part II — Maple Inc. 전수조사 (Allergen 관련 기능)

### 1. Maple의 공식 allergen 마케팅 클레임

**확인된 클레임 (다수 출처)**:
- "answers FAQs like hours, menu items, **allergies**" (homepage)
- "deep integration to merchant systems and attention to details like menu knowledge, **allergies, and dietary needs**"
- "advanced understanding of complex dietary needs and **cross-contamination risks**"
- "intelligent **ingredient substitution** recommendations"
- "seamless integration with **nutritional databases**"
- "proactive **allergy warning systems** for customer safety"
- "specialized callout system" + "immediate recognition of allergy-related language"
- "seamless **handoff protocols** when uncertainty exists"
- "real-time menu integration with POS systems"
- "allergen-specific conversation flows"
- "automatic staff notification for complex cases"
- "customer preference learning for repeat callers"

**조사 한계 (2026-05-02)**:
- maple.inc (homepage + product page)는 직접 fetch 시 **403 Forbidden** — bot detection으로 차단.
- LinkedIn / Capterra / 3rd-party 리뷰 사이트 + Hostie/Loman/Kea의 비교 글에서 추출.
- **구체 architecture 미공개**: 데이터 모델, allergen 입력 UI, manager handoff trigger 정확한 wording 등은 marketing copy 수준만 노출.
- Loman 비판: "Maple Voice has been criticized for confidence overruns" — 일부 환각 사례 보고.

### 2. Maple allergen 기능 — 추정 분해

조사한 marketing copy 기반으로 reverse-engineer:

| 기능 | 명시 여부 | 추정 implementation |
|---|---|---|
| FDA top-9 매트릭스 저장 | 명시 | menu item별 jsonb 또는 column 추가 (JM 동일 접근) |
| Dietary tags (vegan/GF/etc) | 명시 | 별도 tags 컬럼 (JM 동일) |
| Cross-contamination 데이터 | 명시 | 키친 시설/도구 share 정보 입력 UI 존재 추정 |
| Ingredient substitution 추천 | 명시 | "dairy-free milk available" 류 — substitution rules 별도 테이블 추정 |
| Real-time POS sync | 명시 | Quantic/Toast/Square API webhook으로 메뉴 + 가능 allergen pull (단 POS 자체가 allergen 메타 보유는 드물다 — manager dashboard 입력으로 보완 필수) |
| Nutritional database 통합 | 명시 | USDA FoodData Central 등 외부 DB 추정 — 단 식당 specific은 매핑 정확도 낮음 |
| Allergy warning system | 명시 | 발화 차단 + manager alert 추정 |
| Manager handoff (uncertainty) | 명시 | 현재 통화 중 transfer 또는 SMS alert 추정 |
| Per-merchant ML 개선 | 명시 (마케팅) | 사실 여부 불명 — 일반 LLM에 prompt-tuning 수준일 가능성 |
| EpiPen / anaphylaxis 키워드 | 미명시 | Hostie framework이 권장하는 trigger — Maple도 채택 가능성 높음 |

### 3. Maple allergen UX 추정 (3rd-party 기반)

리뷰 + 비교 글에서 유추:
- 고객이 "Does X have nuts?" 발화 → 즉시 allergen check (보통 1-2초 latency)
- "Yes, contains tree nuts" 또는 "I'd want our manager to confirm" 응답
- Manager handoff 시 통화 중 transfer (Twilio Conference 또는 staff app push notification 추정)
- Customer preference (repeat caller) 저장 — caller-id로 "you've previously asked about gluten — same restriction?" 류 (Maple-specific UX, JM은 v2)

### 4. Maple의 weak points (Loman/Kea/Hostie 비교 글)

1. **"Confidence overruns"** (Loman 2025 12월 글): allergen 답변에서 너무 confident하게 발화하는 사례 보고 — disclaimer 부족.
2. **POS 통합이 "allergen" 차원에서는 약함**: POS는 inventory + order만 — allergen 메타데이터는 manager dashboard에서 수동 입력 필요. Maple도 사실상 같음.
3. **Manager handoff latency**: live transfer는 Twilio cost + 가용 staff 필요. SMS alert는 즉시성 떨어짐.
4. **Per-merchant ML "claim"**: 마케팅 위주, 실제 ML 학습 사이클 증거 약함. 결국 prompt + curated data로 운영 추정.
5. **Multi-language allergen**: EN/ES/CN/TL 지원이지만 allergen 용어 정확도 비교 데이터 없음.

### 5. Maple — JM 상대 격차

| 차원 | Maple | JM (B5 spec) | 격차 |
|---|---|---|---|
| FDA top-9 매트릭스 | 8 | 8 (동일 채택) | 동등 |
| Dietary tags | 7 | 7 | 동등 |
| Operator-curated only invariant | 5 (claim 강함, 실제 enforce 불명) | **9** | JM 우위 — HonestUnknown invariant + 단위 테스트로 lock |
| Cross-contamination 데이터 | 6 | 0 (v1 미지원) | Maple 우위 |
| Ingredient substitution | 6 | 0 | Maple 우위 |
| Nutritional DB 통합 | 5 (USDA 추정) | 0 | Maple 우위 |
| Manager handoff (live transfer) | 6 | 0 (v1 SMS만) | Maple 우위 |
| EpiPen / anaphylaxis 키워드 | ?5 | 0 (v1 미지원) | Maple 약간 우위 |
| Per-store RLS isolation | 1 | **9** | JM 결정 우위 |
| Audit trail (allergen_lookup log) | 3 | 8 | JM 우위 |
| Customer dietary preference 학습 | 4 | 0 (v1) | Maple 우위 |
| **POS-independent operation** | 0 (POS 의존) | **8** (Supabase POS adapter) | JM 우위 — POS 없는 매장 대응 |
| Test coverage | ? | 9 (15 RED 계획) | JM 우위 |

**합계 (allergen-only)**:
- Maple 평균: ~5.0
- JM B5 v1 (planned): ~4.6
- v2 추가 시 (cross-contam + manager live transfer + EpiPen detect): JM ~6.5

**전략적 관점**: B5 v1이 ship되면 Maple과 동등 수준. v2로 전환하면 JM이 RLS + audit + curated invariant 강도로 확실한 우위 확보.

---

## Part III — JM B5 spec 보강 결정사항

조사 결과 spec 이미 lock된 7개 결정 모두 유지 + 다음 추가 권장:

### v1에 추가 (immediate)
1. **EpiPen / anaphylaxis 키워드 자동 manager handoff** (Tier 3 trigger) — system prompt rule 12에 추가.
2. **Disclaimer wording 강화** — `allergen_absent` 시 "per our kitchen records" 표현 (이미 spec에 포함).
3. **`is_celiac` / `severe_allergy` 키워드 감지** → 자동 manager offer (rule 12 보강).

### v2 deferral 명시 (spec OOS section에 추가)
1. Cross-contamination 컬럼 (`cross_contam_risk` jsonb)
2. Ingredient substitution recommendations (`substitutions` 별도 테이블)
3. Live manager transfer (Twilio Conference)
4. Customer dietary preference 학습 (`customer_dietary_history` 테이블)
5. Multi-item dietary filter ("what's vegan?")
6. USDA / nutritional DB 통합

### Risk register 추가
- **Liability**: 잘못된 allergen 발화 → 식당 책임. JM 계약서에 vendor 면책 + AI disclaimer 의무 조항 추가 필요 (legal review).
- **Insurance**: 식당이 allergen-related E&O insurance 보유 여부 확인 권장 (JM 입점 onboarding 체크리스트).
- **California 2026.07.01 law**: 20+ chain 영업 시 written notification 의무 — JM이 이 의무 충족 도구로 marketing 가능.

---

## Sources

- [FDA Food Allergies](https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/food-allergies)
- [USDA FSIS Big 9 Allergens](https://www.fsis.usda.gov/food-safety/safe-food-handling-and-preparation/food-safety-basics/food-allergies-big-9)
- [California Allergen-Disclosure Law (effective 2026-07-01)](https://www.thefdalawblog.com/2025/10/californias-new-allergen-disclosure-law-a-sign-of-things-to-come/)
- [Hostie — Voice AI Allergy Best Practices 2025](https://hostie.ai/resources/voice-ai-allergy-dietary-questions-menu-aware-bots-2025)
- [Maple Inc Product Page](https://maple.inc/product/) (403 — claims via 3rd party)
- [Loman vs Maple AI (Dec 2025)](https://loman.ai/blog/loman-vs-maple-ai-phone-assistant-restaurants)
- [Kea AI — Restaurant Voice AI 2026 Comparison](https://kea.ai/blog/restaurant-voice-ai-comparison-2026-kea-ai-vs-maple-revmo-loman)
- [Lavu — AI Allergen Management for Restaurants](https://lavu.com/ai-allergen-management-restaurants/)
- [Menumiz — AI Allergen Safety Beyond Gluten-Free](https://brand.menumiz.com/if-your-restaurants-ai-cant-handle-gluten-free-its-not-ready-for-prime-time/)
- [Franchise Times — New Food Allergen Laws Pushing Restaurants Toward AI](https://www.franchisetimes.com/franchise_news/new-food-allergen-laws-are-pushing-restaurants-toward-ai/article_199158f3-8568-4ed2-bc74-8b2c7def9305.html)
- [PMC — Food allergy risks and dining industry](https://pmc.ncbi.nlm.nih.gov/articles/PMC10090668/)
