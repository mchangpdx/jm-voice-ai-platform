"""Tests for allergen auto-inference.

The yaml templates are the source of truth; these tests anchor a few
high-signal cases (FDA-9 patterns + pizza-specific pork rule) and the
behavior of the per-item allergen guess (preserves existing tags,
fills only when empty).
(yaml이 source of truth — 핵심 케이스만 anchor, override behavior 검증)
"""
from __future__ import annotations

from app.services.onboarding.ai_helper import (
    apply_allergen_inference_to_normalized,
    infer_allergens,
)
from app.services.onboarding.schema import NormalizedMenuItem


def test_dairy_from_cheese_in_name() -> None:
    assert "dairy" in infer_allergens("Cheese Pizza", None, "pizza")


def test_gluten_from_crust_descriptor() -> None:
    assert "gluten" in infer_allergens("Garlic Knots", None, "pizza")


def test_pizza_pork_pattern_on_pepperoni() -> None:
    """Pizza vertical has a custom (non-FDA-9) pork rule."""
    out = infer_allergens("Pepperoni Slice", None, "pizza")
    assert "pork" in out


def test_multiple_allergens_combined_from_description() -> None:
    out = infer_allergens(
        "Big Joe",
        "Housemade meatballs, lemon ricotta, basil, garlic",
        "pizza",
    )
    # ricotta → dairy, meatball binder → egg/gluten
    assert {"dairy", "egg", "gluten"}.issubset(set(out))


def test_unknown_vertical_returns_empty_list() -> None:
    assert infer_allergens("Cheese Pizza", None, "atlantis") == []


def test_empty_name_returns_empty_list() -> None:
    assert infer_allergens("", None, "pizza") == []


def test_apply_preserves_existing_tags() -> None:
    items: list[NormalizedMenuItem] = [
        {"name": "Cheese Pizza", "detected_allergens": ["dairy", "gluten"],
         "variants": [{"price": 18.0}], "confidence": 1.0},
        {"name": "Caesar Salad", "detected_allergens": None,
         "variants": [{"price": 11.0}], "confidence": 1.0,
         "description": "Romaine, parmesan, croutons, anchovy"},
    ]
    out = apply_allergen_inference_to_normalized(items, vertical="pizza")
    # First item kept as-is (already had tags).
    assert out[0]["detected_allergens"] == ["dairy", "gluten"]
    # Second item filled — must include dairy + fish + gluten.
    salad_allergens = set(out[1]["detected_allergens"] or [])
    assert {"dairy", "fish", "gluten"}.issubset(salad_allergens)


def test_apply_does_not_mutate_input_list() -> None:
    items: list[NormalizedMenuItem] = [
        {"name": "Latte", "variants": [{"price": 5.5}], "confidence": 1.0},
    ]
    apply_allergen_inference_to_normalized(items, vertical="cafe")
    # Original input untouched — detected_allergens still absent.
    assert items[0].get("detected_allergens") is None
