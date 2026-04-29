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


# ── Phase 2-B.1.6 — Receipt Completion (TDD) ──────────────────────────────────
# Loyverse rejects POST /receipts unless these fields are present:
#   store_id (Loyverse internal id, NOT our Supabase UUID)
#   payment_type_id (must come from /payment_types)
#   total_money + payments[].money_amount (must match)
#   line_items[].variant_id, item_id (from menu_items lookup)
# (Loyverse 영수증 필수 필드 — 없으면 MISSING_REQUIRED_PARAMETER 거절)


@pytest.mark.asyncio
async def test_fetch_payment_type_id_returns_first_active_id():
    """GET /payment_types — used to resolve payment_type_id required by /receipts.
    (영수증 POST에 필요한 payment_type_id 조회 — 활성 결제 유형 첫 번째 사용)
    """
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: {
        "payment_types": [
            {"id": "pt-cash-uuid",  "name": "Cash",          "type": "CASH"},
            {"id": "pt-card-uuid",  "name": "Card",          "type": "OTHER"},
        ]
    }

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        a = LoyversePOSAdapter(api_key="k")
        pt_id = await a.fetch_payment_type_id()

    assert pt_id == "pt-cash-uuid"
    assert "/payment_types" in instance.get.call_args.args[0]


@pytest.mark.asyncio
async def test_fetch_payment_type_id_returns_none_on_empty():
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: {"payment_types": []}

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        a = LoyversePOSAdapter(api_key="k")
        assert await a.fetch_payment_type_id() is None


@pytest.mark.asyncio
async def test_fetch_loyverse_store_id_returns_first_store():
    """GET /stores — Loyverse internal store id is required on every receipt.
    Different from our Supabase store UUID. (Loyverse 내부 매장 ID 조회 — 영수증 필수)
    """
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: {
        "stores": [{"id": "lyv-store-1", "name": "JM Cafe"}]
    }

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        a = LoyversePOSAdapter(api_key="k")
        store_id = await a.fetch_loyverse_store_id()

    assert store_id == "lyv-store-1"
    assert "/stores" in instance.get.call_args.args[0]


@pytest.mark.asyncio
async def test_create_pending_includes_required_loyverse_fields():
    """Phase 2-B.1.6 — create_pending must build a complete Loyverse receipt:
    store_id (Loyverse), payment_type_id, total_money, payments[], receipt_type='SALE'.
    Adapter pre-fetches /payment_types and /stores before POST.
    (필수 필드 모두 포함된 완전한 페이로드 구성 + 사전 조회)
    """
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    payment_types_resp = AsyncMock(); payment_types_resp.status_code = 200
    payment_types_resp.json = lambda: {"payment_types": [{"id": "pt-1"}]}

    stores_resp = AsyncMock(); stores_resp.status_code = 200
    stores_resp.json = lambda: {"stores": [{"id": "lyv-store-1"}]}

    receipt_resp = AsyncMock(); receipt_resp.status_code = 200
    receipt_resp.json = lambda: {"receipt_number": "1-2001", "id": "uuid"}

    captured: dict = {}

    async def fake_get(url, **_kw):
        if "/payment_types" in url:  return payment_types_resp
        if "/stores"        in url:  return stores_resp
        return AsyncMock(status_code=404)

    async def fake_post(url, **kwargs):
        captured["url"]     = url
        captured["payload"] = kwargs.get("json")
        return receipt_resp

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(side_effect=fake_get)
        instance.post = AsyncMock(side_effect=fake_post)

        a = LoyversePOSAdapter(api_key="k")
        obj_id = await a.create_pending(
            vertical="restaurant",
            store_id="our-store-uuid",
            payload={
                "pos_object_type": "order",
                "items": [
                    {"variant_id": "v-1", "item_id": "item-1",
                     "quantity": 2, "price": 4.50, "name": "Latte"},
                    {"variant_id": "v-2", "item_id": "item-2",
                     "quantity": 1, "price": 7.00, "name": "Bagel"},
                ],
                "customer_name":  "Michael",
                "customer_phone": "+15035550100",
            },
        )

    assert obj_id == "1-2001"

    body = captured["payload"]
    # Required fields per Loyverse v1.0 spec
    assert body["store_id"]      == "lyv-store-1"
    assert body["receipt_type"]  == "SALE"
    assert body["source"]        == "JM Voice AI"
    assert body["total_money"]   == 16.0  # (2 * 4.50) + (1 * 7.00)

    # payments[] must mirror total_money and reference payment_type_id
    assert isinstance(body["payments"], list) and len(body["payments"]) == 1
    assert body["payments"][0]["payment_type_id"] == "pt-1"
    assert body["payments"][0]["money_amount"]    == 16.0

    # line_items carry variant_id + item_id + price + quantity
    li = body["line_items"]
    assert len(li) == 2
    assert li[0]["variant_id"] == "v-1"
    assert li[0]["item_id"]    == "item-1"
    assert li[0]["quantity"]   == 2
    assert li[0]["price"]      == 4.50


@pytest.mark.asyncio
async def test_create_pending_total_money_overrides_payload_total():
    """Even if caller provides total_cents, adapter recomputes from line_items
    (line_items가 truth source — orderData.total_amount 신뢰 안 함)
    """
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    payment_types_resp = AsyncMock(); payment_types_resp.status_code = 200
    payment_types_resp.json = lambda: {"payment_types": [{"id": "pt-1"}]}
    stores_resp = AsyncMock(); stores_resp.status_code = 200
    stores_resp.json = lambda: {"stores": [{"id": "s-1"}]}
    receipt_resp = AsyncMock(); receipt_resp.status_code = 200
    receipt_resp.json = lambda: {"receipt_number": "1-1", "id": "u"}

    captured: dict = {}

    async def fake_get(url, **_):
        if "/payment_types" in url: return payment_types_resp
        if "/stores"        in url: return stores_resp
        return AsyncMock(status_code=404)

    async def fake_post(url, **kw):
        captured["payload"] = kw.get("json")
        return receipt_resp

    with patch("app.services.bridge.pos.loyverse.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(side_effect=fake_get)
        instance.post = AsyncMock(side_effect=fake_post)

        a = LoyversePOSAdapter(api_key="k")
        await a.create_pending(
            vertical="restaurant", store_id="s",
            payload={
                "pos_object_type": "order",
                "total_cents": 999_99,  # garbage from caller — must be ignored
                "items": [{"variant_id": "v", "quantity": 3, "price": 5.00}],
            },
        )

    assert captured["payload"]["total_money"] == 15.0
    assert captured["payload"]["payments"][0]["money_amount"] == 15.0


@pytest.mark.asyncio
async def test_create_pending_strips_control_chars_from_api_key():
    """API keys stored in DB sometimes have stray \\n / \\t / spaces — must be
    stripped before going into Authorization header (Invalid character error guard).
    (DB API 키의 제어 문자 제거 — 헤더 오류 방지)
    """
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    a = LoyversePOSAdapter(api_key="  key_with_ws\n\t  ")
    assert a.api_key == "key_with_ws"
    assert "\n" not in a._headers()["Authorization"]
    assert "\t" not in a._headers()["Authorization"]
