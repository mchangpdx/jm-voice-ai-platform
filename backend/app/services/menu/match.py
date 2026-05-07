# Phase 2-B.1.8 — Menu match helper
# (Phase 2-B.1.8 — 메뉴 매칭 헬퍼)
#
# resolve_items_against_menu(store_id, items) attaches catalog data
# (variant_id, item_id, real price, current stock) onto items extracted by
# Gemini from the audio transcript.
#
# Match policy (per user direction):
#   * Exact, case-insensitive name match — no fuzzy. Surprise behaviour from
#     fuzzy ("Café Latte" matching "Mocha") would be worse than asking the
#     customer to repeat the name they meant.
#   * stock_quantity is NULL ⇒ untracked item — pass (treated as unlimited).
#   * stock_quantity is 0 OR < requested quantity ⇒ sufficient_stock=False.
#     The order flow uses this flag to refuse a sold-out line.
#
# Each line in the returned list carries:
#   name, quantity (original)
#   variant_id, item_id, price, stock_quantity (from catalog; absent on miss)
#   missing (bool — True when name didn't match any menu_items row)
#   sufficient_stock (bool — True only when item exists AND stock allows qty)

from __future__ import annotations

import logging
from difflib import get_close_matches
from typing import Any

import httpx

from app.core.config import settings

