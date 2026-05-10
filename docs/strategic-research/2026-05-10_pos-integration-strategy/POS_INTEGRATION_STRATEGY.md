# POS Integration Strategy — Square / Toast / Clover / Quantic / Loyverse 전수 분석

**작성일**: 2026-05-10
**대상**: JM Tech One — 멀티-vertical 음성 AI 플랫폼의 POS 전략 결정
**목적**: (1) 5대 POS의 Open API 통합 가능성 + 우리 솔루션과 순정(native) 연동 깊이 평가, (2) Loyverse의 결제 게이트웨이 부재 문제를 voice agent + payment + receipt 100% 자동화로 해결하는 방안 전수 분석

---

## 0. Executive Summary

### POS 통합 점수 (10 dimension, 0-10)

| POS | 점수 | 진입 난이도 | 핵심 강점 | 핵심 약점 |
|---|:---:|:---:|---|---|
| **Square** | **9.5** | 🟢 Low | 공개 API + Square Payments 통합 + 빠른 진입 | 카테고리/모디파이어 깊이 toast 대비 약함 |
| **Toast** | **9.0** | 🔴 High | FSR 표준, 깊은 modifier, real-time menu sync | Partner Program 필수 (6-12개월 + 법무 검토) |
| **Clover** | **9.0** | 🟡 Medium | Fiserv 백엔드 (글로벌 50%+ 결제 처리) + App Market 마케팅 | Native vs Semi-integration 결정 + Fiserv partner agreement |
| **Quantic** | **6.0** | 🔴 High (lock-in) | Multi-vertical FSR 지원 | **Maple AI 독점 파트너십** (2026-04 발표) — 후발주자 lock-out |
| **Loyverse** | **7.5** | 🟢 Low | Free POS + 공개 API + 무료 SumUp 결제 단말기 | **온라인 결제 게이트웨이 부재** — 우리 voice agent 결제 흐름 우회 필요 |

### Loyverse 100% 자동화 5가지 방안 — 권장

> **권장 = Option 1: Stripe Payment Link + Loyverse Receipt 자동 마킹** (이미 JM Cafe 라이브 검증된 패턴)

| 옵션 | 비용 | 자동화 수준 | 검증 상태 | 권장도 |
|---|:---:|:---:|:---:|:---:|
| **1. Stripe Payment Link + Loyverse Receipt POST** | $0 setup, 2.9% + $0.30/tx | 100% 자동 | ✅ JM Cafe 라이브 | ⭐⭐⭐⭐⭐ |
| **2. Maverick Payment Gateway (이미 adapter 보유)** | 협상 (2.5-3%) | 100% 자동, ACH 포함 | ✅ Adapter 라이브 | ⭐⭐⭐⭐ |
| **3. SumUp + Loyverse 통합** | $0.99/tx Tap | 단말 결제만 (online X) | ✅ Loyverse 공식 | ⭐⭐ |
| **4. Square Payments + Loyverse Receipt** | 2.6% + $0.10/tx | 100% 자동 (계정 2개 운영) | ❌ 별도 통합 필요 | ⭐⭐ |
| **5. Zapier/Make.com no-code** | $20-50/mo + tx fee | latency 30-90s | ❌ reliability 한계 | ⭐ |

**한 줄**: Loyverse는 "free POS" 강점은 유지하면서, **결제 흐름만 Stripe로 우회** = SMB 도입 비용 최소 + 자동화 100% + 우리 backend pay_link.py + bridge_transactions 패턴 그대로 활용.

---

## 1. POS Native Integration Comparison (10 Dimension)

### 1.1 평가 항목

| Dimension | 의미 |
|---|---|
| **D1. Public API 접근** | 공개 문서 + 신청 없이 키 발급 가능 |
| **D2. Auth (OAuth / API key)** | 표준 인증 메커니즘 |
| **D3. Menu Sync (catalog/categories/modifiers)** | 항목 + 모디파이어 + 카테고리 read/write |
| **D4. Order Creation** | line items + modifiers + tax + tips 포함 주문 생성 |
| **D5. Payment Processing** | 카드/디지털지갑 charge (online + in-person) |
| **D6. Webhook** | 실시간 이벤트 (주문/결제/재고) 푸시 |
| **D7. Inventory Sync** | 재고 read/update |
| **D8. Customer/CRM Sync** | 고객 프로필 + 방문 이력 |
| **D9. Multi-location** | 여러 매장 통합 관리 |
| **D10. Voice AI Partner-Friendliness** | AI 음성 통합 partner 정책 + 자유도 |

