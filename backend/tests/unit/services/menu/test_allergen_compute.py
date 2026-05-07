# Phase 7-A.B — Dynamic allergen compute helper tests
# (Phase 7-A.B — 동적 알러젠 계산 helper 테스트)
#
# compute_effective_allergens(base, selected, modifier_index):
#   For each (group, option) in selected, look up the option's allergen_add /
#   allergen_remove and apply: result = (base ⊕ add) ⊖ remove.
#
# Order of operations: ALL adds collected first, then ALL removes applied.
# This prevents an earlier modifier's remove from being undone by a later
# modifier's add. Live case: 'oat milk + caramel syrup' on a Cafe Latte.
#   - oat: +gluten +wheat -dairy
#   - caramel: +dairy
#   Naive sequential ((dairy + gluten + wheat - dairy) + dairy) = dairy+gluten+wheat
#   Adds-then-removes ((dairy + gluten + wheat + dairy) - dairy) = gluten+wheat
#
# Both interpretations have semantic merit, but caramel syrup ON oat milk
# realistically still contains dairy (caramel is a dairy ingredient regardless
# of the milk choice). We choose ADD-LAST semantics: removes apply first,
# then adds layer on. Result for oat+caramel: gluten+wheat+dairy.

import pytest


def _index_from_groups(groups):
    """Build the (group_code, option_code) -> option dict index used by callers."""
    out = {}
    for g in groups:
        for o in g.get("options", []):
            out[(g["code"], o["code"])] = o
    return out


@pytest.fixture
def jm_cafe_index():
    """Mirror the JM Cafe modifier_options data we already verified in DB."""
    return _index_from_groups([
        {"code": "milk", "options": [
            {"code": "whole",  "allergen_add": ["dairy"], "allergen_remove": []},
            {"code": "oat",    "allergen_add": ["gluten", "wheat"],
                               "allergen_remove": ["dairy"]},
            {"code": "almond", "allergen_add": ["nuts"],
                               "allergen_remove": ["dairy"]},
            {"code": "soy",    "allergen_add": ["soy"],
                               "allergen_remove": ["dairy"]},
            {"code": "coconut", "allergen_add": [],
                               "allergen_remove": ["dairy"]},
        ]},
        {"code": "temperature", "options": [
            {"code": "iced", "allergen_add": [], "allergen_remove": []},
            {"code": "blended", "allergen_add": ["dairy"], "allergen_remove": []},
        ]},
        {"code": "syrup", "options": [
            {"code": "vanilla",  "allergen_add": [], "allergen_remove": []},
            {"code": "hazelnut", "allergen_add": ["nuts"], "allergen_remove": []},
            {"code": "caramel",  "allergen_add": ["dairy"], "allergen_remove": []},
        ]},
        {"code": "whip", "options": [
            {"code": "with_whip", "allergen_add": ["dairy"], "allergen_remove": []},
            {"code": "no_whip",   "allergen_add": [], "allergen_remove": []},
        ]},
    ])


# ── Core algebra ──────────────────────────────────────────────────────────────

def test_no_modifiers_returns_base_unchanged(jm_cafe_index):
    from app.services.menu.allergen_compute import compute_effective_allergens
    assert compute_effective_allergens(["dairy"], [], jm_cafe_index) == ["dairy"]


def test_oat_milk_replaces_dairy_with_gluten_wheat(jm_cafe_index):
    """Cafe Latte (dairy) + oat milk → gluten, wheat (dairy removed)."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"], [{"group": "milk", "option": "oat"}], jm_cafe_index)
    assert sorted(result) == ["gluten", "wheat"]


def test_almond_milk_replaces_dairy_with_nuts(jm_cafe_index):
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"], [{"group": "milk", "option": "almond"}], jm_cafe_index)
    assert result == ["nuts"]


def test_iced_temperature_no_allergen_change(jm_cafe_index):
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"], [{"group": "temperature", "option": "iced"}], jm_cafe_index)
    assert result == ["dairy"]


def test_oat_milk_plus_caramel_syrup_brings_dairy_back(jm_cafe_index):
    """Adds-after-removes semantics: caramel re-introduces dairy on top of oat.
    Customer-safety reasoning: caramel sauce contains dairy regardless of the
    milk choice, so the safe answer is "yes, dairy present"."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"],
        [{"group": "milk",  "option": "oat"},
         {"group": "syrup", "option": "caramel"}],
        jm_cafe_index,
    )
    assert sorted(result) == ["dairy", "gluten", "wheat"]


def test_almond_milk_plus_hazelnut_syrup_double_nuts(jm_cafe_index):
    """Both add nuts; result must dedupe (set semantics)."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"],
        [{"group": "milk",  "option": "almond"},
         {"group": "syrup", "option": "hazelnut"}],
        jm_cafe_index,
    )
    assert result == ["nuts"]


def test_coconut_milk_strips_dairy_no_replacement(jm_cafe_index):
    """Coconut milk has no allergen_add — drink becomes allergen-free."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"], [{"group": "milk", "option": "coconut"}], jm_cafe_index)
    assert result == []


def test_unknown_group_or_option_silently_skipped(jm_cafe_index):
    """A garbled tool argument from the LLM must NOT raise — skip and return
    base unchanged. Live risk: the model invents a 'milk: rice' option.
    (LLM이 존재하지 않는 옵션을 보내면 무시 — 통화 중단 사유 아님)"""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"],
        [{"group": "milk", "option": "rice"},          # not in index
         {"group": "ice_cream", "option": "vanilla"}], # group not in index
        jm_cafe_index,
    )
    assert result == ["dairy"]


def test_result_is_sorted_for_stable_output(jm_cafe_index):
    """Callers compare result lists in tests and rely on deterministic order."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    # Mix that produces multiple allergens
    result = compute_effective_allergens(
        ["dairy"],
        [{"group": "milk",  "option": "oat"},
         {"group": "syrup", "option": "caramel"},
         {"group": "whip",  "option": "with_whip"}],
        jm_cafe_index,
    )
    # dairy from caramel + dairy from whip dedupe; oat strips base dairy first
    assert result == sorted(result)
    assert "gluten" in result and "wheat" in result and "dairy" in result


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_base_with_modifier_adds(jm_cafe_index):
    """Allergen-free base + caramel syrup → just dairy."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        [], [{"group": "syrup", "option": "caramel"}], jm_cafe_index)
    assert result == ["dairy"]


def test_remove_allergen_not_in_base_is_noop(jm_cafe_index):
    """Croissant is gluten+dairy. Adding oat milk (which removes dairy) should
    leave gluten in place. allergen_remove for an absent allergen is a no-op."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["gluten", "dairy"], [{"group": "milk", "option": "oat"}], jm_cafe_index)
    assert sorted(result) == ["gluten", "wheat"]
    # dairy was in base AND removed by oat → gone
    # original gluten + oat-added gluten dedupe → single gluten
    # oat-added wheat → present


def test_malformed_modifier_dict_is_skipped(jm_cafe_index):
    """Defensive: missing 'group' or 'option' key must not crash."""
    from app.services.menu.allergen_compute import compute_effective_allergens
    result = compute_effective_allergens(
        ["dairy"],
        [{"group": "milk"},                    # missing option
         {"option": "oat"},                    # missing group
         {},                                   # empty
         {"group": "milk", "option": "oat"}],  # valid
        jm_cafe_index,
    )
    assert sorted(result) == ["gluten", "wheat"]
