"""Tests for the DB seeder.

Supabase REST is mocked at the httpx.AsyncClient layer so we exercise
the orchestrator + per-seeder payload shaping without touching a real
database. The point is to lock the wire-step heuristic (items↔groups
via applies_to_categories) and the response shape the wizard depends on.
(supabase mock — payload shape + wire heuristic 검증)
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.onboarding.db_seeder import (
    finalize_store,
    wire_items_to_modifier_groups,
)


def _resp(status: int, payload: list[dict] | dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    r.content = b"x"  # truthy so _post calls .json()
    r.text = ""
    return r


@pytest.mark.asyncio
async def test_wire_uses_applies_to_categories_heuristic() -> None:
    """Group with applies_to_categories=['classic_pies'] wires to that
    category's items only — Soda (drinks) gets no rows."""
    item_ids  = {"cheese_pizza": "ITEM-A", "soda": "ITEM-B"}
    group_ids = {"size": "GROUP-SIZE"}
    items_yaml = [
        {"id": "cheese_pizza", "en": "Cheese", "category": "classic_pies"},
        {"id": "soda",         "en": "Soda",   "category": "drinks"},
    ]
    groups = {
        "size": {"applies_to_categories": ["classic_pies"], "options": []},
    }

    posted_payload: list[dict] = []

    class FakeClient:
        async def post(self, *a, **kw):
            posted_payload.extend(kw["json"])
            return _resp(201, kw["json"])

    out = await wire_items_to_modifier_groups(
        FakeClient(), item_ids, group_ids, items_yaml, groups,
    )
    assert out == 1
    assert posted_payload[0]["menu_item_id"] == "ITEM-A"
    assert posted_payload[0]["group_id"] == "GROUP-SIZE"


@pytest.mark.asyncio
async def test_wire_universal_group_applies_to_all_categories() -> None:
    """Group with no applies_to_categories wires to every item."""
    item_ids  = {"a": "A", "b": "B"}
    group_ids = {"extras": "G-EXTRAS"}
    items_yaml = [
        {"id": "a", "en": "A", "category": "x"},
        {"id": "b", "en": "B", "category": "y"},
    ]
    groups = {"extras": {"options": []}}  # no applies_to_categories

    captured: list[dict] = []

    class FakeClient:
        async def post(self, *a, **kw):
            captured.extend(kw["json"])
            return _resp(201, kw["json"])

    count = await wire_items_to_modifier_groups(
        FakeClient(), item_ids, group_ids, items_yaml, groups,
    )
    assert count == 2


@pytest.mark.asyncio
async def test_wire_skips_items_without_category() -> None:
    out = await wire_items_to_modifier_groups(
        MagicMock(),
        {"a": "A"},
        {"g": "G"},
        [{"id": "a", "en": "A"}],  # no category
        {"g": {"applies_to_categories": ["x"], "options": []}},
    )
    assert out == 0


@pytest.mark.asyncio
async def test_finalize_returns_counts_and_next_steps() -> None:
    """Full orchestrator path with the supabase HTTP layer mocked.

    Each route returns enough rows for the orchestrator to compute
    real counts — verifies the response shape the wizard's Step 6
    page reads (counts + next_steps).
    (orchestrator response — counts + next_steps 검증)
    """
    menu_yaml: dict[str, Any] = {
        "items": [
            {"id": "cheese_pizza", "en": "Cheese Pizza", "base_price": 18.0,
             "category": "classic_pies", "base_allergens": ["dairy", "gluten"]},
            {"id": "soda", "en": "Soda", "base_price": 2.5,
             "category": "drinks", "base_allergens": []},
        ],
    }
    modifier_groups_yaml: dict[str, Any] = {
        "groups": {
            "size": {
                "required": True, "min": 1, "max": 1,
                "applies_to_categories": ["classic_pies"],
                "options": [
                    {"id": "14inch", "en": "14 inch", "price_delta": 0.0, "default": True},
                    {"id": "18inch", "en": "18 inch", "price_delta": 8.0},
                ],
            },
        },
    }

    # Map (method, path-suffix) → list of response payloads to return in order.
    responses_by_route: dict[tuple[str, str], list[Any]] = {
        ("POST", "stores"):                   [[{"id": "NEW-STORE-ID"}]],
        ("POST", "menu_items"):               [[
            {"id": "I1", "sku": "cheese_pizza"},
            {"id": "I2", "sku": "soda"},
        ]],
        ("POST", "modifier_groups"):          [[{"id": "G-SIZE", "code": "size"}]],
        ("POST", "modifier_options"):         [[{"id": "O1"}, {"id": "O2"}]],
        ("POST", "menu_item_modifier_groups"):[[{"id": "W1"}]],
        ("GET",  "menu_items"):               [[
            {"name": "Cheese Pizza", "price": 18.0, "category": "classic_pies"},
            {"name": "Soda",         "price": 2.5,  "category": "drinks"},
        ]],
        ("PATCH","stores"):                   [None],
    }

    def _route(method: str, url: str) -> tuple[str, str]:
        # path comes back as full URL; we match on the last segment
        # because supabase URLs end with /rest/v1/<table>
        for key in responses_by_route:
            if key[0] == method and url.rstrip("/").endswith("/" + key[1]):
                return key
        raise AssertionError(f"unexpected {method} {url}")

    async def fake_post(url, **kw):
        key = _route("POST", url)
        payload = responses_by_route[key].pop(0)
        return _resp(201, payload)

    async def fake_get(url, **kw):
        key = _route("GET", url)
        payload = responses_by_route[key].pop(0)
        return _resp(200, payload)

    async def fake_patch(url, **kw):
        key = _route("PATCH", url)
        responses_by_route[key].pop(0)
        r = MagicMock()
        r.status_code = 204
        r.text = ""
        return r

    with patch("app.services.onboarding.db_seeder.httpx.AsyncClient") as MockAC:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__  = AsyncMock(return_value=None)
        instance.post   = AsyncMock(side_effect=fake_post)
        instance.get    = AsyncMock(side_effect=fake_get)
        instance.patch  = AsyncMock(side_effect=fake_patch)
        MockAC.return_value = instance

        result = await finalize_store(
            store_name           = "Test Pizza Shop",
            phone_number         = "+19711234567",
            manager_phone        = "+15037079566",
            vertical             = "pizza",
            menu_yaml            = menu_yaml,
            modifier_groups_yaml = modifier_groups_yaml,
        )

    assert result["store_id"] == "NEW-STORE-ID"
    assert result["counts"]["menu_items"]       == 2
    assert result["counts"]["modifier_groups"]  == 1
    assert result["counts"]["modifier_options"] == 2
    assert result["counts"]["item_group_wires"] == 1
    # next_steps surfaces the Twilio URL + verification call instructions.
    # PHONE_TO_STORE edit is intentionally NOT here — routing is auto via
    # stores.phone DB lookup (see realtime_voice._resolve_store_id).
    next_blob = " ".join(result["next_steps"])
    assert "+19711234567" in next_blob
    assert "twilio" in next_blob.lower()
    assert "verification call" in next_blob.lower()
    assert "PHONE_TO_STORE" not in next_blob
