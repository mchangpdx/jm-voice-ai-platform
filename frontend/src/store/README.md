# src/store/ — Global State Management (Zustand)
# (전역 상태 관리 — Zustand 기반 상태 스토어)

## Role
Central state management using Zustand. Stores authentication state, current vertical,
user role, and shared UI state used across views.
(Zustand 기반 중앙 상태 관리. 인증 상태·현재 업종·사용자 역할·공유 UI 상태 저장)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `authStore.ts` | JWT token, user profile, role (JWT·사용자 프로필·역할) |
| `appStore.ts` | Active vertical, sidebar state, global loading (활성 업종·사이드바·로딩) |
| `fsrStore.ts` | FSR-specific reactive state (FSR 반응형 상태) |
| `homecareStore.ts` | Home Care reactive state (홈케어 반응형 상태) |
| `retailStore.ts` | Retail reactive state (리테일 반응형 상태) |

## Coding Rules
- Never persist sensitive data (tokens, API keys) to localStorage via Zustand persist middleware.
  (Zustand persist 미들웨어로 민감한 데이터를 localStorage에 저장 금지)
- Store slices must be typed with TypeScript interfaces — no untyped state.
  (스토어 슬라이스는 TypeScript 인터페이스로 타입 지정 필수 — 비타입 상태 금지)
- Vertical stores are reset on logout — implement a `reset()` action in each store.
  (업종 스토어는 로그아웃 시 초기화 — 각 스토어에 `reset()` 액션 구현 필수)
