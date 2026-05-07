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

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.services.menu.inventory import apply_inventory_levels
from app.services.menu.sync import sync_menu_from_pos
from app.services.sync.freeze import is_blocked, is_globally_frozen

log = logging.getLogger(__name__)

router = APIRouter(tags=["Menu"])

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def _find_loyverse_store_ids() -> list[str]:
    """Return all store UUIDs whose pos_provider is 'loyverse'.
    (pos_provider='loyverse' 매장 목록 — items webhook이 어느 매장 메뉴를 갱신할지 결정)

    Loyverse webhooks don't carry our internal store UUID, so we resolve by
    pos_provider. Single-tenant deployments return one row; multi-tenant
    setups (multiple JM stores on the same Loyverse merchant) return all
    of them and we re-sync each. A future enhancement maps merchant_id to
    a specific store row to avoid the broadcast.
    (단일 테넌트는 1개 행 / 멀티 테넌트는 전체 — 향후 merchant_id 매핑으로 정밀화)
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"pos_provider": "eq.loyverse", "select": "id"},
        )
    if resp.status_code != 200:
        return []
    return [row["id"] for row in (resp.json() or [])]


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


@router.post("/api/webhooks/loyverse/item")
@router.post("/api/webhooks/loyverse/items")
async def loyverse_items_webhook(request: Request) -> dict[str, Any]:
    """Loyverse items.update events — re-sync the affected store's catalog.
    (Loyverse 항목 변경 웹훅 — 영향 받은 매장 카탈로그 재동기화)

    Loyverse fires this on every item create / update / delete (price, name,
    description, new variant, etc.). The payload only carries item ids — not
    enough to update menu_items in place — and crucially does NOT include
    our internal store UUID. We therefore call sync_menu_from_pos() on every
    Loyverse-configured store, which fetches /items + /inventory and upserts
    the rows. Idempotent: repeat firings are safe.

    Trade-off: a full sync on every item edit. Acceptable for menus under
    a few hundred rows; if the catalog grows large, switch to a partial
    fetch by item id (future enhancement).
    (전체 재동기화 — 수백 항목 미만 메뉴에 적합 / 대용량은 추후 부분 fetch로 최적화)
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    n_items = len(body.get("items", []) or []) if isinstance(body, dict) else 0

    # Phase 7-A — sync freeze: ignore the webhook (still return 200 so Loyverse
    # stops retrying) when an onboarding/migration window is active. Avoids
    # touching the upstream webhook registration which is known-unreliable.
    # (Loyverse webhook 등록 그대로 보존 + freeze 모드에서는 200만 반환하고 sync skip)
    if is_globally_frozen():
        log.warning("[FROZEN] items webhook skipped (n_items=%d)", n_items)
        return {"received": True, "items": n_items, "skipped": "frozen"}

    store_ids = await _find_loyverse_store_ids()
    refreshed: list[dict[str, Any]] = []
    for sid in store_ids:
        if is_blocked(sid):
            log.warning("[FROZEN] items webhook skipped for store=%s", sid)
            refreshed.append({"store_id": sid, "skipped": "frozen"})
            continue
        try:
            res = await sync_menu_from_pos(sid)
            refreshed.append({"store_id": sid, **res})
        except Exception as exc:
            # One store failure must not abort the others — Loyverse retries
            # the whole webhook on non-2xx, so we still want to return 200
            # even if one tenant misconfigured its API key.
            # (한 매장 실패가 다른 매장 재동기화를 막으면 안 됨)
            log.warning("items webhook sync failed | store=%s | %s", sid, exc)
            refreshed.append({"store_id": sid, "success": False, "error": str(exc)})

    log.info("loyverse items webhook: items=%d, refreshed_stores=%d",
             n_items, len(refreshed))
    return {"received": True, "items": n_items, "synced": refreshed}


@router.post("/api/webhooks/loyverse/customers")
async def loyverse_customers_webhook(request: Request) -> dict[str, Any]:
    """Stub for Loyverse customer create/update/delete events.
    (Loyverse 고객 변경 웹훅 — 200 OK 스텁)

    CRM (phone-based caller recognition) lands in Phase 3 — at that point
    this handler will upsert into a `customers` table so the voice agent
    can greet returning callers by name. Until then we acknowledge and
    drop. (Phase 3 CRM에서 customers 테이블 upsert로 확장 예정)
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    n_custs = len(body.get("customers", []) or []) if isinstance(body, dict) else 0
    log.info("loyverse customers webhook: customers=%d", n_custs)
    return {"received": True, "customers": n_custs}


@router.post("/api/webhooks/loyverse/inventory")
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

    # Phase 7-A — sync freeze: same pattern as items webhook.
    # (메뉴 webhook과 동일 freeze 패턴 — onboarding 윈도우 동안 무시)
    if is_globally_frozen():
        log.warning("[FROZEN] inventory webhook skipped (n_levels=%d)", len(levels))
        return {"received": True, "applied": 0, "skipped": "frozen"}

    result = await apply_inventory_levels(levels)
    return result
