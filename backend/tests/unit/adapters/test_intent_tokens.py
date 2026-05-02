# TDD — _has_explicit_modify_intent token coverage for cancel
# (B2 cancel_order 게이트 회복 — 'cancel' 토큰 인식)
#
# Live: call_1df4b0188bf43b006ba989f406b T11/T12 — customer said
# "Also, can I cancel" / "Also, can I cancel Americano?" after a
# successful modify. The MODIFY COOLDOWN gate ran
# _has_explicit_modify_intent_since_outcome → returned False because
# "cancel" was not in _MODIFY_INTENT_TOKENS, so cooldown swallowed
# the intent and yielded the closing line. cancel_order tool was
# never called even though Gemini knew about it (system prompt
# rule 7) — the gate locked it out.
#
# Fix: add "cancel" to _MODIFY_INTENT_TOKENS. The token only governs
# whether cooldown lets the turn THROUGH to the AUTO-FIRE recital
# stage; the actual tool selection (modify_order vs cancel_order)
# stays with Gemini per its system prompt rules.

from app.api.voice_websocket import _has_explicit_modify_intent


# ── B2 fix: cancel must register as explicit intent ──────────────────────────

def test_cancel_alone_is_explicit_intent():
    assert _has_explicit_modify_intent("cancel") is True


def test_cancel_my_order_is_explicit_intent():
    assert _has_explicit_modify_intent("cancel my order") is True


def test_can_i_cancel_americano_is_explicit_intent():
    """Live phrase from call_1df4b018… T12."""
    assert _has_explicit_modify_intent("Okay, great. Also, can I cancel Americano?") is True


def test_never_mind_cancel_it_is_explicit_intent():
    assert _has_explicit_modify_intent("Never mind, cancel it.") is True


# ── Regression — existing tokens still recognized ─────────────────────────────

def test_add_still_explicit_intent():
    assert _has_explicit_modify_intent("Can I add a latte?") is True


def test_remove_still_explicit_intent():
    assert _has_explicit_modify_intent("Please remove the croissant.") is True


def test_change_still_explicit_intent():
    assert _has_explicit_modify_intent("Change it to two lattes instead.") is True


def test_actually_still_explicit_intent():
    """Live: customers very often start mods with 'Actually...'."""
    assert _has_explicit_modify_intent("Actually, can you make it three?") is True


# ── Regression — bare acks must NOT register as intent ───────────────────────

def test_bare_okay_not_explicit_intent():
    """Critical: cooldown depends on bare ack returning False so the bot
    stops modifying after the customer just acknowledges."""
    assert _has_explicit_modify_intent("okay") is False


def test_bare_thanks_not_explicit_intent():
    assert _has_explicit_modify_intent("thanks") is False


def test_bare_yes_not_explicit_intent():
    assert _has_explicit_modify_intent("yes") is False


def test_okay_great_thank_you_not_explicit_intent():
    """Live phrase that closed the previous call cleanly — must stay False."""
    assert _has_explicit_modify_intent("Okay, great. Thank you.") is False


def test_empty_text_not_explicit_intent():
    assert _has_explicit_modify_intent("") is False


def test_none_text_not_explicit_intent():
    assert _has_explicit_modify_intent(None) is False
