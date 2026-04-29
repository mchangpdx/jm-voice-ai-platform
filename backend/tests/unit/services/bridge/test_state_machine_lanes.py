# Phase 2-B.1.7b — State machine extension for fire_immediate lane (TDD)
# (Phase 2-B.1.7b — fire_immediate lane을 위한 상태 기계 확장)
#
# New states:
#   FIRED_UNPAID — kitchen has the ticket, awaiting customer payment
#   NO_SHOW      — fired_unpaid + 30min timeout, written off
#
# New edges:
#   PENDING       → FIRED_UNPAID  (fire_immediate lane decision)
#   FIRED_UNPAID  → PAID          (customer pays via SMS pay link)
#   FIRED_UNPAID  → NO_SHOW       (timeout — bridge_reconciliation cron)
#   FIRED_UNPAID  → CANCELED      (operator cancel)

import pytest


def test_fire_immediate_states_exist():
    from app.services.bridge.state_machine import State
    assert State.FIRED_UNPAID == "fired_unpaid"
    assert State.NO_SHOW      == "no_show"


def test_pending_can_transition_to_fired_unpaid():
    from app.services.bridge.state_machine import can_transition, State
    assert can_transition(State.PENDING, State.FIRED_UNPAID) is True


def test_fired_unpaid_can_transition_to_paid():
    from app.services.bridge.state_machine import can_transition, State
    assert can_transition(State.FIRED_UNPAID, State.PAID) is True


def test_fired_unpaid_can_transition_to_no_show():
    from app.services.bridge.state_machine import can_transition, State
    assert can_transition(State.FIRED_UNPAID, State.NO_SHOW) is True


def test_fired_unpaid_can_transition_to_canceled():
    from app.services.bridge.state_machine import can_transition, State
    assert can_transition(State.FIRED_UNPAID, State.CANCELED) is True


def test_no_show_is_terminal():
    from app.services.bridge.state_machine import can_transition, State
    # NO_SHOW is a terminal write-off — no recovery edges
    assert can_transition(State.NO_SHOW, State.PAID)      is False
    assert can_transition(State.NO_SHOW, State.PENDING)   is False
    assert can_transition(State.NO_SHOW, State.FULFILLED) is False


def test_pending_to_no_show_directly_is_blocked():
    """A pending order must pass through fired_unpaid before no_show — preserves
    audit trail. (no_show 직행 차단 — 감사 추적 보장)
    """
    from app.services.bridge.state_machine import can_transition, State
    assert can_transition(State.PENDING, State.NO_SHOW) is False
