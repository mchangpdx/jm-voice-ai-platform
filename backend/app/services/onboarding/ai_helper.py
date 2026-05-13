"""Allergen auto-inference for newly extracted items.

The vertical templates already ship `allergen_rules.yaml` (pizza/cafe/
kbbq) with FDA-9 keyword patterns. This module loads them and runs
`name + description` text through the matchers, returning the union
of `add_allergens` for every matching rule. The wizard's Step 3 lets
the operator review and edit before final seeding, so 90% recall is
the right target — false negatives hurt diners, false positives are
cheap to fix in review.
(Phase 2 — vertical template 기반 알러젠 추론, operator review가 backstop)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 2.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.services.onboarding.schema import NormalizedMenuItem, RawMenuItem

log = logging.getLogger(__name__)


# Where vertical templates live. `backend/app/templates/<vertical>/
# allergen_rules.yaml` is the single source of truth — never duplicate
# the rules here, just load them.
# (template 경로 — yaml이 single source of truth, 중복 정의 금지)
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


@lru_cache(maxsize=8)
def _load_rules(vertical: str) -> dict[str, Any]:
    """Read and cache one vertical's allergen_rules.yaml.

    Missing files (verticals without a template yet — sushi, mexican,
    general) return an empty rules dict so the inference call silently
    becomes a no-op. The cache is small + per-vertical so adding a new
    template only requires dropping the file in place.
    (vertical 없으면 empty dict — no-op, cache는 vertical별)
    """
    path = _TEMPLATES_DIR / vertical / "allergen_rules.yaml"
    if not path.is_file():
        return {"patterns": []}
    try:
        with path.open("r") as f:
            return yaml.safe_load(f) or {"patterns": []}
    except yaml.YAMLError as exc:
        log.warning("allergen_rules.yaml parse failed for %s: %s", vertical, exc)
        return {"patterns": []}


def _haystack(name: str, description: str | None) -> str:
    """Combined lowercase text used for keyword matching."""
    desc = description or ""
    return f"{name} {desc}".lower()


def infer_allergens(
    name:        str,
    description: str | None,
    vertical:    str,
) -> list[str]:
    """Return the sorted union of allergens triggered by name+description.

    Each pattern entry in the yaml has `keywords` (any-match) and
    `add_allergens`. We treat keyword matching as substring — that
    catches both "Pepperoni Pizza" and "pizza" (without word-boundary
    surprises) at the cost of occasional false matches like "almond"
    inside "Almondine" — rare enough that operator review handles it.
    (substring match — pattern 단순, false positive는 review에서 수정)
    """
    if not name:
        return []
    rules = _load_rules(vertical)
    patterns = rules.get("patterns") or []
    if not patterns:
        return []

    text = _haystack(name, description)
    found: set[str] = set()
    for pat in patterns:
        if not isinstance(pat, dict):
            continue
        keywords = pat.get("keywords") or []
        adds = pat.get("add_allergens") or []
        for kw in keywords:
            if isinstance(kw, str) and kw and kw.lower() in text:
                found.update(adds)
                break  # one keyword per pattern is enough — go to next pattern
    return sorted(found)


def apply_allergen_inference_to_normalized(
    items:    list[NormalizedMenuItem],
    vertical: str,
) -> list[NormalizedMenuItem]:
    """Fill in `detected_allergens` for items that don't have one yet.

    Items whose adapter already set allergens (Loyverse with custom_data,
    operator manual entry, vision call that returned allergen tags) are
    left alone — the adapter's signal beats ours. Only None / empty
    lists get filled.
    (이미 allergens 있는 item은 유지, None/빈 list만 inference로 채움)
    """
    out: list[NormalizedMenuItem] = []
    for it in items:
        existing = it.get("detected_allergens")
        if existing:
            out.append(it)
            continue
        guessed = infer_allergens(
            name        = it.get("name") or "",
            description = it.get("description"),
            vertical    = vertical,
        )
        new_item: NormalizedMenuItem = {**it}  # type: ignore[assignment]
        new_item["detected_allergens"] = guessed
        out.append(new_item)
    return out


def apply_allergen_inference_to_raw(
    items:    list[RawMenuItem],
    vertical: str,
) -> list[RawMenuItem]:
    """Same as above but for raw items (called before normalize if desired).

    Either ordering works — applying before normalize means each
    variant row gets a guess; applying after means one guess per merged
    item. After is cheaper (1 inference per ~24 items vs 1 per 34 raw
    rows) and the result is identical since variants share a name.
    Wizard wires the "after" order.
    (raw 단계에서도 호출 가능 — 사용 권장은 normalize 후)
    """
    out: list[RawMenuItem] = []
    for it in items:
        existing = it.get("detected_allergens")
        if existing:
            out.append(it)
            continue
        guessed = infer_allergens(
            name        = it.get("name") or "",
            description = it.get("description"),
            vertical    = vertical,
        )
        new_item: RawMenuItem = {**it}  # type: ignore[assignment]
        new_item["detected_allergens"] = guessed
        out.append(new_item)
    return out
