# adapters/relay/ — POS-CCTV Text Overlay Relay Engine
# (릴레이 엔진 — POS-CCTV 텍스트 오버레이 파이프라인)

## Role
The central relay orchestrator. Ingests Loyverse `receipts.update` webhook events,
maps `variant_id` and `payment_type_id`, standardizes the payload, and pushes
text overlay to Solink for real-time CCTV synchronization.
(Loyverse 웹훅 수신 → variant_id 매핑 → 페이로드 표준화 → Solink CCTV 오버레이 푸시)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `engine.py` | Main relay orchestration logic (릴레이 오케스트레이션 메인 로직) |
| `mapper.py` | `variant_id` and `payment_type_id` resolution (variant_id·payment_type_id 해석) |
| `payload.py` | Standardized payload builder (표준화 페이로드 빌더) |
| `retry.py` | Exponential backoff retry for failed overlays (실패한 오버레이 지수 백오프 재시도) |

## Coding Rules
- The relay pipeline must be fully async and use background tasks — never await in route handlers.
  (릴레이 파이프라인은 완전 비동기·백그라운드 작업 — 라우트 핸들러에서 직접 await 금지)
- Every relay attempt (success or failure) must write a record to `pos_events`.
  (모든 릴레이 시도는 성공·실패 불문 `pos_events`에 기록)
