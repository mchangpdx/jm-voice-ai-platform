# Phase 2-C.B5 — Allergen / dietary lookup skill
# (Phase 2-C.B5 — 알레르겐/식이 조회 스킬)
#
# Spec: backend/docs/specs/B5_allergen_qa.md
#
# Operator-curated only — never LLM inference (CUSTOMER SAFETY INVARIANT).
# Returns deterministic ai_script_hint values that the voice handler maps
# to ALLERGEN_SCRIPT_BY_HINT lines (skills/order/order.py).
#
# Read-only over the menu_items aggregate. Single-row lookup per call
# (OneItemPerQuery I2). Multi-item dietary filter is deferred to v2.

from __future__ import annotations

import logging
from difflib import get_close_matches
from typing import Any

import httpx

from app.core.config import settings
from app.services.menu.allergen_compute import compute_effective_allergens

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"

# More permissive than create_order's 0.85 — wrong allergen info is recoverable
# (customer corrects "did you mean Cafe Latte?"); failing to match misses an
# operator-curated answer entirely. Per Decision #6.
# (퍼지 임계값 0.7 — create_order보다 관대, 매칭 실패가 잘못된 매칭보다 비용이 큼)
_FUZZY_CUTOFF = 0.7


# ── Tool definition (Voice Engine ↔ Gemini) ──────────────────────────────────

ALLERGEN_LOOKUP_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "allergen_lookup",
            "description": (
                "Look up allergen and dietary information for ONE menu item. "
                "Use this WHENEVER the customer asks about ingredients, "
                "allergies, dairy, gluten, nuts, vegan, vegetarian, "
                "gluten-free, dairy-free, etc. NEVER answer allergen "
                "questions from your own knowledge — call this tool. "
                "Pass the menu item name as the customer said it; the "
                "system handles fuzzy matching. Pass the allergen or "
                "dietary tag the customer asked about (or empty string "
                "if they asked generically). When the customer mentions "
                "modifiers ('iced oat latte', 'almond milk cappuccino'), "
                "pass them in selected_modifiers so allergens are computed "
                "for the actual drink (e.g. oat milk replaces dairy with "
                "gluten+wheat). The tool returns operator-curated data — "
                "speak its result VERBATIM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_name": {
                        "type": "string",
                        "description": (
                            "The BASE menu item the customer asked about "
                            "(e.g. 'cafe latte', 'croissant'). Strip modifier "
                            "words like 'iced', 'large', 'oat milk' from the "
                            "name and pass them via selected_modifiers."
                        ),
                    },
                    "allergen": {
                        "type": "string",
                        "description": (
                            "Specific allergen category if asked (one of: "
                            "dairy, gluten, wheat, nuts, peanuts, soy, "
                            "shellfish, egg, fish, sesame). Empty string "
                            "for generic 'what's in this' or for dietary "
                            "tag queries. Pass exactly what the customer "
                            "said — the tool aliases 'wheat' against "
                            "'gluten' data conservatively."
                        ),
                    },
                    "dietary_tag": {
                        "type": "string",
                        "description": (
                            "Specific dietary tag if asked (one of: vegan, "
                            "vegetarian, gluten_free, dairy_free, nut_free, "
                            "kosher, halal). Empty string for allergen queries."
                        ),
                    },
                    "selected_modifiers": {
                        "type": "array",
                        "description": (
                            "Modifier choices the customer mentioned. Pull "
                            "the group code and option code from the MENU "
                            "MODIFIERS section of your instructions. Examples: "
                            "'iced oat latte' → "
                            "[{'group':'temperature','option':'iced'},"
                            "{'group':'milk','option':'oat'}]; "
                            "'almond milk cappuccino' → "
                            "[{'group':'milk','option':'almond'}]. "
                            "Pass [] when no modifiers were spoken."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "group":  {"type": "string"},
                                "option": {"type": "string"},
                            },
                            "required": ["group", "option"],
                        },
                    },
                },
                "required": ["menu_item_name"],
            },
        }
    ]
}


# ── Skill flow ───────────────────────────────────────────────────────────────

