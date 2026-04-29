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
    """A FIRED_UNPAID order older than the store's timeout ⇒ advance to NO_SHOW
    with no_show_at stamped. (매장 timeout 초과한 FIRED_UNPAID는 NO_SHOW로 전이)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    overdue_tx = {
        "id": "tx-old", "state": "fired_unpaid",
        "store_id": "S-1",
        "fired_at": (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(),
    }

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [overdue_tx]

    advance_calls: list = []

    async def fake_advance(**kw):
        advance_calls.append(kw)
        return {"state": kw["to_state"]}

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx, \
         patch("app.services.bridge.no_show_sweep.read_no_show_timeouts",
               new=AsyncMock(return_value={"S-1": 30})):
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
    Sweep evaluates the per-store timeout in Python after fetching all
    FIRED_UNPAID rows.
    (타임아웃 윈도우 내 주문은 그대로 유지 — 매장 timeout 적용 후 결정)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    recent_tx = {
        "id": "tx-recent", "state": "fired_unpaid", "store_id": "S-1",
        "fired_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [recent_tx]

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx, \
         patch("app.services.bridge.no_show_sweep.read_no_show_timeouts",
               new=AsyncMock(return_value={"S-1": 30})):
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
        {"id": "tx-a", "state": "fired_unpaid", "store_id": "S-1",
         "fired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
        {"id": "tx-b", "state": "fired_unpaid", "store_id": "S-1",
         "fired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
    ]
    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: rows

    async def fake_advance(**kw):
        if kw["transaction_id"] == "tx-a":
            raise RuntimeError("transient")
        return {"state": kw["to_state"]}

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx, \
         patch("app.services.bridge.no_show_sweep.read_no_show_timeouts",
               new=AsyncMock(return_value={"S-1": 30})):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)
        mock_tx.advance_state = AsyncMock(side_effect=fake_advance)

        result = await sweep_no_shows()

    # tx-a failed, tx-b succeeded
    assert result["transitioned"] == 1
    assert result["failed"]       == 1


# ── Per-store timeout dial (이번 작업) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_show_sweep_uses_per_store_timeout():
    """Two stores with different timeouts: 15-min store rolls a 20-min-old order
    over to NO_SHOW; 60-min store leaves the same-aged order alone.
    (매장별 timeout 차등 적용 검증)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    twenty_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    rows = [
        {"id": "tx-fast", "state": "fired_unpaid", "store_id": "S-FAST",
         "fired_at": twenty_min_ago},
        {"id": "tx-slow", "state": "fired_unpaid", "store_id": "S-SLOW",
         "fired_at": twenty_min_ago},
    ]
    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: rows

    advance_calls: list = []

    async def fake_advance(**kw):
        advance_calls.append(kw)
        return {"state": kw["to_state"]}

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx, \
         patch("app.services.bridge.no_show_sweep.read_no_show_timeouts",
               new=AsyncMock(return_value={"S-FAST": 15, "S-SLOW": 60})):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)
        mock_tx.advance_state = AsyncMock(side_effect=fake_advance)

        result = await sweep_no_shows()

    assert result["transitioned"] == 1
    assert advance_calls[0]["transaction_id"] == "tx-fast"


@pytest.mark.asyncio
async def test_no_show_sweep_falls_back_to_default_when_store_missing():
    """Store with no order_policy entry ⇒ falls back to the global default
    (settings.no_show_timeout_minutes). (정책 누락 매장은 글로벌 기본값 사용)
    """
    from app.services.bridge.no_show_sweep import sweep_no_shows

    overdue = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    rows = [
        {"id": "tx-1", "state": "fired_unpaid", "store_id": "S-NEW",
         "fired_at": overdue},
    ]
    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: rows

    with patch("app.services.bridge.no_show_sweep.httpx.AsyncClient") as MockClient, \
         patch("app.services.bridge.no_show_sweep.transactions") as mock_tx, \
         patch("app.services.bridge.no_show_sweep.read_no_show_timeouts",
               new=AsyncMock(return_value={})):     # no per-store entry
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)
        mock_tx.advance_state = AsyncMock()

        result = await sweep_no_shows()

    # 45 min > default 30 min → transitioned
    assert result["transitioned"] == 1


# ── read_no_show_timeouts helper ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_no_show_timeouts_returns_per_store_map():
    """Helper reads order_policy.no_show_timeout_minutes per store_configs row.
    (각 store_configs 행에서 매장별 timeout 추출)
    """
    from app.services.policy.order_lanes import read_no_show_timeouts

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"store_id": "S-A", "order_policy": {"no_show_timeout_minutes": 15}},
        {"store_id": "S-B", "order_policy": {"no_show_timeout_minutes": 60}},
        {"store_id": "S-C", "order_policy": {"fire_immediate_threshold_cents": 2000}},  # missing key
        {"store_id": "S-D", "order_policy": None},
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        result = await read_no_show_timeouts()

    assert result == {"S-A": 15, "S-B": 60}        # rows missing the key are excluded


@pytest.mark.asyncio
async def test_read_no_show_timeouts_clamps_invalid_values():
    """Out-of-range values (≤0 or >1440) are dropped so a misconfig can't
    accidentally disable or balloon the sweep.
    (범위 밖 값은 무시 — 운영 사고 방지)
    """
    from app.services.policy.order_lanes import read_no_show_timeouts

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"store_id": "S-OK",   "order_policy": {"no_show_timeout_minutes": 30}},
        {"store_id": "S-NEG",  "order_policy": {"no_show_timeout_minutes": -5}},
        {"store_id": "S-HUGE", "order_policy": {"no_show_timeout_minutes": 99999}},
        {"store_id": "S-ZERO", "order_policy": {"no_show_timeout_minutes": 0}},
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        result = await read_no_show_timeouts()

    assert result == {"S-OK": 30}
