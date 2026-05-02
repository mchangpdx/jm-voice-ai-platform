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
