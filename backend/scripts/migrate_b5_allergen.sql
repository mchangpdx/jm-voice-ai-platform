-- Phase 2-C.B5 — Allergen + dietary tag columns on menu_items
-- (Phase 2-C.B5 — menu_items에 allergen/dietary 컬럼 추가)
--
-- Spec: backend/docs/specs/B5_allergen_qa.md §2 / Decision #7
-- Operator-curated only (CUSTOMER SAFETY INVARIANT — never LLM inference).
-- Default '[]' = "no data on hand" → bot answers `allergen_unknown` and
-- offers manager transfer (HonestUnknown invariant I1).

alter table menu_items
    add column if not exists allergens     jsonb not null default '[]'::jsonb;

alter table menu_items
    add column if not exists dietary_tags  jsonb not null default '[]'::jsonb;

-- v1: no GIN index — single-row lookup per query (OneItemPerQuery I2).
-- v2 dietary_filter (whole-menu scan) will revisit indexing.
