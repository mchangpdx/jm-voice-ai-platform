# Bridge Server — POS Adapter interface TDD tests
# (Bridge Server — POS 어댑터 인터페이스 TDD 테스트)
#
# POSAdapter abstracts where transactions get persisted.
# Today: SupabasePOSAdapter (writes to existing reservations table)
# Future: QuanticPOSAdapter (writes via Quantic REST after white-label deal)
#
# Both implement the same protocol so vertical_adapter never changes.

import pytest
from unittest.mock import AsyncMock, patch


# ── Interface contract ────────────────────────────────────────────────────────

def test_pos_adapter_base_defines_protocol():
    """Base class declares the 3 methods every concrete adapter must implement."""
    from app.services.bridge.pos.base import POSAdapter

    # Required methods (raises NotImplementedError on base)
    for method in ("create_pending", "mark_paid", "get_object"):
        assert hasattr(POSAdapter, method), f"POSAdapter must define {method}"


@pytest.mark.asyncio
async def test_base_adapter_methods_raise_not_implemented():
    from app.services.bridge.pos.base import POSAdapter

    a = POSAdapter()
    with pytest.raises(NotImplementedError):
        await a.create_pending(vertical="restaurant", store_id="S", payload={})
    with pytest.raises(NotImplementedError):
        await a.mark_paid(vertical="restaurant", object_id="X")
    with pytest.raises(NotImplementedError):
        await a.get_object(vertical="restaurant", object_id="X")


# ── SupabasePOSAdapter — restaurant (reservations) ────────────────────────────

@pytest.mark.asyncio
async def test_supabase_pos_create_reservation_returns_id():
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    fake_resp = AsyncMock(); fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 999}]

    with patch("app.services.bridge.pos.supabase.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        adapter = SupabasePOSAdapter()
        obj_id = await adapter.create_pending(
            vertical="restaurant",
            store_id="STORE-1",
            payload={
                "customer_name":    "Michael Chang",
                "customer_phone":   "+15037079566",
                "party_size":       4,
                "reservation_time": "2026-04-29T02:00:00+00:00",
            },
        )

    # Returns string id (POS may use int or string — adapter normalizes)
    assert obj_id == "999"
    sent = instance.post.call_args_list[0].kwargs["json"]
    assert sent["store_id"] == "STORE-1"
    assert sent["status"] == "pending"


@pytest.mark.asyncio
async def test_supabase_pos_unknown_vertical_raises():
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    a = SupabasePOSAdapter()
    with pytest.raises(ValueError, match="vertical"):
        await a.create_pending(vertical="banking", store_id="S", payload={})


@pytest.mark.asyncio
async def test_supabase_pos_mark_paid_patches_status():
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [{"id": 999, "status": "confirmed"}]

    with patch("app.services.bridge.pos.supabase.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.patch = AsyncMock(return_value=fake_resp)

        adapter = SupabasePOSAdapter()
        await adapter.mark_paid(vertical="restaurant", object_id="999")

        sent = instance.patch.call_args.kwargs["json"]
        assert sent["status"] == "confirmed"


@pytest.mark.asyncio
async def test_supabase_pos_get_reservation_returns_dict_or_none():
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": 999, "customer_name": "X"}]

    with patch("app.services.bridge.pos.supabase.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        adapter = SupabasePOSAdapter()
        row = await adapter.get_object(vertical="restaurant", object_id="999")
        assert row["id"] == 999

    # Empty result → None
    fake_get.json = lambda: []
    with patch("app.services.bridge.pos.supabase.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)
        adapter = SupabasePOSAdapter()
        row = await adapter.get_object(vertical="restaurant", object_id="missing")
        assert row is None


# ── 4-vertical mapping ────────────────────────────────────────────────────────

def test_supabase_pos_table_mapping_covers_4_verticals():
    """Verify each vertical maps to its table name. Locks the contract."""
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    a = SupabasePOSAdapter()
    assert a._table_for_vertical("restaurant")    == "reservations"
    assert a._table_for_vertical("home_services") == "jobs"
    assert a._table_for_vertical("beauty")        == "appointments"
    assert a._table_for_vertical("auto_repair")   == "service_orders"


def test_supabase_pos_paid_status_per_vertical():
    """Each vertical may have a different 'paid' status name (confirmed/scheduled/etc)."""
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    a = SupabasePOSAdapter()
    # Restaurant reservations use 'confirmed' (matches existing schema convention)
    assert a._paid_status_for_vertical("restaurant") == "confirmed"
