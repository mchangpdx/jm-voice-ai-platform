# Admin endpoints — sync freeze/unfreeze toggle.
# (관리 API — sync freeze/unfreeze 토글)
#
# Used during onboarding/migration to safely block POS webhook callbacks
# without touching the upstream webhook registration (Loyverse webhook
# DELETE/POST is known-unreliable).
#
# Auth: minimal — these endpoints are bound to localhost via uvicorn
# 127.0.0.1 in dev. In production they should require a service-role JWT
# or be moved behind an internal-only route.

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.audit import audit_log, get_actor
from app.services.sync.freeze import (
    freeze_all,
    freeze_store,
    is_globally_frozen,
    status,
    unfreeze_store,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/sync", tags=["Admin Sync"], include_in_schema=False)


@router.post("/freeze")
async def admin_freeze(
    duration_min: int = Query(30, ge=1, le=240),
    store_id: Optional[str] = Query(None),
    actor: dict = Depends(get_actor),
):
    """Activate sync freeze. If store_id is given, freezes that store only;
    otherwise freezes all stores globally.
    (sync 일시 차단 — store_id 없으면 전역 freeze)
    """
    if store_id:
        result = freeze_store(store_id, duration_min)
    else:
        result = freeze_all(duration_min)

    await audit_log(
        actor_user_id=actor["user_id"] or "anonymous",
        actor_email=actor["email"],
        action="system.sync_freeze",
        target_type="store" if store_id else "system",
        target_id=store_id,
        before=None,
        after={"duration_min": duration_min, "scope": store_id or "*"},
        ip_address=actor["ip_address"],
        user_agent=actor["user_agent"],
    )
    return {"ok": True, **result, "status": status()}


@router.post("/unfreeze")
async def admin_unfreeze(
    store_id: Optional[str] = Query(None),
    actor: dict = Depends(get_actor),
):
    """Lift the freeze. If store_id is given, unfreezes that store only;
    otherwise lifts the global freeze ('*').
    (sync 차단 해제 — store_id 없으면 전역 해제)
    """
    key = store_id or "*"
    cleared = unfreeze_store(key)

    await audit_log(
        actor_user_id=actor["user_id"] or "anonymous",
        actor_email=actor["email"],
        action="system.sync_unfreeze",
        target_type="store" if store_id else "system",
        target_id=store_id,
        before={"scope": key, "was_frozen": cleared},
        after=None,
        ip_address=actor["ip_address"],
        user_agent=actor["user_agent"],
    )
    return {"ok": True, "cleared": cleared, "status": status()}


@router.get("/status")
async def admin_sync_status():
    """Snapshot of current freeze state.
    (현재 freeze 상태 조회)
    """
    return {
        "globally_frozen": is_globally_frozen(),
        "details": status(),
    }
