# Phase 2-B.1.10 — No-show sweep
# (Phase 2-B.1.10 — no-show 청소 작업)
#
# sweep_no_shows() finds bridge_transactions in FIRED_UNPAID state whose
# fired_at is older than settings.no_show_timeout_minutes (default 30) and
# transitions them to NO_SHOW. Designed to run periodically from a cron
# worker; a single pass is idempotent because PostgREST filters out rows
# already advanced past FIRED_UNPAID.
#
# Failure mode: per-row advance_state errors are caught and counted in
# 'failed' so one bad row never aborts the whole batch.

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.services.bridge import transactions
from app.services.bridge.state_machine import State

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def sweep_no_shows() -> dict[str, Any]:
    """Transition overdue FIRED_UNPAID rows to NO_SHOW.
    (시간 초과한 FIRED_UNPAID 행을 NO_SHOW로 전이)

    Returns:
        {scanned: N, transitioned: K, failed: F}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.no_show_timeout_minutes
    )
    cutoff_iso = cutoff.isoformat()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={
                "state":    f"eq.{State.FIRED_UNPAID}",
                "fired_at": f"lte.{cutoff_iso}",
                "select":   "id,state,fired_at,store_id",
                "order":    "fired_at.asc",
                "limit":    "100",   # cap per pass — cron runs again next tick
            },
        )

    rows: list[dict[str, Any]] = resp.json() if resp.status_code == 200 else []
    scanned = len(rows)
    if scanned == 0:
        return {"scanned": 0, "transitioned": 0, "failed": 0}

    transitioned = 0
    failed       = 0
    now_iso      = datetime.now(timezone.utc).isoformat()

    for row in rows:
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
            # Log but keep going — partial success is acceptable; next sweep
            # will retry whatever stayed in FIRED_UNPAID. (한 행 실패는 다음 스윕이 재시도)
            log.warning("no_show_sweep skip tx=%s: %s", row.get("id"), exc)
            failed += 1

    log.info(
        "no_show_sweep: scanned=%d transitioned=%d failed=%d",
        scanned, transitioned, failed,
    )
    return {"scanned": scanned, "transitioned": transitioned, "failed": failed}
