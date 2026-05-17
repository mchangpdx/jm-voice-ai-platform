"""Phase 3.2 — service_lookup tool unit tests.
(Phase 3.2 — service_lookup 단위 테스트)

Covers:
  - Tool def shape (Gemini function_declarations contract)
  - Exact + fuzzy matching against menu_items (service rows)
  - service_kind=null rows excluded (food items don't leak into beauty)
  - HonestUnknown hints (missing duration / missing price / not found)
  - REST error fallback (no raise, returns service_not_found)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.skills.appointment.service_lookup import (
    SERVICE_LOOKUP_TOOL_DEF,
    service_lookup,
)


# ── Tool def shape ──────────────────────────────────────────────────────────


def test_tool_def_shape_is_gemini_compatible():
    assert "function_declarations" in SERVICE_LOOKUP_TOOL_DEF
    decls = SERVICE_LOOKUP_TOOL_DEF["function_declarations"]
    assert len(decls) == 1
    fn = decls[0]
    assert fn["name"] == "service_lookup"
    assert "description" in fn
    params = fn["parameters"]
    assert params["required"] == ["service_name"]
    assert "service_name" in params["properties"]


# ── Helpers ────────────────────────────────────────────────────────────────


def _mock_rest(rows: list[dict], *, status: int = 200):
    """Build a patched httpx.AsyncClient whose GET returns `rows`."""
    mock_resp = AsyncMock()
    mock_resp.status_code = status
    mock_resp.json = lambda: rows

    patcher = patch("app.skills.appointment.service_lookup.httpx.AsyncClient")
    ac_cls = patcher.start()
    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_resp)
    ac_cls.return_value.__aenter__.return_value = client
    return patcher, client


# ── Match flows ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_match_returns_service_found():
    rows = [
        {"name": "Haircut", "duration_min": 45, "price": 55.0, "service_kind": "beauty"},
    ]
    patcher, _ = _mock_rest(rows)
    try:
        out = await service_lookup(store_id="s1", service_name="haircut")
    finally:
        patcher.stop()
    assert out["ai_script_hint"] == "service_found"
    assert out["matched_name"] == "Haircut"
    assert out["duration_min"] == 45
    assert out["price"] == 55.0
    assert out["service_kind"] == "beauty"


@pytest.mark.asyncio
async def test_fuzzy_match_above_cutoff():
    """'balayag' (typo) → 'Balayage' via 0.7 cutoff."""
    rows = [
        {"name": "Balayage", "duration_min": 180, "price": 220.0, "service_kind": "beauty"},
        {"name": "Manicure", "duration_min": 30,  "price": 25.0,  "service_kind": "beauty"},
    ]
    patcher, _ = _mock_rest(rows)
    try:
        out = await service_lookup(store_id="s1", service_name="balayag")
    finally:
        patcher.stop()
    assert out["ai_script_hint"] == "service_found"
    assert out["matched_name"] == "Balayage"


@pytest.mark.asyncio
async def test_no_match_returns_not_found():
    rows = [
        {"name": "Haircut", "duration_min": 45, "price": 55.0, "service_kind": "beauty"},
    ]
    patcher, _ = _mock_rest(rows)
    try:
        out = await service_lookup(store_id="s1", service_name="oil change")
    finally:
        patcher.stop()
    assert out["ai_script_hint"] == "service_not_found"
    assert out["matched_name"] == "oil change"
    assert out["duration_min"] is None
    assert out["price"] is None


@pytest.mark.asyncio
async def test_empty_service_name_returns_not_found_without_db():
    """Empty input shortcircuits — must not even attempt REST."""
    with patch(
        "app.skills.appointment.service_lookup.httpx.AsyncClient"
    ) as ac_cls:
        out = await service_lookup(store_id="s1", service_name="   ")
        ac_cls.assert_not_called()
    assert out["ai_script_hint"] == "service_not_found"


# ── HonestUnknown hints ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_duration_returns_unknown_duration_hint():
    rows = [
        {"name": "Consultation", "duration_min": None, "price": 0, "service_kind": "beauty"},
    ]
    patcher, _ = _mock_rest(rows)
    try:
        out = await service_lookup(store_id="s1", service_name="consultation")
    finally:
        patcher.stop()
    assert out["ai_script_hint"] == "service_unknown_duration"
    assert out["matched_name"] == "Consultation"


@pytest.mark.asyncio
async def test_missing_price_returns_unknown_price_hint():
    rows = [
        {"name": "Color Quote", "duration_min": 30, "price": None, "service_kind": "beauty"},
    ]
    patcher, _ = _mock_rest(rows)
    try:
        out = await service_lookup(store_id="s1", service_name="color quote")
    finally:
        patcher.stop()
    assert out["ai_script_hint"] == "service_unknown_price"


# ── REST resilience ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rest_5xx_falls_back_to_not_found():
    patcher, _ = _mock_rest([], status=500)
    try:
        out = await service_lookup(store_id="s1", service_name="haircut")
    finally:
        patcher.stop()
    assert out["ai_script_hint"] == "service_not_found"


@pytest.mark.asyncio
async def test_rest_exception_falls_back_to_not_found():
    """httpx raising mid-call must not propagate — degrade to not_found."""
    with patch(
        "app.skills.appointment.service_lookup.httpx.AsyncClient"
    ) as ac_cls:
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("network down"))
        ac_cls.return_value.__aenter__.return_value = client
        out = await service_lookup(store_id="s1", service_name="haircut")
    assert out["ai_script_hint"] == "service_not_found"


# ── service_kind filter (server-side) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rest_call_filters_service_kind_not_null():
    """The REST query must include service_kind=not.is.null so food items
    from a multi-vertical store never appear in the service catalog.
    (서버측 service_kind not null 필터 — 음식 row 차단 검증)"""
    rows = [{"name": "Haircut", "duration_min": 45, "price": 55.0, "service_kind": "beauty"}]
    patcher, client = _mock_rest(rows)
    try:
        await service_lookup(store_id="s1", service_name="haircut")
    finally:
        patcher.stop()
    # client.get called with params containing the service_kind filter
    _, kwargs = client.get.call_args
    params = kwargs.get("params") or {}
    assert params.get("service_kind") == "not.is.null"
    assert params.get("store_id") == "eq.s1"
