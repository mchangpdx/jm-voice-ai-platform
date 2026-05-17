"""list_stylists — Gemini Function Calling tool for service resources.
(list_stylists — 서비스 리소스 조회용 Gemini Function Calling 도구)

Read-only over the per-vertical `scheduler.yaml` (Layer 6 of the
9-layer Vertical Template Framework). Returns the `resources` array
flattened into a stable shape:

  [{id, name, specialties}, ...]

Used by service-kind verticals (beauty / spa / barber / etc.) when the
customer asks 'who's available', 'what stylists do you have', 'can I
book with anyone in particular'. Also useful as a soft pre-step before
book_appointment so Gemini knows whether a `stylist_preference` value
is a real name vs an unknown one.

Pure file I/O via `app.templates._base.validator.load_template` — no DB,
no network. Lenient: a missing/empty scheduler returns an empty list
plus a structured hint rather than raising.
"""
from __future__ import annotations

import logging
from typing import Any

from app.templates._base.validator import load_template

log = logging.getLogger(__name__)


# ── Tool definition ──────────────────────────────────────────────────────────


LIST_STYLISTS_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "list_stylists",
            "description": (
                "List the stylists, technicians, or service providers "
                "available at this store. Call this when the customer asks "
                "'who's working today', 'what stylists do you have', 'do "
                "you have anyone who specializes in [service]'. The "
                "result is read-only — speak the names VERBATIM. Optional "
                "specialty filter narrows the list to providers who list "
                "that specialty in their profile."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty_filter": {
                        "type": "string",
                        "description": (
                            "Optional service id to filter by (e.g. "
                            "'balayage', 'oil_change'). Empty string "
                            "returns all providers."
                        ),
                    },
                },
                "required": [],
            },
        }
    ]
}


# ── Pure formatter (unit-testable) ───────────────────────────────────────────


def format_resources(
    resources: list[dict[str, Any]] | None,
    *,
    specialty_filter: str = "",
) -> list[dict[str, Any]]:
    """Flatten scheduler.resources into a stable {id, name, specialties} list.
    (scheduler.resources → 표준 stylist shape)

    - Drops non-dict entries (lenient).
    - Applies `specialty_filter` case-insensitively against each row's
      `specialties` list.
    """
    if not isinstance(resources, list):
        return []

    needle = (specialty_filter or "").strip().lower()
    out: list[dict[str, Any]] = []
    for r in resources:
        if not isinstance(r, dict):
            continue
        specialties = r.get("specialties") or []
        if not isinstance(specialties, list):
            specialties = []
        if needle:
            specs_lc = {str(s).strip().lower() for s in specialties}
            if needle not in specs_lc:
                continue
        out.append({
            "id":          r.get("id") or r.get("en") or "",
            "name":        r.get("en") or r.get("id") or "",
            "specialties": [str(s) for s in specialties],
            "capacity":    r.get("capacity"),
        })
    return out


# ── Public flow ──────────────────────────────────────────────────────────────


async def list_stylists(
    *,
    vertical:         str,
    specialty_filter: str = "",
) -> dict[str, Any]:
    """Return the stylist roster for a vertical's scheduler.yaml.
    (vertical scheduler.yaml의 stylist 명단 반환 — Phase 3.5)

    ai_script_hint values:
        stylists_listed              → ≥1 provider returned
        no_stylists_match_filter     → filter applied, 0 matches but roster non-empty
        no_stylists_configured       → roster empty (or scheduler.yaml absent)
    """
    template = load_template(vertical)
    sched = template.get("scheduler") or {}
    if not isinstance(sched, dict):
        sched = {}

    roster_all = format_resources(sched.get("resources"), specialty_filter="")
    filtered   = format_resources(sched.get("resources"),
                                   specialty_filter=specialty_filter)

    if not roster_all:
        hint = "no_stylists_configured"
    elif not filtered:
        hint = "no_stylists_match_filter"
    else:
        hint = "stylists_listed"

    log.info("list_stylists vertical=%s filter=%r count=%d hint=%s",
             vertical, specialty_filter, len(filtered), hint)

    return {
        "success":          True,
        "vertical":         vertical,
        "slot_kind":        sched.get("slot_kind"),
        "specialty_filter": specialty_filter or None,
        "stylists":         filtered,
        "ai_script_hint":   hint,
    }


__all__ = [
    "LIST_STYLISTS_TOOL_DEF",
    "format_resources",
    "list_stylists",
]
