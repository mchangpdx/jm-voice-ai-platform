# Phase 2-B.1.7 — Menu Sync Service
# (Phase 2-B.1.7 — 메뉴 동기화 서비스)
#
# Pulls the live menu from a store's POS via the POSAdapter.fetch_menu()
# capability, flattens items × variants into menu_items rows, and writes a
# pre-formatted menu_cache string back to stores.menu_cache for the Voice
# Engine system prompt.
#
# Direct-to-DB pattern (no staging table) — `on_conflict (store_id, variant_id)`
# upsert is the single transaction that mutates the catalog. menu_cache is
# refreshed in the same run so the cache never lags the rows.
#
# Triggered by:
#   - Manual: POST /api/pos/sync/{store_id} (operator action)
#   - Scheduled: cron worker (planned in Phase 2-B.2)
#   - Webhook: items.update from Loyverse (deferred — for now full re-sync)

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.bridge.pos.factory import get_pos_adapter_for_store

log = logging.getLogger(__name__)

_SUPABASE_HEADERS_BASE = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def sync_menu_from_pos(store_id: str) -> dict[str, Any]:
    """Pull the catalog from a store's POS and refresh menu_items + menu_cache.
    (매장 POS에서 카탈로그 조회 → menu_items + menu_cache 갱신)

    Returns a result dict with keys:
        success     bool
        synced      int  — number of variant rows upserted
        item_count  int  — number of distinct POS items received
        error       str  — present only when success is False
    """
    adapter = await get_pos_adapter_for_store(store_id)

    # Capability gate — adapter must opt-in to menu_sync. Without this gate, an
    # adapter that doesn't override fetch_menu would crash with NotImplementedError.
    # (capability flag 검사 — 미지원 어댑터는 명확한 오류 반환)
    if not getattr(adapter, "SUPPORTS_MENU_SYNC", False):
        return {
            "success": False,
            "error":   "adapter does not support menu_sync",
        }

    items = await adapter.fetch_menu()

    # Flatten items × variants → upsertable rows. menu_items.variant_id is the
    # natural primary key for receipt line_items, so we store one row per variant.
    # (항목 × 변형 평탄화 — variant_id가 영수증 라인 항목 자연 키)
    rows: list[dict[str, Any]] = []
    for item in items:
        for v in item.get("variants", []) or []:
            rows.append({
                "store_id":       store_id,
                "pos_item_id":    item.get("pos_item_id"),
                "variant_id":     v.get("variant_id"),
                "sku":            v.get("sku"),
                "name":           item.get("name"),
                "option_value":   v.get("option_value"),
                "price":          float(v.get("price") or 0),
                "stock_quantity": int(v.get("stock_quantity") or 0),
                "category_id":    item.get("category_id"),
                "color":          item.get("color"),
                "description":    item.get("description"),
            })

    if not rows:
        log.warning("sync_menu_from_pos %s: 0 variants", store_id)
        return {"success": True, "synced": 0, "item_count": len(items)}

    # Build menu_cache: one line per item at its lowest variant price. Lowest
    # is shown so the LLM never quotes a price the customer can't actually get.
    # (메뉴 캐시: 항목당 최저 변형 가격 한 줄 — 고객이 못 받는 가격 인용 방지)
    #
    # Cache hygiene: drop sentinel rows that exist in menu_items for internal
    # bookkeeping (e.g. the synthetic 'Reservation' $0.00 row used by the
    # restaurant reservation flow). Exposing them on the prompt confuses the
    # LLM into routing pickup orders through make_reservation. Filter on:
    #   - name 'Reservation' (case-insensitive)  ← legacy seed
    #   - price <= 0                              ← any zero/free placeholder
    # (가짜 시드 항목 제외 — Gemini가 reservation tool로 오라우팅하는 것 방지)
    lowest_price: dict[str, float] = {}
    for r in rows:
        nm    = r["name"]
        price = r["price"]
        if not nm or price <= 0:
            continue
        if nm.strip().lower() == "reservation":
            continue
        if nm not in lowest_price or price < lowest_price[nm]:
            lowest_price[nm] = price

    menu_cache = "\n".join(
        f"{nm} - ${price:.2f}" for nm, price in lowest_price.items()
    )

    # ── Upsert menu_items rows ──────────────────────────────────────────────
    # Prefer header tells PostgREST to merge on the unique index instead of
    # erroring on conflict. on_conflict query param names the index columns.
    upsert_headers = {
        **_SUPABASE_HEADERS_BASE,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        upsert_resp = await client.post(
            f"{_REST}/menu_items?on_conflict=store_id,variant_id",
            headers=upsert_headers,
            json=rows,
        )
        if upsert_resp.status_code not in (200, 201):
            log.error(
                "sync_menu_from_pos upsert failed: %s %s",
                upsert_resp.status_code,
                getattr(upsert_resp, "text", "")[:200],
            )
            return {
                "success": False,
                "error":   f"upsert failed: {upsert_resp.status_code}",
            }

        # PATCH stores.menu_cache so the Voice Engine prompt sees fresh prices
        # without an extra DB round-trip from the audio path.
        # (Voice Engine 프롬프트가 음성 경로에서 추가 DB 왕복 없이 신선한 가격 사용)
        cache_resp = await client.patch(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS_BASE,
            params={"id": f"eq.{store_id}"},
            json={"menu_cache": menu_cache},
        )
        if cache_resp.status_code not in (200, 204):
            # Non-fatal: rows are upserted, cache write missed. Sync run still
            # counts as successful — the next run will retry the cache.
            # (치명적이지 않음 — 다음 동기화에서 재시도)
            log.warning(
                "sync_menu_from_pos cache write missed: %s",
                cache_resp.status_code,
            )

    log.info(
        "sync_menu_from_pos %s: synced=%d item_count=%d",
        store_id, len(rows), len(items),
    )
    return {
        "success":    True,
        "synced":     len(rows),
        "item_count": len(items),
    }
