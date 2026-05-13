"""URL source adapter — fetch a public menu page and extract items.

Three-stage pipeline:
  1. httpx GET (with a realistic User-Agent + redirects + size cap),
  2. stdlib html.parser strips script/style/nav/footer and emits
     visible text only,
  3. gpt-4o-mini reads the cleaned text and returns structured items
     in the same shape sources/pdf_image.py uses.

We deliberately skip BeautifulSoup (no dependency) and Playwright
(no headless browser stack). That means SPAs and Anti-bot-protected
sites (DoorDash, Yelp) often return zero items — Phase 2-AI follow-up
will add Playwright behind a feature flag. For independent operator
sites (static menus, WordPress plugins, Squarespace), the stdlib
approach already gets us 80% recall in practice.
(httpx + stdlib html.parser + LLM normalize. SPA/anti-bot은 후속)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 3 scenario C.
"""
from __future__ import annotations

import json
import logging
from html.parser import HTMLParser
from typing import Optional

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.onboarding.schema import RawMenuExtraction, RawMenuItem
from app.services.onboarding.sources.pdf_image import _normalize_item

log = logging.getLogger(__name__)


# Same model + prompt family as the vision extractor — gpt-4o-mini is
# cheap, handles structured output, and we want consistent extraction
# behavior across image and url sources so operator review state is
# uniform in Step 3.
# (gpt-4o-mini 공통 — vision adapter와 일관된 추출)
_LLM_MODEL = "gpt-4o-mini"

# Page-size cap before LLM call. 100KB of cleaned text is ~30K tokens
# (well within gpt-4o-mini's 128K context) but covers any reasonable
# menu page; runaway pages (entire blogs, comment threads) get truncated
# instead of burning $0.50 per onboarding call.
# (LLM 입력 cap — 100KB ≈ 30K tokens, 비용 방어선)
_MAX_TEXT_CHARS = 100_000

# Real desktop UA. Bare "python-httpx/..." gets 403'd by Squarespace
# and a few popular WP themes; menu sites rarely fingerprint deeper.
# (UA — Squarespace 403 회피)
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


_EXTRACTION_PROMPT = (
    "You are extracting menu items from a restaurant website's text "
    "(scraped from HTML — expect navigation noise, hours, contact info "
    "interleaved with the menu).\n\n"
    "Return strictly valid JSON of this shape:\n"
    '{\n'
    '  "items": [\n'
    '    {\n'
    '      "name": "Margherita Pizza",\n'
    '      "price": 16.00,\n'
    '      "size_hint": "12 inch" | null,\n'
    '      "category": "Pizzas" | null,\n'
    '      "description": "..." | null,\n'
    '      "confidence": 0.92\n'
    '    }\n'
    '  ],\n'
    '  "detected_modifiers": ["size", "toppings", ...]\n'
    '}\n\n'
    "Rules:\n"
    "- Skip navigation, hours, location, contact, reservation, social "
    "media, footer, and shipping copy.\n"
    "- One JSON object per row in the menu — split size variants into "
    "separate items.\n"
    "- price is a number, not a string. No currency symbols.\n"
    "- Use null (not empty string) when a field is absent.\n"
    "- confidence is 0.0-1.0; lower it (0.6-0.8) when the price isn't "
    "adjacent to the name in the text or when the row looks like "
    "navigation/SEO copy rather than a real menu line.\n"
    "- detected_modifiers names the add-on dimensions advertised on "
    "the page. Empty array if none.\n"
    "- Return ONLY the JSON object, no prose, no markdown fence."
)


class _VisibleTextExtractor(HTMLParser):
    """Strip non-content tags and emit visible text.

    Skip-list is conservative — keeps menu sites' main/article/section/
    div content but discards script/style (executable junk) and
    nav/footer/header (boilerplate). Inline data inside skip-tags is
    counted out via a depth counter so a nested <span> inside <nav>
    doesn't leak through.
    (visible text 추출 — depth counter로 nested tag 처리)
    """
    _SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "header", "noscript", "svg"})
    _BLOCK_TAGS = frozenset({
        "p", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "div", "section", "article", "br",
    })

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")  # break visually so LLM sees lines

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped + " ")

    def text(self) -> str:
        # Collapse multiple newlines but preserve single ones (LLM uses
        # them as item separators).
        # (newline 정리 — 단일 유지, 다중 collapse)
        raw = "".join(self._parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def _html_to_text(html: str) -> str:
    parser = _VisibleTextExtractor()
    try:
        parser.feed(html)
    except Exception as exc:  # malformed HTML — partial extraction is fine
        log.info("url_crawler html.parser failed mid-stream: %s", exc)
    return parser.text()[:_MAX_TEXT_CHARS]


async def extract_from_url(url: str) -> RawMenuExtraction:
    """Fetch a URL, clean to visible text, and LLM-extract menu items.

    A few failure modes degrade gracefully into warnings + empty items:
    HTTP 4xx/5xx, connection error, empty body, LLM returns non-JSON.
    Missing API key fails loud — the rest of the call would silently
    succeed with zero results and confuse the operator.
    (4xx/5xx/empty/bad-JSON → warning. API key 없으면 RuntimeError)
    """
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing — URL extraction needs it")

    warnings: list[str] = []

    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers=_DEFAULT_HEADERS,
        ) as http:
            resp = await http.get(url)
    except httpx.RequestError as exc:
        return {
            "source":             "url",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           [f"fetch failed: {type(exc).__name__}: {exc}"],
        }

    if resp.status_code >= 400:
        return {
            "source":             "url",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           [f"HTTP {resp.status_code} from {url}"],
        }

    text = _html_to_text(resp.text)
    if not text:
        return {
            "source":             "url",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           ["page returned no visible text — likely a SPA needing Playwright"],
        }

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        llm_resp = await client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{
                "role": "user",
                "content": _EXTRACTION_PROMPT + "\n\nPAGE TEXT:\n" + text,
            }],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        body = llm_resp.choices[0].message.content or ""
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        return {
            "source":             "url",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           [f"LLM returned non-JSON: {exc}"],
        }
    except Exception as exc:  # network / OpenAI errors
        return {
            "source":             "url",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           [f"LLM call failed: {exc!r}"],
        }

    items: list[RawMenuItem] = []
    for entry in (parsed.get("items") or []):
        if not isinstance(entry, dict):
            continue
        norm = _normalize_item(entry, url)
        if norm is not None:
            items.append(norm)

    modifiers = [
        m for m in (parsed.get("detected_modifiers") or [])
        if isinstance(m, str)
    ]
    return {
        "source":             "url",
        "items":              items,
        "detected_modifiers": modifiers,
        "vertical_guess":     None,  # router fills via detect_vertical
        "warnings":           warnings,
    }
