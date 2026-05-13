"""NormalizedMenuItem.variants → modifier_groups.yaml dict (size group).

The Phase 2 normalizer keeps size variants under each item, but the
voice agent's modifier engine wants them as a separate `size` modifier
group with price_deltas (the same `applies_to_categories` /
`options[].price_delta` shape that
`backend/app/templates/<vertical>/modifier_groups.yaml` ships with).
This module folds the per-item variant list back out into that group
so the seeder + voice agent get a vertical-template-shaped yaml from
auto-extracted data.

For now we only emit the `size` group. Other groups (crust, sauce,
cheese, milk, syrup, ...) need either a vertical template default
(merge step in Phase 3) or AI inference from menu copy (Phase 2-AI).
(Phase 2 — variants → size modifier group. 다른 group은 다음 단계.)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 2.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services.onboarding.schema import NormalizedMenuItem


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _option_id(size_hint: str) -> str:
    """Compact slug used as option id (matches existing pizza yaml style).

    `"14 inch (Small)"` → `"14inch"` — keeps the leading dimension+unit
    and drops the parenthetical descriptor so the id stays stable when
    operators rewrite the user-facing label.
    (slug — 숫자+단위만 유지, descriptor 제거)
    """
    head = size_hint.split("(")[0].strip().lower()
    slug = _SLUG_RE.sub("", head)  # "14 inch" → "14inch"
    return slug or "size"


def _category_slug(category: str | None) -> str | None:
    """Mirror menu_yaml_exporter._category_id for join consistency.

    `applies_to_categories` references the same snake_case ids the
    exporter writes to `menu.yaml` — both files come out of one source,
    they have to agree on category slugs or the seeder won't wire
    items↔groups correctly.
    (category slug 규칙 — menu_yaml_exporter와 동일)
    """
    if not category:
        return None
    return _SLUG_RE.sub("_", category.strip().lower()).strip("_") or None


def extract_size_modifier_group(
    items: list[NormalizedMenuItem],
) -> dict[str, Any] | None:
    """Build a `size` modifier group dict from items with multi-variant rows.

    Returns None when no item carries more than one variant — there's
    no size dimension to extract. The returned dict slots straight into
    `modifier_groups.yaml`'s `groups.size` key.

    Price deltas are the median across items relative to each item's
    cheapest variant. Median (not mean) keeps one mispriced row from
    skewing the group default — common when an operator typo'd one
    pizza's large price. The cheapest size is marked `default: true`.
    Sizes that show up in fewer than half the multi-variant items are
    excluded (probably an outlier label on one item).
    (median price_delta — typo 회피, 출현 빈도 50% 미만 size는 제외)
    """
    multi_variant = [it for it in items if len(it.get("variants") or []) > 1]
    if not multi_variant:
        return None

    # Count how often each size_hint appears across multi-variant items.
    # Used to filter outliers (only-on-one-item sizes).
    # (size_hint 출현 빈도 — 절반 미만은 outlier로 제외)
    size_counts: Counter[str] = Counter()
    for it in multi_variant:
        for v in it["variants"]:
            label = (v.get("size_hint") or "").strip()
            if label:
                size_counts[label] += 1

    threshold = max(1, len(multi_variant) // 2)
    common_sizes = [s for s, n in size_counts.items() if n >= threshold]
    if not common_sizes:
        return None

    # Collect (size_hint → list of deltas-from-min) across items.
    # Items contribute one delta per size present; missing sizes don't
    # poison the median (we just skip them).
    # (size별 delta 분포 — 각 item의 min variant 대비)
    deltas_by_size: dict[str, list[float]] = {s: [] for s in common_sizes}
    for it in multi_variant:
        variants = it["variants"]
        prices = [v.get("price") or 0.0 for v in variants]
        if not prices:
            continue
        base_price = min(prices)
        for v in variants:
            label = (v.get("size_hint") or "").strip()
            if label in deltas_by_size:
                deltas_by_size[label].append((v.get("price") or 0.0) - base_price)

    def _median(values: list[float]) -> float:
        s = sorted(values)
        n = len(s)
        if n == 0:
            return 0.0
        mid = n // 2
        return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0

    options = []
    # Order by median delta ascending so the cheapest size shows first.
    # (delta 오름차순 — 가장 저렴한 size가 default)
    ordered_sizes = sorted(common_sizes, key=lambda s: _median(deltas_by_size[s]))
    for idx, label in enumerate(ordered_sizes):
        opt: dict[str, Any] = {
            "id":          _option_id(label),
            "en":          label,
            "price_delta": round(_median(deltas_by_size[label]), 2),
        }
        if idx == 0:
            opt["default"] = True
        options.append(opt)

    applies_to = sorted({
        _category_slug(it.get("category"))
        for it in multi_variant
        if _category_slug(it.get("category"))
    })

    group: dict[str, Any] = {
        "required": True,
        "min":      1,
        "max":      1,
        "options":  options,
    }
    if applies_to:
        group["applies_to_categories"] = applies_to
    return group


def export_modifier_groups_yaml(
    items: list[NormalizedMenuItem],
) -> dict[str, Any]:
    """Top-level wrapper — emits a `groups: {...}` dict.

    Mirrors `backend/app/templates/<vertical>/modifier_groups.yaml`
    layout. Empty groups dict is a valid return value (the seeder skips
    modifier-group seeding gracefully) and is what you get when no
    multi-variant items were detected.
    (top-level dict — groups가 비어도 valid)
    """
    groups: dict[str, Any] = {}
    size_group = extract_size_modifier_group(items)
    if size_group is not None:
        groups["size"] = size_group
    return {"groups": groups}
