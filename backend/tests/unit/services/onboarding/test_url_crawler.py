"""Tests for URL source adapter.

httpx + OpenAI both mocked — these run offline. The key behaviors to
lock in are: graceful degradation on every network failure, correct
HTML→text stripping (script/nav noise out, item text in), and JSON
parsing tolerance via the shared _normalize_item helper.
(network mock — degradation paths + HTML cleaning + JSON tolerance)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.onboarding.sources.url_crawler import (
    _html_to_text,
    extract_from_url,
)


# ── HTML cleaning ────────────────────────────────────────────────────────────

def test_html_to_text_strips_script_and_nav() -> None:
    html = """
    <html><head>
      <script>var x = 1;</script>
      <style>.a {}</style>
    </head>
    <body>
      <nav>Home Menu About</nav>
      <main>
        <h1>Our Menu</h1>
        <p>Margherita Pizza - $16</p>
        <p>Pepperoni - $18</p>
      </main>
      <footer>(c) 2026</footer>
    </body></html>
    """
    text = _html_to_text(html)
    assert "Margherita" in text
    assert "Pepperoni" in text
    # nav + footer + script contents must be gone
    assert "Home Menu About" not in text
    assert "(c) 2026" not in text
    assert "var x" not in text


def test_html_to_text_inserts_line_breaks_on_block_tags() -> None:
    html = "<div>Latte $5</div><div>Mocha $6</div>"
    text = _html_to_text(html)
    # Block tags emit newlines so the LLM sees one row per line.
    assert "\n" in text
    assert "Latte" in text and "Mocha" in text


def test_html_to_text_handles_nested_skip_tags() -> None:
    html = "<nav><span>Inside Nav</span></nav><p>Real Item $5</p>"
    text = _html_to_text(html)
    assert "Inside Nav" not in text
    assert "Real Item" in text


# ── extract_from_url ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.url_crawler.settings.openai_api_key",
        "",
    )
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await extract_from_url("https://example.com")


@pytest.mark.asyncio
async def test_http_error_becomes_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.url_crawler.settings.openai_api_key",
        "sk-test",
    )
    fake_resp = MagicMock()
    fake_resp.status_code = 404
    fake_resp.text = ""

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__  = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_resp)

    with patch(
        "app.services.onboarding.sources.url_crawler.httpx.AsyncClient",
        return_value=fake_client,
    ):
        result = await extract_from_url("https://example.com/missing")

    assert result["items"] == []
    assert any("HTTP 404" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_connection_error_becomes_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.url_crawler.settings.openai_api_key",
        "sk-test",
    )
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__  = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=httpx.ConnectError("no route"))

    with patch(
        "app.services.onboarding.sources.url_crawler.httpx.AsyncClient",
        return_value=fake_client,
    ):
        result = await extract_from_url("https://unreachable.example")

    assert result["items"] == []
    assert any("fetch failed" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_happy_path_extract_pizzeria_html(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.url_crawler.settings.openai_api_key",
        "sk-test",
    )

    # Realistic fragment from an independent pizzeria's static site.
    page_html = """
    <html><body>
      <nav>Home Menu Order Online</nav>
      <main>
        <h1>Atlas Pizza Menu</h1>
        <p>Margherita - $16</p>
        <p>Pepperoni - $18</p>
        <p>Caesar Salad - $11</p>
      </main>
    </body></html>
    """
    fake_http_resp = MagicMock()
    fake_http_resp.status_code = 200
    fake_http_resp.text = page_html

    fake_http_client = MagicMock()
    fake_http_client.__aenter__ = AsyncMock(return_value=fake_http_client)
    fake_http_client.__aexit__  = AsyncMock(return_value=None)
    fake_http_client.get = AsyncMock(return_value=fake_http_resp)

    llm_payload = json.dumps({
        "items": [
            {"name": "Margherita", "price": 16.0, "category": "Pizza", "confidence": 0.95},
            {"name": "Pepperoni",  "price": 18.0, "category": "Pizza", "confidence": 0.95},
            {"name": "Caesar Salad", "price": 11.0, "category": "Salad", "confidence": 0.90},
        ],
        "detected_modifiers": ["size", "toppings"],
    })
    fake_llm_resp = MagicMock()
    fake_llm_resp.choices = [MagicMock(message=MagicMock(content=llm_payload))]
    fake_llm_create = AsyncMock(return_value=fake_llm_resp)

    with patch(
        "app.services.onboarding.sources.url_crawler.httpx.AsyncClient",
        return_value=fake_http_client,
    ), patch(
        "app.services.onboarding.sources.url_crawler.AsyncOpenAI"
    ) as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create = fake_llm_create
        result = await extract_from_url("https://atlas-pizza.example/menu")

    assert result["source"] == "url"
    names = [it["name"] for it in result["items"]]
    assert names == ["Margherita", "Pepperoni", "Caesar Salad"]
    assert result["detected_modifiers"] == ["size", "toppings"]
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_llm_returns_non_json_becomes_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.onboarding.sources.url_crawler.settings.openai_api_key",
        "sk-test",
    )

    fake_http_resp = MagicMock()
    fake_http_resp.status_code = 200
    fake_http_resp.text = "<html><body><p>Item $5</p></body></html>"

    fake_http_client = MagicMock()
    fake_http_client.__aenter__ = AsyncMock(return_value=fake_http_client)
    fake_http_client.__aexit__  = AsyncMock(return_value=None)
    fake_http_client.get = AsyncMock(return_value=fake_http_resp)

    fake_llm_resp = MagicMock()
    fake_llm_resp.choices = [MagicMock(message=MagicMock(content="not json"))]
    fake_llm_create = AsyncMock(return_value=fake_llm_resp)

    with patch(
        "app.services.onboarding.sources.url_crawler.httpx.AsyncClient",
        return_value=fake_http_client,
    ), patch(
        "app.services.onboarding.sources.url_crawler.AsyncOpenAI"
    ) as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create = fake_llm_create
        result = await extract_from_url("https://example.com/menu")

    assert result["items"] == []
    assert any("non-JSON" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_empty_page_becomes_spa_hint(monkeypatch) -> None:
    """Empty body / pure JS shells (Squarespace SPA, React app shell)
    should suggest Playwright as the next step rather than silently
    returning zero items."""
    monkeypatch.setattr(
        "app.services.onboarding.sources.url_crawler.settings.openai_api_key",
        "sk-test",
    )

    fake_http_resp = MagicMock()
    fake_http_resp.status_code = 200
    # SPAs render via JS — initial body is just <div id="root"></div>.
    fake_http_resp.text = "<html><body><div id='root'></div></body></html>"

    fake_http_client = MagicMock()
    fake_http_client.__aenter__ = AsyncMock(return_value=fake_http_client)
    fake_http_client.__aexit__  = AsyncMock(return_value=None)
    fake_http_client.get = AsyncMock(return_value=fake_http_resp)

    with patch(
        "app.services.onboarding.sources.url_crawler.httpx.AsyncClient",
        return_value=fake_http_client,
    ):
        result = await extract_from_url("https://spa.example/")

    assert result["items"] == []
    assert any("Playwright" in w for w in result["warnings"])
