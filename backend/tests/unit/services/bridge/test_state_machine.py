# Bridge Server — State machine TDD tests
# (Bridge Server — 상태 기계 TDD 테스트)
#
# State graph (spec §3.3):
#   pending ──────► payment_sent ──────► paid ──────► fulfilled
#      │                  │                │
#      ▼                  ▼                ▼
#    canceled          failed           refunded
#
# All transitions are server-enforced, one-way (refund is the only backward edge),
# and any invalid transition raises InvalidTransition.

import pytest


# ── Constants ────────────────────────────────────────────────────────────────

def test_states_enum_complete():
    from app.services.bridge.state_machine import State
    assert State.PENDING        == "pending"
    assert State.PAYMENT_SENT   == "payment_sent"
    assert State.PAID           == "paid"
    assert State.FULFILLED      == "fulfilled"
    assert State.CANCELED       == "canceled"
    assert State.FAILED         == "failed"
    assert State.REFUNDED       == "refunded"


# ── Valid transitions ────────────────────────────────────────────────────────

def test_pending_can_transition_to_payment_sent():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PENDING, State.PAYMENT_SENT) is True


def test_payment_sent_can_transition_to_paid():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PAYMENT_SENT, State.PAID) is True


def test_paid_can_transition_to_fulfilled():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PAID, State.FULFILLED) is True


def test_pending_can_transition_to_canceled():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PENDING, State.CANCELED) is True


def test_payment_sent_can_transition_to_canceled():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PAYMENT_SENT, State.CANCELED) is True


def test_payment_sent_can_transition_to_failed():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PAYMENT_SENT, State.FAILED) is True


def test_paid_can_transition_to_refunded():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PAID, State.REFUNDED) is True


def test_fulfilled_can_transition_to_refunded():
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.FULFILLED, State.REFUNDED) is True


# ── Invalid transitions ──────────────────────────────────────────────────────

def test_canceled_is_terminal():
    from app.services.bridge.state_machine import State, can_transition
    for nxt in [State.PENDING, State.PAYMENT_SENT, State.PAID, State.FULFILLED]:
        assert can_transition(State.CANCELED, nxt) is False


def test_refunded_is_terminal():
    from app.services.bridge.state_machine import State, can_transition
    for nxt in [State.PENDING, State.PAYMENT_SENT, State.PAID, State.FULFILLED]:
        assert can_transition(State.REFUNDED, nxt) is False


def test_cannot_skip_payment():
    """pending → paid (skipping payment_sent) is forbidden — must go via Maverick"""
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.PENDING, State.PAID) is False


def test_cannot_unfulfill():
    """fulfilled cannot go back to paid (only forward to refunded)"""
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.FULFILLED, State.PAID) is False


def test_failed_is_terminal_except_for_recovery():
    """Failed payments cannot transition forward — must create new payment"""
    from app.services.bridge.state_machine import State, can_transition
    assert can_transition(State.FAILED, State.PAID) is False
    assert can_transition(State.FAILED, State.PAYMENT_SENT) is False


# ── Transition() with audit ──────────────────────────────────────────────────

def test_transition_returns_event_dict_on_success():
    from app.services.bridge.state_machine import State, transition
    evt = transition(
        from_state=State.PENDING,
        to_state=State.PAYMENT_SENT,
        source="voice",
        actor="tool_call:create_order",
    )
    assert evt["from_state"] == State.PENDING
    assert evt["to_state"]   == State.PAYMENT_SENT
    assert evt["source"]     == "voice"
    assert evt["actor"]      == "tool_call:create_order"
    assert evt["event_type"] == "state_transition"
    assert "ts" in evt


def test_transition_raises_on_invalid_edge():
    from app.services.bridge.state_machine import State, transition, InvalidTransition
    with pytest.raises(InvalidTransition):
        transition(
            from_state=State.CANCELED,
            to_state=State.PAID,
            source="webhook",
            actor="maverick",
        )


def test_transition_idempotent_when_already_in_target_state():
    """Transition to same state is allowed but emits no-op event (for replay safety)."""
    from app.services.bridge.state_machine import State, transition
    evt = transition(
        from_state=State.PAID,
        to_state=State.PAID,
        source="webhook",
        actor="maverick",
    )
    assert evt["from_state"] == State.PAID
    assert evt["to_state"]   == State.PAID
    assert evt.get("noop")   is True
