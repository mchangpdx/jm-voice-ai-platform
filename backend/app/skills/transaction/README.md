# skills/transaction/ — Payment & Invoice Processor
# (트랜잭션 스킬 — 결제 및 인보이스 처리)

## Role
Handles all payment workflows: generating payment links, processing POS injections via Loyverse,
and creating invoice records. Records every event to `pos_events` table for Solink overlay.
(결제 링크 생성, Loyverse POS 주입, 인보이스 생성 처리. 모든 이벤트를 `pos_events`에 기록)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `payment_link.py` | Payment URL generation logic (결제 URL 생성 로직) |
| `pos_injection.py` | Loyverse POS push with `variant_id` mapping (variant_id 매핑 POS 주입) |
| `invoice.py` | Invoice record creation (인보이스 레코드 생성) |

## Coding Rules
- POS injection must validate `variant_id` and `payment_type_id` before sending to Loyverse.
  (POS 주입 전 `variant_id`·`payment_type_id` 유효성 검사 필수)
- All transaction records must set `overlay_status` for Solink relay tracking.
  (모든 거래 레코드에 Solink 릴레이 추적용 `overlay_status` 설정 필수)
- Use fire-and-forget async pattern for the Solink overlay push.
  (Solink 오버레이 푸시는 비동기 fire-and-forget 패턴 사용)
