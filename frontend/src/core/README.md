# src/core/ — Global Layouts & Auth
# (공통 레이아웃 및 전역 인증 — 앱 공통 구조)

## Role
Application shell: root layout, navigation sidebar, authentication guards,
and role-based routing logic (Agency vs Store per vertical).
(앱 셸: 루트 레이아웃·내비게이션·인증 가드·역할 기반 라우팅)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `RootLayout.tsx` | App shell with sidebar and header (사이드바·헤더가 포함된 앱 셸) |
| `AuthGuard.tsx` | Route-level authentication guard (라우트 수준 인증 가드) |
| `RoleGuard.tsx` | Agency vs Store access control (에이전시·점주 접근 제어) |
| `router.tsx` | React Router v6 route definitions (라우트 정의) |
| `theme.ts` | Design tokens and color palette (디자인 토큰·색상 팔레트) |

## Coding Rules
- `RoleGuard` reads the user's role from the global Zustand store — never from localStorage directly.
  (역할 정보는 localStorage가 아닌 전역 Zustand 스토어에서 읽기)
- Navigation links are generated dynamically based on `vertical` and `role` — no hardcoded menus.
  (내비게이션 링크는 `vertical`·`role` 기반으로 동적 생성 — 하드코딩 금지)
