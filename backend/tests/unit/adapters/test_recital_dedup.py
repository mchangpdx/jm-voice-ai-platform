# TDD tests for recital dedup helper — Wave 1 P0-1
# (recital 중복 발화 차단 헬퍼 — confirm prompt 무한 반복 fix)
#
# Background: live call call_9b67f4ec… T15→T16 emitted the same recital
# 'Just to confirm — your updated order is 2 Cafe Lattes, 1 Croissant —
# is that right?' twice within 1 second because Retell's STT issued a
# partial→final pair for the same user utterance ('Can you remove one
# garlic bread?'). The bot recited identically and the customer thought
# the bot was broken.
#
# Helper contract:
#   _should_skip_recital(session: dict, recital_sig: str,
#                        now_ts: float, window_s: float = 8.0) -> bool
#
#   - Compares (sig, ts) against session['last_recital_sig'].
#   - Returns True when the same sig was seen within window_s seconds —
#     caller should silently return without yielding.
#   - On True, mutates session['last_recital_sig'] to bump count, but
#     keeps the original ts so the window does not slide forever.
#   - Returns False otherwise — caller must call _remember_recital(...)
#     after yielding so the next attempt within window can be caught.

import pytest
from app.api.voice_websocket import _should_skip_recital, _remember_recital


# ── T1: same sig within window → skip ─────────────────────────────────────────
def test_same_sig_within_window_returns_true():
    """Same recital sig fired 1s after the first — should skip."""
    session = {"last_recital_sig": ("", 0.0, 0)}
    sig     = "modify_order|2 Cafe Lattes,1 Croissant"

    # First emission — caller would yield, then remember
    _remember_recital(session, sig, now_ts=100.0)

    # Second attempt 1s later — same sig
    assert _should_skip_recital(session, sig, now_ts=101.0, window_s=8.0) is True


# ── T2: same sig after window expires → do NOT skip ───────────────────────────
def test_same_sig_after_window_returns_false():
    """Same recital sig 9s after the first — window expired, allow re-emit."""
    session = {"last_recital_sig": ("", 0.0, 0)}
    sig     = "modify_order|2 Cafe Lattes,1 Croissant"

    _remember_recital(session, sig, now_ts=100.0)

    # 9s later, window (8s) expired — fresh recital is legitimate
    assert _should_skip_recital(session, sig, now_ts=109.0, window_s=8.0) is False


# ── T3: different items (different sig) within window → do NOT skip ───────────
def test_different_sig_within_window_returns_false():
    """Items legitimately changed → different sig → fresh recital allowed."""
    session = {"last_recital_sig": ("", 0.0, 0)}
    sig_a   = "modify_order|2 Cafe Lattes,1 Croissant"
    sig_b   = "modify_order|2 Cafe Lattes,1 Croissant,1 Americano"

    _remember_recital(session, sig_a, now_ts=100.0)

    # 2s later, items changed (Americano added)
    assert _should_skip_recital(session, sig_b, now_ts=102.0, window_s=8.0) is False


# ── T4: empty session (first call) → do NOT skip ──────────────────────────────
def test_empty_session_returns_false():
    """First-ever recital with no prior state → must allow yield."""
    session = {"last_recital_sig": ("", 0.0, 0)}
    sig     = "create_order|1 Cheese Pizza"

    assert _should_skip_recital(session, sig, now_ts=100.0, window_s=8.0) is False


# ── T5: different tool name (create vs modify) within window → do NOT skip ────
def test_different_tool_name_returns_false():
    """tool_name baked into sig — create_order ≠ modify_order, distinct recitals."""
    session = {"last_recital_sig": ("", 0.0, 0)}
    sig_create = "create_order|1 Latte"
    sig_modify = "modify_order|1 Latte"

    _remember_recital(session, sig_create, now_ts=100.0)
    assert _should_skip_recital(session, sig_modify, now_ts=101.0, window_s=8.0) is False


# ── T6: skip path bumps count but keeps original ts ───────────────────────────
def test_skip_path_does_not_slide_window():
    """count bumps on each skip; ts stays at original emission so window
    expires deterministically rather than extending forever."""
    session = {"last_recital_sig": ("", 0.0, 0)}
    sig     = "modify_order|2 Cafe Lattes"

    _remember_recital(session, sig, now_ts=100.0)
    assert session["last_recital_sig"] == (sig, 100.0, 0)

    # Skip 1
    assert _should_skip_recital(session, sig, now_ts=102.0, window_s=8.0) is True
    assert session["last_recital_sig"][0] == sig
    assert session["last_recital_sig"][1] == 100.0     # ts unchanged
    assert session["last_recital_sig"][2] == 1          # count bumped

    # Skip 2 (still within 8s of original)
    assert _should_skip_recital(session, sig, now_ts=105.0, window_s=8.0) is True
    assert session["last_recital_sig"][1] == 100.0
    assert session["last_recital_sig"][2] == 2


# ── T7: session with missing key → graceful default ───────────────────────────
def test_missing_session_key_treated_as_first_call():
    """Defensive: if session doesn't have last_recital_sig yet, treat as first."""
    session = {}                                   # NO last_recital_sig
    sig     = "modify_order|1 Latte"

    assert _should_skip_recital(session, sig, now_ts=100.0, window_s=8.0) is False


# ── T8: None session → graceful (no-op skip=False, no crash) ──────────────────
def test_none_session_returns_false_no_crash():
    """Edge: helper must not crash on None session (early-init paths)."""
    assert _should_skip_recital(None, "x", now_ts=100.0, window_s=8.0) is False
    # _remember_recital must also no-op on None
    _remember_recital(None, "x", now_ts=100.0)