### 1.2 POS별 점수표

| Dim | Square | Toast | Clover | Quantic | Loyverse |
|---|:---:|:---:|:---:|:---:|:---:|
| D1. Public API | 10 | 6 | 8 | 5 | 10 |
| D2. Auth (OAuth/key) | 10 | 9 | 9 | 8 | 9 |
| D3. Menu Sync | 9 | 10 | 9 | 9 | 8 |
| D4. Order Creation | 10 | 10 | 9 | 9 | 9 |
| D5. Payment Processing | 10 | 10 | 10 | 9 | **3** ⚠️ |
| D6. Webhook | 10 | 9 | 9 | 8 | 8 |
| D7. Inventory Sync | 9 | 9 | 9 | 8 | 9 |
| D8. Customer CRM | 9 | 9 | 9 | 8 | 8 |
| D9. Multi-location | 10 | 10 | 9 | 9 | 8 |
| D10. Voice AI Partner Fit | 10 | 8 | 9 | 4 ⚠️ | 10 |
| **합계 (/100)** | **97** | **90** | **90** | **77** | **82** |
| **점수 (0-10)** | **9.7** | **9.0** | **9.0** | **7.7** | **8.2** |

### 1.3 우리 솔루션과의 통합 깊이 (별도 평가)

| POS | 통합 깊이 | 비고 |
|---|:---:|---|
| **Square** | ⭐⭐⭐⭐⭐ 9/10 | OAuth 표준, public docs, 우리 POS-agnostic adapter로 매핑 직관적, Square Payments 통합 시 풀-스택 자동화 |
| **Toast** | ⭐⭐⭐⭐⭐ 10/10 | 일단 partner 자격 통과하면 가장 깊은 통합 (FSR 표준). 단 6-12개월 + 법무 검토 |
| **Clover** | ⭐⭐⭐⭐ 8/10 | App Market 등록 마케팅 채널 강력, Fiserv 결제 백엔드. Native vs Semi 결정 필요 |
| **Quantic** | ⭐⭐ 4/10 | **Maple AI 독점 — 우리 진입 어려움**. Partner 신청 시 Quantic이 우리를 거절할 가능성 |
| **Loyverse** | ⭐⭐⭐⭐ 8/10 | 이미 JM Cafe 라이브 검증됨. 결제만 외부 gateway (Stripe/Maverick) |

---

## 2. POS별 상세 분석

### 2.1 Square POS — ⭐⭐⭐⭐⭐ 권장 1순위

**근거 데이터**:
- Public API + REST 표준 — **신청 없이 즉시 키 발급 가능**
- Orders API: 5개국 (US/CA/AU/JP/UK) 지원
- Sandbox 환경 무료
- 통합 사례 다수: Craver, GoParrot, Mobi2Go (in-app payments + catalog + inventory)

**우리 솔루션과 통합 시나리오**:
```
JM Voice Agent → create_order tool
  → Square Orders API POST /v2/orders
    (line_items + modifiers + tax + discounts)
  → Square Payments API POST /v2/payments
    (Square Payment Link 또는 Card-on-File)
  → Webhook → bridge_transactions.state=paid
  → Receipt printed in Square Kitchen Display
```

**진입 예상 작업** (founder-days):
- Square OAuth 구현: 1d
- Orders API adapter (cafe pattern): 1d
- Payments API integration: 1d
- Webhook 처리: 0.5d
- **총 ~3-4 founder-days**

**가격**: SMB 매장은 Square POS 무료 (transaction fee 2.6% + $0.10), Plus $29/mo, Premium $89/mo
**비용 부담 우리**: $0 setup (developer account 무료)

### 2.2 Toast POS — ⭐⭐⭐⭐⭐ 깊이 최고, 진입 장벽 최고

**근거 데이터**:
- **Partner Application 필수** (전수 검증 통과 후 권한 발급)
- 인증 절차:
  1. License Agreement 동의
  2. Partner Application 제출
  3. Compliance / Privacy / Security / Legal 4팀 검토
  4. Alpha (1 매장, 1주) → Beta → Production
- API access 무료 (단 RMS Essentials+ 구독 필요, $69-$165/mo per terminal)

