# Phase 7-A.B — Dynamic allergen compute helper
# (Phase 7-A.B — 동적 알러젠 계산 helper)
#
# When a customer asks an allergen question about a menu item with modifiers
# ("does the oat milk latte have wheat?"), the answer cannot come from
# menu_items.allergens alone — modifier choices change the allergen profile:
#   Cafe Latte base       : ['dairy']
#   + oat milk            : +['gluten','wheat']  -['dairy']
#   = effective allergens : ['gluten', 'wheat']
#
# Algorithm (adds-after-removes):
#   1. Start with base allergens as a set.
#   2. For each selected modifier, accumulate add[] and remove[] sets across
#      ALL modifiers first (do not interleave with the base).
#   3. Apply removes to the base, then layer the accumulated adds on top.
#
# Why adds-after-removes?
#   Live edge case: oat milk (-dairy) + caramel syrup (+dairy) on a Cafe Latte.
#   Caramel syrup contains dairy regardless of the milk choice, so a customer
#   with a dairy allergy must hear "yes, dairy present" — the safe answer.
#   Naive sequential application could let an earlier remove silently swallow
#   a later add and ship dairy to a dairy-allergic customer.
#   (사용자 안전 — caramel은 milk 선택과 무관하게 dairy 함유, 보수적으로 add 살림)

from __future__ import annotations

from typing import Any


def compute_effective_allergens(
    base_allergens: list[str],
    selected_modifiers: list[dict[str, str]],
    modifier_index: dict[tuple[str, str], dict[str, Any]],
) -> list[str]:
    """Compute the effective allergen list for an item with modifiers.

    Args:
        base_allergens:     menu_items.allergens for the base item.
        selected_modifiers: list of {"group": <code>, "option": <code>} dicts.
                            Unknown or malformed entries are silently skipped.
        modifier_index:     dict keyed (group_code, option_code) → option row
                            (with allergen_add[] and allergen_remove[] lists).

    Returns:
        Deduped, sorted list of allergen strings.

    Never raises — defensive against LLM tool-arg hallucinations.
    (LLM이 존재하지 않는 group/option을 보내도 silently skip + base 반환)
    """
    base_set: set[str] = set(base_allergens or [])
    add_set:  set[str] = set()
    remove_set: set[str] = set()

    for sel in selected_modifiers or []:
        if not isinstance(sel, dict):
            continue
        gcode = sel.get("group")
        ocode = sel.get("option")
        if not gcode or not ocode:
            continue
        opt = modifier_index.get((gcode, ocode))
        if opt is None:
            continue
        for a in (opt.get("allergen_add") or []):
            if a:
                add_set.add(a)
        for a in (opt.get("allergen_remove") or []):
            if a:
                remove_set.add(a)

    # Removes applied to base first, then adds layered on. An allergen that is
    # both removed AND added stays present (safety bias toward declaring).
    # (remove 먼저 적용, add 마지막 — 충돌 시 add가 우선)
    effective = (base_set - remove_set) | add_set
    return sorted(effective)
