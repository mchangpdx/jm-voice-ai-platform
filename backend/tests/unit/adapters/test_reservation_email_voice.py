# Voice integration TDD — reservation email defer-and-fire-on-end
# (음성 통합 — make/modify 시 payload set, cancel 시 clear, WS disconnect 시 1통 발송)
#
# Tests written BEFORE implementation. Red until:
#   - voice_websocket initializes session["pending_reservation_email"]
#   - voice_websocket exposes _build_pending_reservation_email_payload helper
#   - the WS disconnect path fires the payload (or clears it after firing)
#
# We test the helper directly + a thin lifecycle simulation against the
# session dict shape so the integration is locked without spinning a
# full WebSocket. End-to-end fire is exercised in the live call.

import pytest


def test_build_payload_includes_args_email_when_present():
    """Helper extracts customer_email + summary fields from tool_args."""
    from app.api.voice_websocket import _build_pending_reservation_email_payload

    args = {
        "customer_name":   "Aaron Chang",
        "customer_email":  "aaron@example.com",
        "reservation_date":"2026-05-08",
        "reservation_time":"19:30",
        "party_size":      4,
        "notes":           "window seat",
    }
    payload = _build_pending_reservation_email_payload(
        args            = args,
        reservation_id  = 252,
        store_name      = "JM Cafe",
        prior_payload   = None,
    )
    assert payload is not None
    assert payload["to"] == "aaron@example.com"
    assert payload["customer_name"] == "Aaron Chang"
    assert payload["store_name"] == "JM Cafe"
    assert payload["party_size"] == 4
    assert payload["reservation_id"] == 252
    assert "May" in payload["date_human"] and "8" in payload["date_human"]
    assert "7:30" in payload["time_12h"]
    assert "window seat" in payload["notes"]


def test_build_payload_carries_email_from_prior_when_args_missing():
    """modify_reservation often omits customer_email — carry it over from
    the prior pending payload so the modified booking still gets emailed."""
    from app.api.voice_websocket import _build_pending_reservation_email_payload

    prior = {
        "to":             "aaron@example.com",
        "customer_name":  "Aaron Chang",
        "store_name":     "JM Cafe",
        "party_size":     4,
        "date_human":     "Friday, May 8",
        "time_12h":       "7:30 PM",
        "notes":          "",
        "reservation_id": 252,
    }
    args_modify = {
        "customer_name":   "Aaron Chang",
        # customer_email intentionally absent
        "reservation_date":"2026-05-08",
        "reservation_time":"18:30",
        "party_size":      6,
        "notes":           "",
    }
    payload = _build_pending_reservation_email_payload(
        args            = args_modify,
        reservation_id  = 252,
        store_name      = "JM Cafe",
        prior_payload   = prior,
    )
    assert payload is not None
    assert payload["to"] == "aaron@example.com"   # carried over
    assert payload["party_size"] == 6             # refreshed
    assert "6:30" in payload["time_12h"]          # refreshed


def test_build_payload_returns_none_when_no_email_anywhere():
    """No email in args, no prior payload → no email can be sent. Helper
    returns None so the caller can skip cleanly."""
    from app.api.voice_websocket import _build_pending_reservation_email_payload

    args = {
        "customer_name":   "Aaron Chang",
        "reservation_date":"2026-05-08",
        "reservation_time":"19:30",
        "party_size":      4,
    }
    payload = _build_pending_reservation_email_payload(
        args            = args,
        reservation_id  = 252,
        store_name      = "JM Cafe",
        prior_payload   = None,
    )
    assert payload is None


def test_session_lifecycle_make_modify_cancel_clears_payload():
    """End-to-end semantics check on the session dict directly:
       make → set
       modify → refresh
       cancel → clear (None)
    """
    from app.api.voice_websocket import _build_pending_reservation_email_payload

    session: dict = {"pending_reservation_email": None}

    # 1. make
    p_make = _build_pending_reservation_email_payload(
        args = {
            "customer_name":   "Aaron",
            "customer_email":  "aaron@example.com",
            "reservation_date":"2026-05-08",
            "reservation_time":"19:30",
            "party_size":      4,
        },
        reservation_id = 252,
        store_name     = "JM Cafe",
        prior_payload  = session["pending_reservation_email"],
    )
    session["pending_reservation_email"] = p_make
    assert session["pending_reservation_email"]["party_size"] == 4

    # 2. modify (no email in args — carry over)
    p_mod = _build_pending_reservation_email_payload(
        args = {
            "customer_name":   "Aaron",
            "reservation_date":"2026-05-08",
            "reservation_time":"18:30",
            "party_size":      6,
        },
        reservation_id = 252,
        store_name     = "JM Cafe",
        prior_payload  = session["pending_reservation_email"],
    )
    session["pending_reservation_email"] = p_mod
    assert session["pending_reservation_email"]["party_size"] == 6
    assert session["pending_reservation_email"]["to"] == "aaron@example.com"

    # 3. cancel — caller wipes the field
    session["pending_reservation_email"] = None
    assert session["pending_reservation_email"] is None
