# adapters/loyverse/ — Loyverse POS Bridge
# (Loyverse 어댑터 — Loyverse POS 브릿지)

## Role
Handles all Loyverse POS integration: webhook reception for `receipts.update` events,
inventory lookups, and POS injection for AI-confirmed orders.
(Loyverse 웹훅 수신·재고 조회·AI 확인 주문의 POS 주입 처리)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `webhook.py` | Webhook endpoint and event validation (웹훅 엔드포인트·이벤트 검증) |
| `client.py` | Loyverse REST API client (Loyverse REST API 클라이언트) |
| `injector.py` | POS order injection with variant_id mapping (variant_id 매핑 POS 주문 주입) |
| `inventory.py` | Real-time inventory query (실시간 재고 조회) |

## Coding Rules
- Webhook signature must be verified before processing any payload.
  (페이로드 처리 전 웹훅 서명 검증 필수)
- `loyverse_token` is stored encrypted in `stores.loyverse_token` — decrypt at runtime only.
  (토큰은 `stores.loyverse_token`에 암호화 저장 — 런타임에만 복호화)
