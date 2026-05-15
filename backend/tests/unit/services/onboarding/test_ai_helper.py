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
    infer_dietary_tags,
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


# ── dietary inference ───────────────────────────────────────────────────────


def test_dietary_cafe_latte_excludes_dairy_free() -> None:
    """Latte has dairy → reverse rule `if_absent: [dairy]` must not fire."""
    tags = infer_dietary_tags(
        name="Latte", description=None, allergens=["dairy"], vertical="cafe",
    )
    assert "dairy_free" not in tags


def test_dietary_cafe_iced_tea_gets_dairy_and_nut_free() -> None:
    """Plain iced tea has no allergens → dairy_free + nut_free fire (≥0.90)."""
    tags = infer_dietary_tags(
        name="Iced Tea", description=None, allergens=[], vertical="cafe",
    )
    assert "dairy_free" in tags
    assert "nut_free" in tags


def test_dietary_cafe_low_confidence_filtered() -> None:
    """cafe `vegan: 0.50` and `gluten_free: 0.85` are below 0.90 → not auto."""
    tags = infer_dietary_tags(
        name="Iced Tea", description=None, allergens=[], vertical="cafe",
    )
    assert "vegan" not in tags
    assert "gluten_free" not in tags


def test_dietary_pizza_keyword_vegan() -> None:
    """Forward pattern: 'vegan' keyword in name → vegan tag (conf default 1.0)."""
    tags = infer_dietary_tags(
        name="Vegan Garden Pizza", description=None,
        allergens=["gluten"], vertical="pizza",
    )
    assert "vegan" in tags


def test_dietary_mexican_beans_vegetarian_blocked_by_low_conf() -> None:
    """Mexican `vegetarian: 0.50` rule is below cutoff — should not auto-apply."""
    tags = infer_dietary_tags(
        name="Refried Beans", description=None,
        allergens=[], vertical="mexican",
    )
    assert "vegetarian" not in tags
    # But high-confidence absence rules still fire.
    assert "nut_free" in tags


def test_dietary_unknown_vertical_returns_empty() -> None:
    assert infer_dietary_tags("Cheese Pizza", None, [], "atlantis") == []


def test_dietary_empty_name_returns_empty() -> None:
    assert infer_dietary_tags("", None, [], "cafe") == []


def test_dietary_kbbq_forward_chicken_tag() -> None:
    """kbbq `chicken` keyword adds `poultry` (conf 0.95 ≥ 0.90)."""
    tags = infer_dietary_tags(
        name="Chicken Bulgogi", description=None,
        allergens=["beef"], vertical="kbbq",
    )
    assert "poultry" in tags