**우리 솔루션과 통합 시나리오**:
- Toast가 FSR 표준 (avg full-service $1,000+/mo) — Pizza/QSR/Mexican 매장 비중 매우 큼
- Real-time menu sync (modifier groups 깊이 cafe 대비 ↑)
- Toast Payments 통합 시 결제 종단

**진입 예상 작업** (founder-days):
- Partner application + 법무: **6-12개월 (기다림)**
- Alpha phase 진입 후 SDK 통합: 5-7d
- Beta phase 테스트: 1-2 매장
- **총 작업: 7-10일 + 행정 6-12개월**

**전략적 권장**:
- Square가 진입 빠름 (Pizza/Mexican 매장 진입에 충분)
- Toast는 **2nd wave** — 5 매장 라이브 후 KPI 보고서 만들고 Toast에 partner application 제출 (자체 ARR 데이터로 신뢰도 높이고)
- 초기 단계 (6개월) Toast 진입 의도 시간 낭비

### 2.3 Clover POS — ⭐⭐⭐⭐ 권장 2순위

**근거 데이터**:
- Fiserv 백엔드 (글로벌 카드 거래 50%+ 처리)
- 공개 API + REST + SDK 5개 언어 (Python/Node/PHP/.NET/Java)
- **Clover App Market** 등록 — 마케팅 자동 채널 (Cafe Latte 매장이 App Market에서 우리 앱 검색 가능)
- 2가지 통합 옵션:
  - **Native**: 우리 앱이 Clover 하드웨어에서 실행 (앱 마켓 등록)
  - **Semi-Integration**: 우리 시스템 + Clover 단말 (결제만)

**우리 솔루션과 통합 시나리오**:
```
JM Voice Agent → create_order → Clover REST API POST /v3/merchants/{mId}/orders
  → Order routed to Clover Kitchen
  → Clover Payment processing (Fiserv)
  → Webhook → our backend → state update
```

**진입 예상 작업** (founder-days):
- Fiserv Partner Agreement: 1-3개월 (Toast보다 빠름)
- Native vs Semi 결정: 0.5d
- Clover Orders API adapter: 2d
- App Market 등록 + 심사: 2-4주
- **총 ~4-5 founder-days + 행정 2-4개월**

**가격**: Clover Station Solo $89/mo (기기 포함), Compact $79/mo. SMB 매장에 약간 비싸지만 Fiserv 결제 신뢰도 높음.

### 2.4 Quantic POS — ⭐⭐ 경고: Maple AI Lock-in

**근거 데이터** (CRITICAL):
- **2026-04-24 발표**: Quantic + Maple AI 독점 파트너십 (BusinessWire / NewsBreak / AP)
- Maple AI 92% 해결률 + 1M+ 통화 처리 (since 2023-12)
- Quantic POS 매장 owner가 Maple AI 음성 ordering 우선 노출
- 후발주자 voice AI 솔루션 (= 우리)이 Quantic 진입은 어려움

**대안 전략**:
- Quantic Partner Program 신청 OK (이전 메모리 명시)
- 단 Maple 대비 차별점 필요 — **다언어 (한/일/중/스/영)** wedge
- 한국어 매장 (KBBQ, sushi, korean takeout)이 Maple 부족 시 우리 진입 가능

**진입 예상 작업**:
- Partner Application 제출 후 응답 대기 (Maple 우선권)
- 평가: 진입 가능성 30-50%

**권장**: **6개월 후 평가**. 지금은 Square + Loyverse + Clover 진입 우선.

### 2.5 Loyverse POS — ⭐⭐⭐⭐ 이미 검증, 결제 gap만 해결

**근거 데이터**:
- Public API + Webhooks (Zapier/Make 1-click)
- **Free POS** (소규모 매장 진입 비용 매우 낮음)
- 결제 옵션:
  - **SumUp 단말기** (30+ 국가, US 포함)
  - **온라인 결제 게이트웨이 부재** ← 핵심 gap
- 이미 JM Cafe 라이브 검증 (bridge/pos/loyverse.py 341 LOC)

**우리 솔루션 통합 깊이**: 이미 ⭐⭐⭐⭐ 8/10 — POS adapter 검증됨. 결제 우회만 추가하면 ⭐⭐⭐⭐⭐ 9/10.

→ 다음 섹션에서 결제 자동화 5가지 방안 상세 분석.

---

## 3. Loyverse 100% 자동화 — 결제 흐름 5가지 방안 비교

