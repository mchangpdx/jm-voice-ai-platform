# adapters/solink/ — Solink Cloud API Interface
# (Solink 어댑터 — Solink 클라우드 API 인터페이스)

## Role
HTTP client wrapper for the Solink Cloud API. Handles authentication,
text overlay push requests, and camera-site mapping per tenant.
(Solink 클라우드 API HTTP 클라이언트. 인증·텍스트 오버레이 푸시·카메라-사이트 매핑 처리)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `client.py` | Async httpx-based Solink API client (httpx 기반 비동기 Solink 클라이언트) |
| `auth.py` | Solink API key management per tenant (테넌트별 Solink API 키 관리) |
| `overlay.py` | Text overlay request builder and sender (텍스트 오버레이 요청 빌더·발송) |
| `camera_map.py` | `site_id` and camera_mapping resolver (site_id·카메라 매핑 해석기) |

## Coding Rules
- Solink API credentials must be read from `stores.solink_config` JSONB, not env vars.
  (Solink API 자격증명은 환경변수가 아닌 `stores.solink_config` JSONB에서 읽기)
- All HTTP calls must have a timeout of 5 seconds maximum.
  (모든 HTTP 호출은 최대 5초 타임아웃 설정 필수)
