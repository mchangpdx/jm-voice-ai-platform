# Phase 2-C.B5 — allergen_lookup skill tests (T1–T10)
# (Phase 2-C.B5 — allergen_lookup 스킬 테스트 10개)
#
# Spec: backend/docs/specs/B5_allergen_qa.md §8 skill tests.
# Each test mocks the Supabase REST round-trip with a fixed list of rows,
# then verifies the returned ai_script_hint + payload shape.

from unittest.mock import AsyncMock, patch

import pytest

from app.skills.menu.allergen import allergen_lookup

_STORE_ID       = "5b5b5b5b-5b5b-5b5b-5b5b-5b5b5b5b5b5b"
_OTHER_STORE_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


# ── Fixture rows (mirror the JM Cafe backfill) ────────────────────────────────

def _row(name, allergens=None, dietary_tags=None):
    return {
        "name":         name,
        "allergens":    list(allergens or []),
        "dietary_tags": list(dietary_tags or []),
    }


def _jm_cafe_rows():
    return [
        _row("Cafe Latte",      ["dairy"],                  ["vegetarian", "gluten_free", "nut_free"]),
        _row("Cheese Pizza",    ["gluten", "dairy"],        ["vegetarian", "nut_free"]),
        _row("Donuts",          [],                          []),                                     # unknown
        _row("Croissant",       ["gluten", "dairy"],        ["vegetarian", "nut_free"]),
        _row("Americano",       [],                          ["vegan", "vegetarian", "gluten_free", "dairy_free", "nut_free", "kosher", "halal"]),
    ]


def _patched_get(rows, status=200):
    """Return a mock that resp.status_code=status and resp.json()=rows."""
    resp = AsyncMock()
    resp.status_code = status
    resp.json = lambda: rows
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)
    return client


# ── T1: item not in menu → fuzzy fails → item_not_found ──────────────────────

@pytest.mark.asyncio
async def test_t1_item_not_found():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Sushi Roll",  # not on menu, no fuzzy match
            allergen        = "fish",
        )
    assert result["success"] is True
    assert result["ai_script_hint"] == "item_not_found"


# ── T2: item found, both arrays empty → allergen_unknown ─────────────────────

@pytest.mark.asyncio
async def test_t2_allergen_unknown():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Donuts",
            allergen        = "gluten",
        )
    assert result["ai_script_hint"] == "allergen_unknown"
    assert result["matched_name"] == "Donuts"


# ── T3: allergen present in row → allergen_present ───────────────────────────

@pytest.mark.asyncio
async def test_t3_allergen_present():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Cafe Latte",
            allergen        = "dairy",
        )
    assert result["ai_script_hint"] == "allergen_present"
    assert "dairy" in result["allergens"]


# ── T4: allergen absent + row has explicit data → allergen_absent ────────────

@pytest.mark.asyncio
async def test_t4_allergen_absent():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Cheese Pizza",
            allergen        = "nuts",  # not in ['gluten','dairy']
        )
    assert result["ai_script_hint"] == "allergen_absent"


# ── T5: dietary tag in row.dietary_tags → dietary_match ──────────────────────

@pytest.mark.asyncio
async def test_t5_dietary_match():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Americano",
            dietary_tag     = "vegan",
        )
    assert result["ai_script_hint"] == "dietary_match"


# ── T6: dietary tag NOT in row.dietary_tags → dietary_no_match ───────────────

@pytest.mark.asyncio
async def test_t6_dietary_no_match():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Croissant",
            dietary_tag     = "gluten_free",
        )
    assert result["ai_script_hint"] == "dietary_no_match"


# ── T7: no allergen + no dietary specified (generic) ─────────────────────────

@pytest.mark.asyncio
async def test_t7_generic():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Cheese Pizza",
            allergen        = "",
            dietary_tag     = "",
        )
    assert result["ai_script_hint"] == "generic"
    assert "gluten" in result["allergens"]
    assert "dairy" in result["allergens"]


# ── T8: RLS — cross-store query returns no rows → item_not_found ─────────────

@pytest.mark.asyncio
async def test_t8_rls_isolation():
    # Mock returns empty rows (simulates RLS filtering everything out for
    # a different store_id). Lookup must fall through to item_not_found
    # rather than crash or speak about another store's data.
    client = _patched_get([])
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _OTHER_STORE_ID,
            menu_item_name  = "Cafe Latte",
            allergen        = "dairy",
        )
    assert result["ai_script_hint"] == "item_not_found"


# ── T9: fuzzy match cutoff 0.7 — "lattay" matches "Cafe Latte" ────────────────

@pytest.mark.asyncio
async def test_t9_fuzzy_match_cutoff_07():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "cafe lattay",  # one-letter typo
            allergen        = "dairy",
        )
    assert result["matched_name"] == "Cafe Latte"
    assert result["ai_script_hint"] == "allergen_present"


# ── T10: both allergen + dietary specified → allergen wins ───────────────────

@pytest.mark.asyncio
async def test_t10_allergen_wins_over_dietary():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Cafe Latte",
            allergen        = "dairy",
            dietary_tag     = "vegan",   # ignored — allergen branch wins
        )
    assert result["ai_script_hint"] == "allergen_present"
    # queried_dietary should have been zeroed out by mutual-exclusion
    assert result["queried_dietary"] == ""


# ── T11: wheat alias — gluten present → wheat present (FDA conservative) ─────
# Phase 5 scenario 4 (CA0f91961): caller asked about wheat in croissant; bot
# hallucinated allergen='nuts' because 'wheat' was missing from the tool enum.
# Fix: enum now includes 'wheat'; tool aliases wheat against gluten data.
# (wheat alias 검증 — gluten 함유 시 wheat present 응답)

@pytest.mark.asyncio
async def test_t11_wheat_alias_gluten_present_implies_wheat_present():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Croissant",
            allergen        = "wheat",
        )
    assert result["ai_script_hint"] == "allergen_present"
    assert result["queried_allergen"] == "wheat"


# ── T12: wheat alias — gluten absent → escalate to UNKNOWN, NOT absent ───────
# Safety asymmetry: gluten-free does NOT guarantee wheat-free (barley/rye-only
# items exist). Saying 'wheat-free' on a row that's only marked gluten-free
# is the same class of failure as scenario 4 — never go that route.
# (gluten-free ≠ wheat-free 100% — absent 대신 unknown으로 escalate)

@pytest.mark.asyncio
async def test_t12_wheat_alias_no_gluten_marker_returns_unknown():
    client = _patched_get(_jm_cafe_rows())
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Cafe Latte",  # ['dairy'] — no gluten, no wheat
            allergen        = "wheat",
        )
    assert result["ai_script_hint"] == "allergen_unknown"


# ── T13: wheat alias — explicit 'wheat' marker takes priority ────────────────
# Operator can override the alias by tagging a row with 'wheat' directly.

@pytest.mark.asyncio
async def test_t13_wheat_explicit_marker_returns_present():
    rows = _jm_cafe_rows() + [_row("Whole-Wheat Bagel", ["wheat", "gluten"], [])]
    client = _patched_get(rows)
    with patch("app.skills.menu.allergen.httpx.AsyncClient", return_value=client):
        result = await allergen_lookup(
            store_id        = _STORE_ID,
            menu_item_name  = "Whole-Wheat Bagel",
            allergen        = "wheat",
        )
    assert result["ai_script_hint"] == "allergen_present"
