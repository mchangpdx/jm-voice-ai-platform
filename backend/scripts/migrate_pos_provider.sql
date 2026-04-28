-- Phase 2-B.1.5 — Add pos_provider + pos_api_key to stores
-- (Phase 2-B.1.5 — stores 테이블에 pos_provider + pos_api_key 컬럼 추가)
--
-- Backwards compatible: existing stores default to 'supabase' (current behavior).
-- New stores can opt into 'loyverse', 'quantic', etc.

alter table stores
    add column if not exists pos_provider text not null default 'supabase'
        check (pos_provider in ('supabase', 'loyverse', 'quantic'));

alter table stores
    add column if not exists pos_api_key text;   -- per-store override; NULL = use global env

-- For our 4 demo stores, leave default 'supabase' — they read/write our own
-- reservations/jobs/appointments/service_orders tables. JM Cafe will be the
-- first store to flip to 'loyverse' for live menu sync verification.
