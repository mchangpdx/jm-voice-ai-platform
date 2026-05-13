"""Normalized output shape every input source produces.

Every adapter in `sources/` returns a `RawMenuExtraction`. Phase 2's
normalizer takes this shape and emits `menu.yaml` + `modifier_groups.yaml`,
which feeds the DB seeder and the POS pusher.
(모든 source adapter는 RawMenuExtraction을 반환 — Phase 2 normalizer 입력)
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict


SourceType = Literal["loyverse", "url", "pdf", "image", "csv", "manual"]


class RawMenuItem(TypedDict, total=False):
    """One menu entry as discovered by a source adapter.

    `confidence` is 0.0-1.0 — vision/crawl adapters set it from the
    extractor's signal; deterministic adapters (Loyverse, CSV) set 1.0.
    Phase 2 normalizer groups same-name items into variants based on
    `size_hint` and similar fields.
    (source가 발견한 1개 메뉴 — confidence는 0-1, 결정적 source는 1.0)
    """
    name:               str
    price:              float
    category:           Optional[str]
    description:        Optional[str]
    size_hint:          Optional[str]
    detected_allergens: Optional[list[str]]
    pos_item_id:        Optional[str]
    pos_variant_id:     Optional[str]
    sku:                Optional[str]
    stock_quantity:     Optional[int]
    confidence:         float


class NormalizedVariant(TypedDict, total=False):
    """One pricing tier of a normalized menu item.

    Carries the POS identifiers so downstream sync can match by SKU or
    variant_id without re-fetching. `size_hint` is the operator-facing
    label ("14 inch (Small)") preserved verbatim from the source.
    (1개 variant — POS id 보존, size_hint는 source label 그대로)
    """
    size_hint:      Optional[str]
    price:          float
    pos_variant_id: Optional[str]
    sku:            Optional[str]
    stock_quantity: Optional[int]


class NormalizedMenuItem(TypedDict, total=False):
    """Phase 2 output — same base name's variants folded together.

    `variants` is non-empty for items with size tiers (most pizzas) and a
    single-element list for standalone items, so the wizard renders both
    uniformly. `pos_item_id` is shared across the variants because
    Loyverse / our DB treat it as the item root.
    (Phase 2 결과 — 같은 base name의 variants를 1개 item으로 통합)
    """
    name:               str
    category:           Optional[str]
    description:        Optional[str]
    pos_item_id:        Optional[str]
    detected_allergens: Optional[list[str]]
    confidence:         float
    variants:           list[NormalizedVariant]


class RawMenuExtraction(TypedDict, total=False):
    """Top-level result. The router unwraps this for the Wizard preview.

    `vertical_guess` may be empty when the source carries no signal
    (CSV/manual); Phase 2 vertical_detector fills it from menu keywords.
    `warnings` carries non-fatal issues operators should see in the UI
    (low confidence rows, dropped pages, fetch retries, etc).
    (source의 raw 결과 — Phase 2 normalizer가 vertical/warnings 보강)
    """
    source:             SourceType
    items:              list[RawMenuItem]
    detected_modifiers: list[str]
    vertical_guess:     Optional[str]
    warnings:           list[str]
