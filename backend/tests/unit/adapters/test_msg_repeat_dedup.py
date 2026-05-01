# TDD tests for tool-result yield dedup — Wave 1 P0-3
# (bridge tool-result 같은 message 8초 내 재발화 차단)
#
# Background: even after P0-2 swapped 'Your order is unchanged' for the
# clarification line ('Hmm, I didn't catch the change...'), the SAME
# clarification gets yielded twice when the customer keeps trying to
# modify with the same off-menu request. Live: call_9b67f4ec… T17/T18
# (21:39:44 → 21:39:50, 6s apart) yielded the noop script back-to-back
# because the upstream last_tool_sig dedup window is 5s — T18 is just
# past it. This is the third dedup layer (after tool-call dedup and
# recital dedup) and operates on the literal yielded string.
#
# Helper contract:
#   _should_skip_msg_repeat(session: dict|None, msg: str,
#                           now_ts: float, window_s: float = 8.0) -> bool
#   _remember_msg(session: dict|None, msg: str, now_ts: float) -> None

from app.api.voice_websocket import _should_skip_msg_repeat, _remember_msg


# ── T1: same msg within window → skip ────────────────────────────────────────
def test_same_msg_within_window_returns_true():
    """Same yielded line 6s after the first — should skip."""
    session = {}
    msg     = "Hmm, I didn't catch the change. Your order is still 1 Latte for $4.99."

    _remember_msg(session, msg, now_ts=100.0)
    assert _should_skip_msg_repeat(session, msg, now_ts=106.0, window_s=8.0) is True


# ── T2: same msg after window → do NOT skip ──────────────────────────────────
def test_same_msg_after_window_returns_false():
    """Same line 9s after — window expired, allow re-emit."""
    session = {}
    msg     = "Updated — your new total is $5.99. The same payment link still works."

    _remember_msg(session, msg, now_ts=100.0)
    assert _should_skip_msg_repeat(session, msg, now_ts=109.0, window_s=8.0) is False


# ── T3: different msg within window → do NOT skip ────────────────────────────
def test_different_msg_within_window_returns_false():
    """Customer-facing line legitimately changed — must yield the new one."""
    session = {}
    msg_a   = "Updated — your new total is $5.99. The same payment link still works."
    msg_b   = "Your order is unchanged — the total is still $5.99. Tap the payment link whenever you're ready."

    _remember_msg(session, msg_a, now_ts=100.0)
    assert _should_skip_msg_repeat(session, msg_b, now_ts=102.0, window_s=8.0) is False


# ── T4: empty msg → no skip, no crash ─────────────────────────────────────────
def test_empty_msg_returns_false():
    """Empty string is never deduped — fallback yield path stays intact."""
    session = {}
    _remember_msg(session, "", now_ts=100.0)
    assert _should_skip_msg_repeat(session, "", now_ts=101.0, window_s=8.0) is False


# ── T5: None session → no crash, no skip ──────────────────────────────────────
def test_none_session_returns_false():
    """Defensive: helper must not crash on None session."""
    assert _should_skip_msg_repeat(None, "x", now_ts=100.0, window_s=8.0) is False
    _remember_msg(None, "x", now_ts=100.0)


# ── T6: missing key in session → treated as first call ────────────────────────
def test_missing_session_key_treated_as_first_call():
    """First yield with no prior state must allow."""
    session = {}
    assert _should_skip_msg_repeat(session, "hello", now_ts=100.0, window_s=8.0) is False


# ── T7: skip path does NOT slide the window ───────────────────────────────────
def test_skip_path_does_not_slide_window():
    """Repeated skips bump count but ts stays anchored at first emission."""
    session = {}
    msg     = "Updated — your new total is $9.99. The same payment link still works."

    _remember_msg(session, msg, now_ts=100.0)
    assert session["last_msg_sig"][0] == msg
    assert session["last_msg_sig"][1] == 100.0
    assert session["last_msg_sig"][2] == 0

    # First skip
    assert _should_skip_msg_repeat(session, msg, now_ts=102.0, window_s=8.0) is True
    assert session["last_msg_sig"][1] == 100.0    # ts unchanged
    assert session["last_msg_sig"][2] == 1         # count bumped

    # Second skip — ts still anchored
    assert _should_skip_msg_repeat(session, msg, now_ts=105.0, window_s=8.0) is True
    assert session["last_msg_sig"][1] == 100.0
    assert session["last_msg_sig"][2] == 2

    # Past window — fresh emission
    assert _should_skip_msg_repeat(session, msg, now_ts=109.0, window_s=8.0) is False


# ── T8: long msg uses literal compare (no truncation) ─────────────────────────
def test_long_msg_literal_compare():
    """Two long messages differing only at the end must NOT match."""
    session = {}
    a = "Updated — your new total is $5.99. " + ("X" * 200)
    b = "Updated — your new total is $5.99. " + ("Y" * 200)

    _remember_msg(session, a, now_ts=100.0)
    assert _should_skip_msg_repeat(session, b, now_ts=101.0, window_s=8.0) is False
