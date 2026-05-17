-- Phase 2 — Schema abstraction for multi-vertical architecture.
-- (Phase 2 — multi-vertical 아키텍처를 위한 스키마 추상화. Beauty MVP sprint 산출물.)
--
-- Run once in Supabase SQL editor. Safe to re-run (idempotent guards
-- everywhere). Backwards compatible: every existing food store keeps
-- its current code path because vertical_kind defaults seed to 'order'.
--
-- See backend/app/templates/_base/spec.md §6 (Backward Compatibility Promise)
-- and Beauty MVP plan §Phase 2 for the architectural intent.

-- ─────────────────────────────────────────────────────────────────────────
-- Phase 2.1 — stores.vertical_kind column
-- (어떤 vertical kind인지 명시. 'order' / 'service' / 'service_with_dispatch'.)
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE stores
    ADD COLUMN IF NOT EXISTS vertical_kind text;

-- Enforce the allowed enum via a NOT-VALID check first, then validate so
-- existing NULL rows don't block the add. (NULL is allowed during the
-- backfill window — Phase 2.2 fills every row.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'stores_vertical_kind_chk'
    ) THEN
        ALTER TABLE stores
            ADD CONSTRAINT stores_vertical_kind_chk
            CHECK (vertical_kind IS NULL
                   OR vertical_kind IN ('order', 'service', 'service_with_dispatch'))
            NOT VALID;
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────────
-- Phase 2.2 — Seed existing stores to their kind.
-- (기존 매장을 vertical_kind로 채움. industry → kind 매핑은 vertical_kinds.yaml과 동일.)
--
-- order:                 cafe, restaurant, pizza, mexican, kbbq, sushi, chinese
-- service:               beauty
-- service_with_dispatch: home_services, auto_repair
-- ─────────────────────────────────────────────────────────────────────────

UPDATE stores SET vertical_kind = 'order'
 WHERE vertical_kind IS NULL
   AND lower(industry) IN ('cafe', 'restaurant', 'pizza', 'mexican',
                           'kbbq', 'sushi', 'chinese');

UPDATE stores SET vertical_kind = 'service'
 WHERE vertical_kind IS NULL
   AND lower(industry) IN ('beauty');

UPDATE stores SET vertical_kind = 'service_with_dispatch'
 WHERE vertical_kind IS NULL
   AND lower(industry) IN ('home_services', 'auto_repair');

-- Validate the check now that every row is populated. Skipped if VALIDATED
-- already (no-op).
DO $$
BEGIN
    BEGIN
        ALTER TABLE stores VALIDATE CONSTRAINT stores_vertical_kind_chk;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'constraint validation skipped: %', SQLERRM;
    END;
END $$;

CREATE INDEX IF NOT EXISTS idx_stores_vertical_kind
    ON stores(vertical_kind)
    WHERE vertical_kind IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- Phase 2.3 — bridge_jobs view.
-- (bridge_transactions를 generic 'jobs'로 재명명한 view — service-kind 매장이
--  appointments / dispatches로 read할 수 있게. mutation은 base table에 그대로.)
--
-- SELECT-only view. Future Phase 3 service tools (book_appointment etc.)
-- can SELECT from bridge_jobs while still INSERTing into the underlying
-- bridge_transactions until we decide whether to split into a separate
-- physical table. (Out of scope for Phase 2.)
-- ─────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW bridge_jobs AS
SELECT
    t.*,
    s.vertical_kind AS store_vertical_kind
FROM bridge_transactions t
JOIN stores s ON s.id = t.store_id;

COMMENT ON VIEW bridge_jobs IS
  'Generic ''jobs'' alias of bridge_transactions enriched with vertical_kind.'
  ' service-kind verticals (beauty/home/auto) read appointments via this view.'
  ' Phase 2.3.';

-- PostgREST exposes views only when the API roles can SELECT from them.
-- (PostgREST는 view에 SELECT 권한이 grant되어야 expose함 — 2026-05-18 추가)
GRANT SELECT ON bridge_jobs TO anon, authenticated, service_role;

-- ─────────────────────────────────────────────────────────────────────────
-- Phase 2.4 — menu_items.service_kind + duration_min.
-- (service-kind 매장의 menu_items에 서비스 분류 + 소요시간 nullable column.
--  음식점 매장은 NULL이라 영향 zero.)
--
-- service_kind:  e.g. haircut, color, manicure, oil_change, hvac_diag
-- duration_min:  e.g. 30, 45, 60, 90, 120  (used by scheduler.yaml slot model)
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE menu_items
    ADD COLUMN IF NOT EXISTS service_kind text,
    ADD COLUMN IF NOT EXISTS duration_min integer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'menu_items_duration_min_nonneg'
    ) THEN
        ALTER TABLE menu_items
            ADD CONSTRAINT menu_items_duration_min_nonneg
            CHECK (duration_min IS NULL OR duration_min >= 0);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_menu_items_service_kind
    ON menu_items(service_kind)
    WHERE service_kind IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- Verification queries (run interactively after applying).
-- (적용 후 확인용 쿼리.)
-- ─────────────────────────────────────────────────────────────────────────
--
-- SELECT name, industry, vertical_kind FROM stores ORDER BY name;
-- SELECT count(*) FROM stores WHERE vertical_kind IS NULL;          -- expect 0
-- SELECT count(*) FROM stores GROUP BY vertical_kind;
-- SELECT count(*) FROM bridge_jobs;                                  -- =bridge_transactions
-- \d+ menu_items                                                     -- service_kind + duration_min visible

-- ─────────────────────────────────────────────────────────────────────────
-- Rollback (only if disaster — should be near-impossible since every
-- step is additive + nullable).
-- (롤백 — 모든 변경이 additive + nullable이라 거의 불필요.)
-- ─────────────────────────────────────────────────────────────────────────
--
-- DROP VIEW IF EXISTS bridge_jobs;
-- DROP INDEX IF EXISTS idx_stores_vertical_kind;
-- DROP INDEX IF EXISTS idx_menu_items_service_kind;
-- ALTER TABLE stores DROP CONSTRAINT IF EXISTS stores_vertical_kind_chk;
-- ALTER TABLE menu_items DROP CONSTRAINT IF EXISTS menu_items_duration_min_nonneg;
-- ALTER TABLE stores DROP COLUMN IF EXISTS vertical_kind;
-- ALTER TABLE menu_items DROP COLUMN IF EXISTS duration_min;
-- ALTER TABLE menu_items DROP COLUMN IF EXISTS service_kind;
