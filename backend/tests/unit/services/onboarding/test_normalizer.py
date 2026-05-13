"""Regression tests for the variant normalizer.

Anchors the 34→24 fold observed against JM Pizza on 2026-05-12 so future
changes to the grouping key or variant ordering surface immediately.
(JM Pizza 라이브 데이터 기반 regression — 34 raw rows → 24 normalized)
"""
from __future__ import annotations

from app.services.onboarding.normalizer import normalize_items
from app.services.onboarding.schema import RawMenuItem


def _row(name: str, price: float, **kw) -> RawMenuItem:
    base: RawMenuItem = {"name": name, "price": price, "confidence": 1.0}
    base.update(kw)  # type: ignore[typeddict-item]
    return base


def test_folds_size_variants_under_one_item() -> None:
    rows = [
        _row("Cheese Pizza", 18.0, size_hint="14 inch (Small)", pos_item_id="P1"),
        _row("Cheese Pizza", 26.0, size_hint="18 inch (Large)", pos_item_id="P1"),
        _row("Soda",          2.5),
    ]
    items = normalize_items(rows)
    assert len(items) == 2
    pizza = next(i for i in items if i["name"] == "Cheese Pizza")
    assert len(pizza["variants"]) == 2
    assert pizza["variants"][0]["size_hint"] == "14 inch (Small)"
    assert pizza["variants"][1]["size_hint"] == "18 inch (Large)"
    soda = next(i for i in items if i["name"] == "Soda")
    assert len(soda["variants"]) == 1


def test_variants_are_ordered_by_price_ascending() -> None:
    rows = [
        _row("Big Joe", 34.0, size_hint="18 inch (Large)", pos_item_id="P2"),
        _row("Big Joe", 26.0, size_hint="14 inch (Small)", pos_item_id="P2"),
    ]
    [item] = normalize_items(rows)
    prices = [v["price"] for v in item["variants"]]
    assert prices == sorted(prices)
    assert prices[0] == 26.0


def test_same_name_different_pos_id_stays_separate() -> None:
    # Two stores with identically-named items must not cross-merge.
    # (이름 동일 + pos_item_id 다름 → 별도 item으로 유지)
    rows = [
        _row("Special", 10.0, pos_item_id="A"),
        _row("Special", 12.0, pos_item_id="B"),
    ]
    items = normalize_items(rows)
    assert len(items) == 2


def test_confidence_is_minimum_across_group() -> None:
    rows = [
        _row("Item", 5.0, pos_item_id="X", confidence=0.95),
        _row("Item", 7.0, pos_item_id="X", confidence=0.60),
    ]
    [item] = normalize_items(rows)
    assert item["confidence"] == 0.60


def test_empty_input_returns_empty_list() -> None:
    assert normalize_items([]) == []


def test_jm_pizza_live_data_folds_34_rows_to_24_items() -> None:
    """Regression anchor: JM Pizza Loyverse menu snapshot 2026-05-12.

    Names and variant counts taken from the live fetch result. If this
    breaks, either the JM Pizza menu was edited (update the fixture) or
    the normalizer is mis-grouping.
    (JM Pizza 라이브 fixture — 메뉴 변경 시 fixture 갱신, 그 외는 normalizer 버그)
    """
    # 10 pizzas × 2 sizes + 14 standalone = 34 rows → 24 items
    pizza_names = [
        "White Pizza", "Sausage Pizza", "Pepperoni Pizza", "Cheese Pizza",
        "Vegan Garden", "Veggie Supreme", "Hawaiian",
        "Spicy Meat & Veggie", "Meat Lover", "Big Joe",
    ]
    standalone_names = [
        "Soda", "Chocolate Chip Cookie", "Brownie", "Buffalo Wings",
        "Breadsticks", "Garlic Knots", "Caprese Salad", "House Salad",
        "Caesar Salad", "Gluten-Free Slice", "Vegan Slice",
        "Daily Special Slice", "Pepperoni Slice", "Cheese Slice",
    ]
    rows: list[RawMenuItem] = []
    for i, name in enumerate(pizza_names):
        rows.append(_row(name, 18.0, size_hint="14 inch (Small)", pos_item_id=f"P{i}"))
        rows.append(_row(name, 26.0, size_hint="18 inch (Large)", pos_item_id=f"P{i}"))
    for j, name in enumerate(standalone_names):
        rows.append(_row(name, 5.0, pos_item_id=f"S{j}"))

    items = normalize_items(rows)
    assert len(rows) == 34
    assert len(items) == 24
    multi_variant = [i for i in items if len(i["variants"]) > 1]
    assert len(multi_variant) == 10
