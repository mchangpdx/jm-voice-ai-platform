# Email NATO recital latch — regression tests for Call #2 'cym eet@gmail.com' bug
# (이메일 NATO recital 별도 latch — Call #2 공백 버그 회귀 방지)
#
# Live trigger: 2026-05-08 callSid CA47b6683b4d922210ca01d030cf15664f.
# Agent NATO recital was correct ("C as in Charlie, ... T as in Tango at
# gmail.com" → cymeet@gmail.com), but by the time create_order fired,
# session_state["last_assistant_text"] had been overwritten by the order
# confirmation ("Confirming one 20 ounce iced oat milk café latte..."), so
# reconcile_email_with_recital saw a non-NATO text, returned None, and the
# LLM-generated args.customer_email "cym eet@gmail.com" sailed through to
# bridge_transactions verbatim.
#
# Fix: latch any agent text containing a parseable NATO email into a
# separate session_state field that survives across intervening turns.

from __future__ import annotations

import pytest

from app.services.voice.recital import (
    extract_email_from_recital,
    reconcile_email_with_recital,
)


# Real Call #2 NATO recital (verbatim from log line 09:40:28)
CALL2_NATO_RECITAL = (
    "Just to confirm — C as in Charlie, Y as in Yankee, M as in Mike, "
    "E as in Echo, E as in Echo, T as in Tango at gmail.com — did I "
    "get that right?"
)

# The agent's NEXT turn (the order confirmation that overwrote
# last_assistant_text in the broken path).
CALL2_ORDER_CONFIRM = (
    "Confirming one 20 ounce iced oat milk café latte for Sophia for "
    "$7.25 — is that right?"
)

# What the LLM put in args.customer_email — note the inserted space.
CALL2_BUGGY_ARGS_EMAIL = "cym eet@gmail.com"

# What the customer actually confirmed (and what the agent's NATO spelled).
CALL2_CORRECT_EMAIL = "cymeet@gmail.com"


# ── Lookup logic (mirrors realtime_voice.py:173 reconcile dispatch) ───────────

def _resolve_recital_text(session_state: dict) -> str | None:
    """Mirror the production lookup: prefer the latched NATO slot, fall
    back to last_assistant_text. Returns the text reconcile should parse.
    """
    return (
        session_state.get("last_email_recital_text")
        or session_state.get("last_assistant_text")
    )


# ── Bug regression: the exact Call #2 sequence ────────────────────────────────

def test_call2_regression_nato_then_order_confirm():
    """Reproduce the live failure mode and prove the fix repairs it."""
    # Pre-fix state (what production had on 2026-05-08): NATO recital was
    # spoken at turn 5, order confirmation at turn 6 overwrote it. By the
    # time create_order fires at turn 7, last_assistant_text is the order
    # text and reconcile cannot find the NATO source.
    pre_fix = {"last_assistant_text": CALL2_ORDER_CONFIRM}
    pre_fix_text = _resolve_recital_text(pre_fix)
    pre_fix_result = reconcile_email_with_recital(
        args_email=CALL2_BUGGY_ARGS_EMAIL,
        last_assistant_text=pre_fix_text,
    )
    # Pre-fix path returns the buggy args verbatim — the bug we shipped.
    assert pre_fix_result == CALL2_BUGGY_ARGS_EMAIL

    # Post-fix state: last_email_recital_text was latched at the email turn
    # and survives the order confirmation overwriting last_assistant_text.
    post_fix = {
        "last_assistant_text":      CALL2_ORDER_CONFIRM,
        "last_email_recital_text":  CALL2_NATO_RECITAL,
    }
    post_fix_text = _resolve_recital_text(post_fix)
    post_fix_result = reconcile_email_with_recital(
        args_email=CALL2_BUGGY_ARGS_EMAIL,
        last_assistant_text=post_fix_text,
    )
    assert post_fix_result == CALL2_CORRECT_EMAIL


# ── Latch trigger: only NATO-bearing texts update the slot ────────────────────

