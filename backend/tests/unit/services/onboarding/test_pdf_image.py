"""Tests for the vision-based image source adapter.

Network is mocked — these are unit tests. The wins we want to lock in:
  - JSON parse failures degrade gracefully to warnings (one bad page
    doesn't sink the run).
  - Cross-page dedupe on (name, price, size_hint).
  - String-price and percent-confidence coercion (real model misfires).
  - Empty input returns an empty extraction, not an error.
(network mock — JSON 실패/dedupe/coercion/empty path 검증)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.onboarding.sources.pdf_image import (
    _dedupe_across_pages,
    _normalize_item,
    extract_from_images,
)


def test_normalize_drops_empty_name() -> None:
    assert _normalize_item({"name": "", "price": 5.0}, "x.jpg") is None


def test_normalize_coerces_string_price_and_percent_confidence() -> None:
    out = _normalize_item(
        {"name": "Latte", "price": "$5.50", "confidence": 95},
        "x.jpg",
    )
    assert out is not None
    assert out["price"] == 5.50
    assert out["confidence"] == 0.95


def test_normalize_drops_non_numeric_price() -> None:
    out = _normalize_item({"name": "Mystery", "price": "tbd"}, "x.jpg")
    assert out is None


def test_dedupe_keeps_distinct_variants_drops_exact_duplicates() -> None:
    rows = [
        {"name": "Big Joe", "price": 26.0, "size_hint": "14 inch", "confidence": 0.95},
        {"name": "Big Joe", "price": 34.0, "size_hint": "18 inch", "confidence": 0.95},
        {"name": "Big Joe", "price": 26.0, "size_hint": "14 inch", "confidence": 0.90},
    ]
    out = _dedupe_across_pages(rows)  # type: ignore[arg-type]
    assert len(out) == 2
    prices = sorted(it["price"] for it in out)
    assert prices == [26.0, 34.0]


@pytest.mark.asyncio
async def test_empty_input_returns_empty_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.pdf_image.settings.openai_api_key",
        "sk-test",
    )
    result = await extract_from_images([])
    assert result["source"] == "image"
    assert result["items"] == []
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_missing_api_key_raises_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.pdf_image.settings.openai_api_key",
        "",
    )
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await extract_from_images(["/tmp/whatever.jpg"])


@pytest.mark.asyncio
async def test_vision_call_with_two_pages_dedupes_and_collects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    # Two fake image files (content unread because we mock the API call).
    img_a = tmp_path / "page1.jpg"
    img_b = tmp_path / "page2.jpg"
    img_a.write_bytes(b"\xff\xd8\xff\xe0fake1")
    img_b.write_bytes(b"\xff\xd8\xff\xe0fake2")

    monkeypatch.setattr(
        "app.services.onboarding.sources.pdf_image.settings.openai_api_key",
        "sk-test",
    )

    page1_response = MagicMock()
    page1_response.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "items": [
            {"name": "Big Joe", "price": 26.0, "size_hint": "14 inch", "confidence": 0.95},
            {"name": "Big Joe", "price": 34.0, "size_hint": "18 inch", "confidence": 0.95},
        ],
        "detected_modifiers": ["size", "crust"],
    })))]
    page2_response = MagicMock()
    page2_response.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "items": [
            # Duplicate Big Joe 14" — must be deduped.
            {"name": "Big Joe", "price": 26.0, "size_hint": "14 inch", "confidence": 0.90},
            {"name": "Cheese Pizza", "price": 18.0, "size_hint": "14 inch", "confidence": 0.92},
        ],
        "detected_modifiers": ["size"],
    })))]
    mock_create = AsyncMock(side_effect=[page1_response, page2_response])

    with patch("app.services.onboarding.sources.pdf_image.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = mock_create
        result = await extract_from_images([str(img_a), str(img_b)])

    names = sorted(it["name"] for it in result["items"])
    assert names == ["Big Joe", "Big Joe", "Cheese Pizza"]
    # First-seen-order modifier dedupe: size then crust.
    assert result["detected_modifiers"] == ["size", "crust"]
    # One dedupe warning, no error warnings.
    assert any("deduped" in w for w in result["warnings"])
    assert not any("failed" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_non_json_response_becomes_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    img = tmp_path / "page.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake")
    monkeypatch.setattr(
        "app.services.onboarding.sources.pdf_image.settings.openai_api_key",
        "sk-test",
    )

    bad_response = MagicMock()
    bad_response.choices = [MagicMock(message=MagicMock(content="not json at all"))]
    mock_create = AsyncMock(return_value=bad_response)

    with patch("app.services.onboarding.sources.pdf_image.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = mock_create
        result = await extract_from_images([str(img)])

    assert result["items"] == []
    assert any("non-JSON" in w for w in result["warnings"])
