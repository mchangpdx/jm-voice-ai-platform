"""Tests for keyword-based vertical inference.

The JM Pizza anchor case mirrors the live 2026-05-12 detection (44%
match share). The mixed-menu case asserts that a borderline menu falls
through to "general" instead of misclassifying.
(JM Pizza 라이브 결과 anchor + borderline menu → general fallback)
"""
from __future__ import annotations

from app.services.onboarding.schema import RawMenuItem
from app.services.onboarding.vertical_detector import detect_vertical


def _item(name: str) -> RawMenuItem:
    return {"name": name, "price": 1.0, "confidence": 1.0}


def test_empty_menu_returns_general_zero() -> None:
    assert detect_vertical([]) == ("general", 0.0)


def test_jm_pizza_live_menu_detects_pizza() -> None:
    names = [
        "White Pizza", "Sausage Pizza", "Pepperoni Pizza", "Cheese Pizza",
        "Vegan Garden", "Veggie Supreme", "Hawaiian",
        "Spicy Meat & Veggie", "Meat Lover", "Big Joe",
        "Pepperoni Slice", "Cheese Slice", "Gluten-Free Slice",
        "Vegan Slice", "Daily Special Slice",
        "Garlic Knots", "Breadsticks",
        "Caprese Salad", "House Salad", "Caesar Salad",
        "Buffalo Wings", "Soda", "Chocolate Chip Cookie", "Brownie",
    ]
    vertical, confidence = detect_vertical([_item(n) for n in names])
    assert vertical == "pizza"
    assert confidence > 0.30  # ~44% live; loose bound tolerates keyword tweaks


def test_cafe_menu_detects_cafe() -> None:
    names = [
        "Iced Latte", "Hot Latte", "Cappuccino", "Espresso Doppio",
        "Cold Brew", "Matcha Latte", "Americano", "Mocha",
        "Croissant", "Bagel",
    ]
    vertical, _ = detect_vertical([_item(n) for n in names])
    assert vertical == "cafe"


def test_kbbq_menu_detects_kbbq() -> None:
    names = [
        "Galbi Short Rib", "Bulgogi Beef", "Samgyeopsal Pork Belly",
        "Kimchi Stew", "Bibimbap", "Japchae", "Tteokbokki",
        "Banchan Set",
    ]
    vertical, _ = detect_vertical([_item(n) for n in names])
    assert vertical == "kbbq"


def test_below_confidence_floor_returns_general() -> None:
    # Only 1 of 10 items has a vertical token → 10% < 15% floor.
    # (10개 중 1개만 매칭 → confidence floor 미달, general로 fallback)
    names = [
        "Pizza Special",
        "Daily Soup", "Garden Salad", "Veggie Wrap", "Turkey Sandwich",
        "Mixed Greens", "Tomato Bisque", "Chicken Plate",
        "Beef Bowl", "Rice Dish",
    ]
    vertical, confidence = detect_vertical([_item(n) for n in names])
    assert vertical == "general"
    assert confidence < 0.15