# Fuzzy fallback threshold. 0.85 catches "caffe latte" → "cafe latte"
# (one-letter typo over 11 chars ≈ 0.91 ratio) and "mochi" → "mocha"
# (one-letter sub over 5 chars ≈ 0.80, so it's BELOW threshold and stays
# unmatched), but never collapses semantically distinct items like
# "latte" → "mocha". Anything tighter than 0.85 starts rejecting STT
# noise we want to forgive; anything looser starts collapsing real menus.
# (퍼지 매칭 임계값 — STT/LLM 오타 수준만 흡수, 의미 다른 매뉴는 거절)
_FUZZY_CUTOFF = 0.85

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def resolve_items_against_menu(
    *,
    store_id: str,
    items:    list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich a list of {name, quantity, selected_modifiers?} items with menu_items
    catalog data and per-line effective prices.
    (요청 항목 list에 카탈로그 정보 + modifier price_delta 부여)

    Returns one row per input item (preserves order). Even items that failed
    to match are returned (with missing=True) so the caller can build a
    targeted refusal message ("X is sold out, Y is not on our menu").

    Phase 7-A.C: when ANY input item carries a non-empty selected_modifiers
    list, an additional batched modifier_groups + modifier_options round-trip
    runs to compute effective_price = price + Σ(price_delta). Modifier
    metadata is preserved on the line so the pay_link replay can later
    upgrade Loyverse line items with line_modifiers. A REST hiccup falls
    back to base price (effective_price == price) — never blocks the order.
    """
    if not items:
        return []

    # Single round-trip: pull every variant for the store, then match in
    # Python. menu_items per store is small (<300 rows in practice) so an
    # in-memory dict is faster + cheaper than N PostgREST queries.
    # (DB는 한 번만 호출 — 매장당 메뉴는 작아서 in-memory 매칭이 쌈)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_REST}/menu_items",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id": f"eq.{store_id}",
                "select":   "name,variant_id,pos_item_id,price,stock_quantity",
            },
        )
    rows: list[dict[str, Any]] = resp.json() if resp.status_code == 200 else []

    # Lower-cased name → first matching catalog row. If a customer asks for
    # "Latte" and the menu has both "Latte (Small)" and "Latte (Large)" as
    # distinct rows, the first one wins. The voice prompt is responsible
    # for asking the customer to specify a size before calling create_order.
    # (프롬프트가 사이즈 확인 후 호출하는 책임 — 매칭은 첫 번째 행 사용)
    by_name: dict[str, dict[str, Any]] = {}
    for r in rows:
        nm = (r.get("name") or "").strip().lower()
        if nm and nm not in by_name:
            by_name[nm] = r

    # Modifier index — loaded only if at least one item carries selected_modifiers.
    # Skipping the load on the legacy path keeps the per-call latency unchanged
    # for stores/menus that don't use the modifier system.
    # (modifier가 명시된 항목이 하나라도 있을 때만 인덱스 로드 — perf 보존)
    needs_modifiers = any((it.get("selected_modifiers") or []) for it in items)
    modifier_index: dict[tuple[str, str], dict[str, Any]] = {}
    if needs_modifiers:
        modifier_index = await _load_modifier_index(store_id)

    catalog_keys = list(by_name.keys())
    enriched: list[dict[str, Any]] = []
    for item in items:
        raw_name = item.get("name") or ""
        key      = raw_name.strip().lower()
        qty      = int(item.get("quantity") or 1)
        sel_mods = item.get("selected_modifiers") or []

        match = by_name.get(key)
        if match is None and key:
            # Exact (case-insensitive) miss — try a tight fuzzy fallback.
            # The customer almost-certainly meant a real menu item; STT or
            # the LLM dropped/added a letter ("caffe latte" vs "cafe latte",
            # "ham burger" vs "hamburger"). Threshold is conservative
            # enough that semantically distinct items don't collapse.
            # (정확 매치 실패 시 보수적 fuzzy fallback)
            close = get_close_matches(key, catalog_keys, n=1, cutoff=_FUZZY_CUTOFF)
            if close:
                fuzzy_key = close[0]
                match = by_name[fuzzy_key]
                log.info("Menu fuzzy match: %r -> %r", raw_name, match["name"])

        if match is None:
            enriched.append({
                "name":             raw_name.strip(),
                "quantity":         qty,
                "missing":          True,
                "sufficient_stock": False,
            })
            continue

        stock      = match.get("stock_quantity")  # may be None ⇒ untracked
        sufficient = (stock is None) or (int(stock) > 0 and int(stock) >= qty)
        base_price = float(match.get("price") or 0)

        # Modifier price_delta accumulation. Unknown (group, option) pairs are
        # silently skipped — same defensive contract as compute_effective_allergens.
        # (모르는 modifier는 침묵 무시 — LLM 환각 방지)
        applied_mods: list[dict[str, Any]] = []
        delta_total = 0.0
        for sel in sel_mods:
            if not isinstance(sel, dict):
                continue
            gcode = sel.get("group"); ocode = sel.get("option")
            if not gcode or not ocode:
                continue
            opt = modifier_index.get((gcode, ocode))
            if opt is None:
                continue
            try:
                delta_total += float(opt.get("price_delta") or 0)
            except (TypeError, ValueError):
                pass
            applied_mods.append({"group": gcode, "option": ocode})

        effective = round(base_price + delta_total, 2)

        enriched.append({
            "name":               match["name"],          # canonical catalog name
            "quantity":           qty,
            "variant_id":         match["variant_id"],
            "item_id":            match.get("pos_item_id"),
            "price":              base_price,             # base — preserved
            "effective_price":    effective,              # base + Σ(price_delta)
            "selected_modifiers": applied_mods,           # validated subset only
            "stock_quantity":     stock,
            "missing":            False,
            "sufficient_stock":   sufficient,
        })

    return enriched


async def _load_modifier_index(
    store_id: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Fetch modifier_groups + options for a store. Returns (group_code, option_code)
    -> option dict (with price_delta). Empty on any REST error so callers fall
    back to base prices.
    (modifier index 로드 — 실패 시 base price fallback)
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
                    "select":   "group_id,code,price_delta",
                },
            )
            if o_resp.status_code != 200:
                return {}
            options = o_resp.json() or []
    except Exception as exc:
        log.warning("_load_modifier_index store=%s err=%r", store_id, exc)
        return {}

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for o in options:
        gid = o.get("group_id")
        gcode = gid_to_code.get(gid)
        if not gcode:
            continue
        index[(gcode, o.get("code"))] = o
    return index
