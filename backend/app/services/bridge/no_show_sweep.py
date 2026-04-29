# Phase 2-B.1.10 / 2026-04-29 — Per-store no-show sweep
# (Phase 2-B.1.10 / 2026-04-29 — 매장별 no-show 청소 작업)
#
# sweep_no_shows() finds bridge_transactions in FIRED_UNPAID state and rolls
# them over to NO_SHOW once they exceed the OWNING STORE's timeout window.
# Per-store dial: store_configs.order_policy.no_show_timeout_minutes (default
# settings.no_show_timeout_minutes when missing). Operator-tunable from the
# dashboard Settings page so a QSR can pick 15-min while a bakery picks
# 2 hours.
#
# Design choice: fetch all FIRED_UNPAID rows in one pass, evaluate the
# per-store cutoff in Python. A SQL-side filter would force one query per
# distinct timeout value (or a CASE expression Loyverse-of-PostgREST
# doesn't support cleanly).
#
# Failure isolation: per-row advance_state errors are caught + counted in
# 'failed' so one bad row never aborts the whole batch.

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.services.bridge import transactions
from app.services.bridge.state_machine import State
from app.services.policy.order_lanes import read_no_show_timeouts

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def sweep_no_shows() -> dict[str, Any]:
    """Roll overdue FIRED_UNPAID rows to NO_SHOW using per-store timeouts.
    (매장별 timeout으로 FIRED_UNPAID → NO_SHOW)

    Returns:
        {scanned: N, transitioned: K, failed: F}
    """
    # Bound the result set in SQL with the *most lenient* cutoff (the global
    # default). A row younger than that can't possibly exceed any per-store
    # window (per-store values are <= 1440 by validation), so this is a safe
    # pre-filter that keeps the in-Python loop small.
    # (전역 기본값으로 1차 필터 — 더 짧은 매장 timeout 대상은 모두 포함됨)
    global_default = settings.no_show_timeout_minutes
    now            = datetime.now(timezone.utc)
    pre_cutoff     = now - timedelta(minutes=global_default)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={
                "state":    f"eq.{State.FIRED_UNPAID}",
                "fired_at": f"lte.{pre_cutoff.isoformat()}",
                "select":   "id,state,fired_at,store_id",
                "order":    "fired_at.asc",
                "limit":    "100",   # bounded per pass
            },
        )

    rows: list[dict[str, Any]] = resp.json() if resp.status_code == 200 else []
    scanned = len(rows)
    if scanned == 0:
        return {"scanned": 0, "transitioned": 0, "failed": 0}

    # Per-store override map; missing stores fall back to the global default.
    # Loaded once per sweep so we don't hammer store_configs row-by-row.
    # (매장별 override 한 번만 조회 — 행마다 DB 호출 안 함)
    timeouts = await read_no_show_timeouts()

    transitioned = 0
    failed       = 0
    now_iso      = now.isoformat()

    for row in rows:
        store_id  = row.get("store_id")
        fired_at  = row.get("fired_at")
        if not fired_at:
            failed += 1
            continue

        timeout_minutes = timeouts.get(store_id, global_default)
        cutoff = now - timedelta(minutes=timeout_minutes)
        try:
            fired_dt = datetime.fromisoformat(fired_at.replace("Z", "+00:00"))
        except ValueError:
            failed += 1
            continue

        if fired_dt > cutoff:
            # Still within the store's window — skip.
            # (매장 timeout 내 — 건너뜀)
            continue

        try:
            await transactions.advance_state(
                transaction_id = row["id"],
                to_state       = State.NO_SHOW,
                source         = "cron",
                actor          = "no_show_sweep",
                extra_fields   = {"no_show_at": now_iso},
            )
            transitioned += 1
        except Exception as exc:
            log.warning("no_show_sweep skip tx=%s: %s", row.get("id"), exc)
            failed += 1

    log.info(
        "no_show_sweep: scanned=%d transitioned=%d failed=%d",
        scanned, transitioned, failed,
    )
    return {"scanned": scanned, "transitioned": transitioned, "failed": failed}
