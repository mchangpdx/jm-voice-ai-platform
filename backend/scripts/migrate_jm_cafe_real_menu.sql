-- Phase 6 prep — JM Cafe real menu (replaces 12 임시 items)
-- (2026-05-07 — JM Cafe 임시 메뉴를 실제 PDX fast-casual 카페 메뉴 25개로 교체)
--
-- Source: docs/strategic-research/2026-05-07_onboarding-automation/01_jm_cafe_menu_redesign.md
-- (확장: 18 → 25 items per user request "10-30개")
--
-- ⚠️ APPLIED ALREADY via Python REST API (2026-05-07). DO NOT re-run.
--    Result: 25 new items + Reservation (preserved) = 26 active items.
--    Re-running would create duplicates (variant_id auto-generated each call).
--
-- Strategy (for reference / future template re-use):
--   1. Soft-delete 12 existing items (is_available=false). pos_item_id preserved
--      so a Loyverse webhook re-sync can reactivate if the operator decides.
--   2. INSERT 25 new items with pos_item_id=NULL (manual seed, immune to next sync).
--   3. UPDATE stores.menu_cache so the Voice system prompt sees the new menu.
--
-- Safety: 'Reservation' item kept active (system meaning, not menu).
--
-- Schema note: allergens + dietary_tags are jsonb columns. SQL Editor requires
-- jsonb literal format `'["a","b"]'::jsonb`, NOT TEXT[] `'{a,b}'`. The Python
-- REST API auto-handles both (Python list → jsonb).

-- ── Step 0: Backup current menu_items (audit trail) ──────────────────────────

CREATE TABLE IF NOT EXISTS menu_items_backup_20260507 AS
SELECT * FROM menu_items
WHERE store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9';

-- ── Step 1: Soft-delete 11 임시 items (Reservation 보존) ─────────────────────

UPDATE menu_items
SET is_available = false,
    updated_at   = NOW()
WHERE store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9'
  AND name IN (
    'Cheese Pizza', 'Mozzarella Pizza', 'Pepperoni Pizza',  -- 카페 아님
    'Garlic Bread', 'Strawberry Cake',                       -- 카페 아님
    'Donuts', 'Chocolate Cake',                              -- 신규 set으로 교체
    'Americano', 'Cafe Latte', 'Croissant', 'Flat White'    -- 신규 set으로 정확히 재작성
  );

-- 결과: Reservation만 active 유지. 나머지 11 items unavailable.

-- ── Step 2: INSERT 25 신규 items ─────────────────────────────────────────────

-- jsonb-compatible array literals: '[]'::jsonb (empty) / '["a","b"]'::jsonb
-- (allergens + dietary_tags are jsonb columns, not TEXT[])
INSERT INTO menu_items
    (store_id, name, price, category, allergens, dietary_tags, is_available, stock_quantity, pos_item_id, variant_id)
VALUES
    -- ☕ Espresso Drinks (8) — base price = 12oz Small
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Drip Coffee',          3.25, 'Espresso',     '[]'::jsonb,                                            '["vegan","vegetarian","gluten_free","dairy_free","nut_free"]'::jsonb, true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Americano',            3.75, 'Espresso',     '[]'::jsonb,                                            '["vegan","vegetarian","gluten_free","dairy_free","nut_free"]'::jsonb, true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Espresso',             3.25, 'Espresso',     '[]'::jsonb,                                            '["vegan","vegetarian","gluten_free","dairy_free","nut_free"]'::jsonb, true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Macchiato',            4.25, 'Espresso',     '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cappuccino',           5.00, 'Espresso',     '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cafe Latte',           5.50, 'Espresso',     '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Mocha',                5.75, 'Espresso',     '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Flat White',           5.50, 'Espresso',     '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),

    -- 🍵 Non-Espresso Drinks (5)
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cold Brew',            5.00, 'Non-Espresso', '[]'::jsonb,                                            '["vegan","vegetarian","gluten_free","dairy_free","nut_free"]'::jsonb, true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Iced Tea',             3.75, 'Non-Espresso', '[]'::jsonb,                                            '["vegan","vegetarian","gluten_free","dairy_free","nut_free"]'::jsonb, true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Matcha Latte',         5.75, 'Non-Espresso', '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Chai Latte',           5.50, 'Non-Espresso', '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Hot Chocolate',        4.75, 'Non-Espresso', '["dairy"]'::jsonb,                                     '["vegetarian","gluten_free","nut_free"]'::jsonb,                       true, 100, NULL, gen_random_uuid()),

    -- 🥐 Pastries (6)
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Croissant',            4.50, 'Pastry',       '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 50,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Almond Croissant',     5.50, 'Pastry',       '["gluten","wheat","dairy","egg","nuts"]'::jsonb,       '["vegetarian"]'::jsonb,                                                true, 30,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Pain au Chocolat',     5.00, 'Pastry',       '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 30,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Blueberry Muffin',     4.25, 'Pastry',       '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 40,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cinnamon Roll',        4.75, 'Pastry',       '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 30,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Plain Bagel + Cream Cheese', 5.00, 'Pastry', '["gluten","wheat","dairy"]'::jsonb,                    '["vegetarian","nut_free"]'::jsonb,                                     true, 40,  NULL, gen_random_uuid()),

    -- 🥪 Food (4)
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Avocado Toast',        9.50, 'Food',         '["gluten","wheat"]'::jsonb,                            '["vegan","vegetarian","nut_free","dairy_free"]'::jsonb,                true, 25,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Breakfast Sandwich',   8.50, 'Food',         '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 25,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Yogurt Parfait',       6.75, 'Food',         '["dairy","nuts"]'::jsonb,                              '["vegetarian","gluten_free"]'::jsonb,                                  true, 20,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Quiche Lorraine',      7.50, 'Food',         '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 15,  NULL, gen_random_uuid()),

    -- 🍪 Desserts (2)
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Chocolate Chip Cookie',3.50, 'Dessert',      '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 60,  NULL, gen_random_uuid()),
    ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Brownie',              4.00, 'Dessert',      '["gluten","wheat","dairy","egg"]'::jsonb,              '["vegetarian","nut_free"]'::jsonb,                                     true, 40,  NULL, gen_random_uuid());

-- ── Step 3: UPDATE stores.menu_cache (Voice system prompt inject) ────────────

UPDATE stores
SET menu_cache = E'Drip Coffee - $3.25\nAmericano - $3.75\nEspresso - $3.25\nMacchiato - $4.25\nCappuccino - $5.00\nCafe Latte - $5.50\nMocha - $5.75\nFlat White - $5.50\nCold Brew - $5.00\nIced Tea - $3.75\nMatcha Latte - $5.75\nChai Latte - $5.50\nHot Chocolate - $4.75\nCroissant - $4.50\nAlmond Croissant - $5.50\nPain au Chocolat - $5.00\nBlueberry Muffin - $4.25\nCinnamon Roll - $4.75\nPlain Bagel + Cream Cheese - $5.00\nAvocado Toast - $9.50\nBreakfast Sandwich - $8.50\nYogurt Parfait - $6.75\nQuiche Lorraine - $7.50\nChocolate Chip Cookie - $3.50\nBrownie - $4.00'
WHERE id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9';

-- ── Step 4: Verify ────────────────────────────────────────────────────────────

-- SELECT name, price, category, is_available, allergens
-- FROM menu_items
-- WHERE store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9'
--   AND is_available = true
-- ORDER BY category, name;

-- SELECT length(menu_cache) FROM stores WHERE id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9';
