# Menu sync + Loyverse inventory webhook routes
# (메뉴 동기화 + Loyverse 인벤토리 웹훅 라우트)
#
# Two endpoints:
#   POST /api/pos/sync/{store_id}                  — operator-triggered full re-sync
#   POST /api/webhooks/loyverse/inventory_levels   — Loyverse pushes stock updates
#
# Phase 2-B.1.7. Menu fetch happens via the POS adapter selected for the store
# (Supabase / Loyverse / future Quantic). All logic lives in app.services.menu.

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.services.menu.inventory import apply_inventory_levels
from app.services.menu.sync import sync_menu_from_pos

log = logging.getLogger(__name__)

router = APIRouter(tags=["Menu"])


@router.post("/api/pos/sync/{store_id}")
async def trigger_menu_sync(store_id: str) -> dict[str, Any]:
    """Run a full catalog re-sync for a store. Idempotent — every run upserts
    on (store_id, variant_id) and rewrites menu_cache.
    (매장 카탈로그 전체 재동기화 — 멱등성 보장)
    """
    try:
        result = await sync_menu_from_pos(store_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        # ValueError = unknown pos_provider or missing API key — operator config error
        # (구성 오류 — 매장 설정 점검 필요)
        raise HTTPException(status_code=400, detail=str(e))

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result


@router.post("/api/webhooks/loyverse/inventory_levels")
async def loyverse_inventory_webhook(request: Request) -> dict[str, Any]:
    """Loyverse posts inventory_levels.update events here. Body shape per the
    Loyverse webhook spec is one of:
        { "inventory_levels": [{ variant_id, in_stock, store_id }, ...] }
        [{ variant_id, in_stock, store_id }, ...]    (some legacy installations)
    Both shapes are accepted defensively.
    (두 가지 페이로드 형태 모두 수용)

    HMAC signature verification is intentionally deferred to a follow-up commit
    once Loyverse rotates a webhook secret for our tenant. Until then, the
    endpoint is gated by network ACL only.
    (HMAC 검증은 Loyverse 시크릿 로테이션 후 추가 — 현재는 네트워크 ACL 보호)
    """
    body = await request.json()
    if isinstance(body, dict):
        levels = body.get("inventory_levels") or []
    elif isinstance(body, list):
        levels = body
    else:
        levels = []

    result = await apply_inventory_levels(levels)
    return result