class TestLatchTrigger:
    """Mirror the realtime_voice latching rule:
        if extract_email_from_recital(agent_text):
            session_state["last_email_recital_text"] = agent_text
    """
    def _maybe_latch(self, agent_text: str, session_state: dict) -> None:
        if extract_email_from_recital(agent_text):
            session_state["last_email_recital_text"] = agent_text

    def test_nato_text_latches(self):
        s: dict = {}
        self._maybe_latch(CALL2_NATO_RECITAL, s)
        assert s.get("last_email_recital_text") == CALL2_NATO_RECITAL

    def test_order_confirm_does_not_latch(self):
        s: dict = {}
        self._maybe_latch(CALL2_ORDER_CONFIRM, s)
        assert "last_email_recital_text" not in s

    def test_generic_greeting_does_not_latch(self):
        s: dict = {}
        self._maybe_latch("JM Cafe, how can I help?", s)
        assert "last_email_recital_text" not in s

    def test_order_confirm_after_nato_does_not_overwrite(self):
        """The whole point of the fix — non-NATO texts must not clear it."""
        s: dict = {}
        self._maybe_latch(CALL2_NATO_RECITAL, s)
        self._maybe_latch(CALL2_ORDER_CONFIRM, s)
        assert s.get("last_email_recital_text") == CALL2_NATO_RECITAL

    def test_second_nato_recital_overwrites_first(self):
        """If the customer corrects their email, the latch must update."""
        old = "Just to confirm — A as in Alpha, B as in Bravo at gmail.com — right?"
        new = "Just to confirm — X as in X-ray, Y as in Yankee, Z as in Zulu at gmail.com — right?"
        s: dict = {}
        self._maybe_latch(old, s)
        self._maybe_latch(new, s)
        assert s["last_email_recital_text"] == new


# ── Backward compatibility: pre-fix CRM auto-fill path still works ────────────

def test_backcompat_crm_autofill_no_nato_path():
    """Call #1 path: CRM block auto-filled the email, no NATO recital ever
    spoken. Reconcile must still let the args email through unchanged.
    """
    s = {
        "last_assistant_text": (
            "I have cymeet@gmail.com on file—do you want to use that?"
        ),
        # last_email_recital_text never set
    }
    text = _resolve_recital_text(s)
    result = reconcile_email_with_recital(
        args_email="cymeet@gmail.com",
        last_assistant_text=text,
    )
    assert result == "cymeet@gmail.com"


def test_backcompat_no_email_at_all():
    """Reservation flow without email NATO — reconcile is a no-op."""
    s = {"last_assistant_text": "Confirming a reservation for Jamie..."}
    text = _resolve_recital_text(s)
    result = reconcile_email_with_recital(
        args_email=None,
        last_assistant_text=text,
    )
    assert result is None


# ── Edge: empty/None latch field falls back gracefully ────────────────────────
# session_state initializes the slot to "" (falsy). The latch code only
# overwrites it with a string that has a parseable NATO email — meaning a
# whitespace-only or other "junk truthy" value can never legitimately end
# up in the slot. Parametrize over the realistic empty values only.

@pytest.mark.parametrize("latched", [None, ""])
def test_empty_latch_falls_back_to_last_assistant_text(latched):
    s = {
        "last_assistant_text":     CALL2_NATO_RECITAL,
        "last_email_recital_text": latched,
    }
    text = _resolve_recital_text(s)
    result = reconcile_email_with_recital(
        args_email=CALL2_BUGGY_ARGS_EMAIL,
        last_assistant_text=text,
    )
    # Fallback path: last_assistant_text happens to BE the NATO this time,
    # so reconcile still recovers the correct email.
    assert result == CALL2_CORRECT_EMAIL


# ── Cross-flow: NATO for reservation_email also benefits from the latch ──────

def test_reservation_email_nato_then_summary_overwrite():
    """make_reservation flow: NATO email → reservation summary → tool fire.
    Same overwrite mechanism, same fix.
    """
    nato = (
        "Just to confirm — J as in Juliet, A as in Alpha, M as in Mike, "
        "I as in India, E as in Echo at gmail.com — did I get that right?"
    )
    summary = (
        "Confirming a reservation for Jamie, party of 4, "
        "Friday, May 9 at 7:00 PM — is that right?"
    )
    s = {
        "last_assistant_text":      summary,
        "last_email_recital_text":  nato,
    }
    text = _resolve_recital_text(s)
    result = reconcile_email_with_recital(
        args_email="jaime@gmail.com",   # LLM dropped a letter
        last_assistant_text=text,
    )
    assert result == "jamie@gmail.com"
