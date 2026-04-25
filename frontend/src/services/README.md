# src/services/ — API Communication Layer
# (API 통신 레이어 — 백엔드와의 모든 통신 처리)

## Role
All HTTP and WebSocket communication with the FastAPI backend.
Organized by vertical to mirror the backend API structure.
(FastAPI 백엔드와의 모든 HTTP·WebSocket 통신. 백엔드 API 구조를 반영한 업종별 구성)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `api.ts` | Base axios/fetch client with auth interceptors (인증 인터셉터가 포함된 기본 클라이언트) |
| `fsr.service.ts` | FSR vertical API calls (FSR 업종 API 호출) |
| `homecare.service.ts` | Home Care API calls (홈케어 API 호출) |
| `retail.service.ts` | Retail API calls (리테일 API 호출) |
| `auth.service.ts` | Login, refresh, logout calls (인증 API 호출) |
| `socket.ts` | WebSocket/SSE connection managers (WebSocket·SSE 연결 관리) |

## Coding Rules
- All service functions must return typed Promises — no `any` types.
  (모든 서비스 함수는 타입이 지정된 Promise 반환 — `any` 타입 금지)
- The base client must automatically attach the JWT token from the Zustand store.
  (기본 클라이언트는 Zustand 스토어의 JWT 토큰 자동 첨부 필수)
- Service layer catches and normalizes API errors before they reach view components.
  (서비스 레이어는 뷰 컴포넌트 도달 전 API 에러를 잡아 정규화)
