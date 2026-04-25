# frontend/ — Matrix UI Architecture (React + Vite)
# (매트릭스 UI 아키텍처 — React + Vite 기반 프론트엔드)

## Role
The single-page application delivering the Industry × Role matrix dashboard.
Connects to the FastAPI backend and renders real-time CCTV, POS, and Voice AI data.
(산업 × 역할 매트릭스 대시보드를 제공하는 SPA. 실시간 CCTV·POS·Voice AI 데이터 렌더링)

## Key Files Expected
| Path | Purpose (목적) |
|------|----------------|
| `src/core/` | Global layouts, auth guards, routing (공통 레이아웃·인증·라우팅) |
| `src/components/` | Reusable UI widgets (재사용 가능한 UI 위젯) |
| `src/views/` | Matrix views — Industry × Role (매트릭스 뷰 — 업종 × 역할) |
| `src/services/` | API communication layer (API 통신 레이어) |
| `src/store/` | Global state management (Zustand) (전역 상태 관리) |
| `vite.config.ts` | Vite bundler configuration (Vite 번들러 설정) |
| `package.json` | Node.js dependencies (Node.js 의존성) |

## Layer-Specific Coding Rules
- Agency views aggregate across multiple stores; Store views scope to a single `tenant_id`.
  (에이전시 뷰는 다중 매장 집계, 점주 뷰는 단일 `tenant_id` 스코프)
- All API calls go through `src/services/` — no direct fetch calls in components or views.
  (모든 API 호출은 `src/services/` 경유 — 컴포넌트·뷰에서 직접 fetch 금지)
- Use lazy-loading (`React.lazy`) per vertical route to minimize initial bundle size.
  (초기 번들 크기 최소화를 위해 업종별 라우트에 `React.lazy` 사용)
