# pos/factory.py — store-based adapter selection TDD
# (pos/factory.py — 매장 기반 어댑터 선택 TDD)
#
# Each store has a pos_provider column ("supabase" | "loyverse" | "quantic" | future).
# Factory reads it and returns the correct adapter instance. Orchestration code
# (flows.py) calls get_pos_adapter_for_store(store_id) instead of hardcoding.
#
# Default: "supabase" (current behavior — no breaking change for existing stores).

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_factory_returns_supabase_adapter_when_provider_supabase():
    from app.services.bridge.pos import factory
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": "S1", "pos_provider": "supabase"}]

    with patch("app.services.bridge.pos.factory.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        adapter = await factory.get_pos_adapter_for_store("S1")
        assert isinstance(adapter, SupabasePOSAdapter)


@pytest.mark.asyncio
async def test_factory_returns_loyverse_adapter_when_provider_loyverse():
    from app.services.bridge.pos import factory
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": "S2", "pos_provider": "loyverse",
                              "pos_api_key": "store_specific_key"}]

    with patch("app.services.bridge.pos.factory.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        adapter = await factory.get_pos_adapter_for_store("S2")
        assert isinstance(adapter, LoyversePOSAdapter)
        # Per-store api_key takes precedence over global settings
        assert adapter.api_key == "store_specific_key"


@pytest.mark.asyncio
async def test_factory_defaults_to_supabase_when_provider_missing():
    """Stores without a pos_provider column value default to Supabase (current behavior)."""
    from app.services.bridge.pos import factory
    from app.services.bridge.pos.supabase import SupabasePOSAdapter

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": "S3", "pos_provider": None}]

    with patch("app.services.bridge.pos.factory.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        adapter = await factory.get_pos_adapter_for_store("S3")
        assert isinstance(adapter, SupabasePOSAdapter)


@pytest.mark.asyncio
async def test_factory_raises_on_unknown_provider():
    from app.services.bridge.pos import factory

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": "S4", "pos_provider": "TosuPOS_2099"}]

    with patch("app.services.bridge.pos.factory.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        with pytest.raises(ValueError, match="unknown pos_provider"):
            await factory.get_pos_adapter_for_store("S4")


@pytest.mark.asyncio
async def test_factory_raises_when_store_not_found():
    from app.services.bridge.pos import factory

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: []

    with patch("app.services.bridge.pos.factory.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        with pytest.raises(LookupError, match="store"):
            await factory.get_pos_adapter_for_store("MISSING")