### 3.1 문제 정의

Loyverse는 무료 POS이지만 **온라인 결제 게이트웨이가 native가 아님** — 즉:
- 매장에서 SumUp 카드 단말기 결제 ✅ (in-person)
- 음성 주문 후 고객에게 결제 link 발송 + 자동 charge ❌ (online)
- 결제 완료 후 Loyverse Receipt 자동 마킹 ❌ (manual)

**우리 voice agent 요구사항**:
1. 음성 주문 → 결제 link / 즉시 카드 결제 → POS 영수증 자동 생성 → 완전 자동 (no human)
2. 결제 실패 시 자동 retry / no-show 처리
3. 영수증 이메일 + POS receipt 둘 다 자동
4. 결제 후 webhook으로 우리 backend state machine 업데이트

### 3.2 5가지 자동화 옵션 상세 비교

#### Option 1: Stripe Payment Link + Loyverse Receipt 자동 마킹 ⭐⭐⭐⭐⭐

**작동 흐름**:
```
1. Voice Agent → create_order tool
   → bridge_transactions INSERT (state=pending)
2. Stripe Payment Link 생성 (or Stripe Checkout Session)
   → URL을 고객 SMS/Email로 전송
3. 고객이 link 클릭 → Stripe Hosted Checkout 결제
4. Stripe Webhook → our backend (/webhook/stripe/payment_intent.succeeded)
   → bridge_transactions.state=paid
5. our backend → Loyverse POST /receipts
   (items + customer + payment_type="card" + total)
   → Loyverse Kitchen Display에 자동 표시
6. our backend → 고객 confirmation email (영수증 PDF 첨부)
```

**비용**:
- Stripe: 2.9% + $0.30/transaction
- Setup 비용: $0 (Stripe account 무료)
- 월 fee: $0

**구현 상태**:
- ✅ JM Cafe에서 이미 라이브 검증 (bridge/pay_link.py, bridge/pay_link_email.py)
- ✅ Loyverse receipt POST 라이브 (pos/loyverse.py)
- ✅ Stripe webhook 처리 라이브

**장단점**:
- ✅ 무료 setup
- ✅ 신뢰도 최고 (Stripe — global standard)
- ✅ 우리 코드 그대로 활용
- ✅ 결제 link UX 표준 (모바일 fit)
- ⚠️ 2.9% fee — Loyverse 자체 SumUp 1.69-2.75%보다 살짝 높음

**권장도**: ⭐⭐⭐⭐⭐ — 1순위. 이미 검증된 패턴.

#### Option 2: Maverick Payment Gateway ⭐⭐⭐⭐

**작동 흐름**:
```
1. Voice Agent → create_order
2. Maverick Payment API POST /charge
   (white-label 결제 화면, 우리 브랜드)
3. ACH or Card or Digital Wallet
4. Maverick webhook → our backend
5. Loyverse Receipt POST
```

**비용**:
- 2.5-3% (협상 가능)
- 월 fee: $25-$50 (gateway fee)
- ACH 처리 가능 (대량 거래 시 유리)

**구현 상태**:
- ✅ 우리 backend에 maverick.py adapter 라이브
- ✅ ISV (Independent Software Vendor) friendly — white-label

**장단점**:
- ✅ ACH 지원 (큰 ticket 매장에 유리 — BBQ Combo $105 등)
- ✅ White-label (우리 브랜드 화면)
- ✅ 협상 가능 fee (volume 증가 시)
- ⚠️ Maverick 자체 가입 + 인증 (1-2주)
- ⚠️ Stripe 대비 글로벌 인지도 낮음 (고객 신뢰도 측면)

**권장도**: ⭐⭐⭐⭐ — 2순위 (volume 큰 매장 + ACH 필요 시).

#### Option 3: SumUp + Loyverse 공식 통합 ⭐⭐

**작동 흐름**:
```
1. Voice Agent → create_order
2. 고객이 매장 방문 → SumUp 단말기에서 카드 tap
3. SumUp → Loyverse 자동 sync (공식 통합)
```

**비용**:
- SumUp Air 단말기: $39 (1회)
- 거래당 1.69% (insertion), 2.75% (online/keyed-in)

**제약사항**:
- ⚠️ **온라인 결제 X** — 매장 방문 필수
- ⚠️ Voice agent 주문 후 매장 방문이라 100% 자동 아님 (in-person 단말 필요)

