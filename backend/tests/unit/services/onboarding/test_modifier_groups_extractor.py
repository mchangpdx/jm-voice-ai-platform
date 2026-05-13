"""Tests for size modifier group extraction.

Anchors the JM Pizza pattern (14"/18" → median delta $8) and verifies
outlier protection (one mispriced pizza doesn't move the group default).
(JM Pizza 14"/18" pattern + outlier 보호 검증)
"""
from __future__ import annotations

from app.services.onboarding.modifier_groups_extractor import (
    _option_id,
    export_modifier_groups_yaml,
    extract_size_modifier_group,
)
from app.services.onboarding.schema import NormalizedMenuItem


def _ni(name: str, sized_prices: list[tuple[str | None, float]],
        category: str | None = None) -> NormalizedMenuItem:
    variants = [{"size_hint": s, "price": p} for s, p in sized_prices]
    return {
        "name":       name,
        "category":   category,
        "variants":   variants,
        "confidence": 1.0,
    }


def test_option_id_compact_slug() -> None:
    assert _option_id("14 inch (Small)") == "14inch"
    assert _option_id("18 inch (Large)") == "18inch"
    assert _option_id("Medium") == "medium"


def test_no_multi_variant_items_returns_none() -> None:
    items = [_ni("Soda", [(None, 2.5)]), _ni("Brownie", [(None, 4.0)])]
    assert extract_size_modifier_group(items) is None


def test_jm_pizza_pattern_yields_size_group() -> None:
    # 10 pizzas, all 14"/18" with +$8 delta (matches live JM Pizza).
    pizzas = [
        ("Cheese Pizza",    18.0, 26.0),
        ("Pepperoni Pizza", 20.0, 28.0),
        ("White Pizza",     22.0, 30.0),
        ("Hawaiian",        22.0, 30.0),
        ("Veggie Supreme",  24.0, 32.0),
        ("Spicy Meat",      26.0, 34.0),
        ("Vegan Garden",    26.0, 34.0),
        ("Big Joe",         26.0, 34.0),
        ("Meat Lover",      28.0, 36.0),
        ("Sausage Pizza",   20.0, 28.0),
    ]
    items = [
        _ni(name, [("14 inch (Small)", small), ("18 inch (Large)", large)],
            category="Classic Pies")
        for name, small, large in pizzas
    ]
    group = extract_size_modifier_group(items)
    assert group is not None
    assert group["required"] is True
    assert group["min"] == 1 and group["max"] == 1
    assert group["applies_to_categories"] == ["classic_pies"]

    opts = group["options"]
    assert [o["id"] for o in opts] == ["14inch", "18inch"]
    assert opts[0]["default"] is True
    assert opts[1].get("default") is None or opts[1].get("default") is False
    assert opts[0]["price_delta"] == 0.0
    assert opts[1]["price_delta"] == 8.0


def test_median_resists_one_outlier_price() -> None:
    # 9 pizzas at +$8, 1 typo at +$80. Mean=$15.2, median=$8.
    # (mean=$15.2, median=$8 — outlier 1개 무시)
    items = [
        _ni(f"Pizza {i}",
            [("14 inch", 18.0), ("18 inch", 18.0 + (80.0 if i == 0 else 8.0))],
            category="pies")
        for i in range(10)
    ]
    group = extract_size_modifier_group(items)
    assert group is not None
    large = next(o for o in group["options"] if o["id"] == "18inch")
    assert large["price_delta"] == 8.0


def test_rare_size_below_threshold_excluded() -> None:
    # 10 items have "14 inch"/"18 inch"; only 1 has "24 inch".
    # threshold = 10 // 2 = 5 → 24 inch (count=1) excluded.
    # (희귀 size — 출현 빈도 threshold 미만은 제외)
    items = [
        _ni(f"Pie {i}", [("14 inch", 18.0), ("18 inch", 26.0)])
        for i in range(10)
    ]
    items.append(_ni("Family Pie",
                     [("14 inch", 20.0), ("18 inch", 28.0), ("24 inch", 40.0)]))
    group = extract_size_modifier_group(items)
    assert group is not None
    assert {o["id"] for o in group["options"]} == {"14inch", "18inch"}


def test_top_level_wrapper_returns_groups_dict() -> None:
    items = [_ni("Soda", [(None, 2.5)])]
    yaml = export_modifier_groups_yaml(items)
    assert yaml == {"groups": {}}


def test_applies_to_categories_deduped_and_sorted() -> None:
    items = [
        _ni("A", [("S", 10.0), ("L", 14.0)], category="Salads"),
        _ni("B", [("S", 12.0), ("L", 16.0)], category="Classic Pies"),
        _ni("C", [("S", 11.0), ("L", 15.0)], category="Salads"),
    ]
    group = extract_size_modifier_group(items)
    assert group is not None
    assert group["applies_to_categories"] == ["classic_pies", "salads"]
