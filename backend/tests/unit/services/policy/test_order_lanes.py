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
    assert len(decision["reason"]) > 0
