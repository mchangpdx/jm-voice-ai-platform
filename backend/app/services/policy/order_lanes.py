# Phase 2-B.1.7b — Order Policy Engine (threshold lane only)
# (Phase 2-B.1.7b — 주문 정책 엔진 — 임계값 lane 전용)
#
# decide_lane(store_id, total_cents) reads store_configs.order_policy and
# returns a routing decision used by Bridge flows to choose between the
# fire_immediate lane (small ticket — kitchen now, pay link later) and the
# pay_first lane (current default — payment confirmed before kitchen).
#
# Only the A-axis (ticket threshold) is exposed in this version. The B-axis
# (trusted customer tier) and C-axis (daily uncollected cap) ship later when
# CRM and reconciliation are wired up.

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Lane labels (also used as bridge_transactions.payment_lane values)
LANE_FIRE_IMMEDIATE = "fire_immediate"
LANE_PAY_FIRST      = "pay_first"


async def decide_lane(*, store_id: str, total_cents: int) -> dict[str, Any]:
    """Decide which order lane this transaction should take.
    (이 트랜잭션이 어떤 주문 lane을 따라야 하는지 결정)

    Returns:
        {
          "lane": "fire_immediate" | "pay_first",
          "threshold_cents": int,           # the threshold consulted (0 = policy off)
          "reason": str                     # short audit string for bridge_events
        }

    Behaviour:
        * threshold == 0 OR row missing OR order_policy NULL ⇒ pay_first (safe default)
        * total_cents <  threshold ⇒ fire_immediate
        * total_cents >= threshold ⇒ pay_first
    """
    threshold = await _read_threshold_cents(store_id)

    if threshold <= 0:
        return {
            "lane":            LANE_PAY_FIRST,
            "threshold_cents": 0,
            "reason":          "policy_off_default_pay_first",
        }

    if total_cents < threshold:
        return {
            "lane":            LANE_FIRE_IMMEDIATE,
            "threshold_cents": threshold,
            "reason":          f"total_{total_cents}<threshold_{threshold}",
        }

    return {
        "lane":            LANE_PAY_FIRST,
        "threshold_cents": threshold,
        "reason":          f"total_{total_cents}>=threshold_{threshold}",
    }


async def _read_threshold_cents(store_id: str) -> int:
    """Read store_configs.order_policy.fire_immediate_threshold_cents for a store.
    Missing row, NULL policy, missing key ⇒ 0 (policy off).
    (정책 행 없음 / NULL / 키 없음 ⇒ 0 — 정책 비활성)
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/store_configs",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id": f"eq.{store_id}",
                "select":   "order_policy",
                "limit":    "1",
            },
        )
    if resp.status_code != 200:
        log.warning("decide_lane: store_configs read %s for %s",
                    resp.status_code, store_id)
        return 0

    rows = resp.json() or []
    if not rows:
        return 0

    policy = rows[0].get("order_policy")
    if not isinstance(policy, dict):
        return 0

    raw = policy.get("fire_immediate_threshold_cents")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0
