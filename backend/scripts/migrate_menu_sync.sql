-- Phase 2-B.1.7 — Menu items table + menu_cache column on stores
-- (Phase 2-B.1.7 — menu_items 테이블 + stores.menu_cache 컬럼)
--
-- menu_items: catalog mirror of POS items. One row per (store_id, variant_id)
-- — Loyverse exposes variants per item; we flatten so receipt line_items can
-- carry variant_id directly without re-resolving from item_id every call.
--
-- stores.menu_cache: pre-formatted "item - $price" lines for the Voice Engine
-- system prompt. Refreshed by the same sync run that upserts menu_items —
-- avoids a DB round-trip from the live audio path.
--
-- Re-runs are safe: ON CONFLICT (store_id, variant_id) DO UPDATE.

create table if not exists menu_items (
    id              serial primary key,
    store_id        uuid not null references stores(id) on delete cascade,
    pos_item_id     text not null,                 -- Loyverse item UUID (parent)
    variant_id      text not null,                 -- Loyverse variant UUID — receipt line key
    sku             text,
    name            text not null,
    option_value    text,                          -- e.g. "Small", "Large"
    price           numeric(10,2) not null default 0,
    stock_quantity  integer not null default 0,    -- in_stock from /inventory or /items
    category_id     text,
    color           text,
    description     text,
    raw             jsonb,                         -- preserved Loyverse payload for audit
    last_synced_at  timestamptz not null default now(),
    created_at      timestamptz not null default now()
);

create unique index if not exists menu_items_store_variant_unique
    on menu_items (store_id, variant_id);

create index if not exists menu_items_store_idx       on menu_items (store_id);
create index if not exists menu_items_lower_name_idx  on menu_items (store_id, lower(name));

alter table stores
    add column if not exists menu_cache text;     -- pre-formatted prompt-ready menu

-- Note: RLS is intentionally NOT enabled here yet. menu_items contain no PII
-- and the sync writer uses the service_role key. Phase 3 (CRM) will revisit
-- when per-tenant policies are tightened across all bridge tables.
