"""N1 fix (2026-05-18) — wire_items_to_modifier_groups must accept both
`applies_to` (Beauty / shorter form) and `applies_to_categories`
(cafe / pizza / mexican / kbbq historical form) yaml keys.
(N1 fix — yaml 키 두 가지 모두 인식 회귀 가드)

Live regression: JM Beauty Salon Calls CA012751f7 + CA664fb622
(2026-05-18). Wire produced 90 universal rows (5 groups × 18 items)
instead of 33 category-filtered rows because Beauty modifier_groups.yaml
uses the `applies_to` key while the seeder only read
`applies_to_categories`. The Korean Manicure caller went through 5
extraneous modifier turns (hair_length / toner / blow_dry / polish /
facial_addon all asked) before reaching CONFIRM.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.onboarding.db_seeder import wire_items_to_modifier_groups


def _capture_wire_calls():
    """Patch _post and capture the payload that lands in
    menu_item_modifier_groups. Returns (start, stop, captured) so each
    test can introspect the wire payload it produced.
    (wire payload 캡처용 fixture helper)"""
    captured: dict[str, Any] = {"payloads": []}

    async def fake_post(client, table, payload, **kw):
        captured["payloads"].append((table, payload))
        # Mimic the real _post return shape — list of inserted rows
        return payload

    patcher = patch(
        "app.services.onboarding.db_seeder._post",
        new=AsyncMock(side_effect=fake_post),
    )
    return patcher, captured


# ── Fixture data ───────────────────────────────────────────────────────────


_BEAUTY_ITEMS = [
    {"id": "haircut_women",     "category": "haircut"},
    {"id": "balayage",          "category": "color"},
    {"id": "manicure_classic",  "category": "nails"},
    {"id": "facial_signature",  "category": "spa"},
]

_BEAUTY_ITEM_IDS = {
    "haircut_women":    "db-haircut-women",
    "balayage":         "db-balayage",
    "manicure_classic": "db-manicure-classic",
    "facial_signature": "db-facial-signature",
}

_BEAUTY_GROUPS_APPLIES_TO = {   # Beauty yaml shape — short key
    "hair_length":  {"applies_to": ["haircut", "color", "treatment"]},
    "toner":        {"applies_to": ["color"]},
    "polish":       {"applies_to": ["nails"]},
    "facial_addon": {"applies_to": ["spa"]},
    "universal":    {},          # no applies-to → wires against everything
}

_CAFE_GROUPS_APPLIES_TO_CATEGORIES = {  # legacy yaml shape — long key
    "size":        {"applies_to_categories": ["espresso", "non_espresso"]},
    "temperature": {"applies_to_categories": ["espresso", "non_espresso"]},
    "milk":        {"applies_to_categories": ["espresso"]},
}

_CAFE_ITEMS = [
    {"id": "drip_coffee",    "category": "espresso"},
    {"id": "cold_brew",      "category": "non_espresso"},
    {"id": "croissant",      "category": "pastry"},
]
_CAFE_ITEM_IDS = {
    "drip_coffee": "db-drip",
    "cold_brew":   "db-cold-brew",
    "croissant":   "db-croissant",
}


# ── applies_to (Beauty shape) gets honored ─────────────────────────────────


@pytest.mark.asyncio
async def test_wire_honors_short_applies_to_key():
    """Beauty modifier_groups.yaml uses `applies_to` (no _categories suffix).
    Must produce category-filtered wires, not universal.
    (yaml short key 인식 — Beauty 회귀 가드)"""
    patcher, captured = _capture_wire_calls()
    patcher.start()
    try:
        group_ids = {code: f"gid-{code}" for code in _BEAUTY_GROUPS_APPLIES_TO}
        wire_count = await wire_items_to_modifier_groups(
            client     = None,
            item_ids   = _BEAUTY_ITEM_IDS,
            group_ids  = group_ids,
            items_yaml = _BEAUTY_ITEMS,
            groups     = _BEAUTY_GROUPS_APPLIES_TO,
        )
    finally:
        patcher.stop()

    # Build the (item_id, group_id) set the seeder asked to wire.
    payloads = captured["payloads"]
    assert len(payloads) == 1
    rows = payloads[0][1]
    pairs = {(r["menu_item_id"], r["group_id"]) for r in rows}

    # Expected per fixture:
    #   haircut_women (haircut) → hair_length + universal
    #   balayage (color)        → hair_length + toner + universal
    #   manicure_classic (nails)→ polish + universal
    #   facial_signature (spa)  → facial_addon + universal
    # Total: 2 + 3 + 2 + 2 = 9
    assert wire_count == 9
    assert ("db-haircut-women",    "gid-hair_length")  in pairs
    assert ("db-haircut-women",    "gid-polish")       not in pairs    # critical
    assert ("db-manicure-classic", "gid-polish")       in pairs
    assert ("db-manicure-classic", "gid-hair_length")  not in pairs    # critical
    assert ("db-manicure-classic", "gid-universal")    in pairs
    assert ("db-facial-signature", "gid-facial_addon") in pairs
    assert ("db-facial-signature", "gid-hair_length")  not in pairs    # critical


# ── applies_to_categories (legacy shape) still works ───────────────────────


@pytest.mark.asyncio
async def test_wire_honors_legacy_applies_to_categories_key():
    """Existing cafe / pizza / mexican / kbbq yaml must keep working — the
    short-key fallback never overrides the long-key value.
    (legacy key — cafe/pizza 회귀 zero 가드)"""
    patcher, captured = _capture_wire_calls()
    patcher.start()
    try:
        group_ids = {code: f"gid-{code}" for code in _CAFE_GROUPS_APPLIES_TO_CATEGORIES}
        wire_count = await wire_items_to_modifier_groups(
            client     = None,
            item_ids   = _CAFE_ITEM_IDS,
            group_ids  = group_ids,
            items_yaml = _CAFE_ITEMS,
            groups     = _CAFE_GROUPS_APPLIES_TO_CATEGORIES,
        )
    finally:
        patcher.stop()

    rows = captured["payloads"][0][1]
    pairs = {(r["menu_item_id"], r["group_id"]) for r in rows}

    # drip_coffee (espresso)    → size + temperature + milk
    # cold_brew (non_espresso)  → size + temperature
    # croissant (pastry)        → none
    # Total: 3 + 2 + 0 = 5
    assert wire_count == 5
    assert ("db-drip",       "gid-size")        in pairs
    assert ("db-drip",       "gid-milk")        in pairs
    assert ("db-cold-brew",  "gid-milk")        not in pairs   # critical
    assert ("db-croissant",  "gid-size")        not in pairs   # critical


# ── Both keys present → short key still readable, long key wins ────────────


@pytest.mark.asyncio
async def test_wire_prefers_applies_to_categories_when_both_keys_set():
    """If a future yaml accidentally sets both keys, the long key wins
    (it's the historical canonical name). Defends against operator
    half-migrating a yaml and silently breaking wires.
    (두 키 동시 set 시 long key 우선 — 마이그레이션 안전)"""
    patcher, captured = _capture_wire_calls()
    patcher.start()
    try:
        # applies_to=[haircut] but applies_to_categories=[color]
        groups = {
            "conflict": {
                "applies_to":            ["haircut"],
                "applies_to_categories": ["color"],
            },
        }
        await wire_items_to_modifier_groups(
            client     = None,
            item_ids   = _BEAUTY_ITEM_IDS,
            group_ids  = {"conflict": "gid-conflict"},
            items_yaml = _BEAUTY_ITEMS,
            groups     = groups,
        )
    finally:
        patcher.stop()

    rows = captured["payloads"][0][1] if captured["payloads"] else []
    pairs = {(r["menu_item_id"], r["group_id"]) for r in rows}

    # applies_to_categories=color wins; only balayage wires (it's color).
    assert pairs == {("db-balayage", "gid-conflict")}


# ── Universal group (no applies-to keys at all) ────────────────────────────


@pytest.mark.asyncio
async def test_wire_universal_group_wires_all_items_with_category():
    """A group with neither key wires against every categorised item.
    Behavior unchanged from pre-fix — universal semantics preserved.
    (universal 동작 보존)"""
    patcher, captured = _capture_wire_calls()
    patcher.start()
    try:
        groups = {"universal": {}}
        wire_count = await wire_items_to_modifier_groups(
            client     = None,
            item_ids   = _BEAUTY_ITEM_IDS,
            group_ids  = {"universal": "gid-universal"},
            items_yaml = _BEAUTY_ITEMS,
            groups     = groups,
        )
    finally:
        patcher.stop()

    assert wire_count == len(_BEAUTY_ITEMS)
