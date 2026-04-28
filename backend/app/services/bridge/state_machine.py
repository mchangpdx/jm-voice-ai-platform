# Bridge Server — State machine
# (Bridge Server — 상태 기계)
#
# State graph:
#   pending ──────► payment_sent ──────► paid ──────► fulfilled
#      │                  │                │             │
#      ▼                  ▼                ▼             ▼
#   canceled            canceled        refunded      refunded
#                       failed
#
# All transitions are server-enforced. The transition() function is the ONLY way
# to advance state — direct DB updates are forbidden by convention (and ideally
# enforced by RLS / audit triggers in production).

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class State:
    """Transaction state. Module-level constants for stable string comparison.
    (트랜잭션 상태 상수)
    """
    PENDING       = "pending"
    PAYMENT_SENT  = "payment_sent"
    PAID          = "paid"
    FULFILLED     = "fulfilled"
    CANCELED      = "canceled"
    FAILED        = "failed"
    REFUNDED      = "refunded"


# Adjacency list of valid forward edges (refund is the only retro edge)
_VALID_TRANSITIONS: dict[str, set[str]] = {
    State.PENDING:      {State.PAYMENT_SENT, State.CANCELED},
    State.PAYMENT_SENT: {State.PAID, State.CANCELED, State.FAILED},
    State.PAID:         {State.FULFILLED, State.REFUNDED},
    State.FULFILLED:    {State.REFUNDED},
    State.CANCELED:     set(),     # terminal
    State.FAILED:       set(),     # terminal — recovery requires NEW payment row
    State.REFUNDED:     set(),     # terminal
}


class InvalidTransition(Exception):
    """Raised when a state transition is not allowed by the state machine.
    (상태 기계 규칙으로 허용되지 않는 전이 발생 시 예외)
    """
    pass


def can_transition(from_state: str, to_state: str) -> bool:
    """Pure predicate: is this state transition allowed?
    (순수 술어: 이 상태 전이가 허용되는가)
    """
    if from_state == to_state:
        return True  # idempotent self-transition (replay-safe)
    allowed = _VALID_TRANSITIONS.get(from_state, set())
    return to_state in allowed


def transition(
    from_state: str,
    to_state:   str,
    source:     str,        # 'voice' | 'webhook' | 'cron' | 'admin'
    actor:      str,        # 'tool_call:create_order' | 'maverick' | 'reconciliation' etc.
) -> dict[str, Any]:
    """Validate + emit audit event for a state transition.
    (상태 전이 검증 + 감사 이벤트 발생)

    Returns a dict suitable for INSERT into bridge_events. Caller is responsible
    for the actual DB write (this function is pure aside from time).

    Raises InvalidTransition if the edge is not in the state graph.
    """
    if not can_transition(from_state, to_state):
        raise InvalidTransition(
            f"cannot transition {from_state!r} → {to_state!r} (source={source}, actor={actor})"
        )

    evt: dict[str, Any] = {
        "event_type": "state_transition",
        "from_state": from_state,
        "to_state":   to_state,
        "source":     source,
        "actor":      actor,
        "ts":         datetime.now(timezone.utc).isoformat(),
    }
    if from_state == to_state:
        evt["noop"] = True
    return evt
