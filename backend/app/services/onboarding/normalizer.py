"""Phase 2 normalizer — folds same-name rows into items + variants.

Every source adapter emits a flat list of RawMenuItem. This module groups
rows that represent the same menu entry (same name + same POS item id)
and emits NormalizedMenuItem with the size tiers collected under
`variants`. Standalone items (no size variant) become single-variant
items so the wizard can render every row the same way.
(Phase 2 — 같은 메뉴의 size variant들을 1개 item으로 통합)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 2.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.services.onboarding.schema import (
    NormalizedMenuItem,
    NormalizedVariant,
    RawMenuItem,
)


def _group_key(item: RawMenuItem) -> tuple[str, str]:
    """Grouping key: (name, pos_item_id-or-blank).

    Same display name with different `pos_item_id` is rare but real
    (e.g. two stores merged into one tenant); keeping the POS id in the
    key prevents accidental cross-merge. Items without a POS id (manual
    entry, vision extraction) fall back to name-only grouping.
    (그룹화 키 — 같은 name + 같은 pos_item_id, POS id 없으면 name만)
    """
    return (item.get("name") or "", item.get("pos_item_id") or "")


def _variant_from_raw(raw: RawMenuItem) -> NormalizedVariant:
    """Project a raw row's variant-shaped fields into NormalizedVariant."""
    return {
        "size_hint":      raw.get("size_hint"),
        "price":          float(raw.get("price") or 0.0),
        "pos_variant_id": raw.get("pos_variant_id"),
        "sku":            raw.get("sku"),
        "stock_quantity": raw.get("stock_quantity"),
    }


def normalize_items(rows: Iterable[RawMenuItem]) -> list[NormalizedMenuItem]:
    """Fold rows sharing the same (name, pos_item_id) into one item.

    The first row in each group seeds the item-level fields (description,
    category, allergens). Confidence becomes the minimum across the group
    — if any source row was uncertain, the merged item inherits that
    uncertainty so the wizard flags it for operator review.
    Variants are ordered by price ascending — small/14" before large/18"
    — which is how operators read menu boards.
    (그룹의 첫 row → item-level 필드, confidence는 min, variants는 price 오름차순)
    """
    groups: dict[tuple[str, str], list[RawMenuItem]] = defaultdict(list)
    for r in rows:
        groups[_group_key(r)].append(r)

    out: list[NormalizedMenuItem] = []
    for (_, _), group in groups.items():
        head = group[0]
        variants = sorted(
            (_variant_from_raw(r) for r in group),
            key=lambda v: v.get("price") or 0.0,
        )
        out.append({
            "name":               head.get("name") or "",
            "category":           head.get("category"),
            "description":        head.get("description"),
            "pos_item_id":        head.get("pos_item_id"),
            "detected_allergens": head.get("detected_allergens"),
            "confidence":         min(
                (r.get("confidence") or 1.0) for r in group
            ),
            "variants":           variants,
        })
    return out
