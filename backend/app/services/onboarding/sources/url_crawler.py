"""URL source adapter — Playwright crawl + Claude normalization (scenario C).

Phase 1: skeleton. Phase 2 wires Playwright headless crawl + DoorDash/Yelp
fallback chain. Anti-bot considerations drive the fallback order:
direct site → Yelp → DoorDash (deepest crawl, most anti-bot risk).
(URL crawl — Phase 2 구현)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 3 scenario C.
"""
from __future__ import annotations

from app.services.onboarding.schema import RawMenuExtraction


async def extract_from_url(url: str) -> RawMenuExtraction:
    """TODO Phase 2 — Playwright crawl + Claude normalization."""
    raise NotImplementedError("url source adapter — implement in Phase 2")
