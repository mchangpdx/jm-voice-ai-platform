"""Tests for input_router dispatch + manual passthrough adapter.

Live network sources (Loyverse, URL) are excluded from this unit suite —
they belong in integration tests so unit runs stay fast and offline.
(network 의존 source는 integration test로 분리)
"""
from __future__ import annotations

import pytest

from app.services.onboarding.input_router import extract


@pytest.mark.asyncio
async def test_unknown_source_type_raises() -> None:
    with pytest.raises(ValueError):
        await extract("unknown", {})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_manual_passthrough_keeps_valid_rows_drops_invalid() -> None:
    result = await extract("manual", {"items": [
        {"name": "Latte",       "price": 5.5, "category": "drinks"},
        {"name": "",            "price": 4.0},          # dropped — no name
        {"name": "Bagel",       "price": None},          # dropped — no price
        {"name": "Croissant",   "price": 4.5},
    ]})
    assert result["source"] == "manual"
    names = [it["name"] for it in result["items"]]
    assert names == ["Latte", "Croissant"]
    assert len(result["warnings"]) == 2


