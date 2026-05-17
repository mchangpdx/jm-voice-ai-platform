"""service_lookup — Gemini Function Calling tool for service catalogs.
(service_lookup — 서비스 카탈로그 조회용 Gemini Function Calling 도구)

Architecture mirrors `skills/menu/allergen.py`:
  - Read-only over the `menu_items` aggregate filtered to service rows
    (service_kind IS NOT NULL — set by Phase 2 schema migration).
  - Fuzzy match (0.7 cutoff) — same permissiveness as allergen_lookup
    because failing to match misses an operator-curated answer entirely
    while a wrong match is recoverable ("did you mean a deluxe manicure?").
  - Returns deterministic `ai_script_hint` strings; the voice handler maps
    these to phrasing templates per vertical.
  - One service per call (OneItemPerQuery I2) — Gemini calls again for the
    next item if the customer asks about multiple services.

Used by service-kind verticals (beauty, future spa / nails / barber) before
calling `book_appointment` so duration_min and price come from the store's
curated catalog instead of LLM imagination.
"""
from __future__ import annotations

import logging
from difflib import get_close_matches
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Mirrors allergen_lookup — wrong match is recoverable, missing match is not.
# (퍼지 임계값 0.7 — allergen_lookup과 동일 근거)
_FUZZY_CUTOFF = 0.7


# ── Tool definition (Voice Engine ↔ Gemini / OpenAI Realtime) ────────────────


SERVICE_LOOKUP_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "service_lookup",
            "description": (
                "Look up the duration and price for ONE service offered by "
                "the store. Use this BEFORE calling book_appointment so the "
                "duration_min and price you pass come from the store's "
                "curated catalog, not your own estimate. Also use this when "
                "the customer asks 'how much is a haircut' or 'how long does "
                "color take'. NEVER invent service durations or prices — "
                "always call this tool. Pass the service name as the customer "
                "said it; the system handles fuzzy matching against the "
                "store's service catalog (menu_items where service_kind is "
                "set). Speak the returned price and duration VERBATIM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": (
                            "The service the customer asked about (e.g. "
                            "'haircut', 'balayage', 'manicure', 'pedicure', "
                            "'oil change'). Pass it as the customer said it; "
                            "the tool fuzzy-matches against the catalog."
                        ),
                    },
                },
                "required": ["service_name"],
            },
        }
    ]
}


# ── Skill flow ───────────────────────────────────────────────────────────────


async def service_lookup(
    *,
    store_id:     str,
    service_name: str,
) -> dict[str, Any]:
    """Look up duration_min + price for a single service.
    (단일 서비스의 duration + price 조회 — Phase 3.2)

    Returns a structured payload with `ai_script_hint` that the voice
    handler maps to phrasing templates. Never raises on missing data —
    emits `service_not_found` instead (HonestUnknown invariant I1).

    ai_script_hint values:
      - service_found            — matched_name + duration_min + price all set
      - service_unknown_duration — matched but duration_min is NULL (operator
                                   left it blank; bot must ask in-person)
      - service_unknown_price    — matched but price is NULL / 0
      - service_not_found        — no row matched, even with fuzzy
    """
    raw_name = (service_name or "").strip()
    if not raw_name:
        return _result(
            matched_name=raw_name,
            duration_min=None,
            price=None,
            service_kind=None,
            hint="service_not_found",
        )

    # Pull every service row for this store, filter in Python.
    # menu_items per store is small (< ~300); same pattern as allergen_lookup.
    # `service_kind=not.is.null` keeps order-kind items (food) out of the
    # result so a query for "burger" at a beauty salon doesn't accidentally
    # match a stray food row.
    # (DB 1회 호출 + Python 매칭. service_kind NULL은 제외 — 음식 item 차단)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_REST}/menu_items",
                headers=_SUPABASE_HEADERS,
                params={
                    "store_id":     f"eq.{store_id}",
                    "service_kind": "not.is.null",
                    "select":       "name,duration_min,price,service_kind",
                },
            )
        rows: list[dict[str, Any]] = resp.json() if resp.status_code == 200 else []
    except Exception as exc:
        log.warning("service_lookup REST error store=%s err=%r", store_id, exc)
        rows = []

    by_name: dict[str, dict[str, Any]] = {}
    for r in rows:
        nm = (r.get("name") or "").strip().lower()
        if nm and nm not in by_name:
            by_name[nm] = r

    key = raw_name.strip().lower()
    match = by_name.get(key)
    if match is None and key:
        close = get_close_matches(key, list(by_name.keys()), n=1, cutoff=_FUZZY_CUTOFF)
        if close:
            match = by_name[close[0]]
            log.info("service fuzzy match: %r -> %r", raw_name, match.get("name"))

    if match is None:
        log.warning("service_lookup store=%s service=%r result=service_not_found",
                    store_id, raw_name)
        return _result(
            matched_name=raw_name,
            duration_min=None,
            price=None,
            service_kind=None,
            hint="service_not_found",
        )

    matched_name = match.get("name") or raw_name
    duration_min = match.get("duration_min")
    price        = match.get("price")
    service_kind = match.get("service_kind")

    if duration_min in (None, 0):
        hint = "service_unknown_duration"
    elif price in (None, 0):
        hint = "service_unknown_price"
    else:
        hint = "service_found"

    log.warning("service_lookup store=%s service=%r dur=%s price=%s result=%s",
                store_id, matched_name, duration_min, price, hint)

    return _result(
        matched_name=matched_name,
        duration_min=duration_min,
        price=price,
        service_kind=service_kind,
        hint=hint,
    )


def _result(
    *,
    matched_name: str,
    duration_min: int | None,
    price:        float | int | None,
    service_kind: str | None,
    hint:         str,
) -> dict[str, Any]:
    return {
        "success":        True,
        "matched_name":   matched_name,
        "duration_min":   duration_min,
        "price":          price,
        "service_kind":   service_kind,
        "ai_script_hint": hint,
    }


__all__ = [
    "SERVICE_LOOKUP_TOOL_DEF",
    "service_lookup",
]
