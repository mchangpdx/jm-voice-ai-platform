# Phase 2-C.B5 — Voice integration tests for allergen_lookup (V1–V8)
# (Phase 2-C.B5 — voice_websocket의 allergen_lookup 통합 테스트 8개)
#
# Spec: backend/docs/specs/B5_allergen_qa.md §8 voice tests.
# These are surface-level tests — they verify imports, schema shape, script
# coverage, dispatcher dispatch logic, prompt content, and the Tier 3 helper.

import pytest


MOCK_STORE = {
    "name":             "JM Cafe",
    "system_prompt":    "You are Aria, the friendly AI for JM Cafe.",
    "business_hours":   "Mon-Sat 7am-9pm, Sun 8am-6pm",
    "menu_cache":       "Cafe Latte: $5.99\nCheese Pizza: $11.99",
    "temporary_prompt": "Matcha latte is sold out today.",
    "custom_knowledge": "Free WiFi",
}


# ── V1: ALLERGEN_LOOKUP_TOOL_DEF exported with required menu_item_name only ──

def test_v1_allergen_lookup_tool_def_is_exported():
    from app.skills.menu.allergen import ALLERGEN_LOOKUP_TOOL_DEF

    decls = ALLERGEN_LOOKUP_TOOL_DEF.get("function_declarations", [])
    assert len(decls) == 1
    decl = decls[0]
    assert decl["name"] == "allergen_lookup"

    params = decl["parameters"]["properties"]
    for fld in ("menu_item_name", "allergen", "dietary_tag"):
        assert fld in params, f"missing param: {fld}"

    required = decl["parameters"].get("required", [])
    assert required == ["menu_item_name"]


# ── V2: ALLERGEN_SCRIPT_BY_HINT covers all 7 hints ───────────────────────────

def test_v2_allergen_script_map_covers_all_hints():
    from app.skills.order.order import ALLERGEN_SCRIPT_BY_HINT

    expected = {
        "item_not_found",
        "allergen_unknown",
        "allergen_present",
        "allergen_absent",
        "dietary_match",
        "dietary_no_match",
        "generic",
    }
    missing = expected - set(ALLERGEN_SCRIPT_BY_HINT.keys())
    assert not missing, f"missing script hints: {missing}"
    for hint, script in ALLERGEN_SCRIPT_BY_HINT.items():
        assert isinstance(script, str) and len(script) > 0, f"{hint} has empty script"


# ── V3: System prompt rule 12 mentions allergen_lookup + safety invariant ────

def test_v3_system_prompt_rule_12_present():
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "allergen_lookup" in prompt
    assert "CUSTOMER SAFETY INVARIANT" in prompt


# ── V4: dispatcher .format() substitutes {item} + {allergen} correctly ───────

def test_v4_script_format_substitutes_placeholders():
    from app.skills.order.order import ALLERGEN_SCRIPT_BY_HINT

    rendered = ALLERGEN_SCRIPT_BY_HINT["allergen_present"].format(
        item="Cafe Latte", allergen="dairy",
    )
    assert "Cafe Latte" in rendered
    assert "dairy" in rendered

    rendered_absent = ALLERGEN_SCRIPT_BY_HINT["allergen_absent"].format(
        item="Cheese Pizza", allergen="nuts",
    )
    assert "Cheese Pizza" in rendered_absent
    assert "nuts-free" in rendered_absent
    assert "per our kitchen records" in rendered_absent  # disclaimer qualifier


# ── V5: NO AUTO-FIRE gate for allergen_lookup ────────────────────────────────

def test_v5_allergen_lookup_not_in_auto_fire_gate():
    """allergen_lookup is read-only — fires on first mention, no recital
    required. The AUTO-FIRE gate tuple in voice_websocket._stream_gemini_response
    must NOT contain 'allergen_lookup'."""
    import inspect
    from app.api import voice_websocket

    src = inspect.getsource(voice_websocket._stream_gemini_response)
    # The gate is an `if tool_name in (...)` tuple — match the literal block
    # and verify allergen_lookup is excluded.
    assert "create_order" in src and "make_reservation" in src, (
        "AUTO-FIRE gate not located in source"
    )
    # Find the tuple literal that lists tool names; assert allergen_lookup
    # is not a substring of any line containing both 'tool_name in' and
    # the exclusive set of write-tools.
    for line in src.splitlines():
        if "tool_name in (" in line and "create_order" in line:
            assert "allergen_lookup" not in line, (
                "allergen_lookup must NOT be in AUTO-FIRE gate (read-only)"
            )


# ── V6: _has_severe_allergy_signal true on Tier 3 keywords ────────────────────

def test_v6_severe_allergy_signal_keywords():
    from app.api.voice_websocket import _has_severe_allergy_signal

    # Positive cases — case-insensitive whole-word match
    positives = [
        "I have an EpiPen",
        "She is anaphylactic",
        "deathly allergic to nuts",
        "I'm severely allergic to dairy",
        "I have celiac",
        "we got hospitalized last time",
        "react badly to gluten",
        "Coeliac disease",
    ]
    for txt in positives:
        assert _has_severe_allergy_signal(txt), f"failed positive: {txt}"

    # Negative cases — non-keywords or empty
    negatives = [
        "Just a regular allergy",
        "I'd like a coffee please",
        "",
    ]
    for txt in negatives:
        assert not _has_severe_allergy_signal(txt), f"false positive: {txt!r}"


# ── V7: Tier 3 intercept happens BEFORE allergen_lookup ──────────────────────

def test_v7_tier3_intercept_before_lookup():
    """When _has_severe_allergy_signal is True for the last user turn,
    the dispatcher must yield the manager-transfer line and skip the
    allergen_lookup tool call entirely. We verify by inspecting the
    dispatcher source for the intercept block ordering."""
    import inspect
    from app.api import voice_websocket

    src = inspect.getsource(voice_websocket._stream_gemini_response)
    # Locate the allergen_lookup branch
    branch_start = src.find('elif tool_name == "allergen_lookup":')
    assert branch_start >= 0, "allergen_lookup branch missing"

    # End the branch at the next dispatcher entry — either a sibling
    # `elif tool_name == "..."` (same outer if/elif chain) or the
    # `unsupported tool` fallback that closes the chain. The `else:` of
    # the inner Tier 3 if/else is NOT a chain boundary, so we anchor on
    # the unsupported-tool sentinel string.
    # (분기 끝 마커 — 내부 if/else의 else: 와 헷갈리지 않도록 sentinel 사용)
    sentinel = "unsupported tool"
    branch_end = src.find(sentinel, branch_start + 10)
    if branch_end == -1:
        branch_end = len(src)
    branch_block = src[branch_start:branch_end]

    intercept_idx = branch_block.find("_has_severe_allergy_signal")
    lookup_idx    = branch_block.find("await allergen_lookup")
    assert intercept_idx >= 0, "Tier 3 intercept missing in allergen_lookup branch"
    assert lookup_idx >= 0, "allergen_lookup() call missing in branch"
    assert intercept_idx < lookup_idx, (
        "Tier 3 intercept must come BEFORE the allergen_lookup() call"
    )
    assert "manager" in branch_block.lower(), (
        "manager-transfer line must appear in intercept path"
    )


# ── V8: System prompt contains Tier 3 keyword list + manager-offer wording ───

def test_v8_system_prompt_tier3_keywords_present():
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)

    # Sentinel keywords from spec §6e
    for kw in ("EpiPen", "anaphylaxis", "celiac"):
        assert kw in prompt, f"Tier 3 keyword missing in prompt: {kw}"

    # Manager-offer wording
    assert "connect you with our manager" in prompt