async def allergen_lookup(
    *,
    store_id:           str,
    menu_item_name:     str,
    allergen:           str = "",
    dietary_tag:        str = "",
    selected_modifiers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Look up allergens / dietary tags for a single menu item.
    (단일 메뉴 항목의 allergen / dietary 조회 — Phase 2-C.B5 + 7-A.B)

    Returns a structured payload with ai_script_hint that the voice handler
    maps to ALLERGEN_SCRIPT_BY_HINT. Never raises on missing data — emits
    an honest-unknown hint instead (HonestUnknown invariant I1).

    Phase 7-A.B: selected_modifiers (e.g. [{group:'milk',option:'oat'}])
    triggers two extra REST calls (modifier_groups + modifier_options) and
    composes the effective allergen profile via compute_effective_allergens.
    Empty / None list keeps the legacy single-query path.
    """
    raw_name = (menu_item_name or "").strip()
    queried_allergen = (allergen or "").strip().lower()
    queried_dietary  = (dietary_tag or "").strip().lower()

    # Allergen wins when both are passed (mutually-exclusive semantics — T10).
    # (둘 다 들어오면 allergen 우선)
    if queried_allergen:
        queried_dietary = ""

    if not raw_name:
        return _result(
            success=True,
            matched_name=raw_name,
            allergens=[],
            dietary_tags=[],
            queried_allergen=queried_allergen,
            queried_dietary=queried_dietary,
            hint="item_not_found",
        )

    # Single round-trip — pull every menu_items row for this store, filter
    # in Python. menu_items per store is small (< ~300) and we already
    # follow this pattern in services/menu/match.py.
    # (DB 1회 호출 + Python 매칭)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_REST}/menu_items",
                headers=_SUPABASE_HEADERS,
                params={
                    "store_id": f"eq.{store_id}",
                    "select":   "name,allergens,dietary_tags",
                },
            )
        rows: list[dict[str, Any]] = resp.json() if resp.status_code == 200 else []
    except Exception as exc:
        log.warning("allergen_lookup REST error store=%s err=%r", store_id, exc)
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
            log.info("allergen fuzzy match: %r -> %r", raw_name, match.get("name"))

    if match is None:
        log.warning("allergen_lookup store=%s item=%r a=%r d=%r result=item_not_found",
                    store_id, raw_name, queried_allergen, queried_dietary)
        return _result(
            success=True,
            matched_name=raw_name,
            allergens=[],
            dietary_tags=[],
            queried_allergen=queried_allergen,
            queried_dietary=queried_dietary,
            hint="item_not_found",
        )

    matched_name  = match.get("name") or raw_name
    base_allergens = list(match.get("allergens") or [])
    dietary_tags  = list(match.get("dietary_tags") or [])

    # Phase 7-A.B — apply modifier-driven allergen mutations.
    # When selected_modifiers is non-empty we fetch the modifier index
    # (two more REST calls) and compose the effective profile. The empty
    # path is the unchanged legacy behavior.
    # (modifier 적용 시 effective allergens 재계산. 빈 리스트면 기존 동작)
    if selected_modifiers:
        index = await _fetch_modifier_index(store_id)
        if index:
            allergens = compute_effective_allergens(
                base_allergens, selected_modifiers, index)
        else:
            # Modifier table read failed — bias toward unchanged base. The
            # alternative (returning unknown) would block real allergen
            # questions during a transient REST hiccup.
            # (modifier index 로드 실패 시 base allergens fallback)
            allergens = list(base_allergens)
    else:
        allergens = list(base_allergens)

    # HonestUnknown — both arrays empty means operator hasn't curated this
    # item yet. Bot must NOT speak "free of X"; hand off to manager.
    # (양쪽 모두 비어있으면 honest-unknown — 매니저 인계)
    if not allergens and not dietary_tags:
        hint = "allergen_unknown"
    elif queried_allergen == "wheat":
        # FDA major allergen but not a curated category in our data — gluten
        # is the closest marker (wheat is a gluten source). Safety asymmetry:
        #   gluten present  → wheat likely present  → PRESENT
        #   gluten absent   → wheat absence NOT guaranteed (barley/rye-only
        #                     items exist) → escalate to UNKNOWN, never absent
        # Operator can override by adding 'wheat' to the row explicitly.
        # Live trigger: Phase 5 scenario 4 (CA0f91961) — Japanese caller asked
        # about wheat in croissant, bot hallucinated allergen='nuts' because
        # 'wheat' was missing from the tool enum.
        # (wheat 별도 카테고리 미사용 — gluten 함유원으로 alias. absent 방향은 안전 차단)
        if "wheat" in allergens or "gluten" in allergens:
            hint = "allergen_present"
        else:
            hint = "allergen_unknown"
    elif queried_allergen:
        hint = "allergen_present" if queried_allergen in allergens else "allergen_absent"
    elif queried_dietary:
        hint = "dietary_match" if queried_dietary in dietary_tags else "dietary_no_match"
    else:
        hint = "generic"

    log.warning("allergen_lookup store=%s item=%r a=%r d=%r result=%s",
                store_id, matched_name, queried_allergen, queried_dietary, hint)

    return _result(
        success=True,
        matched_name=matched_name,
        allergens=allergens,
        dietary_tags=dietary_tags,
        queried_allergen=queried_allergen,
        queried_dietary=queried_dietary,
        hint=hint,
    )


async def _fetch_modifier_index(
    store_id: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Fetch modifier groups + options and return a (group_code, option_code)
    -> option-row index for compute_effective_allergens.
    (modifier_groups + options 인덱스 조회 — allergen 동적 계산용)

    Returns {} on any REST failure — caller falls back to base allergens.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            g_resp = await client.get(
                f"{_REST}/modifier_groups",
                headers=_SUPABASE_HEADERS,
                params={"store_id": f"eq.{store_id}", "select": "id,code"},
            )
            if g_resp.status_code != 200:
                return {}
            groups = g_resp.json() or []
            if not groups:
                return {}
            gid_to_code = {g["id"]: g["code"] for g in groups}

            o_resp = await client.get(
                f"{_REST}/modifier_options",
                headers=_SUPABASE_HEADERS,
                params={
                    "group_id": "in.(" + ",".join(gid_to_code.keys()) + ")",
                    "select":   "group_id,code,allergen_add,allergen_remove",
                },
            )
            if o_resp.status_code != 200:
                return {}
            options = o_resp.json() or []
    except Exception as exc:
        log.warning("_fetch_modifier_index store=%s err=%r", store_id, exc)
        return {}

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for o in options:
        gid = o.get("group_id")
        gcode = gid_to_code.get(gid)
        if not gcode:
            continue
        index[(gcode, o.get("code"))] = o
    return index


def _result(
    *,
    success:           bool,
    matched_name:      str,
    allergens:         list[str],
    dietary_tags:      list[str],
    queried_allergen:  str,
    queried_dietary:   str,
    hint:              str,
) -> dict[str, Any]:
    return {
        "success":          success,
        "matched_name":     matched_name,
        "allergens":        allergens,
        "dietary_tags":     dietary_tags,
        "queried_allergen": queried_allergen,
        "queried_dietary":  queried_dietary,
        "ai_script_hint":   hint,
    }