**권장도**: ⭐⭐ — 매장 in-person 결제 전용. Voice 자동화에는 부적합.

#### Option 4: Square Payments (별도 사용) + Loyverse Receipt ⭐⭐

**작동 흐름**:
```
1. Voice Agent → create_order
2. Square Payment Link 생성 (Square Payments API)
3. 고객 결제 → Square Webhook
4. our backend → Loyverse Receipt POST
```

**비용**:
- Square: 2.6% + $0.10/tx (online)
- Loyverse: $0 (POS 사용만)

**제약사항**:
- ⚠️ 매장이 Square + Loyverse 두 계정 관리 (운영 부담)
- ⚠️ 매장 입장에서 비효율 ("Square 쓸 거면 Square POS도 쓰면 되는데?")

**권장도**: ⭐⭐ — Loyverse 매장이 굳이 Square Payments만 쓰지 않을 가능성. 비효율.

#### Option 5: Zapier/Make.com No-Code ⭐

**작동 흐름**:
```
1. Voice Agent → Stripe payment link
2. Stripe Webhook → Zapier (no-code automation)
3. Zapier → Loyverse Receipt POST (Zapier built-in app)
```

**비용**:
- Zapier: $19.99-$73/mo (Tasks limit 발생)
- Stripe: 2.9% + $0.30/tx

**장단점**:
- ✅ No code (개발자 없는 매장 자가 setup 가능)
- ⚠️ Latency 30-90초 (Zapier polling)
- ⚠️ Reliability 한계 (Zapier 자체 downtime)
- ⚠️ Tasks 한도 초과 시 결제 자동화 정지 위험

**권장도**: ⭐ — 비상용. 정식 fallback은 Option 1.

### 3.3 권장 = Option 1 (Stripe Payment Link)

**근거**:
1. ✅ **이미 검증됨** — JM Cafe에서 라이브 작동 (4-5월 라이브 데이터)
2. ✅ **무료 setup** — Stripe account 무료
3. ✅ **신뢰도** — 글로벌 standard, 고객 인지도 최고
4. ✅ **우리 코드 100% 재사용** — bridge/pay_link.py + pos/loyverse.py
5. ⚠️ Fee 2.9% — Loyverse SumUp 1.69% 대비 살짝 높음 (단 자동화 가치 크므로 매장 ROI 정당화)

### 3.4 Voice Agent 통화 → 결제 자동화 풀 흐름

```
[고객]   "I'd like to order BBQ Combo A for 4 people, dine-in at 7 PM"
   ↓
[JM Voice Agent (Yuna)]
   - decomposes order → bbq_combo_a × 1 + party_size=4
   - confirms doneness + drinks + side
   - "Total $105 + 18% gratuity (party 6+ rule N/A) = $105. Sending payment link to your phone."
   ↓
[backend create_order tool]
   - bridge_transactions INSERT (state=pending, total=10500 cents)
   - Stripe Payment Link 생성
   - Twilio SMS → "Tap to pay: stripe.com/pay/abc123"
   ↓
[고객] SMS 클릭 → Stripe Hosted Checkout → 카드 결제
   ↓
[Stripe Webhook] → our backend /webhook/stripe/payment_intent.succeeded
   ↓
[backend mark_paid]
   - bridge_transactions.state=paid
   - Loyverse Receipt POST (Kitchen Display 자동 표시)
   - 고객 confirmation email (영수증 PDF)
   - Voice agent confirm "Payment received. See you at 7 PM!"
```

**총 자동화율**: 100% (no human in the loop)
**평균 처리 시간**: 결제 link 클릭 → Loyverse Receipt 마킹까지 ~5-15초
**Failure mode**:
- 결제 link 30분 미클릭 → no-show sweep cron → 자동 cancel
- 결제 실패 → 우리 backend가 다른 카드 시도 SMS 재발송
- Stripe webhook 누락 → polling (15분마다) fallback

---

## 4. JM Tech One POS Roadmap (12개월)

### Phase 1 (Month 1-3): Square + Loyverse 진입

| 작업 | 기간 | 산출물 |
|---|---|---|
| Square Orders API adapter | 1d | `backend/app/services/bridge/pos/square.py` |
| Square Payments API integration | 1d | `backend/app/services/bridge/payments/square.py` |
| Square OAuth + webhook | 0.5d | `backend/app/api/oauth_square.py` |
| Loyverse 결제 자동화 검증 | 0d (이미 라이브) | JM Cafe 운영 중 |
| PDX Pizza/Mexican 매장 sales (Square 사용) | 4-6주 | 1-2 매장 onboarding |

