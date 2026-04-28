# LoyversePOSAdapter — TDD tests
# (Loyverse POS 어댑터 TDD)
#
# Loyverse REST API: https://api.loyverse.com/v1.0
# Auth: Bearer token via X-Tenant-ID-style header
# Endpoints used:
#   - POST /receipts            — create order (Loyverse calls them "receipts")
#   - GET  /items?limit=250     — fetch full menu
#   - GET  /categories          — fetch category names
#   - GET  /receipts/{id}       — fetch a receipt by id
#
# Adapter pattern: implements POSAdapter interface (create_pending / mark_paid /
# get_object) — same as SupabasePOSAdapter — so flows.py code never branches on
# which POS is wired underneath.
#
# Reservations: Loyverse has no reservation object → for vertical='restaurant' +
# pos_object_type='reservation', adapter raises NotSupported. Orchestration falls
# back to SupabasePOSAdapter for that case (vertical_adapter logic in factory).

import pytest
from unittest.mock import AsyncMock, patch


# ── Construction ──────────────────────────────────────────────────────────────

def test_loyverse_adapter_requires_api_key():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter
    # Either explicit api_key arg or settings.loyverse_api_key fallback
    a = LoyversePOSAdapter(api_key="test_key_abc")
    assert a.api_key == "test_key_abc"


def test_loyverse_adapter_falls_back_to_settings_api_key():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter
    # When no key is passed, adapter reads settings.loyverse_api_key
    a = LoyversePOSAdapter()
    # Either set via .env or empty — either way the attribute exists
    assert hasattr(a, "api_key")


def test_loyverse_adapter_raises_when_no_key_available():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter
    # When key is empty AND no settings fallback, fail fast
    with patch("app.services.bridge.pos.loyverse.settings") as mock_settings:
        mock_settings.loyverse_api_key = ""
        mock_settings.loyverse_api_url = "https://api.loyverse.com/v1.0"
        with pytest.raises(ValueError, match="api_key"):
            LoyversePOSAdapter()


# ── create_pending — POST /receipts ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_pending_order_posts_to_receipts():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.json = lambda: {"receipt_number": "1-1042", "id": "rec-uuid-1"}

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        a = LoyversePOSAdapter(api_key="key123")
        obj_id = await a.create_pending(
            vertical="restaurant",
            store_id="STORE-1",
            payload={
                "pos_object_type": "order",
                "items": [{"variant_id": "v-1", "quantity": 2, "price": 12.50}],
                "customer_name":  "Michael Chang",
                "customer_phone": "+15037079566",
            },
        )

    # Returns receipt_number (POS-issued external id)
    assert obj_id == "1-1042"

    # POST to /receipts with Bearer auth
    url = instance.post.call_args.args[0]
    assert "/receipts" in url
    headers = instance.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer key123"


@pytest.mark.asyncio
async def test_create_pending_for_reservation_raises_not_supported():
    """Loyverse has no reservation object — adapter must signal this clearly so
    factory can fall back to SupabasePOSAdapter."""
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter, NotSupported

    a = LoyversePOSAdapter(api_key="key")
    with pytest.raises(NotSupported, match="reservation"):
        await a.create_pending(
            vertical="restaurant",
            store_id="STORE-1",
            payload={"pos_object_type": "reservation"},
        )


@pytest.mark.asyncio
async def test_create_pending_handles_4xx_from_loyverse():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_resp = AsyncMock()
    fake_resp.status_code = 401
    fake_resp.text = '{"error":"unauthorized"}'

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        a = LoyversePOSAdapter(api_key="bad")
        with pytest.raises(RuntimeError, match="401"):
            await a.create_pending(
                vertical="restaurant",
                store_id="S",
                payload={"pos_object_type": "order", "items": []},
            )


# ── mark_paid — typically Loyverse marks paid at POST time ────────────────────

@pytest.mark.asyncio
async def test_mark_paid_is_noop_when_already_paid_at_creation():
    """Loyverse receipts are paid at POST time. mark_paid is a no-op for now;
    Phase 2-B will add update support if Loyverse exposes a status endpoint."""
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    a = LoyversePOSAdapter(api_key="k")
    # Should not raise; should not make any HTTP call
    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        await a.mark_paid(vertical="restaurant", object_id="1-1042")
        MockClient.assert_not_called()


# ── get_object — GET /receipts/{id} ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_object_returns_receipt():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: {"receipt_number": "1-1042", "total_money": 25.00}

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        a = LoyversePOSAdapter(api_key="k")
        row = await a.get_object(vertical="restaurant", object_id="1-1042")

    assert row["receipt_number"] == "1-1042"
    url = instance.get.call_args.args[0]
    assert "/receipts/1-1042" in url


@pytest.mark.asyncio
async def test_get_object_returns_none_on_404():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_get = AsyncMock(); fake_get.status_code = 404

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        a = LoyversePOSAdapter(api_key="k")
        row = await a.get_object(vertical="restaurant", object_id="missing")
        assert row is None


# ── fetch_menu — Loyverse-specific capability beyond base interface ───────────

@pytest.mark.asyncio
async def test_fetch_menu_returns_normalized_items():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: {
        "items": [
            {
                "id": "item-1", "item_name": "Latte",
                "category_id": "cat-1", "color": "BLUE",
                "variants": [
                    {"variant_id": "v-1", "sku": "LAT-S",
                     "option1_value": "Small", "default_price": 4.50,
                     "stores": [{"price": 4.50, "in_stock": 100}]}
                ]
            }
        ]
    }

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        a = LoyversePOSAdapter(api_key="k")
        items = await a.fetch_menu()

    assert len(items) == 1
    item = items[0]
    assert item["pos_item_id"] == "item-1"
    assert item["name"]        == "Latte"
    assert item["variants"][0]["price"]          == 4.50
    assert item["variants"][0]["stock_quantity"] == 100
