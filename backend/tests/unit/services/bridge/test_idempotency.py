# Bridge Server — Idempotency tests
# (Bridge Server — 멱등성 테스트)
#
# Two scopes of idempotency:
#   1. Inbound tool_call from Gemini — same call_id+intent should NOT create
#      duplicate transactions (covers Retell barge-in resends)
#   2. Inbound Maverick webhook — same maverick_txn_id should be processed once

import pytest


def test_idempotency_key_from_tool_call_is_deterministic():
    """Same store + customer_phone + intent_hash → same key."""
    from app.services.bridge.idempotency import key_from_tool_call

    args = {
        "store_id":       "STORE-1",
        "customer_phone": "+15037079566",
        "intent":         "create_order",
        "intent_args":    {"items": [{"id": "X", "qty": 1}]},
    }
    k1 = key_from_tool_call(**args)
    k2 = key_from_tool_call(**args)
    assert k1 == k2
    assert isinstance(k1, str)
    assert len(k1) >= 16


def test_idempotency_key_differs_for_different_phone():
    from app.services.bridge.idempotency import key_from_tool_call
    base = {"store_id": "S1", "intent": "create_order", "intent_args": {"x": 1}}
    k1 = key_from_tool_call(customer_phone="+15037079566", **base)
    k2 = key_from_tool_call(customer_phone="+15037079567", **base)
    assert k1 != k2


def test_idempotency_key_differs_for_different_args():
    from app.services.bridge.idempotency import key_from_tool_call
    base = {"store_id": "S1", "customer_phone": "+1503", "intent": "create_order"}
    k1 = key_from_tool_call(intent_args={"items": [{"id": "A"}]}, **base)
    k2 = key_from_tool_call(intent_args={"items": [{"id": "B"}]}, **base)
    assert k1 != k2


def test_idempotency_key_args_order_independent():
    """JSON object key ordering must not affect key (canonical form)."""
    from app.services.bridge.idempotency import key_from_tool_call
    base = {"store_id": "S1", "customer_phone": "+1503", "intent": "x"}
    k1 = key_from_tool_call(intent_args={"a": 1, "b": 2}, **base)
    k2 = key_from_tool_call(intent_args={"b": 2, "a": 1}, **base)
    assert k1 == k2


def test_webhook_idempotency_key_uses_maverick_txn_id():
    from app.services.bridge.idempotency import key_from_webhook
    k1 = key_from_webhook(maverick_txn_id="TX-9876")
    k2 = key_from_webhook(maverick_txn_id="TX-9876")
    assert k1 == k2
    assert "TX-9876" in k1


def test_webhook_idempotency_distinct_txn_ids():
    from app.services.bridge.idempotency import key_from_webhook
    assert key_from_webhook(maverick_txn_id="TX-1") != key_from_webhook(maverick_txn_id="TX-2")
