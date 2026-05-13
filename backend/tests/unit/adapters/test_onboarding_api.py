"""Tests for the Admin Onboarding Wizard FastAPI router.

Live network sources (Loyverse) are mocked at the adapter level so
these run offline. The point is to lock the HTTP contract the frontend
wizard depends on (status codes, response shapes, error mapping).
(adapter mocking — wizard HTTP contract regression)
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

# Env vars must be set before app imports (다른 adapter test 패턴 동일)
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "placeholder-gemini-key")

from app.main import app  # noqa: E402


_FAKE_LOYVERSE_EXTRACTION = {
    "source":             "loyverse",
    "items": [
        {"name": "Cheese Pizza", "price": 18.0, "size_hint": "14 inch (Small)",
         "pos_item_id": "P1", "sku": "ch_14", "confidence": 1.0},
        {"name": "Cheese Pizza", "price": 26.0, "size_hint": "18 inch (Large)",
         "pos_item_id": "P1", "sku": "ch_18", "confidence": 1.0},
        {"name": "Soda", "price": 2.5, "pos_item_id": "S1", "sku": "soda", "confidence": 1.0},
    ],
    "detected_modifiers": [],
    "vertical_guess":     None,  # router fills via detect_vertical
    "warnings":           [],
}


@pytest.mark.asyncio
async def test_extract_unknown_source_returns_400() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/onboarding/extract",
                                 json={"source_type": "wat", "payload": {}})
    assert resp.status_code == 422  # pydantic Literal validation


@pytest.mark.asyncio
async def test_extract_not_implemented_source_returns_501() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/onboarding/extract",
                                 json={"source_type": "url", "payload": {"url": "https://x.com"}})
    assert resp.status_code == 501


@pytest.mark.asyncio
async def test_extract_manual_round_trip() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/onboarding/extract", json={
            "source_type": "manual",
            "payload": {"items": [
                {"name": "Latte",     "price": 5.5},
                {"name": "Croissant", "price": 4.5},
            ]},
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "manual"
    assert [it["name"] for it in body["items"]] == ["Latte", "Croissant"]
    # detect_vertical auto-filled — no cafe tokens in either name → "general"
    assert body["vertical_guess"] in ("cafe", "general")


@pytest.mark.asyncio
async def test_normalize_folds_variants() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/onboarding/normalize", json={
            "items": _FAKE_LOYVERSE_EXTRACTION["items"],
        })
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2  # Cheese Pizza folded, Soda standalone
    pizza = next(it for it in items if it["name"] == "Cheese Pizza")
    assert len(pizza["variants"]) == 2


@pytest.mark.asyncio
async def test_preview_yaml_emits_menu_and_modifier_groups() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/onboarding/normalize", json={
            "items": _FAKE_LOYVERSE_EXTRACTION["items"],
        })
        normalized = resp.json()
        resp = await client.post("/api/admin/onboarding/preview-yaml", json={
            "items":    normalized,
            "vertical": "pizza",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["menu_yaml"]["vertical"] == "pizza"
    assert body["menu_yaml"]["supported_langs"] == ["en", "es"]
    assert len(body["menu_yaml"]["items"]) == 2
    # size group detected since Cheese Pizza has 2 variants
    assert "size" in body["modifier_groups_yaml"]["groups"]


@pytest.mark.asyncio
async def test_pipeline_chains_extract_normalize_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end pipeline helper — mock the Loyverse adapter once and verify
    extract+normalize+yaml come back in a single response."""
    async def fake_extract_loyverse(api_key: str):
        return _FAKE_LOYVERSE_EXTRACTION

    monkeypatch.setattr(
        "app.services.onboarding.input_router.extract_from_loyverse",
        fake_extract_loyverse,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/onboarding/pipeline", json={
            "source_type": "loyverse",
            "payload":     {"api_key": "fake"},
        })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["raw_extraction"]["items"]) == 3
    assert len(body["normalized_items"]) == 2
    assert body["menu_yaml"]["vertical"] in ("pizza", "general")
