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
from typing import Any

import httpx

from app.core.config import settings

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
    """Enrich a list of {name, quantity} items with menu_items catalog data.
    (요청 항목 list에 카탈로그 정보 부여)

    Returns one row per input item (preserves order). Even items that failed
    to match are returned (with missing=True) so the caller can build a
    targeted refusal message ("X is sold out, Y is not on our menu").
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

    enriched: list[dict[str, Any]] = []
    for item in items:
        raw_name = item.get("name") or ""
        key      = raw_name.strip().lower()
        qty      = int(item.get("quantity") or 1)

        match = by_name.get(key)
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

        enriched.append({
            "name":             match["name"],          # canonical catalog name
            "quantity":         qty,
            "variant_id":       match["variant_id"],
            "item_id":          match.get("pos_item_id"),
            "price":            float(match.get("price") or 0),
            "stock_quantity":   stock,
            "missing":          False,
            "sufficient_stock": sufficient,
        })

    return enriched
