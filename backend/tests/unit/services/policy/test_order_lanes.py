# Phase 2-B.1.7b — Order Policy Engine (threshold-only) TDD
# (Phase 2-B.1.7b — 주문 정책 엔진 — 임계값 전용 — TDD)
#
# decide_lane(store_id, total_cents) reads store_configs.order_policy and
# returns a routing decision:
#   { lane: 'fire_immediate' | 'pay_first', threshold_cents, reason }
#
# This version exposes only the A-axis (ticket threshold). B (trusted tier)
# and C (daily uncollected cap) are deferred per user direction.

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_decide_lane_pay_first_when_total_meets_threshold():
    """Order total ≥ threshold ⇒ pay_first lane (current default behavior).
    (총액이 임계값 이상 ⇒ pay_first)
    """
    from app.services.policy.order_lanes import decide_lane

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"order_policy": {"fire_immediate_threshold_cents": 2000}}
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        decision = await decide_lane(store_id="S", total_cents=2000)  # exactly at threshold

    assert decision["lane"] == "pay_first"
    assert decision["threshold_cents"] == 2000


@pytest.mark.asyncio
async def test_decide_lane_fire_immediate_when_below_threshold():
    """Order total < threshold ⇒ fire_immediate (kitchen now, pay link later).
    (임계값 미만 ⇒ fire_immediate)
    """
    from app.services.policy.order_lanes import decide_lane

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"order_policy": {"fire_immediate_threshold_cents": 2500}}
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        decision = await decide_lane(store_id="S", total_cents=899)  # $8.99 coffee

    assert decision["lane"] == "fire_immediate"
    assert decision["threshold_cents"] == 2500


@pytest.mark.asyncio
async def test_decide_lane_defaults_to_pay_first_when_no_policy_row():
    """Missing store_configs row ⇒ safe default of pay_first (threshold=0).
    (정책 행 없음 ⇒ pay_first 기본값 — 안전 우선)
    """
    from app.services.policy.order_lanes import decide_lane

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: []  # no row

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        decision = await decide_lane(store_id="S", total_cents=500)

    assert decision["lane"] == "pay_first"
    assert decision["threshold_cents"] == 0


@pytest.mark.asyncio
async def test_decide_lane_defaults_when_threshold_is_zero():
    """Explicit threshold=0 means policy is OFF — every order goes pay_first.
    (임계값 0 ⇒ 정책 비활성, 모든 주문 pay_first)
    """
    from app.services.policy.order_lanes import decide_lane

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"order_policy": {"fire_immediate_threshold_cents": 0}}
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        decision = await decide_lane(store_id="S", total_cents=100)

    assert decision["lane"] == "pay_first"


@pytest.mark.asyncio
async def test_decide_lane_handles_null_policy_column():
    """Existing store_configs row with NULL order_policy ⇒ safe default.
    (기존 행에 정책 컬럼이 NULL이면 안전 기본값)
    """
    from app.services.policy.order_lanes import decide_lane

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [{"order_policy": None}]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        decision = await decide_lane(store_id="S", total_cents=2000)

    assert decision["lane"] == "pay_first"
    assert decision["threshold_cents"] == 0


@pytest.mark.asyncio
async def test_decide_lane_includes_reason_for_audit():
    """Decision dict carries a human-readable reason — written to bridge_events
    so an operator can trace why a particular order was routed which way.
    (감사용 reason 필드 — 운영자가 라우팅 이유 추적 가능)
    """
    from app.services.policy.order_lanes import decide_lane

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"order_policy": {"fire_immediate_threshold_cents": 1500}}
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        decision = await decide_lane(store_id="S", total_cents=600)

    assert "reason" in decision and isinstance(decision["reason"], str)


# ── Phase 7-A.D Wave A.3 Step 2 — split decide_lane for parallel I/O ──────────
# create_order's hot path runs resolve_items + idempotency_probe + decide_lane
# sequentially. Splitting decide_lane into a public read_threshold_cents
# (I/O) + compute_lane_from_threshold (pure compute) lets create_order
# asyncio.gather() the three independent reads — saves ~150-300ms per order.
# decide_lane remains as a wrapper so existing callers/tests are unaffected.


@pytest.mark.asyncio
async def test_read_threshold_cents_returns_value():
    """read_threshold_cents is the public name of the per-store threshold read.
    (read_threshold_cents — 매장 임계값 단독 read의 public API)
    """
    from app.services.policy.order_lanes import read_threshold_cents

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"order_policy": {"fire_immediate_threshold_cents": 2500}}
    ]

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        threshold = await read_threshold_cents("STORE-UUID")

    assert threshold == 2500


@pytest.mark.asyncio
async def test_read_threshold_cents_zero_when_missing():
    """Row absent / NULL policy / missing key ⇒ 0 (policy off)."""
    from app.services.policy.order_lanes import read_threshold_cents

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: []  # no row

    with patch("app.services.policy.order_lanes.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        threshold = await read_threshold_cents("STORE-UUID")

    assert threshold == 0


def test_compute_lane_from_threshold_zero_returns_pay_first():
    """threshold == 0 (policy off) ⇒ pay_first regardless of total."""
    from app.services.policy.order_lanes import compute_lane_from_threshold

    decision = compute_lane_from_threshold(threshold_cents=0, total_cents=500)
    assert decision["lane"] == "pay_first"
    assert decision["threshold_cents"] == 0
    assert "policy_off" in decision["reason"]


def test_compute_lane_from_threshold_below_returns_fire_immediate():
    """total < threshold ⇒ fire_immediate."""
    from app.services.policy.order_lanes import compute_lane_from_threshold

    decision = compute_lane_from_threshold(threshold_cents=2000, total_cents=899)
    assert decision["lane"] == "fire_immediate"
    assert decision["threshold_cents"] == 2000
    assert "899" in decision["reason"] and "2000" in decision["reason"]


def test_compute_lane_from_threshold_at_or_above_returns_pay_first():
    """total >= threshold ⇒ pay_first (boundary inclusive on threshold side)."""
    from app.services.policy.order_lanes import compute_lane_from_threshold

    eq = compute_lane_from_threshold(threshold_cents=2000, total_cents=2000)
    assert eq["lane"] == "pay_first"
    above = compute_lane_from_threshold(threshold_cents=2000, total_cents=2500)
    assert above["lane"] == "pay_first"


def test_compute_lane_is_pure_no_io():
    """compute_lane_from_threshold must not perform I/O — it's the synchronous
    half of decide_lane. (pure function — gather pattern requires I/O 무동반)"""
    from app.services.policy import order_lanes

    # If compute_lane_from_threshold tried to do I/O, monkey-patching httpx
    # to raise would surface it. Pure compute means the call simply ignores it.
    with patch("app.services.policy.order_lanes.httpx.AsyncClient",
               side_effect=AssertionError("compute_lane must not touch httpx")):
        d = order_lanes.compute_lane_from_threshold(
            threshold_cents=1000, total_cents=500,
        )
    assert d["lane"] == "fire_immediate"
    assert len(d["reason"]) > 0
