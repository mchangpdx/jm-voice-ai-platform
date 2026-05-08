# Phase 7-A.B — Modifier loader + system-prompt formatter tests
# (Phase 7-A.B — modifier 로더 + 시스템 프롬프트 포매터 테스트)
#
# fetch_modifier_groups(store_id):
#   1. GET /modifier_groups?store_id=eq.<id>&order=sort_order
#   2. GET /modifier_options?group_id=in.(<ids>)&order=sort_order  (one batched call)
#   3. Nest options under each group; preserve sort_order in both axes
#   4. Empty input → empty list (never raises)
#
# format_modifier_block(groups):
#   - Returns a single text block for system prompt injection
#   - Groups labeled "(required)" / "(optional)" by is_required
#   - Options listed with display_name + price_delta + allergen markers
#   - Allergen markers: +X (allergen_add) and -X (allergen_remove)
#   - Empty input → empty string

from unittest.mock import AsyncMock, patch

import pytest

_STORE_ID = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"

# ── Fixture rows mirroring JM Cafe DB ────────────────────────────────────────

def _milk_group():
    return {
        "id":            "g-milk",
        "store_id":      _STORE_ID,
        "code":          "milk",
        "display_name":  "Milk",
        "is_required":   True,
        "min_select":    1,
        "max_select":    1,
        "sort_order":    3,
    }


def _temperature_group():
    return {
        "id":            "g-temp",
        "store_id":      _STORE_ID,
        "code":          "temperature",
        "display_name":  "Temperature",
        "is_required":   True,
        "min_select":    1,
        "max_select":    1,
        "sort_order":    2,
    }


def _syrup_group():
    return {
        "id":            "g-syrup",
        "store_id":      _STORE_ID,
        "code":          "syrup",
        "display_name":  "Syrup",
        "is_required":   False,
        "min_select":    0,
        "max_select":    3,
        "sort_order":    6,
    }


def _opt(group_id, code, display_name, price_delta=0.0,
         allergen_add=None, allergen_remove=None, sort_order=1):
    return {
        "id":               f"o-{code}",
        "group_id":         group_id,
        "code":             code,
        "display_name":     display_name,
        "price_delta":      price_delta,
        "allergen_add":     list(allergen_add or []),
        "allergen_remove":  list(allergen_remove or []),
        "sort_order":       sort_order,
        "is_default":       False,
        "is_available":     True,
    }


def _milk_options():
    return [
        _opt("g-milk", "whole",   "Whole milk",   allergen_add=["dairy"], sort_order=1),
        _opt("g-milk", "two_pct", "2% milk",      allergen_add=["dairy"], sort_order=2),
        _opt("g-milk", "oat",     "Oat milk",
             allergen_add=["gluten", "wheat"], allergen_remove=["dairy"], sort_order=4),
        _opt("g-milk", "almond",  "Almond milk",
             allergen_add=["nuts"], allergen_remove=["dairy"], sort_order=5),
    ]


def _temperature_options():
    return [
        _opt("g-temp", "hot",   "Hot",     sort_order=1),
        _opt("g-temp", "iced",  "Iced",    sort_order=2),
        _opt("g-temp", "blended", "Blended",
             allergen_add=["dairy"], sort_order=3),
    ]


def _syrup_options():
    return [
        _opt("g-syrup", "vanilla",  "Vanilla",  sort_order=1),
        _opt("g-syrup", "hazelnut", "Hazelnut",
             allergen_add=["nuts"], sort_order=2),
        _opt("g-syrup", "caramel",  "Caramel",
             price_delta=0.50, allergen_add=["dairy"], sort_order=3),
    ]


def _patched_get_sequence(group_rows, option_rows):
    """Return a mock httpx.AsyncClient that serves /modifier_groups then /modifier_options."""
    g_resp = AsyncMock(); g_resp.status_code = 200
    g_resp.json = lambda: group_rows
    o_resp = AsyncMock(); o_resp.status_code = 200
    o_resp.json = lambda: option_rows

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    # Order of GETs: groups first, then options. async-mock side_effect supports iteration.
    client.get = AsyncMock(side_effect=[g_resp, o_resp])
    return client


# ── fetch_modifier_groups ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_returns_groups_with_nested_options():
    from app.services.menu.modifiers import fetch_modifier_groups

    groups   = [_temperature_group(), _milk_group()]      # unordered on purpose
    options  = _milk_options() + _temperature_options()

    client = _patched_get_sequence(groups, options)
    with patch("app.services.menu.modifiers.httpx.AsyncClient", return_value=client):
        result = await fetch_modifier_groups(_STORE_ID)

    assert len(result) == 2
    # Sort by group sort_order
    assert result[0]["code"] == "temperature"
    assert result[1]["code"] == "milk"

    temp = result[0]
    assert [o["code"] for o in temp["options"]] == ["hot", "iced", "blended"]

    milk = result[1]
    assert [o["code"] for o in milk["options"]] == ["whole", "two_pct", "oat", "almond"]


@pytest.mark.asyncio
async def test_fetch_empty_store_returns_empty_list():
    from app.services.menu.modifiers import fetch_modifier_groups

    client = _patched_get_sequence([], [])
    with patch("app.services.menu.modifiers.httpx.AsyncClient", return_value=client):
        result = await fetch_modifier_groups(_STORE_ID)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_handles_rest_error_gracefully():
    """A 500 from Supabase must not crash the call path — return [] instead."""
    from app.services.menu.modifiers import fetch_modifier_groups

    bad = AsyncMock(); bad.status_code = 500
    bad.json = lambda: {"error": "db down"}
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=bad)

    with patch("app.services.menu.modifiers.httpx.AsyncClient", return_value=client):
        result = await fetch_modifier_groups(_STORE_ID)
    assert result == []


