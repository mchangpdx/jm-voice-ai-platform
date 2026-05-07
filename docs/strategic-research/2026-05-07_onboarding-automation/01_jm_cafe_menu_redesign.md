# JM Cafe Menu Redesign — Real Menu + Modifiers + Multilingual

**Date**: 2026-05-07
**Source**: PDX fast-casual cafe market research + FDA-9 allergen alignment
**Replaces**: 12 임시 메뉴 (Cheese Pizza / Mozzarella Pizza / Pepperoni Pizza / Garlic Bread / Strawberry Cake 등 카페답지 않은 항목)

---

## 1. 신규 메뉴 18개 — 카테고리별

### ☕ Espresso Drinks (8 items)

| # | EN name | ES (스페인어) | KO (한국어) | JA (일본어) | ZH (중국어) | Small (12oz) | Med (16oz) | Large (20oz) | Allergens (base) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Drip Coffee | Café | 드립 커피 | ドリップコーヒー | 滴漏咖啡 | $3.25 | $3.75 | $4.25 | — |
| 2 | Americano | Americano | 아메리카노 | アメリカーノ | 美式咖啡 | $3.75 | $4.25 | $4.75 | — |
| 3 | Espresso (single) | Espresso | 에스프레소 | エスプレッソ | 浓缩咖啡 | $3.25 | — | — | — |
| 4 | Cappuccino | Capuchino | 카푸치노 | カプチーノ | 卡布奇诺 | $5.00 | $5.50 | — | dairy |
| 5 | Cafe Latte | Café con leche | 카페 라떼 | カフェラテ | 拿铁 | $5.50 | $6.00 | $6.50 | dairy |
| 6 | Mocha | Moca | 모카 | モカ | 摩卡 | $5.75 | $6.25 | $6.75 | dairy |
| 7 | Flat White | Flat White | 플랫 화이트 | フラットホワイト | 馥芮白 | $5.50 | $6.00 | — | dairy |
| 8 | Cold Brew | Café frío | 콜드 브루 | コールドブリュー | 冷萃咖啡 | $5.00 | $5.50 | $6.00 | — |

### 🍵 Non-Espresso (3 items)

| # | EN | ES | KO | JA | ZH | Small | Med | Large | Allergens |
|---|---|---|---|---|---|---|---|---|---|
| 9 | Matcha Latte | Té matcha latte | 말차 라떼 | 抹茶ラテ | 抹茶拿铁 | $5.75 | $6.25 | $6.75 | dairy |
| 10 | Chai Latte | Té chai latte | 차이 라떼 | チャイラテ | 印度奶茶 | $5.50 | $6.00 | $6.50 | dairy |
| 11 | Hot Chocolate | Chocolate caliente | 핫 초콜릿 | ホットチョコレート | 热巧克力 | $4.75 | $5.25 | $5.75 | dairy |

### 🥐 Pastries (5 items)

| # | EN | ES | KO | JA | ZH | Price | Allergens (base) |
|---|---|---|---|---|---|---|---|
| 12 | Croissant | Croissant / Cuernito | 크루아상 | クロワッサン | 牛角面包 | $4.50 | gluten, wheat, dairy, egg |
| 13 | Almond Croissant | Croissant de almendra | 아몬드 크루아상 | アーモンドクロワッサン | 杏仁牛角面包 | $5.50 | gluten, wheat, dairy, egg, **nuts** |
| 14 | Blueberry Muffin | Muffin de arándano | 블루베리 머핀 | ブルーベリーマフィン | 蓝莓松饼 | $4.25 | gluten, wheat, dairy, egg |
| 15 | Cinnamon Roll | Rollo de canela | 시나몬 롤 | シナモンロール | 肉桂卷 | $4.75 | gluten, wheat, dairy, egg |
| 16 | Plain Bagel + Cream Cheese | Bagel con queso crema | 베이글 + 크림치즈 | プレーンベーグル + クリームチーズ | 原味百吉饼 + 奶油芝士 | $5.00 | gluten, wheat, dairy |

### 🥪 Food (2 items)

| # | EN | ES | KO | JA | ZH | Price | Allergens (base) |
|---|---|---|---|---|---|---|---|
| 17 | Avocado Toast | Tostada de aguacate | 아보카도 토스트 | アボカドトースト | 牛油果吐司 | $9.50 | gluten, wheat |
| 18 | Breakfast Sandwich | Sándwich de desayuno | 브렉퍼스트 샌드위치 | ブレックファストサンド | 早餐三明治 | $8.50 | gluten, wheat, dairy, egg |

