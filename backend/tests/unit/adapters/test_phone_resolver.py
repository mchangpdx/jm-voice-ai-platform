"""Tests for realtime_voice._resolve_store_id 4-tier lookup.

Each tier is exercised independently (cache → DB → constant fallback →
default) plus the DB-failure fallthrough. Cache state is cleared
between tests so order doesn't matter.
(4단계 lookup — tier 별 격리 + DB 실패 fallthrough)
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "placeholder-gemini-key")

from app.api import realtime_voice  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    realtime_voice._PHONE_CACHE.clear()
    yield
    realtime_voice._PHONE_CACHE.clear()


def _http_resp(rows: list[dict]) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json = MagicMock(return_value=rows)
    return r


def _async_client_returning(rows: list[dict]) -> MagicMock:
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__  = AsyncMock(return_value=None)
    instance.get = AsyncMock(return_value=_http_resp(rows))
    return instance


@pytest.mark.asyncio
async def test_none_called_number_returns_default() -> None:
    result = await realtime_voice._resolve_store_id(None)
    assert result == realtime_voice.JM_CAFE_STORE_ID


@pytest.mark.asyncio
async def test_db_hit_takes_priority_over_constant() -> None:
    """If stores.phone matches, DB wins even if the constant has the
    same number mapped — this enables operator-driven re-routing."""
    db_row_id = "DB-FETCHED-STORE-ID"
    instance = _async_client_returning([{"id": db_row_id}])
    with patch(
        "app.api.realtime_voice.httpx.AsyncClient",
        return_value=instance,
    ):
        # +1503... is in PHONE_TO_STORE → JM_CAFE_STORE_ID.
        # DB row overrides.
        result = await realtime_voice._resolve_store_id("+15039941265")
    assert result == db_row_id


@pytest.mark.asyncio
async def test_db_miss_falls_back_to_hardcoded_pizza_pilot() -> None:
    """Empty DB response → constant fallback."""
    instance = _async_client_returning([])
    with patch(
        "app.api.realtime_voice.httpx.AsyncClient",
        return_value=instance,
    ):
        result = await realtime_voice._resolve_store_id("+19714447137")
    assert result == realtime_voice.JM_PIZZA_STORE_ID


@pytest.mark.asyncio
async def test_db_error_falls_back_to_hardcoded() -> None:
    """Supabase outage / timeout → constant map keeps pilots calling."""
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__  = AsyncMock(return_value=None)
    instance.get = AsyncMock(side_effect=Exception("network down"))
    with patch(
        "app.api.realtime_voice.httpx.AsyncClient",
        return_value=instance,
    ):
        result = await realtime_voice._resolve_store_id("+19714447137")
    assert result == realtime_voice.JM_PIZZA_STORE_ID


@pytest.mark.asyncio
async def test_completely_unknown_number_falls_to_default() -> None:
    """Number not in DB and not in PHONE_TO_STORE → JM Cafe default
    (historical pre-pilot behavior preserved)."""
    instance = _async_client_returning([])
    with patch(
        "app.api.realtime_voice.httpx.AsyncClient",
        return_value=instance,
    ):
        result = await realtime_voice._resolve_store_id("+19998887777")
    assert result == realtime_voice.JM_CAFE_STORE_ID


@pytest.mark.asyncio
async def test_cache_skips_db_on_repeat_hit() -> None:
    """Second call within TTL returns from cache — DB client not invoked."""
    db_row_id = "FIRST-CALL-ID"
    instance = _async_client_returning([{"id": db_row_id}])
    with patch(
        "app.api.realtime_voice.httpx.AsyncClient",
        return_value=instance,
    ) as MockHttp:
        # First call populates cache.
        first = await realtime_voice._resolve_store_id("+15035551212")
        # Second call must short-circuit before constructing AsyncClient.
        MockHttp.reset_mock()
        second = await realtime_voice._resolve_store_id("+15035551212")
    assert first == second == db_row_id
    MockHttp.assert_not_called()
