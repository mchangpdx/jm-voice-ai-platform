# TDD tests for placeholder name guard — Fix #3
# (AUTO-FIRE recital이 'for unknown — is that right?' 발화하던 회귀 차단)
#
# Background: voice_websocket AUTO-FIRE recital builder used
# tool_args.customer_name verbatim. When Gemini hallucinated a
# placeholder ('Customer'/'Global'/'unknown'/'Unknown Customer'),
# the bot said "for unknown — is that right?" before the bridge
# validate step rejected the same value. Bridge already had a
# token-level placeholder set; this test pins the shared module
# constant + helper that voice and bridge now both use.
#
# Live observed: call_6b935ab0 ('Customer'), call_1df4b018 ('Global'),
# call_f424f5b86 ('unknown').

import pytest

from app.services.bridge.flows import (
    PLACEHOLDER_NAMES,
    is_placeholder_name,
)


# ── T1: empty / whitespace → placeholder ──────────────────────────────────────
@pytest.mark.parametrize("raw", ["", "   ", "\t", "\n  \n"])
def test_empty_is_placeholder(raw: str):
    assert is_placeholder_name(raw) is True


# ── T2: exact-match placeholder tokens → placeholder ──────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        "Customer", "customer", "CUSTOMER",
        "Unknown",  "unknown",
        "Global",   "global",
        "Anonymous", "Guest", "Caller", "User",
        "Test", "Tester",
        "N/A", "n/a", "NA", "na",
    ],
)
def test_exact_placeholder_token_rejected(raw: str):
    assert is_placeholder_name(raw) is True


# ── T3: multi-token strings with ANY placeholder token → placeholder ──────────
@pytest.mark.parametrize(
    "raw",
    [
        "Unknown Customer",
        "Customer Service",
        "Global Foods",
        "Test Account",
        "Anonymous User",
    ],
)
def test_multi_token_with_placeholder_rejected(raw: str):
    assert is_placeholder_name(raw) is True


# ── T4: legitimate names that contain placeholder substrings → NOT placeholder
# ('Carmen' contains 'arme' but is not 'guest'; 'Customers' is not a token
# we'd expect from Gemini, but if it ever appears we treat it as legit since
# substring match would over-block. Token-only matching is intentional.)
@pytest.mark.parametrize(
    "raw",
    [
        "Carmen",
        "Michael Chen",
        "Sarah Johnson",
        "Maria Gonzalez",
        "Patel",
        "O'Brien",
        "Jean-Luc",
        "Globalia",
    ],
)
def test_legitimate_names_pass(raw: str):
    assert is_placeholder_name(raw) is False


# ── T5: 'global' is in the shared constant (added 2026-05-03) ─────────────────
def test_global_added_to_placeholder_set():
    assert "global" in PLACEHOLDER_NAMES


# ── T6: constant is an immutable frozenset ────────────────────────────────────
def test_placeholder_names_is_frozenset():
    assert isinstance(PLACEHOLDER_NAMES, frozenset)


# ── T7: helper survives surrounding whitespace ────────────────────────────────
def test_helper_strips_whitespace():
    assert is_placeholder_name("  Customer  ") is True
    assert is_placeholder_name("  Carmen  ") is False


# ── T8 (Issue θ): natural-language placeholders with punctuation must be caught
# Live observed call_0741f688 T9 — Gemini filled customer_name with
# '(customer name not provided)'. Old str.split() left '(customer' and
# 'provided)' as tokens that did not match the bare 'customer' entry.
# Switch to re.split(r'[\W_]+', ...) so punctuation is a separator.
# (괄호/콤마/슬래시 등 punctuation이 token에 붙어 우회되던 결함 회귀 차단)
@pytest.mark.parametrize(
    "raw",
    [
        "(customer name not provided)",
        "(Customer Name Not Provided)",
        "[unknown]",
        '"Guest"',
        "'caller'",
        "Unknown - Customer",
        "Unknown / Caller",
        "Customer.",
        "(unknown)",
        "name: customer",
        "<no name>",
    ],
)
def test_natural_language_placeholders_with_punctuation_rejected(raw: str):
    assert is_placeholder_name(raw) is True


# ── T9 (Issue θ regression guard): legitimate names with internal punctuation
# still pass — punctuation split must NOT over-block real names. None of
# their tokens are in PLACEHOLDER_NAMES.
# (정상 이름의 punctuation 분리는 회귀 0 검증)
@pytest.mark.parametrize(
    "raw",
    [
        "O'Brien",
        "O'Connor",
        "Jean-Luc Picard",
        "Mary-Anne Smith",
        "Anne-Marie",
        "St. John",
        "D'Angelo",
        "De La Cruz",
    ],
)
def test_punctuated_legitimate_names_pass(raw: str):
    assert is_placeholder_name(raw) is False
