"""Menu onboarding automation pipeline (Layer 4 — adapter).

Stage 1: input_router selects a source adapter (Loyverse / URL / PDF /
image / CSV / manual) and produces a `RawMenuExtraction`.
Stage 2: ai_extractor + normalizer fold every source into the same
`menu.yaml` + `modifier_groups.yaml` shape (Phase 2 — not in this file).
Stage 3: Admin Wizard UI reviews/edits and triggers POS sync (Phase 3-4).

Plan source: docs/strategic-research/2026-05-11_menu-onboarding-automation/
(메뉴 온보딩 자동화 — 6 phase 중 Phase 1 입력 계층)
"""
