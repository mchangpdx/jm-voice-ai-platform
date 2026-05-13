"""Tests for menu.yaml exporter.

Locks in the shape the existing seeder (scripts/setup_jm_pizza.py) reads:
top-level vertical/default_lang/supported_langs/categories/items, and
each item has id (slug), en, category, base_price, base_allergens.
(seeder가 읽는 shape 고정 — slug 충돌, variant flatten, vertical defaults)
"""
from __future__ import annotations

from app.services.onboarding.menu_yaml_exporter import (
    _ensure_unique_slugs,
    _slugify,
    export_menu_yaml,
)
from app.services.onboarding.schema import NormalizedMenuItem


def _ni(name: str, prices: list[float], category: str | None = None, **kw) -> NormalizedMenuItem:
    variants = [{"size_hint": None, "price": p} for p in prices]
    item: NormalizedMenuItem = {
        "name":     name,
        "category": category,
        "variants": variants,
        "confidence": 1.0,
    }
    item.update(kw)  # type: ignore[typeddict-item]
    return item


def test_slugify_ascii_and_underscore() -> None:
    assert _slugify("Big Joe") == "big_joe"
    assert _slugify("Spicy! Pizza") == "spicy_pizza"
    assert _slugify("  ") == "item"


def test_ensure_unique_slugs_disambiguates_collisions() -> None:
    out = _ensure_unique_slugs(["a", "a", "b", "a"])
    assert out == ["a", "a_2", "b", "a_3"]


def test_base_price_is_min_variant_price() -> None:
    item = _ni("Cheese Pizza", [18.0, 26.0], category="Classic Pies")
    yaml = export_menu_yaml([item], vertical="pizza")
    assert yaml["items"][0]["base_price"] == 18.0
    # Multi-variant items keep `variants` so the modifier wirer sees sizes.
    assert "variants" in yaml["items"][0]
    assert len(yaml["items"][0]["variants"]) == 2


def test_single_variant_item_has_no_variants_key() -> None:
    item = _ni("Soda", [2.5], category="Drinks")
    yaml = export_menu_yaml([item], vertical="pizza")
    assert yaml["items"][0]["base_price"] == 2.5
    assert "variants" not in yaml["items"][0]


def test_categories_are_deduped_in_first_seen_order() -> None:
    items = [
        _ni("Cheese Pizza",     [18.0], category="Classic Pies"),
        _ni("Caesar Salad",     [11.0], category="Salads"),
        _ni("Pepperoni Pizza",  [20.0], category="Classic Pies"),  # same cat
    ]
    yaml = export_menu_yaml(items, vertical="pizza")
    cat_ids = [c["id"] for c in yaml["categories"]]
    assert cat_ids == ["classic_pies", "salads"]


def test_vertical_defaults_for_pizza_are_en_es() -> None:
    yaml = export_menu_yaml([_ni("Slice", [4.0])], vertical="pizza")
    assert yaml["default_lang"] == "en"
    assert yaml["supported_langs"] == ["en", "es"]


def test_vertical_defaults_for_cafe_are_five_languages() -> None:
    yaml = export_menu_yaml([_ni("Latte", [5.5])], vertical="cafe")
    assert yaml["supported_langs"] == ["en", "es", "ko", "ja", "zh"]


def test_unknown_vertical_falls_back_to_english_only() -> None:
    yaml = export_menu_yaml([_ni("Thing", [1.0])], vertical="some-new-vertical")
    assert yaml["supported_langs"] == ["en"]


def test_description_persists_as_notes_en() -> None:
    item = _ni("Big Joe", [26.0, 34.0], category="Signature Pies",
               description="Housemade meatballs, lemon ricotta, basil")
    yaml = export_menu_yaml([item], vertical="pizza")
    assert yaml["items"][0]["notes_en"].startswith("Housemade meatballs")


def test_collision_disambiguation_end_to_end() -> None:
    yaml = export_menu_yaml([
        _ni("Spicy Pizza",  [22.0]),
        _ni("Spicy! Pizza", [22.0]),
    ], vertical="pizza")
    ids = [it["id"] for it in yaml["items"]]
    assert ids == ["spicy_pizza", "spicy_pizza_2"]