# ── format_modifier_block ─────────────────────────────────────────────────────

def test_format_empty_returns_empty_string():
    from app.services.menu.modifiers import format_modifier_block
    assert format_modifier_block([]) == ""


def test_format_renders_required_marker_and_options():
    from app.services.menu.modifiers import format_modifier_block

    milk = {**_milk_group(), "options": _milk_options()}
    block = format_modifier_block([milk])

    # Header includes required marker
    assert "Milk (required" in block

    # Each option appears with display name
    for opt in ["Whole milk", "2% milk", "Oat milk", "Almond milk"]:
        assert opt in block


def test_format_renders_allergen_add_and_remove_markers():
    from app.services.menu.modifiers import format_modifier_block

    milk = {**_milk_group(), "options": _milk_options()}
    block = format_modifier_block([milk])

    # oat must show +gluten +wheat -dairy
    assert "+gluten" in block
    assert "+wheat" in block
    assert "-dairy" in block

    # almond must show +nuts -dairy
    assert "+nuts" in block


def test_format_renders_price_delta_when_nonzero():
    from app.services.menu.modifiers import format_modifier_block

    syrup = {**_syrup_group(), "options": _syrup_options()}
    block = format_modifier_block([syrup])

    # caramel +$0.50 — vanilla and hazelnut have no delta
    assert "+$0.50" in block or "$0.50" in block


def test_format_optional_group_marker():
    from app.services.menu.modifiers import format_modifier_block

    syrup = {**_syrup_group(), "options": _syrup_options()}
    block = format_modifier_block([syrup])

    assert "Syrup (optional" in block


def test_format_renders_code_prefix_when_display_diverges_from_code():
    """Phase 7-A.D Wave A.1 — size options have code='large' / display_name=
    '20oz', and the bot can't bind a customer's 'large' utterance to
    option='large' unless the prompt shows the mapping. Render as
    'code=Display' so the LLM sees both forms.
    Live trigger CAc4250831...: caller said 'large iced almond cafe latte',
    bot asked 'what size — 12oz, 16oz, or 20oz?', customer answered
    'twenty ounces', bot's recital said '20 ounce' but selected_modifiers
    shipped without the size entry. Size code was invisible to the LLM."""
    from app.services.menu.modifiers import format_modifier_block

    g = {**_milk_group(), "code": "size", "display_name": "Size",
         "options": [
             _opt("g-milk", "small",  "12oz", sort_order=1),
             _opt("g-milk", "medium", "16oz", price_delta=0.5, sort_order=2),
             _opt("g-milk", "large",  "20oz", price_delta=1.0, sort_order=3),
         ]}
    block = format_modifier_block([g])

    # Code/display mapping must be explicit so 'large' → option='large'
    assert "small=12oz" in block
    assert "medium=16oz" in block
    assert "large=20oz" in block


def test_format_skips_code_prefix_when_redundant():
    """When display already starts with the code (milk: oat=Oat milk,
    syrup: vanilla=Vanilla), the prefix would just clutter — keep
    display only."""
    from app.services.menu.modifiers import format_modifier_block

    g = {**_milk_group(), "options": [
        _opt("g-milk", "oat",     "Oat milk",     sort_order=1),
        _opt("g-milk", "vanilla", "Vanilla",      sort_order=2),
    ]}
    block = format_modifier_block([g])
    assert "Oat milk" in block
    assert "oat=Oat milk" not in block
    assert "Vanilla" in block
    assert "vanilla=Vanilla" not in block


def test_format_dedupes_marker_when_display_name_contains_it():
    """JM Cafe DB has a group with display_name='Milk (optional)' and
    is_required=False. Naively appending '(optional)' yields the ugly
    'Milk (optional) (optional):' header — verify dedupe."""
    from app.services.menu.modifiers import format_modifier_block

    g = {
        "id": "g-milk-opt", "store_id": _STORE_ID,
        "code": "milk_optional", "display_name": "Milk (optional)",
        "is_required": False, "min_select": 0, "max_select": 1, "sort_order": 4,
        "options": [_opt("g-milk-opt", "oat", "Oat milk",
                         allergen_add=["gluten", "wheat"], sort_order=1)],
    }
    block = format_modifier_block([g])
    assert "Milk (optional) (optional)" not in block
    assert "Milk (optional):" in block


def test_format_skips_unavailable_options():
    """Options with is_available=False must not leak into the prompt."""
    from app.services.menu.modifiers import format_modifier_block

    opts = _milk_options()
    opts[0]["is_available"] = False  # whole milk discontinued
    milk = {**_milk_group(), "options": opts}

    block = format_modifier_block([milk])
    assert "Whole milk" not in block
    assert "Oat milk" in block


def test_format_includes_interpretation_hint():
    """The block must end with a hint that maps natural-language phrases like
    'iced oat latte' onto base+modifier composition. Without this hint the
    LLM falls back to literal menu_cache matching and rejects valid orders.
    (live trigger: 2026-05-07 12:14 call CA90b88e... — agent denied 'iced oat
    latte' four times despite Cafe Latte + iced + oat all existing in DB)"""
    from app.services.menu.modifiers import format_modifier_block

    milk = {**_milk_group(), "options": _milk_options()}
    block = format_modifier_block([milk])

    # Some sentinel text that signals to the LLM how to compose
    lower = block.lower()
    assert "modifier" in lower or "combinable" in lower or "interpret" in lower
