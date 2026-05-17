# Phase 7-A.B — Modifier loader + system-prompt formatter
# (Phase 7-A.B — modifier 로더 + 시스템 프롬프트 포매터)
#
# Why this exists:
#   The Voice Engine's system prompt receives `stores.menu_cache`, which is a
#   text list of base items only. Modifier_groups (size, milk, temperature,
#   syrup, …) live in separate tables and never reach the LLM, so the agent
#   denies valid composite orders like "iced oat latte". This module:
#     1. Pulls modifier_groups + modifier_options for a store (one batched
#        REST round-trip in addition to the existing store load).
#     2. Renders a single text block to inject into the system prompt right
#        after menu_cache.
#
# Live trigger (root cause):
#   2026-05-07 call CA90b88e53a3eb46ec3e8016ee403c3aa5 — caller asked four
#   times for "large iced oat latte"; agent declined every time because
#   menu_cache only listed "Cafe Latte" and "Iced Tea" as separate lines.
#   Customer hung up. DB had: temperature/iced, milk/oat (allergen_add=
#   ['gluten','wheat'], allergen_remove=['dairy']) — none visible to the LLM.
#
# Data shapes (from public.modifier_groups / public.modifier_options):
#   group  = {id, store_id, code, display_name, is_required, min_select,
#             max_select, sort_order}
#   option = {id, group_id, code, display_name, price_delta, allergen_add[],
#             allergen_remove[], sort_order, is_default, is_available}

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


# ── Data loading ──────────────────────────────────────────────────────────────

