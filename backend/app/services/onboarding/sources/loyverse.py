"""Loyverse source adapter — fastest onboarding path (scenario B).

When the operator already runs Loyverse, their menu is the source of truth.
We re-use `LoyversePOSAdapter.fetch_menu` (the same call the live voice
agent uses) and reshape its output into `RawMenuExtraction`. Confidence
is pinned to 1.0 because Loyverse returns structured data, not OCR.
Allergen tags are intentionally left empty here — Phase 2's ai_helper
infers them from item names. The vertical_guess is also deferred to
Phase 2's vertical_detector so this adapter stays POS-only.
(이미 Loyverse 쓰는 매장 — 5분 onboarding path. confidence=1.0 결정적)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 3 scenario B.
"""
from __future__ import annotations

from app.services.bridge.pos.loyverse import LoyversePOSAdapter
from app.services.onboarding.schema import RawMenuExtraction, RawMenuItem


async def extract_from_loyverse(api_key: str) -> RawMenuExtraction:
    """Pull the live menu from Loyverse and reshape for the wizard.

    Each Loyverse variant becomes one `RawMenuItem` so the Phase 2
    normalizer can decide whether to merge size variants under a single
    base item. Variants without a price (rare — usually staff scratch
    entries) are skipped with a warning. Empty result is returned as
    an empty items list (not an error) so the wizard can show
    "no items found" rather than failing the whole flow.
    (Loyverse variant 1개당 RawMenuItem 1개 — Phase 2가 variant merge 결정)
    """
    adapter = LoyversePOSAdapter(api_key=api_key)
    raw = await adapter.fetch_menu()

    items: list[RawMenuItem] = []
    warnings: list[str] = []
    for it in raw:
        base_name = it.get("name") or ""
        if not base_name:
            warnings.append(f"unnamed item pos_item_id={it.get('pos_item_id')}")
            continue
        pos_item_id = it.get("pos_item_id")
        description = it.get("description")
        for v in it.get("variants", []) or []:
            price = v.get("price")
            if price is None:
                warnings.append(f"missing price item={base_name} sku={v.get('sku')}")
                continue
            items.append({
                "name":           base_name,
                "price":          float(price),
                "category":       None,
                "description":    description,
                "size_hint":      v.get("option_value"),
                "pos_item_id":    pos_item_id,
                "pos_variant_id": v.get("variant_id"),
                "sku":            v.get("sku"),
                "stock_quantity": v.get("stock_quantity"),
                "confidence":     1.0,
            })

    return {
        "source":             "loyverse",
        "items":              items,
        "detected_modifiers": [],
        "vertical_guess":     None,
        "warnings":           warnings,
    }
