# Sync freeze — temporarily ignore POS webhook callbacks without touching
# the upstream webhook registration.
# (POS webhook callback 일시 무시 — 상류 등록은 보존)
#
# Why:
#   Loyverse webhook DELETE→POST is known-unreliable: deletion cache lingers,
#   re-registering the same URL fails with "already exists" for unpredictable
#   periods. The 7 webhooks currently registered to JM Cafe are the result of
#   such failures. We do NOT want to touch them.
#
# Mechanism:
#   - In-memory dict mapping store_id → expiry epoch.
#   - "*" key = global freeze (all stores).
#   - Webhook handlers check is_frozen() / is_globally_frozen() before
#     dispatching to sync logic. Frozen: log + return 200 OK to Loyverse
#     (so it stops retrying), DB unchanged.
#
# Safety:
#   - Auto-expire: every freeze has a duration_min (default 30). Expired
#     entries are dropped on first read.
#   - uvicorn restart auto-clears: in-memory state, no surprise persistence.
#   - Multi-tenant: per-store freeze possible.
#
# Usage:
#   freeze_all(60)              # 60 min global freeze
#   freeze_store(store_id, 30)  # 30 min single-store freeze
#   if is_globally_frozen() or is_frozen(store_id): return 200
#   unfreeze_store("*")         # clear global
#   unfreeze_store(store_id)    # clear one store

from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Module-global state. uvicorn workers share this (single-process FastAPI dev).
# In multi-worker production this would need Redis — out of scope for V0.
# (단일-process 개발 환경 가정 — 다중 worker는 Redis 필요)
_frozen_until: dict[str, float] = {}

# Special key denoting "freeze all stores at once".
GLOBAL_KEY = "*"


def freeze_store(store_id: str, duration_min: int = 30) -> dict:
    """Freeze webhook processing for a single store for duration_min.
    (단일 매장의 webhook 처리 일시 차단)
    """
    expiry = time.time() + duration_min * 60
    _frozen_until[store_id] = expiry
    log.warning(
        "[sync-freeze] store=%s frozen for %d min (expires=%s)",
        store_id, duration_min, time.strftime("%H:%M:%S", time.localtime(expiry)),
    )
    return {"store_id": store_id, "frozen_until": expiry, "duration_min": duration_min}


def freeze_all(duration_min: int = 30) -> dict:
    """Freeze webhook processing for ALL stores. Default 30 min.
    Use during onboarding / migration windows.
    (전체 매장 동시 차단 — onboarding/migration 작업용)
    """
    return freeze_store(GLOBAL_KEY, duration_min)


def unfreeze_store(store_id: str) -> bool:
    """Lift the freeze on one store (or '*' for global). Returns True if
    something was actually cleared.
    (특정 매장 또는 전체의 freeze 해제)
    """
    had = store_id in _frozen_until
    _frozen_until.pop(store_id, None)
    if had:
        log.warning("[sync-freeze] store=%s unfrozen", store_id)
    return had


def is_frozen(store_id: str) -> bool:
    """True iff store is currently frozen (and freeze hasn't expired).
    Auto-cleans expired entries on read.
    (현재 frozen 여부 — 만료된 항목은 자동 정리)
    """
    expiry = _frozen_until.get(store_id)
    if expiry is None:
        return False
    if time.time() >= expiry:
        _frozen_until.pop(store_id, None)
        log.info("[sync-freeze] store=%s freeze auto-expired", store_id)
        return False
    return True


def is_globally_frozen() -> bool:
    """True iff a freeze_all() is currently active.
    (전역 freeze 활성 여부)
    """
    return is_frozen(GLOBAL_KEY)


def is_blocked(store_id: Optional[str] = None) -> bool:
    """True iff webhook processing should be skipped for this store.
    Considers both global freeze and per-store freeze.
    (이 매장의 webhook 처리를 skip할지 — 전역 + 매장별 양쪽 검사)
    """
    if is_globally_frozen():
        return True
    if store_id and is_frozen(store_id):
        return True
    return False


def status() -> dict:
    """Snapshot of current freeze state — for admin/diagnostic display.
    (현재 freeze 상태 스냅샷)
    """
    now = time.time()
    active = {}
    for k, expiry in list(_frozen_until.items()):
        remaining = expiry - now
        if remaining > 0:
            active[k] = {
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(expiry)),
                "remaining_seconds": int(remaining),
            }
        else:
            _frozen_until.pop(k, None)  # lazy cleanup
    return {"global_frozen": GLOBAL_KEY in active, "active": active}
