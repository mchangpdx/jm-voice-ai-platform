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
    store_id:       str,
    items:          list[dict[str, Any]],
    modifier_index: dict[tuple[str, str], dict[str, Any]] | None = None,
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

    Phase 7-A.D Wave A.3: callers that already loaded modifier groups (e.g.
    realtime_voice.py at session.update for the system-prompt block) may
    pass a pre-built `modifier_index` to skip the per-call REST fetch — saves
    ~400-500ms per create_order on the hot path. Pass {} to indicate "store
    has no modifiers" (skip fetch, fall back to base price). Pass None to
    keep the legacy behavior (lazy fetch on first modifier-bearing item).
    (사전 로드된 modifier_index 재사용 — create_order 핫패스에서 modifier REST 우회)
    """
    if not items:
        return []

    # Single round-trip: pull every AVAILABLE variant for the store, then
    # match in Python. menu_items per store is small (<300 rows in practice)
    # so an in-memory dict is faster + cheaper than N PostgREST queries.
    # is_available filter (Phase 7-A.D Wave A.2-F): pre-modifier-system
    # imports left legacy 'Medium'/'Large' size variants on the same item
    # that the modifier system now handles via size price_delta. Excluding
    # is_available=false stops match from picking those legacy rows and
    # double-charging the customer (live trigger CA0459df13... — bot recited
    # $7.25 from menu_cache lowest price, backend charged $7.75 because
    # match picked the 'Medium' variant with $6.00 base instead).
    # (is_available 필터 — legacy size 변형 picking 차단)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_REST}/menu_items",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":     f"eq.{store_id}",
                "is_available": "eq.true",
                "select":       "name,variant_id,pos_item_id,price,stock_quantity",
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

    # Modifier index — loaded only if at least one item carries selected_modifiers
    # AND the caller didn't pass a pre-built index. Skipping the load on the
    # legacy path keeps the per-call latency unchanged for stores/menus that
    # don't use the modifier system; using the pre-built index from
    # realtime_voice's session.update saves ~400-500ms on the hot path.
    # (modifier 인덱스: 사전 로드 우선 → 레거시 경로는 lazy fetch 유지)
    needs_modifiers = any((it.get("selected_modifiers") or []) for it in items)
    if modifier_index is None:
        modifier_index = await _load_modifier_index(store_id) if needs_modifiers else {}

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
        # modifier_lines is a parallel render-friendly list for the pay link
        # email and the post-payment receipt page (Wave A.2-G): each entry
        # carries the operator-curated display_name + signed price_delta so
        # downstream surfaces can show "20oz (+$1.00)" without re-querying.
        # (모르는 modifier는 침묵 무시 + display 라인은 영수증/이메일용 동봉)
        applied_mods: list[dict[str, Any]] = []
        modifier_lines: list[dict[str, Any]] = []
        delta_total = 0.0
        for sel in sel_mods:
            if not isinstance(sel, dict):
                continue
            gcode = sel.get("group"); ocode = sel.get("option")
            if not gcode or not ocode:
                continue
            # Case-insensitive fallback (Bug #5 fix, 2026-05-12):
            # LLM sometimes sends "Regular"/"Thin" capitalized while the
            # modifier_options.code field is lowercase ("regular"/"thin").
            # Try the original keys first, then a lowercased pair. Avoids
            # silently dropping the modifier (Big Joe regular crust ghosted
            # off live tx 13068a40 — price_delta=0 so no $ impact, but
            # the receipt line was missing the crust label).
            # (LLM의 대문자 vs DB의 소문자 → case-insensitive fallback)
            opt = (
                modifier_index.get((gcode, ocode))
                or modifier_index.get((gcode.lower(), ocode.lower()))
            )
            if opt is None:
                continue
            try:
                delta = float(opt.get("price_delta") or 0)
            except (TypeError, ValueError):
                delta = 0.0
            delta_total += delta
            applied_mods.append({"group": gcode, "option": ocode})
            modifier_lines.append({
                "label":       opt.get("display_name") or ocode,
                "group":       gcode,
                "option":      ocode,
                "price_delta": delta,
            })

        effective = round(base_price + delta_total, 2)

        enriched.append({
            "name":               match["name"],          # canonical catalog name
            "quantity":           qty,
            "variant_id":         match["variant_id"],
            "item_id":            match.get("pos_item_id"),
            "price":              base_price,             # base — preserved
            "effective_price":    effective,              # base + Σ(price_delta)
            "selected_modifiers": applied_mods,           # validated subset only
            "modifier_lines":     modifier_lines,         # display rows for email/receipt
            "stock_quantity":     stock,
            "missing":            False,
            "sufficient_stock":   sufficient,
        })

    return enriched


def build_modifier_index_from_groups(
    groups: list[dict[str, Any]] | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Convert fetch_modifier_groups() output into the index shape that
    resolve_items_against_menu consumes. Lets the realtime layer build the
    index once at session.update (when groups are already fetched for the
    system-prompt block) and reuse it across every create_order /
    modify_order in the call.
    (modifiers.fetch_modifier_groups 결과 → match.py가 쓰는 (gcode,ocode)→opt 인덱스로 변환)

    Skips groups/options with empty `code` defensively — those rows can't be
    referenced from selected_modifiers anyway, and including them would
    create unmatchable index entries.

    2026-05-12 — mirrors _load_modifier_index's display_name alias logic so
    LLM args carrying group="Pizza Size"/"Crust Type" (the display name as
    seen in the system-prompt block) also match. Without this, session-start
    builds (used by realtime_voice.py) silently dropped modifiers while the
    REST-fetch path (used by voice_websocket.py) caught them. Live trigger:
    JM Pizza call CAab82cc... where Veggie Supreme 18" Gluten-Free landed
    as $24 instead of $36 because the index only carried the bare codes.
    (display_name 별칭 — session.update 빌드도 _load_modifier_index와 동일 alias 적용)
    """
    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not groups:
        return index

    # First pass — build alias map: display_name variants → real code.
    alias_to_code: dict[str, str] = {}
    for g in groups:
        gcode = (g.get("code") or "").strip()
        disp  = (g.get("display_name") or "").strip()
        if not gcode:
            continue
        if disp:
            d_lower = disp.lower()
            d_snake = d_lower.replace(" ", "_").replace("-", "_")
            if d_lower != gcode:
                alias_to_code[d_lower] = gcode
            if d_snake != gcode:
                alias_to_code[d_snake] = gcode

    # Second pass — write (code, ocode) AND every alias of code.
    for g in groups:
        gcode = (g.get("code") or "").strip()
        if not gcode:
            continue
        for o in (g.get("options") or []):
            ocode = (o.get("code") or "").strip()
            if not ocode:
                continue
            index[(gcode, ocode)] = o
            for alias, real in alias_to_code.items():
                if real == gcode:
                    index[(alias, ocode)] = o
    return index


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
                params={"store_id": f"eq.{store_id}", "select": "id,code,display_name"},
            )
            if g_resp.status_code != 200:
                return {}
            groups = g_resp.json() or []
            if not groups:
                return {}
            gid_to_code = {g["id"]: g["code"] for g in groups}
            # 2026-05-12 — also map display_name → code so the LLM can address
            # a group via its visible label. Live trigger CA4042da3... where the
            # LLM emitted group="pizza_size"/"crust_type" (snake_cased
            # display_name "Pizza Size"/"Crust Type") while the catalog code is
            # "size"/"crust" — modifier silently dropped and the Veggie Supreme
            # was charged $24 instead of the spoken $35. Build a reverse alias
            # table the matcher can consult after the primary lookup misses.
            # (display_name → code 별칭 — LLM의 잘못된 group code 회복)
            alias_to_code: dict[str, str] = {}
            for g in groups:
                code = g.get("code") or ""
                disp = g.get("display_name") or ""
                if not code:
                    continue
                # canonical: lowercase + spaces/dashes → underscores
                canonical = disp.strip().lower().replace(" ", "_").replace("-", "_")
                if canonical and canonical != code:
                    alias_to_code[canonical] = code
                # also accept the bare lowercased display_name (no separator munge)
                if disp:
                    alias_to_code[disp.strip().lower()] = code

            o_resp = await client.get(
                f"{_REST}/modifier_options",
                headers=_SUPABASE_HEADERS,
                params={
                    "group_id": "in.(" + ",".join(gid_to_code.keys()) + ")",
                    "select":   "group_id,code,price_delta,display_name",
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
        ocode = o.get("code") or ""
        index[(gcode, ocode)] = o
        # Add display_name aliases under the same option code so a lookup
        # via (alias_group, option) lands on the same row.
        # (display_name 별칭으로도 조회 가능하게 동일 row 등록)
        for alias_group, real_code in alias_to_code.items():
            if real_code == gcode:
                index[(alias_group, ocode)] = o
    return index
