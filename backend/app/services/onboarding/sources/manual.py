"""Manual entry source adapter — last-resort path.

Used when nothing else works (operator types items into a form in the
admin wizard). The router accepts the raw list as-is; we just stamp
`source="manual"` and `confidence=1.0` (the operator typed it).
(operator 직접 입력 — fallback path)
"""
from __future__ import annotations

from app.services.onboarding.schema import RawMenuExtraction, RawMenuItem


async def extract_from_manual(items: list[dict]) -> RawMenuExtraction:
    """Pass through operator-supplied items with confidence=1.0."""
    normalized: list[RawMenuItem] = []
    warnings: list[str] = []
    for row in items:
        name = (row.get("name") or "").strip()
        price = row.get("price")
        if not name or price is None:
            warnings.append(f"manual row missing name or price: {row!r}")
            continue
        normalized.append({
            "name":        name,
            "price":       float(price),
            "category":    row.get("category"),
            "description": row.get("description"),
            "size_hint":   row.get("size_hint"),
            "confidence":  1.0,
        })
    return {
        "source":             "manual",
        "items":              normalized,
        "detected_modifiers": [],
        "vertical_guess":     None,
        "warnings":           warnings,
    }
