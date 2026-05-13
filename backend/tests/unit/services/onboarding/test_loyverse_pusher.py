"""Tests for Loyverse direct push.

httpx mocked at the AsyncClient layer. We exercise the three waves
(categories / modifiers / items), the size→variant transform, the
idempotent skip-on-exists path, the modifier_codes filter, and the
LoyversePushError surface on non-2xx.
(httpx mock — 3-wave, size→variant, idempotent skip, error 검증)
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.onboarding.loyverse_pusher import (
    LoyversePushError,
    _item_modifier_codes,
    push_categories,
    push_items,
    push_menu_to_loyverse,
    push_modifiers,
)


def _resp(status: int, body: Any) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    r.text = "" if status < 400 else "boom"
    return r


# ── _item_modifier_codes ────────────────────────────────────────────────────

def test_item_modifier_codes_excludes_size() -> None:
    item = {"category": "pies"}
    groups = {
        "size":   {"applies_to_categories": ["pies"], "options": []},
        "crust":  {"applies_to_categories": ["pies"], "options": []},
        "cheese": {"options": []},  # universal — no applies list
    }
    out = _item_modifier_codes(item, groups)
    assert "size" not in out
    assert set(out) == {"crust", "cheese"}


def test_item_modifier_codes_skips_unmatched_category() -> None:
    item = {"category": "drinks"}
    groups = {"crust": {"applies_to_categories": ["pies"], "options": []}}
    assert _item_modifier_codes(item, groups) == []


def test_item_modifier_codes_no_category_returns_empty() -> None:
    assert _item_modifier_codes({"en": "x"}, {"g": {"options": []}}) == []


# ── push_categories ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_categories_creates_new_and_skips_existing() -> None:
    items = [
        {"category": "classic_pies"},
        {"category": "classic_pies"},  # dedupe
        {"category": "drinks"},
    ]
    existing = {"categories": [{"id": "EXIST-CLASSIC", "name": "Classic Pies"}]}
    created = {"id": "NEW-DRINKS"}

    posted = []

    class FakeClient:
        async def get(self, *a, **kw):
            return _resp(200, existing)
        async def post(self, *a, **kw):
            posted.append(kw["json"])
            return _resp(201, created)

    out = await push_categories(FakeClient(), "tok", items)
    assert out["classic_pies"] == "EXIST-CLASSIC"
    assert out["drinks"] == "NEW-DRINKS"
    # Only one POST — drinks; classic_pies was an existing match.
    assert len(posted) == 1
    assert posted[0]["name"] == "Drinks"


@pytest.mark.asyncio
async def test_push_categories_raises_on_post_failure() -> None:
    items = [{"category": "new_cat"}]

    class FakeClient:
        async def get(self, *a, **kw):
            return _resp(200, {"categories": []})
        async def post(self, *a, **kw):
            return _resp(401, None)

    with pytest.raises(LoyversePushError) as exc_info:
        await push_categories(FakeClient(), "bad-token", items)
    assert exc_info.value.status == 401
    assert exc_info.value.path == "categories"


# ── push_modifiers ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_modifiers_excludes_size_and_clamps_negative_prices() -> None:
    groups = {
        "size": {"options": [{"id": "s", "en": "Small", "price_delta": 0}]},
        "crust": {"options": [
            {"id": "thin",  "en": "Thin",        "price_delta": 0.0},
            {"id": "gf",    "en": "Gluten-Free", "price_delta": 4.0},
        ]},
        "cheese": {"options": [
            {"id": "no_cheese", "en": "No Cheese", "price_delta": -2.0},
        ]},
    }

    captured: list[dict] = []

    class FakeClient:
        async def get(self, *a, **kw):
            return _resp(200, {"modifiers": []})
        async def post(self, *a, **kw):
            captured.append(kw["json"])
            return _resp(201, {"id": f"M-{captured[-1]['name']}"})

    out = await push_modifiers(FakeClient(), "tok", groups, "STORE-X")
    assert "size" not in out
    assert set(out) == {"crust", "cheese"}
    # Negative price clamped to 0.
    cheese_body = next(c for c in captured if c["name"] == "Cheese")
    assert cheese_body["modifier_options"][0]["price"] == 0.0
    # store id attached so cashier UI surfaces the modifier.
    assert cheese_body["stores"] == ["STORE-X"]


# ── push_items ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_items_emits_size_variants_when_group_applies() -> None:
    items_yaml = [{
        "id":         "cheese_pizza",
        "en":         "Cheese Pizza",
        "category":   "pies",
        "base_price": 18.0,
    }]
    groups = {
        "size": {
            "applies_to_categories": ["pies"],
            "options": [
                {"id": "14inch", "en": "14 inch (Small)", "price_delta": 0.0},
                {"id": "18inch", "en": "18 inch (Large)", "price_delta": 8.0},
            ],
        },
    }

    posted_items: list[dict] = []

    class FakeClient:
        async def get(self, *a, **kw):
            return _resp(200, {"items": []})
        async def post(self, *a, **kw):
            body = kw["json"]
            posted_items.append(body)
            return _resp(201, {
                "id":       "I1",
                "variants": [
                    {"sku": v["sku"], "variant_id": f"V-{v['sku']}"}
                    for v in body["variants"]
                ],
            })

    out = await push_items(
        FakeClient(), "tok", items_yaml, groups,
        category_id_map={"pies": "C-PIES"},
        modifier_id_map={},
        loyverse_store_id="STORE-X",
    )
    assert len(posted_items) == 1
    body = posted_items[0]
    assert body["option1_name"] == "Size"
    assert len(body["variants"]) == 2
    # 14" = base ($18), 18" = base + 8 ($26)
    prices = sorted(v["default_price"] for v in body["variants"])
    assert prices == [18.0, 26.0]
    # Output exposes per-sku variant_id mapping
    assert "cheese_pizza_14inch" in out["cheese_pizza"]["variants"]


@pytest.mark.asyncio
async def test_push_items_skips_existing_by_handle() -> None:
    items_yaml = [{"id": "soda", "en": "Soda", "category": "drinks", "base_price": 2.5}]
    existing = {"items": [{
        "id": "EXISTING-ID", "handle": "soda",
        "variants": [{"sku": "soda", "variant_id": "VEXIST"}],
    }]}

    class FakeClient:
        async def get(self, *a, **kw):
            return _resp(200, existing)
        async def post(self, *a, **kw):
            raise AssertionError("must not POST when handle exists")

    out = await push_items(
        FakeClient(), "tok", items_yaml, groups={},
        category_id_map={"drinks": "C-DR"},
        modifier_id_map={},
        loyverse_store_id="STORE-X",
    )
    assert out["soda"]["id"] == "EXISTING-ID"


# ── push_menu_to_loyverse orchestrator ──────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_runs_three_waves_and_returns_counts() -> None:
    menu_yaml: dict = {"items": [
        {"id": "cheese_pizza", "en": "Cheese Pizza", "category": "pies", "base_price": 18.0},
        {"id": "soda",         "en": "Soda",         "category": "drinks", "base_price": 2.5},
    ]}
    mg_yaml: dict = {"groups": {
        "size":  {"applies_to_categories": ["pies"], "options": [
            {"id": "14inch", "en": "14 inch", "price_delta": 0.0},
            {"id": "18inch", "en": "18 inch", "price_delta": 8.0},
        ]},
        "crust": {"applies_to_categories": ["pies"], "options": [
            {"id": "thin", "en": "Thin", "price_delta": 0.0},
        ]},
    }}

    state = {"calls": 0}

    async def fake_get(url, **kw):
        if "categories" in url:  return _resp(200, {"categories": []})
        if "modifiers"  in url:  return _resp(200, {"modifiers":  []})
        if "items"      in url:  return _resp(200, {"items":      []})
        raise AssertionError(url)

    async def fake_post(url, **kw):
        state["calls"] += 1
        body = kw["json"]
        if "categories" in url:
            return _resp(201, {"id": f"C-{body['name']}"})
        if "modifiers"  in url:
            return _resp(201, {"id": f"M-{body['name']}"})
        if "items"      in url:
            return _resp(201, {
                "id":       f"I-{body['handle']}",
                "variants": [
                    {"sku": v["sku"], "variant_id": f"V-{v['sku']}"}
                    for v in body["variants"]
                ],
            })
        raise AssertionError(url)

    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__  = AsyncMock(return_value=None)
    instance.get  = AsyncMock(side_effect=fake_get)
    instance.post = AsyncMock(side_effect=fake_post)

    with patch(
        "app.services.onboarding.loyverse_pusher.httpx.AsyncClient",
        return_value=instance,
    ):
        result = await push_menu_to_loyverse(
            access_token=         "tok",
            loyverse_store_id=    "STORE-X",
            menu_yaml=            menu_yaml,
            modifier_groups_yaml= mg_yaml,
        )

    # 2 categories + 1 modifier (size excluded) + 2 items = 5 POSTs.
    assert state["calls"] == 5
    assert result["counts"]["categories"] == 2
    assert result["counts"]["modifiers"]  == 1
    assert result["counts"]["items"]      == 2


@pytest.mark.asyncio
async def test_dry_run_skips_posts_returns_estimated_counts() -> None:
    """dry_run=True must never POST to Loyverse; returns counts + ping."""
    menu_yaml = {"items": [
        {"id": "p1", "en": "Pizza 1", "category": "pies",   "base_price": 18.0},
        {"id": "p2", "en": "Pizza 2", "category": "pies",   "base_price": 20.0},
        {"id": "d1", "en": "Drink",   "category": "drinks", "base_price": 2.5},
    ]}
    mg_yaml = {"groups": {
        "size":  {"applies_to_categories": ["pies"], "options": []},
        "crust": {"applies_to_categories": ["pies"], "options": []},
    }}

    ping_resp = MagicMock(status_code=200)
    ping_resp.json = MagicMock(return_value={"name": "Test Merchant"})
    ping_resp.text = ""

    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__  = AsyncMock(return_value=None)
    instance.get  = AsyncMock(return_value=ping_resp)
    instance.post = AsyncMock(side_effect=AssertionError("dry_run must not POST"))

    with patch(
        "app.services.onboarding.loyverse_pusher.httpx.AsyncClient",
        return_value=instance,
    ):
        result = await push_menu_to_loyverse(
            access_token         = "tok",
            loyverse_store_id    = "STORE-X",
            menu_yaml            = menu_yaml,
            modifier_groups_yaml = mg_yaml,
            dry_run              = True,
        )

    assert result["dry_run"] is True
    # 2 unique categories (pies, drinks), 1 modifier (size excluded), 3 items.
    assert result["counts"] == {"categories": 2, "modifiers": 1, "items": 3}
    assert result["loyverse_ping"]["ok"] is True
    assert "Test Merchant" in result["loyverse_ping"]["message"]
    instance.post.assert_not_called()
