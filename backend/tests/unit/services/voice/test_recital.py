# Phase 7-A.D Wave A.3 Plan E — NATO recital → email extraction TDD
# (NATO 음성 음철 → 이메일 추출 — TDD)
#
# Why this exists:
#   The voice agent's NATO readback ('C as in Charlie, Y as in Yankee...')
#   is what the customer audibly verifies and confirms with 'yes'. But the
#   LLM independently generates the function-call arg `customer_email` from
#   its own internal representation, and live ops 2026-05-08 showed the args
#   drift by 1+ letters in 10 of 11 calls (cymeet → cymet, cymeet → cyeet,
#   cymeet → cyeemt). The recital is the customer-confirmed source of
#   truth; args.customer_email is unreliable.
#
#   extract_email_from_recital(text) parses the bot's most recent response
#   text and returns the canonical email implied by the NATO readback. The
#   dispatcher then prefers this over args.customer_email when present.

import pytest


@pytest.mark.parametrize("text,expected", [
    # Canonical case from live trigger 2026-05-08 21:42:36 — the bot recited
    # the customer's email correctly with NATO but the args dropped an E.
    (
        "Just to confirm—C as in Charlie, Y as in Yankee, M as in Mike, "
        "E as in Echo, E as in Echo, T as in Tango at gmail.com—did I "
        "get that right?",
        "cymeet@gmail.com",
    ),
    # Variant phrasings the model uses interchangeably.
    (
        "Got it, I'll read it back: C as in Charlie, Y as in Yankee, "
        "M as in Mike, E as in Echo, E as in Echo, T as in Tango "
        "at gmail dot com — did I get that right?",
        "cymeet@gmail.com",
    ),
    # Different domain.
    (
        "Confirming—J as in Juliet, S as in Sierra at outlook.com.",
        "js@outlook.com",
    ),
    # Lowercase NATO words still parsed (model isn't always title-cased).
    (
        "c as in charlie, y as in yankee at gmail.com",
        "cy@gmail.com",
    ),
    # Model occasionally uses 'like' instead of 'as in'.
    (
        "C like Charlie, Y like Yankee, M like Mike at gmail.com",
        "cym@gmail.com",
    ),
])
def test_extract_email_from_nato_recital_canonical_cases(text, expected):
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital(text) == expected


def test_extract_email_returns_none_when_no_nato_present():
    """Plain text with no NATO pattern → None. Dispatcher will fall back to
    args.customer_email unchanged. (NATO 패턴 없음 → None → args 유지)"""
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital("Got it, your order is being placed.") is None
    assert extract_email_from_recital("") is None
    assert extract_email_from_recital("What's the best email for the link?") is None


def test_extract_email_returns_none_when_letters_present_but_no_at_domain():
    """Letters spelled but the bot didn't get to the domain yet — incomplete
    recital, don't try to guess. (도메인 미언급 — 추출 불가, None)"""
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital("C as in Charlie, Y as in Yankee...") is None


def test_extract_email_handles_at_dot_pronunciation():
    """Bot says 'at gmail dot com' (TTS-friendly) → return 'gmail.com'.
    (구어체 'dot' 처리 — 도트 포함 도메인 정상 복원)"""
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital(
        "C as in Charlie at gmail dot com"
    ) == "c@gmail.com"


def test_extract_email_supports_subdomain_and_multidot_domains():
    """Outlook/Yahoo/work domains may be multi-dotted. Return them whole.
    (서브도메인 / 다중 dot 도메인 처리)"""
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital(
        "M as in Mike at mail.example.co.uk"
    ) == "m@mail.example.co.uk"


def test_extract_email_picks_last_recital_block_when_multiple():
    """If the bot read back twice in one response (e.g. 'I had X, but you
    corrected to Y, so now it's...'), the LAST NATO block is the binding
    one. (마지막 recital이 최종 — 정정된 값 우선)"""
    from app.services.voice.recital import extract_email_from_recital
    text = (
        "I heard C as in Charlie, X as in X-ray at gmail.com — "
        "you corrected me to "
        "C as in Charlie, Y as in Yankee at gmail.com — did I get it right?"
    )
    assert extract_email_from_recital(text) == "cy@gmail.com"


def test_extract_email_robust_against_punctuation_and_hyphens():
    """Em-dashes, en-dashes, commas, semicolons between letters all OK.
    (구두점 다양성 — em-dash, en-dash, 세미콜론도 허용)"""
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital(
        "C — as in Charlie; Y, as in Yankee — at gmail.com"
    ) == "cy@gmail.com"


def test_extract_email_double_letter_preserved():
    """The original bug — double E (cymeet) was being collapsed by the LLM.
    The recital says E as in Echo TWICE; extraction MUST preserve both.
    (live trigger CYMEET → 'E as in Echo' 두 번 등장 → 'ee' 두 글자 보존)"""
    from app.services.voice.recital import extract_email_from_recital
    assert extract_email_from_recital(
        "C as in Charlie, Y as in Yankee, M as in Mike, "
        "E as in Echo, E as in Echo, T as in Tango at gmail.com"
    ) == "cymeet@gmail.com"


# ── reconcile_email_with_recital — dispatcher-facing helper ───────────────────
# Combines the NATO extraction with the args-side email so the caller can
# do "args.customer_email = reconcile_email_with_recital(args, last_text)".

def test_reconcile_overrides_args_when_drift_detected():
    """args drift → recital wins. The whole point of Plan E."""
    from app.services.voice.recital import reconcile_email_with_recital
    nato_text = ("C as in Charlie, Y as in Yankee, M as in Mike, "
                 "E as in Echo, E as in Echo, T as in Tango at gmail.com")
    out = reconcile_email_with_recital(
        args_email="cymet@gmail.com",   # LLM dropped one E
        last_assistant_text=nato_text,
    )
    assert out == "cymeet@gmail.com"


def test_reconcile_keeps_args_when_recital_matches():
    """No drift → no change. Preserve args verbatim."""
    from app.services.voice.recital import reconcile_email_with_recital
    nato = "C as in Charlie, Y as in Yankee at gmail.com"
    out = reconcile_email_with_recital(
        args_email="cy@gmail.com",
        last_assistant_text=nato,
    )
    assert out == "cy@gmail.com"


def test_reconcile_keeps_args_when_no_nato_in_recital():
    """No NATO present (e.g. bot said 'sending the link now') → trust args."""
    from app.services.voice.recital import reconcile_email_with_recital
    out = reconcile_email_with_recital(
        args_email="someone@example.com",
        last_assistant_text="sending the link to your phone now",
    )
    assert out == "someone@example.com"


def test_reconcile_keeps_args_when_args_empty_and_no_recital():
    """Both empty/missing → return whatever args was (None or empty)."""
    from app.services.voice.recital import reconcile_email_with_recital
    assert reconcile_email_with_recital(args_email=None, last_assistant_text="") is None
    assert reconcile_email_with_recital(args_email="", last_assistant_text="hi") == ""


def test_reconcile_uses_recital_when_args_empty_but_recital_has_email():
    """args missing email but bot recited one → use recital. Edge case for
    LLM forgetting to include the field at all."""
    from app.services.voice.recital import reconcile_email_with_recital
    out = reconcile_email_with_recital(
        args_email=None,
        last_assistant_text="C as in Charlie, Y as in Yankee at gmail.com",
    )
    assert out == "cy@gmail.com"
