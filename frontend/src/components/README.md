# src/components/ — Reusable UI Widgets
# (재사용 가능한 UI 위젯 — 공통 컴포넌트)

## Role
Vertical-agnostic, reusable React components shared across all views.
Examples: KPI cards, data tables, status badges, voice waveform visualizer.
(모든 뷰에서 공유하는 업종 중립적 재사용 컴포넌트. KPI 카드·테이블·상태 배지·음성 시각화 등)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `KpiCard.tsx` | Animated KPI metric display (KPI 수치 표시 카드) |
| `StatusBadge.tsx` | Color-coded status indicator (색상 코드 상태 표시기) |
| `DataTable.tsx` | Paginated, sortable data table (페이징·정렬 가능한 데이터 테이블) |
| `VoiceWave.tsx` | Real-time voice waveform visualizer (실시간 음성 파형 시각화) |
| `index.ts` | Barrel export for all components (모든 컴포넌트 배럴 익스포트) |

## Coding Rules
- Components must accept all data via props — no direct store reads inside widgets.
  (컴포넌트는 모든 데이터를 props로 수신 — 위젯 내부에서 직접 스토어 읽기 금지)
- No vertical-specific logic in this directory — keep components fully generic.
  (이 디렉토리에 업종별 로직 포함 금지 — 완전히 범용적으로 유지)
