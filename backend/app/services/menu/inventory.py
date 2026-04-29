# Phase 2-B.1.7 — Inventory webhook handler
# (Phase 2-B.1.7 — 인벤토리 웹훅 핸들러)
#
# Loyverse fires inventory_levels.update when on-hand quantity changes (sale,
# adjustment, transfer). The webhook posts an array of {variant_id, in_stock,
# store_id} entries. We update menu_items.stock_quantity per variant — the
# voice agent's stock gate consumes that column on the next call.
#
# The webhook signature is verified at the route layer; this module receives
# already-validated payloads.

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def apply_inventory_levels(
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply a batch of {variant_id, in_stock} updates to menu_items.
    (variant_id별 stock_quantity 업데이트 일괄 적용)

    Sequential PATCH per variant — each update is independent and a single
    failure must not abort the batch. Loyverse-internal store_id in the
    payload is intentionally ignored: menu_items.variant_id is unique across
    our DB so no extra scoping is required.
    (PATCH 순차 적용 — 한 항목 실패가 배치 전체 중단 방지)
    """
    if not levels:
        return {"updated": 0}

    updated = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for level in levels:
            variant_id = level.get("variant_id")
            in_stock   = level.get("in_stock")
            if variant_id is None or in_stock is None:
                continue

            resp = await client.patch(
                f"{_REST}/menu_items",
                headers=_SUPABASE_HEADERS,
                params={"variant_id": f"eq.{variant_id}"},
                json={"stock_quantity": int(in_stock)},
            )
            if resp.status_code in (200, 204):
                updated += 1
            else:
                # Log but continue — partial success is acceptable for inventory
                # syncs since Loyverse will retry on next change.
                # (부분 성공 허용 — Loyverse가 다음 변동 시 재시도)
                log.warning(
                    "apply_inventory_levels %s failed: %s",
                    variant_id, resp.status_code,
                )

    log.info("apply_inventory_levels: updated=%d/%d", updated, len(levels))
    return {"updated": updated}
