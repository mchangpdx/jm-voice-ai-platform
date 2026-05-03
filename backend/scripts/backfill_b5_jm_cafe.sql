-- Phase 2-C.B5 — Allergen / dietary backfill for JM Cafe (operator-curated)
-- (Phase 2-C.B5 — JM Cafe 메뉴 11개 allergen/dietary 수동 백필)
--
-- Spec: backend/docs/specs/B5_allergen_qa.md §3 / Decision #3 (operator-curated only)
-- Source: 2026-05-02 menu_items snapshot (12 rows, 'Reservation' excluded)
-- Allergen scope: FDA top-9 (dairy, gluten, nuts, soy, shellfish, egg, fish, sesame).
-- Dietary scope: vegan, vegetarian, gluten_free, dairy_free, nut_free, kosher, halal.
-- Cross-contamination NOT modeled in v1 (Tier 3 EpiPen handoff covers severe cases).
--
-- Update by id (deterministic — fuzzy name matching avoided here).

-- Americano: espresso + water. No allergens.
update menu_items
   set allergens    = '[]'::jsonb,
       dietary_tags = '["vegan","vegetarian","gluten_free","dairy_free","nut_free","kosher","halal"]'::jsonb
 where id = 1
   and name = 'Americano';

-- Cafe Latte: espresso + dairy milk.
update menu_items
   set allergens    = '["dairy"]'::jsonb,
       dietary_tags = '["vegetarian","gluten_free","nut_free"]'::jsonb
 where name = 'Cafe Latte';

-- Cheese Pizza: wheat dough + cheese.
update menu_items
   set allergens    = '["gluten","dairy"]'::jsonb,
       dietary_tags = '["vegetarian","nut_free"]'::jsonb
 where name = 'Cheese Pizza';

-- Chocolate Cake: flour + butter/milk + egg.
update menu_items
   set allergens    = '["gluten","dairy","egg"]'::jsonb,
       dietary_tags = '["vegetarian","nut_free"]'::jsonb
 where name = 'Chocolate Cake';

-- Croissant: laminated wheat dough + butter.
update menu_items
   set allergens    = '["gluten","dairy"]'::jsonb,
       dietary_tags = '["vegetarian","nut_free"]'::jsonb
 where name = 'Croissant';

-- Donuts: INTENTIONALLY LEFT EMPTY for `allergen_unknown` live validation.
-- (Donuts: allergen_unknown 검증용으로 비워둠 — default '[]' 유지)
-- Operator backfill TBD; bot must answer "I don't have allergen info on hand"
-- and offer manager transfer (HonestUnknown invariant I1).

-- Flat White: INTENTIONALLY LEFT EMPTY for `allergen_unknown` live validation.
-- (Flat White: allergen_unknown 검증용으로 비워둠 — default '[]' 유지)
-- Same rationale as Donuts above. Pair with Cafe Latte (curated dairy)
-- to demonstrate operator-curated vs unknown side-by-side in one call.

-- Garlic Bread: bread + butter.
update menu_items
   set allergens    = '["gluten","dairy"]'::jsonb,
       dietary_tags = '["vegetarian","nut_free"]'::jsonb
 where name = 'Garlic Bread';

-- Mozzarella Pizza: wheat dough + mozzarella cheese.
update menu_items
   set allergens    = '["gluten","dairy"]'::jsonb,
       dietary_tags = '["vegetarian","nut_free"]'::jsonb
 where name = 'Mozzarella Pizza';

-- Pepperoni Pizza: wheat dough + cheese + cured pork (NOT vegetarian, NOT halal/kosher).
update menu_items
   set allergens    = '["gluten","dairy"]'::jsonb,
       dietary_tags = '["nut_free"]'::jsonb
 where name = 'Pepperoni Pizza';

-- Strawberry Cake: flour + butter/milk + egg.
update menu_items
   set allergens    = '["gluten","dairy","egg"]'::jsonb,
       dietary_tags = '["vegetarian","nut_free"]'::jsonb
 where name = 'Strawberry Cake';

-- 'Reservation' (id=8c1b858c…) is a B3/B4 placeholder, NOT a food item.
-- Intentionally left at default '[]' — customer never queries allergens for it.

-- Verify backfill (9 curated rows + 2 intentionally-empty rows = 11 total).
-- Donuts + Flat White MUST show allergens='[]' and dietary_tags='[]'.
select id, name, allergens, dietary_tags
  from menu_items
 where name in (
   'Americano','Cafe Latte','Cheese Pizza','Chocolate Cake','Croissant',
   'Donuts','Flat White','Garlic Bread','Mozzarella Pizza','Pepperoni Pizza',
   'Strawberry Cake'
 )
 order by name;