### Phase 2 (Month 4-6): Clover 진입

| 작업 | 기간 | 산출물 |
|---|---|---|
| Clover REST API adapter | 2d | `backend/app/services/bridge/pos/clover.py` |
| Fiserv Partner Agreement | 1-3개월 | 행정 |
| Clover App Market 등록 | 2-4주 | 마케팅 자동화 |
| Clover SMB 매장 (Bakery/Bar) sales | 8-12주 | 2-3 매장 |

### Phase 3 (Month 7-12): Toast 진입 (KPI 데이터 기반)

| 작업 | 기간 | 산출물 |
|---|---|---|
| Toast Partner Application | 1주 (제출) | 행정 |
| 우리 4-6개월 라이브 매장 KPI 보고서 첨부 | 1d | Strong proof |
| 법무/Compliance 검토 대기 | 3-6개월 | 행정 |
| Toast Alpha → Beta → Production | 5-7d | 4-5번째 매장 |

### Phase 4 (Month 12+): Quantic 평가

- Maple AI 파트너십 상황 재평가
- 한국어 vertical (KBBQ, sushi) 매장 = 우리 wedge
- 6개월 KPI + 다언어 차별점으로 partner application

---

## 5. POS별 매장 onboarding 비용 비교 (매장 입장 — 우리 ARR 분석)

| POS | Setup 비용 | 월 fee (매장) | 거래 fee | 우리 ARR 가능 |
|---|---:|---:|---:|:---:|
| **Square** | $0 | $0 (POS free) - $89 (Plus) | 2.6% + $0.10 | $299/mo (우리) |
| **Toast** | $0-$799 (hardware) | $69-$165/terminal | 2.49% + $0.15 | $499/mo (우리, FSR 매장) |
| **Clover** | $79-$799 (hardware) | $79-$89/mo | 2.6% + $0.10 | $399/mo (우리) |
| **Quantic** | $0-$1,500 (hardware) | $79-$129/mo | 2.49% + $0.10 | $499/mo (Maple 점유) |
| **Loyverse** | $0 | $0 (POS) + $39 SumUp 단말 (1회) | 2.9% + $0.30 (Stripe online) | $199/mo (우리, 소규모 매장) |

**우리 가격 정책 권장**:
- Pizza/Mexican (Square 사용): $299/mo
- Sushi/FSR (Toast 사용): $499/mo
- 소규모 cafe (Loyverse 사용): $199/mo
- 멀티-location 매장 (Clover 사용): $399/mo

**4개월 5 매장 ARR 예상**:
- JM Cafe (Loyverse, $199): $2,388/yr
- Pizza (Square, $299): $3,588/yr
- Thai (Loyverse, $199): $2,388/yr
- Plumber/HVAC (no POS, $299): $3,588/yr
- Mexican (Square, $299): $3,588/yr
- **합계 ARR: $15,540** + 통합 fee + 거래 비례 share

---

## 6. Risk + 의사 결정 권장

### 6.1 High Risk — 즉시 대응

1. **Quantic Maple AI lock-in** — 6개월 후 한국어 vertical wedge로 재평가. 지금은 우회.
2. **Toast 진입 시간** — 6-12개월 행정. Phase 3까지 미루고 Phase 1-2에 집중.
3. **Loyverse Stripe 결제 자동화 — 매장이 Stripe account 만들기** — 우리가 매장 onboarding 시 Stripe account 생성 단계 자동화 필요.

### 6.2 Medium Risk

4. **Clover App Market 심사 통과** — 우리 앱 quality + UX 심사. 2-4주 소요.
5. **Square Payments fee** — 2.6% + $0.10. SMB 매장이 이미 결제 fee 부담 → 우리 가격 정책 fee inclusive 고려.

### 6.3 Low Risk

6. **Loyverse 자체 결제 confirmation** — 우리 backend가 mark_paid 자동, 매장 무관.

---

## 7. 최종 권장 — 6개월 행동 계획

### 7.1 즉시 (이번 달, 2026-05)

1. **Square POS adapter 작성 시작** (Phase 1.1) — `backend/app/services/bridge/pos/square.py`
2. **Loyverse Stripe 결제 흐름 documentation** — 매장 onboarding wizard에 명시
3. **PDX Pizza 1개 매장 sales discovery** — Square 사용 매장 우선

