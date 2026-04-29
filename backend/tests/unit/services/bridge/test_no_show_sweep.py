# Phase 2-B.1.10 — No-show sweep TDD
# (Phase 2-B.1.10 — no-show 청소 작업 TDD)
#
# sweep_no_shows(now=None) finds bridge_transactions in FIRED_UNPAID state
# whose fired_at is older than no_show_timeout_minutes (default 30) and
# transitions them to NO_SHOW. Designed to be invoked periodically from a
# cron worker — a single pass is idempotent (only matches rows that haven't
# been transitioned yet).

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_no_show_sweep_transitions_overdue_fired_unpaid():
    """A FIRED_UNPAID order older than the timeout ⇒ advance to NO_SHOW
    with no_show_at stamped. (시간 초과한 FIRED_UNPAID는 NO_SHOW로 전이)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    overdue_tx = {
        "id": "tx-old", "state": "fired_unpaid",
        "fired_at": (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(),
    }

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [overdue_tx]

    advance_calls: list = []

    async def fake_advance(**kw):
        advance_calls.append(kw)
        return {"state": kw["to_state"]}

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)
        mock_tx.advance_state = AsyncMock(side_effect=fake_advance)

        result = await sweep_no_shows()

    assert result["transitioned"] == 1
    assert advance_calls[0]["transaction_id"] == "tx-old"
    assert advance_calls[0]["to_state"]       == "no_show"
    assert "no_show_at" in advance_calls[0].get("extra_fields", {})


@pytest.mark.asyncio
async def test_no_show_sweep_skips_recent_fired_unpaid():
    """A FIRED_UNPAID still within the timeout window is NOT transitioned.
    The PostgREST filter handles this server-side (we just confirm nothing
    overdue means nothing to advance).
    (타임아웃 윈도우 내 주문은 그대로 유지)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: []   # PostgREST returned nothing matching the cutoff

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)
        mock_tx.advance_state = AsyncMock()

        result = await sweep_no_shows()

    assert result["transitioned"] == 0
    mock_tx.advance_state.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_sweep_continues_when_one_advance_fails():
    """One bad row must not abort the rest of the batch.
    (한 행 실패가 배치 전체를 중단시키면 안 됨)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    rows = [
        {"id": "tx-a", "state": "fired_unpaid",
         "fired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
        {"id": "tx-b", "state": "fired_unpaid",
         "fired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
    ]
    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: rows

    async def fake_advance(**kw):
        if kw["transaction_id"] == "tx-a":
            raise RuntimeError("transient")
        return {"state": kw["to_state"]}

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)
        mock_tx.advance_state = AsyncMock(side_effect=fake_advance)

        result = await sweep_no_shows()

    # tx-a failed, tx-b succeeded
    assert result["transitioned"] == 1
    assert result["failed"]       == 1