---

## 2. Modifier Groups (8개) — Cafe Vertical

### Group 1: Size (Required, exactly 1)

| Option | Price delta | Applies to |
|---|---|---|
| Small (12oz) | base | All drinks |
| Medium (16oz) | +$0.50 | Most drinks (Espresso/Cappuccino exclude Large) |
| Large (20oz) | +$1.00 | Drinks listed above |

### Group 2: Temperature (Required, exactly 1)

| Option | Price delta | Allergen impact |
|---|---|---|
| Hot | base | — |
| Iced | base | — |
| Blended (Frappé) | +$0.75 | dairy added (cream base) |

### Group 3: Milk (Required for milk drinks, exactly 1)

| Option | Price delta | Allergen 변화 |
|---|---|---|
| Whole milk | base | dairy |
| 2% milk | base | dairy |
| Skim / Nonfat | base | dairy |
| Oat milk | +$0.75 | **dairy 제거 + gluten + wheat 추가** ⚠️ |
| Almond milk | +$0.75 | **dairy 제거 + nuts 추가** ⚠️ |
| Soy milk | +$0.75 | **dairy 제거 + soy 추가** ⚠️ |
| Coconut milk | +$0.75 | **dairy 제거** |

> **알러젠 dynamic 계산 핵심**: Milk modifier 선택이 메뉴의 알러젠 set을 변경. allergen_lookup tool은 base + modifier 합산해야 정확한 응답 가능 (Phase 7+ 구현 작업).

### Group 4: Espresso Shots (Optional, 0-2 extra)

| Option | Price delta |
|---|---|
| +1 shot | +$1.00 |
| +2 shots | +$2.00 |

### Group 5: Sweetener / Syrup (Optional, 0-3 multi)

| Option | Price delta | Allergen 영향 |
|---|---|---|
| Vanilla | +$0.75 | — |
| Hazelnut | +$0.75 | **nuts 추가** ⚠️ |
| Caramel | +$0.75 | dairy 추가 (caramel sauce) |
| Lavender | +$0.75 | — |
| Sugar-free Vanilla | +$0.75 | — |
| Brown sugar | +$0.50 | — |
| Honey | +$0.50 | — |

### Group 6: Strength (Optional, exactly 1)

| Option | Price delta |
|---|---|
| Regular | base |
| Decaf | base |
| Half-caf | base |

### Group 7: Foam / Texture (Optional, exactly 1)

| Option | Price delta |
|---|---|
| Regular foam | base |
| Extra foam (Dry) | base |
| Light foam (Wet) | base |
| No foam | base |

### Group 8: Whipped Cream (Optional, yes/no)

| Option | Price delta | Allergen 영향 |
|---|---|---|
| With whip | base | dairy 추가 |
| No whip | base | — |

---

## 3. Modifier × Menu Compatibility Matrix

| 메뉴 | Size | Temp | Milk | Shots | Syrup | Strength | Foam | Whip |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Drip Coffee | ✓ | ✓ | (creamer optional) | — | ✓ | ✓ | — | — |
| Americano | ✓ | ✓ | (creamer optional) | ✓ | ✓ | ✓ | — | — |
| Espresso | ✓ (single only) | hot only | — | — | — | ✓ | — | — |
| Cappuccino | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Cafe Latte | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Mocha | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Flat White | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Cold Brew | ✓ | iced/blend only | (creamer optional) | ✓ | ✓ | ✓ | — | — |
| Matcha Latte | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| Chai Latte | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| Hot Chocolate | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| Pastries | — | — | — | — | — | — | — | — |
| Food | — | — | — | — | — | — | — | — |

---

## 4. SQL Migration Script (적용 시)

