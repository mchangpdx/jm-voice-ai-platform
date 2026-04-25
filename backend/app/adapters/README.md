# app/adapters/ — Layer 4: External Bridges & Relay Engine
# (레이어 4: 외부 연동 브릿지 및 릴레이 엔진)

## Role
All outbound integrations with third-party systems. Implements the "Eyes + Ears"
POS-CCTV relay pipeline: Loyverse webhooks → standardized payload → Solink text overlay.
(모든 외부 시스템 연동. Loyverse 웹훅 → 표준화 페이로드 → Solink CCTV 텍스트 오버레이 릴레이 파이프라인)

## Structure
| Directory | Purpose (목적) |
|-----------|----------------|
| `relay/` | Core relay engine — orchestrates Loyverse-to-Solink pipeline (핵심 릴레이 엔진) |
| `solink/` | Solink Cloud API client — text overlay push (Solink API 클라이언트) |
| `loyverse/` | Loyverse webhook receiver and POS injector (Loyverse 웹훅·POS 주입기) |

## Layer-Specific Coding Rules
- All outbound calls MUST be async (fire-and-forget) — never block the request cycle.
  (모든 외부 호출은 비동기 필수 — 요청 사이클 블로킹 금지)
- `variant_id` and `payment_type_id` must be validated BEFORE sending to Solink.
  (Solink 전송 전 `variant_id`·`payment_type_id` 유효성 검사 필수)
- Relay failures must be logged to `pos_events.overlay_status` for retry tracking.
  (릴레이 실패는 재시도 추적을 위해 `pos_events.overlay_status`에 로그 기록)