async def fetch_modifier_groups(store_id: str) -> list[dict[str, Any]]:
    """Fetch modifier groups + their options for a store.
    (매장의 modifier_groups + 옵션 일괄 조회)

    Returns groups sorted by sort_order, with each group's `options` key
    populated and also sorted by sort_order. Each group also gets an
    `applies_to_categories` list — distinct categories of menu_items wired
    to the group via menu_item_modifier_groups. Without this, the LLM has
    no way to tell which base items a Size group actually attaches to and
    will deny valid composite orders. (live trigger: JM Taco call #4
    2026-05-15 — agent denied "Large Burrito al Pastor" because the
    modifier block listed Size in the abstract.)

    Network/REST errors degrade to an empty list — callers must treat
    absence of modifiers as "no modifier section in prompt", never as a
    fatal call-handler error.

    Three REST round-trips:
        GET /modifier_groups?store_id=eq.<id>&order=sort_order
        GET /modifier_options?group_id=in.(<ids>)&order=sort_order
        GET /menu_item_modifier_groups + /menu_items (for applies_to)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            g_resp = await client.get(
                f"{_REST}/modifier_groups",
                headers=_SUPABASE_HEADERS,
                params={
                    "store_id": f"eq.{store_id}",
                    "order":    "sort_order",
                },
            )
            if g_resp.status_code != 200:
                log.warning("fetch_modifier_groups groups status=%s store=%s",
                            g_resp.status_code, store_id)
                return []
            groups: list[dict[str, Any]] = g_resp.json() or []
            if not groups:
                return []

            group_ids = [g["id"] for g in groups]
            o_resp = await client.get(
                f"{_REST}/modifier_options",
                headers=_SUPABASE_HEADERS,
                params={
                    "group_id": "in.(" + ",".join(group_ids) + ")",
                    "order":    "sort_order",
                },
            )
            if o_resp.status_code != 200:
                log.warning("fetch_modifier_groups options status=%s store=%s",
                            o_resp.status_code, store_id)
                # Groups loaded but options didn't — render groups with no options
                # rather than dropping the whole block.
                # (그룹은 살리고 옵션만 비움 — 부분 정보가 무정보보다 안전)
                options: list[dict[str, Any]] = []
            else:
                options = o_resp.json() or []
    except Exception as exc:
        log.warning("fetch_modifier_groups err store=%s err=%r", store_id, exc)
        return []

    # Sort groups (defensive — REST `order` should already do this) and nest
    # options into their respective group dict.
    # (그룹은 sort_order 재정렬 + 옵션 nesting)
    groups_sorted = sorted(groups, key=lambda g: g.get("sort_order") or 0)
    by_group: dict[str, list[dict[str, Any]]] = {g["id"]: [] for g in groups_sorted}
    for o in options:
        gid = o.get("group_id")
        if gid in by_group:
            by_group[gid].append(o)
    for opts in by_group.values():
        opts.sort(key=lambda o: o.get("sort_order") or 0)

    for g in groups_sorted:
        g["options"] = by_group.get(g["id"], [])

    # Resolve applies_to_categories per group via the wire table.
    # Skipped silently if either round-trip fails — the existing
    # vertical-agnostic prompt still functions, just without the
    # category hint. (wire 조회 실패는 prompt 출력에서만 누락)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            w_resp = await client.get(
                f"{_REST}/menu_item_modifier_groups",
                headers=_SUPABASE_HEADERS,
                params={"group_id": "in.(" + ",".join(group_ids) + ")",
                        "select":   "menu_item_id,group_id"},
            )
            wires = w_resp.json() if w_resp.status_code == 200 else []

            item_ids = sorted({w["menu_item_id"] for w in wires})
            categories_by_item: dict[str, str] = {}
            if item_ids:
                i_resp = await client.get(
                    f"{_REST}/menu_items",
                    headers=_SUPABASE_HEADERS,
                    params={"id":     "in.(" + ",".join(item_ids) + ")",
                            "select": "id,category"},
                )
                if i_resp.status_code == 200:
                    for row in i_resp.json() or []:
                        cat = (row.get("category") or "").strip()
                        if cat:
                            categories_by_item[row["id"]] = cat

        cats_by_group: dict[str, set[str]] = {gid: set() for gid in group_ids}
        for w in wires:
            gid = w.get("group_id")
            cat = categories_by_item.get(w.get("menu_item_id"))
            if gid in cats_by_group and cat:
                cats_by_group[gid].add(cat)
        for g in groups_sorted:
            g["applies_to_categories"] = sorted(cats_by_group.get(g["id"], set()))
    except Exception as exc:
        log.warning("fetch_modifier_groups applies_to lookup failed store=%s err=%r",
                    store_id, exc)
        for g in groups_sorted:
            g.setdefault("applies_to_categories", [])

    return groups_sorted


# ── System-prompt rendering ───────────────────────────────────────────────────

_HEADER = "=== MENU MODIFIERS (combinable with menu items above) ==="

_INTERPRETATION_HINT = (
    "NOTE: Each modifier group above lists which menu categories it applies "
    "to ('applies to: X'). When the customer orders an item in one of those "
    "categories, the modifiers ALWAYS apply — actively offer the choice "
    "(e.g. ask 'Medium or Large?' for a required Size group) rather than "
    "denying or assuming a single default. "
    "**NEVER ask a modifier group whose 'applies to:' list does NOT include "
    "the chosen item's category** — e.g. do not ask about 'hair length' or "
    "'blow dry' for a Classic Manicure, do not ask about 'facial add-ons' "
    "for a Haircut. Skipping irrelevant modifier turns is mandatory; the "
    "customer's intake should pass straight to confirmation when no modifier "
    "group applies to their service. "
    "When the customer says a phrase that blends a base item with a modifier "
    "(size + base, milk + drink, temperature + drink, etc.), interpret it "
    "as the base item plus the modifier choice — do NOT deny a request "
    "because the combined phrase is not a separate menu line. If a modifier "
    "choice changes the allergen profile (e.g. a milk option adds "
    "gluten/wheat and removes dairy), call allergen_lookup with the base "
    "item name and selected_modifiers — never answer from memory."
)


def format_modifier_block(groups: list[dict[str, Any]]) -> str:
    """Render the modifier section for system prompt injection.
    (시스템 프롬프트 주입용 modifier 섹션 텍스트 렌더링)

    Returns "" when groups is empty so build_system_prompt can skip the
    block cleanly. Unavailable options are filtered out — callers should
    not get directed to discontinued modifiers.
    """
    if not groups:
        return ""

    lines: list[str] = [_HEADER]
    for g in groups:
        required = bool(g.get("is_required"))
        max_sel  = g.get("max_select") or 1
        marker   = "required" if required else "optional"
        if max_sel and max_sel > 1:
            marker += f", choose up to {max_sel}"
        display = (g.get("display_name") or g.get("code") or "").strip()
        code    = (g.get("code") or "").strip()
        # 2026-05-12 — surface the group `code` next to its display so the
        # LLM stops emitting display-name-as-code in selected_modifiers args.
        # Live regression: 10th call CAab82cc... emitted
        # group="Pizza Size"/"Crust Type" (the human-readable display) while
        # the catalog code is "size"/"crust" — case-insensitive fallback
        # caught the size delta but the deep_dish $3 and gluten_free $4
        # both silently dropped because the alias index didn't include the
        # exact title-case form. Adding "code=X" inline gives the LLM an
        # unambiguous string to copy into args.group.
        # (group code를 LLM에 명시 노출 — args 변덕 차단)
        code_hint = f" code={code}" if code and code.lower() != display.lower() else ""
        # If display_name already encodes the marker (e.g. "Milk (optional)"),
        # skip the parenthetical to avoid "Milk (optional) (optional):".
        # (display_name이 이미 marker를 포함하면 중복 방지)
        applies = g.get("applies_to_categories") or []
        applies_hint = ""
        if applies:
            applies_hint = (
                ", applies to: " + ", ".join(a.replace("_", " ") for a in applies)
            )
        if display.lower().endswith("(optional)") or display.lower().endswith("(required)"):
            header = f"{display}{code_hint}{applies_hint}:" if applies_hint else f"{display}{code_hint}:"
        else:
            header = f"{display}{code_hint} ({marker}{applies_hint}):"

        opts_text = []
        for o in g.get("options") or []:
            if o.get("is_available") is False:
                continue
            opts_text.append(_render_option(o))

        if opts_text:
            lines.append(f"{header} " + ", ".join(opts_text))
        else:
            # Empty group still rendered so the LLM doesn't infer the dimension
            # (e.g. milk) is unavailable.
            # (옵션 비어있어도 그룹 헤더는 노출 — 차원 자체는 존재함을 알림)
            lines.append(f"{header} (no options currently available)")

    lines.append(_INTERPRETATION_HINT)
    return "\n".join(lines)


def _render_option(o: dict[str, Any]) -> str:
    """Render one option as 'code=Display (+$0.50, +nuts -dairy)'.
    (옵션 렌더링 — code/display 매핑 명시)

    Phase 7-A.D Wave A.1: code is now prefixed to display so the LLM can
    map natural-language modifier words ('large', '20 ounce', 'oat milk')
    onto the option code that selected_modifiers expects. Without this
    mapping the bot heard 'large' but had no way to bind it to option=
    'large' — items_json shipped without the size entry (live trigger
    CAc4250831...). When code and display are equal (e.g. milk: oat=Oat
    milk), the duplication is suppressed for readability.
    """
    code     = (o.get("code") or "").strip()
    display  = (o.get("display_name") or o.get("code") or "?").strip()
    # Suppress code= prefix when it adds no information (display already
    # starts with the code, case-insensitive). Keeps milk/syrup terse while
    # making size unambiguous.
    if code and not display.lower().startswith(code.lower()):
        name = f"{code}={display}"
    else:
        name = display

    inner: list[str] = []
    delta = o.get("price_delta")
    try:
        delta = float(delta) if delta is not None else 0.0
    except (TypeError, ValueError):
        delta = 0.0
    if delta and delta != 0.0:
        # Always show sign so LLM never misreads a discount as a surcharge.
        # (부호 명시 — 할인을 추가요금으로 오해 방지)
        sign = "+" if delta > 0 else "-"
        inner.append(f"{sign}${abs(delta):.2f}")

    for a in (o.get("allergen_add") or []):
        inner.append(f"+{a}")
    for a in (o.get("allergen_remove") or []):
        inner.append(f"-{a}")

    if inner:
        return f"{name} ({', '.join(inner)})"
    return name