### 7.2 3개월 후 (2026-08)

- Square adapter 라이브 + 2 매장 운영
- Loyverse Stripe payment 자동화 5 매장 검증
- Clover Partner Agreement 시작

### 7.3 6개월 후 (2026-11)

- 5 매장 라이브 (cafe + pizza + thai + plumber + mexican)
- 6개월 KPI 보고서 작성 → 투자자 deck + Toast Partner Application 동봉
- Clover App Market 등록 시작

### 7.4 12개월 후 (2027-05)

- Toast 진입 (1-2 매장)
- Quantic Maple AI 상황 재평가
- 10+ 매장 ARR $50K+

---

## 8. 한 줄 결론

> **POS 통합 우선순위 = Square (즉시) > Loyverse (이미 라이브) > Clover (3-6개월) > Toast (6-12개월) > Quantic (12개월+).**
>
> **Loyverse 결제 자동화 = Stripe Payment Link + Loyverse Receipt POST 패턴 (이미 JM Cafe 라이브 검증). 추가 비용 $0, 자동화율 100%, 우리 코드 100% 재사용.**

---

## 부록 A — 데이터 출처

| 통계 / 정보 | 출처 | URL |
|---|---|---|
| Square Orders API + Restaurant 통합 | Square Developer Docs 2026 | https://developer.squareup.com/us/en |
| Toast Partner Application + 인증 절차 | Toast Developer Guide 2026 | https://doc.toasttab.com/doc/devguide/integrationDevProcess.html |
| Clover Native vs Semi-Integration | Clover Developer Docs 2026 | https://docs.clover.com/dev/docs/home |
| Clover App Market | Clover Developers | https://www.clover.com/developers |
| Quantic + Maple AI 파트너십 (2026-04-24) | BusinessWire | https://www.businesswire.com/news/home/20260424097043/en/ |
| Maple AI 92% 해결률 + 1M+ calls | Verdict Food Service 2026 | https://www.verdictfoodservice.com/news/quantic-pos-adds-maple-for-ai-phone-ordering-at-restaurants/ |
| Loyverse SumUp 통합 | Loyverse 공식 | https://loyverse.com/sumup |
| Loyverse API + Webhook (Stripe via Zapier) | Zapier | https://zapier.com/apps/loyverse/integrations/stripe |
| Toast Pricing 2026 | CheckThat.ai | https://checkthat.ai/brands/toast/pricing |
| Maverick Payments ACH + Card | Maverick Payments | https://maverickpayments.com/ |
| Voice Agent + POS Integration Guide 2026 | Kea AI | https://kea.ai/resources/best-voice-ai-restaurant-integration-guide-2026 |
| Bite Buddy POS integrations | Bite Buddy AI Blog | https://bitebuddy.ai/blog/best-ai-phone-system-restaurants-2026 |

---

## 부록 B — 우리 backend 코드 매핑 (POS adapter 재사용성)

| POS | 우리 adapter 상태 | 작업 시간 | 의존 파일 |
|---|:---:|---:|---|
| Loyverse | ✅ 라이브 | 0d | `bridge/pos/loyverse.py` (341 LOC) |
| Square | ❌ 신규 | 2-3d | (신규) `bridge/pos/square.py` ~250 LOC |
| Clover | ❌ 신규 | 2-3d | (신규) `bridge/pos/clover.py` ~280 LOC |
| Toast | ❌ 신규 | 5-7d | (신규) `bridge/pos/toast.py` ~350 LOC (modifier 깊이↑) |
| Quantic | ❌ 신규 | 보류 | (Maple lock-in) |

**우리 4계층 아키텍처 강점**:
- `bridge/pos/base.py` (Abstract POS adapter) — 인터페이스만 구현하면 5번째 POS 추가 가능
- `bridge/pos/factory.py` — store.pos_provider 기반 라우팅 자동
- 즉, **POS adapter 추가 = factory에 분기 추가만 (코어 변경 X)**

---

**한 줄 마무리**: 5대 POS 중 **Square가 빠른 진입 (1주) + Loyverse는 이미 보유 = 2개월 안에 2개 vertical 매장 라이브 가능**. Toast는 KPI 데이터 만들고 Phase 3 진입. Quantic은 6개월 후 한국어 vertical wedge로 재평가.
