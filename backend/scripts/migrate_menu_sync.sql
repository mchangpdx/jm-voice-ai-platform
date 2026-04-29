-- Phase 2-B.1.7 — Menu items table + menu_cache column on stores
-- (Phase 2-B.1.7 — menu_items 테이블 + stores.menu_cache 컬럼)
--
-- IMPORTANT: jm-saas-platform Loyverse demo previously created a menu_items
-- table on the same Supabase project with a different shape. CREATE TABLE
-- IF NOT EXISTS would silently keep the legacy shape, so this migration:
--   1. Creates the table only when it's truly missing,
--   2. Adds every required column via ALTER TABLE ... ADD COLUMN IF NOT EXISTS
--      so a legacy table is upgraded in place,
--   3. Builds indexes only after all columns are guaranteed to exist.
--
-- menu_items: catalog mirror of POS items. One row per (store_id, variant_id)
-- — Loyverse exposes variants per item; we flatten so receipt line_items can
-- carry variant_id directly without re-resolving from item_id every call.
--
-- stores.menu_cache: pre-formatted "item - $price" lines for the Voice Engine
-- system prompt. Refreshed by the same sync run that upserts menu_items —
-- avoids a DB round-trip from the live audio path.

-- ── Step 1: Create the table only when missing ────────────────────────────
create table if not exists menu_items (
    id              serial primary key,
    store_id        uuid not null,
    pos_item_id     text,
    variant_id      text not null,
    name            text not null,
    last_synced_at  timestamptz not null default now(),
    created_at      timestamptz not null default now()
);

-- ── Step 2: Upgrade existing/new table to the canonical shape ─────────────
alter table menu_items add column if not exists pos_item_id    text;
alter table menu_items add column if not exists variant_id     text;
alter table menu_items add column if not exists sku            text;
alter table menu_items add column if not exists option_value   text;
alter table menu_items add column if not exists price          numeric(10,2) not null default 0;
alter table menu_items add column if not exists stock_quantity integer not null default 0;
alter table menu_items add column if not exists category_id    text;
alter table menu_items add column if not exists color          text;
alter table menu_items add column if not exists description    text;
alter table menu_items add column if not exists raw            jsonb;
alter table menu_items add column if not exists last_synced_at timestamptz not null default now();
alter table menu_items add column if not exists store_id       uuid;
alter table menu_items add column if not exists name           text;

-- Backfill required NULLs the FK is about to enforce. If legacy rows lack
-- variant_id or store_id, mark them inactive so the unique index can build —
-- a follow-up Loyverse re-sync will overwrite them with real values.
-- (필수 컬럼 NULL 백필 — 인덱스 생성 가능하도록 임시 값 채움)
update menu_items
   set variant_id = coalesce(variant_id, 'legacy-' || id::text)
 where variant_id is null;

update menu_items
   set name = coalesce(name, 'unknown')
 where name is null;

-- Tighten NOT NULL on the columns that should never be missing going forward.
alter table menu_items alter column variant_id set not null;
alter table menu_items alter column name       set not null;

-- Add the FK to stores only if it isn't there yet — older demo setups may
-- already have a different FK. (FK 중복 추가 방지)
do $$
begin
  if not exists (
    select 1 from information_schema.table_constraints
     where table_name = 'menu_items'
       and constraint_type = 'FOREIGN KEY'
       and constraint_name = 'menu_items_store_id_fkey'
  ) then
    alter table menu_items
      add constraint menu_items_store_id_fkey
      foreign key (store_id) references stores(id) on delete cascade;
  end if;
end $$;

-- ── Step 3: Build indexes once columns are guaranteed ────────────────────
create unique index if not exists menu_items_store_variant_unique
    on menu_items (store_id, variant_id);

create index if not exists menu_items_store_idx       on menu_items (store_id);
create index if not exists menu_items_lower_name_idx  on menu_items (store_id, lower(name));

-- ── Step 4: stores.menu_cache for Voice Engine prompt ────────────────────
alter table stores
    add column if not exists menu_cache text;

-- Note: RLS is intentionally NOT enabled here yet. menu_items contain no PII
-- and the sync writer uses the service_role key. Phase 3 (CRM) will revisit
-- when per-tenant policies are tightened across all bridge tables.
