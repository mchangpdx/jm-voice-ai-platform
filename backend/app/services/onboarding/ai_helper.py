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


# ── Dietary tag inference ────────────────────────────────────────────────────
# Templates carry two complementary signals:
#   `dietary_patterns` / `patterns[].add_dietary`  — forward (name keywords)
#   `dietary_inference[].if_absent → suggest`       — reverse (allergen absence)
# Both run through `ui_thresholds.auto_check` (default 0.90) so low-confidence
# suggestions stay off-by-default and reach operators only via the wizard UI.
# (dietary는 forward+reverse 두 source, auto_check 임계치만 자동 적용)


def _auto_check_threshold(rules: dict[str, Any]) -> float:
    """Read `ui_thresholds.auto_check` with a 0.90 fallback."""
    thresholds = rules.get("ui_thresholds") or {}
    raw = thresholds.get("auto_check", 0.90)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.90


def _forward_dietary(
    rules:    dict[str, Any],
    text:     str,
    cutoff:   float,
) -> set[str]:
    """Keyword-driven dietary tags.

    Two layouts are supported because templates evolved separately:
    `dietary_patterns` (pizza) and `patterns[].add_dietary` (kbbq). Pattern
    entries without an explicit `confidence` are treated as 1.0 — they're
    operator-curated keywords that wouldn't ship without intent.
    (두 layout 호환 — confidence 미명시는 1.0 취급)
    """
    found: set[str] = set()
    blocks: list[list[Any]] = []
    if isinstance(rules.get("dietary_patterns"), list):
        blocks.append(rules["dietary_patterns"])
    if isinstance(rules.get("patterns"), list):
        blocks.append(rules["patterns"])

    for block in blocks:
        for pat in block:
            if not isinstance(pat, dict):
                continue
            adds = pat.get("add_dietary") or []
            if not adds:
                continue
            conf = pat.get("confidence", 1.0)
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = 1.0
            if conf < cutoff:
                continue
            for kw in pat.get("keywords") or []:
                if isinstance(kw, str) and kw and kw.lower() in text:
                    found.update(adds)
                    break
    return found


def _reverse_dietary(
    rules:     dict[str, Any],
    allergens: list[str],
    cutoff:    float,
) -> set[str]:
    """Allergen-absence-driven dietary tags.

    Each `dietary_inference` rule fires when EVERY allergen in `if_absent`
    is missing from the item's allergen list. Confidence gating keeps
    low-signal suggestions (e.g., cafe `vegan: 0.50`) out of the auto path
    — those still surface in the wizard UI for operator review.
    (모든 if_absent allergen이 부재해야 fire; auto_check 미달은 wizard용)
    """
    found: set[str] = set()
    have = {a.lower() for a in (allergens or []) if isinstance(a, str)}
    rules_list = rules.get("dietary_inference") or []
    for rule in rules_list:
        if not isinstance(rule, dict):
            continue
        conf = rule.get("confidence", 1.0)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 1.0
        if conf < cutoff:
            continue
        if_absent = [a.lower() for a in (rule.get("if_absent") or []) if isinstance(a, str)]
        if not if_absent:
            continue
        if any(a in have for a in if_absent):
            continue
        found.update(rule.get("suggest") or [])
    return found


def infer_dietary_tags(
    name:        str,
    description: str | None,
    allergens:   list[str],
    vertical:    str,
) -> list[str]:
    """Return sorted dietary tags for one item.

    Combines forward (keywords) and reverse (allergen-absence) signals,
    filtered by the vertical's `ui_thresholds.auto_check` confidence
    cutoff. The reverse path consumes the allergen list produced by
    `infer_allergens` (or any upstream source) — pass an empty list if
    unknown and reverse rules will fire optimistically.
    (forward+reverse 통합, auto_check 임계 적용, allergens는 caller가 공급)
    """
    if not name:
        return []
    rules = _load_rules(vertical)
    if not rules or (not rules.get("dietary_patterns")
                     and not rules.get("dietary_inference")
                     and not rules.get("patterns")):
        return []
    cutoff = _auto_check_threshold(rules)
    text = _haystack(name, description)
    tags = _forward_dietary(rules, text, cutoff) | _reverse_dietary(rules, allergens, cutoff)
    return sorted(tags)


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