```sql
-- backend/scripts/migrate_jm_cafe_real_menu.sql
-- Phase 6 prep — replace temporary menu with real PDX cafe menu

-- 0. Backup current menu_items (safety)
CREATE TABLE IF NOT EXISTS menu_items_backup_20260507 AS
SELECT * FROM menu_items WHERE store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9';

-- 1. Soft-delete temporary items (keep audit trail)
UPDATE menu_items
SET is_active = false, deleted_at = NOW()
WHERE store_id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9'
  AND name IN ('Cheese Pizza','Mozzarella Pizza','Pepperoni Pizza',
               'Garlic Bread','Strawberry Cake','Donuts','Reservation');

-- 2. Insert / upsert real menu (18 items, base price = small/12oz)
-- NOTE: variant_id structure assumed — adjust per Loyverse sync schema
INSERT INTO menu_items (store_id, name, price, allergens, dietary_tags, is_active)
VALUES
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Drip Coffee',        3.25, '{}',                      '{vegan,vegetarian,gluten_free,dairy_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Americano',          3.75, '{}',                      '{vegan,vegetarian,gluten_free,dairy_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Espresso',           3.25, '{}',                      '{vegan,vegetarian,gluten_free,dairy_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cappuccino',         5.00, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cafe Latte',         5.50, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Mocha',              5.75, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Flat White',         5.50, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cold Brew',          5.00, '{}',                      '{vegan,vegetarian,gluten_free,dairy_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Matcha Latte',       5.75, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Chai Latte',         5.50, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Hot Chocolate',      4.75, '{dairy}',                 '{vegetarian,gluten_free,nut_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Croissant',          4.50, '{gluten,wheat,dairy,egg}','{vegetarian,nut_free}',             true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Almond Croissant',   5.50, '{gluten,wheat,dairy,egg,nuts}', '{vegetarian}',                true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Blueberry Muffin',   4.25, '{gluten,wheat,dairy,egg}','{vegetarian,nut_free}',             true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Cinnamon Roll',      4.75, '{gluten,wheat,dairy,egg}','{vegetarian,nut_free}',             true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Plain Bagel + Cream Cheese', 5.00, '{gluten,wheat,dairy}', '{vegetarian,nut_free}',        true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Avocado Toast',      9.50, '{gluten,wheat}',          '{vegan,vegetarian,nut_free,dairy_free}', true),
  ('7c425fcb-91c7-4eb7-982a-591c094ba9c9', 'Breakfast Sandwich', 8.50, '{gluten,wheat,dairy,egg}','{vegetarian,nut_free}',             true);

-- 3. Modifier groups + options (NEW tables — schema design Phase 7-A)
-- See 02_vertical_templates_multilingual.md §5 for schema spec.
-- Defer to JM BBQ adapter implementation phase (template-driven).

-- 4. Multilingual aliases (NEW table)
-- CREATE TABLE menu_item_aliases (
--     menu_item_id INT REFERENCES menu_items(id),
--     lang_code VARCHAR(2),  -- 'en','es','ko','ja','zh'
--     alias TEXT NOT NULL,
--     PRIMARY KEY (menu_item_id, lang_code, alias)
-- );
-- Defer to Phase 7-A.
```

---

## 5. 라이브 검증 시나리오 (적용 후)

**시나리오 1 — 기본 영어**:
- "I'd like a large iced oat latte with vanilla, decaf"
- 기대: $5.50 + $1.00 (large) + $0.75 (oat) + $0.75 (vanilla) = $8.00
- 알러젠: dairy 제거 + gluten/wheat 추가 (oat milk)

**시나리오 2 — 알러젠 wheat (oat milk 케이스)**:
- "Does the oat milk latte have wheat?"
- 기대: tool returns allergen_present (oat = wheat-derived)
- 봇: "Yes, oat milk contains wheat."

**시나리오 3 — Almond Croissant nuts**:
- "Does the almond croissant have tree nuts?"
- 기대: allergen_present (nuts in base)
- 봇: "Yes, almond croissant contains nuts."

**시나리오 4 — 한국어**:
- "아몬드 크루아상에 견과류 들어있나요?"
- 기대: 봇이 한국어 응답 + 정확한 알러젠 정보

**시나리오 5 — Modifier 알러젠 dynamic**:
- "I have a soy allergy. Can I get a latte with soy milk?"
- 기대: 봇이 명시적 경고 — "Soy milk contains soy. Want oat or almond instead?"
- (이건 Phase 7+ 작업 — 현재 V0+ alert는 keyword 기반)

---

## 6. ROI / Production-Readiness 평가 (10점 만점)

| 항목 | 임시 메뉴 | 실제 메뉴 | 비고 |
|---|:---:|:---:|---|
| 매장 운영자 신뢰성 | 3 | **9** | 실제 운영 가능한 메뉴 |
| 알러젠 정확도 | 5 | **9** | FDA-9 align + Modifier 영향 식별 |
| Maple wedge 검증 (다국어) | 2 | **9** | 5 개 언어 alias |
| 라이브 데모 가치 | 4 | **9** | "wheat 알러지인데 oat milk 안전?" 같은 정밀 시나리오 |
| Modifier 검증 base | 3 | **8** | 8 group 정의됨 (Phase 7-A 구현 대기) |
| **합계 / 50** | **17** | **44** | |

→ 실제 메뉴로 교체는 production-readiness 27점 향상.
