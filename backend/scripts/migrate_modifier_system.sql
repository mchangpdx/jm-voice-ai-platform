-- Phase 7-A — Modifier system DDL (3 tables + RLS)
-- (2026-05-07 — Modifier 시스템 schema migration)
--
-- Apply via Supabase SQL Editor (DDL cannot be applied via PostgREST).
-- After this DDL, run scripts/seed_jm_cafe_modifiers.py to seed data.
--
-- Tables created:
--   modifier_groups          — per-store group definitions (size/milk/syrup/...)
--   modifier_options         — options within a group (small/oat/vanilla/...)
--   menu_item_modifier_groups — menu_item ↔ group many-to-many mapping
--
-- RLS pattern follows menu_items: store_id-based isolation.
-- service_role bypasses RLS (used by backend); anon role enforces it.

-- ── Table 1: modifier_groups ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS modifier_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id        UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,                    -- 'size','milk','syrup'
    display_name    TEXT NOT NULL,                    -- 'Size'
    is_required     BOOLEAN NOT NULL DEFAULT false,
    min_select      INT NOT NULL DEFAULT 0,
    max_select      INT NOT NULL DEFAULT 1,
    sort_order      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(store_id, code)
);

CREATE INDEX IF NOT EXISTS idx_modifier_groups_store ON modifier_groups(store_id);

ALTER TABLE modifier_groups ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_iso_select ON modifier_groups;
CREATE POLICY tenant_iso_select ON modifier_groups
    FOR SELECT USING (
        store_id IN (
            SELECT s.id FROM stores s
            WHERE s.owner_id = auth.uid()
               OR s.agency_id IN (
                   SELECT id FROM agencies WHERE owner_id = auth.uid()
               )
        )
    );

DROP POLICY IF EXISTS tenant_iso_modify ON modifier_groups;
CREATE POLICY tenant_iso_modify ON modifier_groups
    FOR ALL USING (
        store_id IN (
            SELECT s.id FROM stores s
            WHERE s.owner_id = auth.uid()
               OR s.agency_id IN (
                   SELECT id FROM agencies WHERE owner_id = auth.uid()
               )
        )
    );

-- ── Table 2: modifier_options ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS modifier_options (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id        UUID NOT NULL REFERENCES modifier_groups(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,                    -- 'small','oat'
    display_name    TEXT NOT NULL,
    price_delta     NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    allergen_add    JSONB NOT NULL DEFAULT '[]'::jsonb,  -- e.g. '["gluten","wheat"]'
    allergen_remove JSONB NOT NULL DEFAULT '[]'::jsonb,  -- e.g. '["dairy"]'
    sort_order      INT NOT NULL DEFAULT 0,
    is_default      BOOLEAN NOT NULL DEFAULT false,   -- e.g. small as default size
    is_available    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(group_id, code)
);

CREATE INDEX IF NOT EXISTS idx_modifier_options_group ON modifier_options(group_id);

ALTER TABLE modifier_options ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_iso_select ON modifier_options;
CREATE POLICY tenant_iso_select ON modifier_options
    FOR SELECT USING (
        group_id IN (
            SELECT id FROM modifier_groups   -- recursive policy via parent table
        )
    );

DROP POLICY IF EXISTS tenant_iso_modify ON modifier_options;
CREATE POLICY tenant_iso_modify ON modifier_options
    FOR ALL USING (
        group_id IN (
            SELECT id FROM modifier_groups
        )
    );

-- ── Table 3: menu_item_modifier_groups (many-to-many) ────────────────────────

CREATE TABLE IF NOT EXISTS menu_item_modifier_groups (
    menu_item_id    UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    group_id        UUID NOT NULL REFERENCES modifier_groups(id) ON DELETE CASCADE,
    sort_order      INT NOT NULL DEFAULT 0,
    PRIMARY KEY (menu_item_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_mim_groups_item ON menu_item_modifier_groups(menu_item_id);
CREATE INDEX IF NOT EXISTS idx_mim_groups_group ON menu_item_modifier_groups(group_id);

ALTER TABLE menu_item_modifier_groups ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_iso_select ON menu_item_modifier_groups;
CREATE POLICY tenant_iso_select ON menu_item_modifier_groups
    FOR SELECT USING (
        menu_item_id IN (SELECT id FROM menu_items)
    );

DROP POLICY IF EXISTS tenant_iso_modify ON menu_item_modifier_groups;
CREATE POLICY tenant_iso_modify ON menu_item_modifier_groups
    FOR ALL USING (
        menu_item_id IN (SELECT id FROM menu_items)
    );

-- ── Verification queries (commented — run separately after seed) ─────────────

-- SELECT COUNT(*) FROM modifier_groups WHERE store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9';
-- -- Expected: 9 (after seed)

-- SELECT g.code, COUNT(o.id) AS option_count
-- FROM modifier_groups g LEFT JOIN modifier_options o ON o.group_id = g.id
-- WHERE g.store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9'
-- GROUP BY g.code ORDER BY g.code;

-- SELECT mi.name, COUNT(mim.group_id) AS group_count
-- FROM menu_items mi LEFT JOIN menu_item_modifier_groups mim ON mim.menu_item_id = mi.id
-- WHERE mi.store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9' AND mi.is_available = true
-- GROUP BY mi.name ORDER BY group_count DESC, mi.name;
