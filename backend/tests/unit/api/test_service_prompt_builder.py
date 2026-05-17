"""C1 fix (2026-05-18) — vertical-aware build_system_prompt.
(C1 fix — Beauty 라이브 통화에서 발견된 prompt poisoning 해결 회귀 가드)

Live trigger: 5 Beauty calls on 2026-05-18 logged 'reservation' (52×),
'party of N' (9×), 'create_order' (16×), 'recent_orders' (5×) inside the
JM Beauty Salon prompt because build_system_prompt was order-vertical only.
The fix branches on store.vertical_kind so service stores get a much
shorter, appointment-vocabulary prompt without touching the order path.

This file pins two contracts:

  1. **ORDER identity** — 4 production order verticals (cafe / pizza /
     mexican / kbbq) MUST produce byte-for-byte identical prompts before
     and after the fix. SHA256 fingerprints captured pre-fix anchor this.

  2. **SERVICE hygiene** — Beauty store prompt MUST NOT contain any of
     the order-vertical tokens (reservation / party / create_order /
     make_reservation / cancel_order / recent_orders) and MUST contain
     the appointment surface (book_appointment / service_lookup /
     appointment / stylist).

Plus length cap, multilingual injection, emergency keyword injection
(C6 piggyback).
"""
from __future__ import annotations

import hashlib
import re

import pytest

from app.api.voice_websocket import build_system_prompt


# build_system_prompt injects a CURRENT DATE/TIME line that varies per call.
# Mask it so SHA256 identity comparisons stay stable across test runs.
# (시각 라인은 매 호출마다 다름 — SHA 비교 전 마스킹)
_TIMESTAMP_RE = re.compile(r"CURRENT DATE/TIME \(America/Los_Angeles\):[^\n]+")
_FROZEN_TIME  = "CURRENT DATE/TIME (America/Los_Angeles): <FROZEN>"


def _frozen_hash(prompt: str) -> tuple[int, str]:
    """Mask the dynamic timestamp line, then return (length, sha256)."""
    normalized = _TIMESTAMP_RE.sub(_FROZEN_TIME, prompt)
    return len(normalized), hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── Minimal fixtures — only fields build_system_prompt touches ─────────────


def _order_store(industry: str) -> dict:
    """Stable minimal order-vertical store dict. Mutating this fixture
    invalidates the SHA256 anchors below."""
    return {
        "id":               f"test-{industry}",
        "name":             f"Test {industry.title()} Store",
        "industry":         industry,
        "business_type":    industry,
        "vertical_kind":    "order",
        "system_prompt":    f"You are Persona, the AI voice assistant for Test {industry.title()} Store.",
        "business_hours":   "Daily 9am-9pm",
        "menu_cache":       "Sample Item — $10.00",
        "custom_knowledge": "",
        "temporary_prompt": "",
    }


def _beauty_store() -> dict:
    return {
        "id":               "test-beauty",
        "name":             "Test Beauty Salon",
        "industry":         "beauty",
        "business_type":    "beauty",
        "vertical_kind":    "service",
        "system_prompt":    "You are Luna, the elegant AI voice assistant for Test Beauty Salon.",
        "business_hours":   "Tuesday-Saturday 10am-7pm",
        "menu_cache":       "Women's Haircut — $65.00 (60 min)",
        "custom_knowledge": "",
        "temporary_prompt": "",
    }


# ── Contract 1: ORDER identity — byte-for-byte invariant ────────────────────


# Captured pre-fix from `build_system_prompt(_order_store(v))` for the
# minimal fixture above. Touching the order code path (or this fixture
# without updating the hashes) trips this test.
_ORDER_BASELINE_SHA256 = {
    "cafe":    "c3632dfd2d31f6a69add3a4d34643e5b3fa0eddd75f17ddbefcb19bca20dfdcd",
    "pizza":   "44b4267e6e823ec9c1383bedceb06325aa26409357192b54a03433c1336bdba0",
    "mexican": "2f71152438ffa94f5218edd2f9bd578a0f31eb7a01cb7f798035a9614d31391f",
    "kbbq":    "47a8499a30023f8fb48dbaff48de484e22fc5437b1411fb614ccc9ecbd94a739",
}

_ORDER_BASELINE_LEN = {
    "cafe":    27415,
    "pizza":   27416,
    "mexican": 27418,
    "kbbq":    27415,
}


@pytest.mark.parametrize("industry", ["cafe", "pizza", "mexican", "kbbq"])
def test_order_vertical_prompt_byte_identical(industry):
    """Order-vertical prompt MUST match the pre-C1 baseline exactly
    (timestamp line masked). A single byte of drift here means we
    accidentally changed behavior for a live food vertical.
    (음식점 4개 vertical은 fix 전후 한 바이트도 다르지 않아야 함 — 시각 라인 마스킹)"""
    prompt = build_system_prompt(_order_store(industry))
    actual_len, actual_sha = _frozen_hash(prompt)

    assert actual_len == _ORDER_BASELINE_LEN[industry], (
        f"{industry} order prompt length drifted "
        f"{_ORDER_BASELINE_LEN[industry]} → {actual_len}"
    )
    assert actual_sha == _ORDER_BASELINE_SHA256[industry], (
        f"{industry} order prompt CHANGED — sha256\n"
        f"  expected: {_ORDER_BASELINE_SHA256[industry]}\n"
        f"  actual:   {actual_sha}"
    )


# ── Contract 2: SERVICE hygiene — no order-vertical tokens ──────────────────


_ORDER_FORBIDDEN_TOKENS = [
    "reservation",       # restaurant table reservation
    "make_reservation",  # order-vertical tool
    "cancel_reservation",
    "modify_reservation",
    "create_order",      # order-vertical tool
    "modify_order",
    "cancel_order",
    "recent_orders",     # caused Call 5 hallucination
    "recall_order",
    "party of",          # restaurant party-size recital
    "party_size",
]


@pytest.mark.parametrize("token", _ORDER_FORBIDDEN_TOKENS)
def test_beauty_prompt_omits_order_vertical_token(token):
    """Beauty (service-kind) prompt must NOT contain restaurant vocabulary.
    Each forbidden token has a documented live-call regression:
    'reservation' / 'party of one' → Call CAdb94554b turn 6 mis-recital,
    'recent_orders' → Call CA218629c6 cancel flow blocked.
    (Beauty prompt에 식당 용어 누출 금지 — 라이브 회귀 가드)"""
    prompt = build_system_prompt(_beauty_store())
    count = prompt.lower().count(token.lower())
    assert count == 0, (
        f"Beauty prompt contains forbidden token {token!r} "
        f"({count} occurrences) — order vertical vocabulary is leaking"
    )


_SERVICE_REQUIRED_TOKENS = [
    "book_appointment",
    "service_lookup",
    "appointment",
    "stylist",
    "Luna",          # persona from system_prompt
]


@pytest.mark.parametrize("token", _SERVICE_REQUIRED_TOKENS)
def test_beauty_prompt_includes_required_service_token(token):
    """Beauty prompt must teach the model the appointment surface."""
    prompt = build_system_prompt(_beauty_store())
    assert token in prompt, (
        f"Beauty prompt missing required service token {token!r}"
    )


# ── Length cap — keep service prompt below the lost-in-the-middle wall ──────


def test_beauty_prompt_length_under_cap():
    """Per feedback_prompt_length_rule — service prompts should stay well
    under the order prompt size (~30K) to avoid the lost-in-the-middle
    failure mode. 15K bytes is a healthy upper bound.
    (압축형 — 30K → 15K 이하 목표)"""
    prompt = build_system_prompt(_beauty_store())
    assert len(prompt) < 15_000, (
        f"Beauty prompt length {len(prompt)}B exceeds 15K cap — compress further"
    )
    assert len(prompt) > 1_500, (
        f"Beauty prompt length {len(prompt)}B suspiciously short — likely under-built"
    )


# ── INTAKE FLOW block still injected (Phase 1.6 reuse) ─────────────────────


def test_beauty_prompt_still_has_intake_flow_block():
    """Phase 1.6 INTAKE FLOW yaml block must survive the C1 fix —
    SERVICE_SELECT / STYLIST / TIME_SLOT / CONFIRM phases from
    templates/beauty/intake_flow.yaml.
    (Phase 1.6 block 재사용 — service vertical phase 4건 필수)"""
    prompt = build_system_prompt(_beauty_store())
    assert "=== INTAKE FLOW (" in prompt
    for phase_id in ("SERVICE_SELECT", "STYLIST", "TIME_SLOT", "CONFIRM"):
        assert phase_id in prompt, f"phase {phase_id} missing from Beauty prompt"


# ── Multilingual policy injected from vertical_kinds.yaml ───────────────────


def test_beauty_prompt_advertises_supported_languages():
    """vertical_kinds.yaml lists beauty multilingual as [en, es, ko, ja, zh].
    The service prompt must declare those supported languages so the model
    mirrors the caller's language consistently (live regression Call 4 —
    Korean caller, EN greeting, mixed-language reply).
    (다국어 정책 yaml 기반 inject — 라이브 회귀 가드)"""
    prompt = build_system_prompt(_beauty_store())
    # Must mention the policy somewhere — accept any common phrasing.
    has_lang_block = (
        ("Supported language" in prompt) or
        ("Supported langs" in prompt)   or
        ("LANGUAGES" in prompt)
    )
    assert has_lang_block, "Beauty prompt missing supported-languages block"
    # Each lang code surfaces explicitly.
    for code in ("en", "es", "ko", "ja", "zh"):
        assert code in prompt.lower(), f"language code {code!r} not in prompt"


# ── Emergency rules keyword auto-trigger (C6 piggyback) ────────────────────


# ── Returning-customer CRM block — CustomerContext dataclass shape ────────


def test_beauty_prompt_accepts_returning_customer_context_without_crash():
    """CustomerContext is a frozen dataclass (services/crm/customer_lookup.py).
    The service prompt builder must access fields via attributes — `.get()`
    raises AttributeError mid-call and silently kills the WebSocket session.
    Live trigger: JM Beauty Salon calls CAf59994ec / CAddcea88c on
    2026-05-18, both dropped after 2-3s because the same caller-ID was a
    returning customer and the dict-style access blew up before
    session.update could send.
    (CustomerContext dataclass — dot 접근 필수, .get() 호출 시 통화 끊김)"""
    from app.services.crm import CustomerContext
    ctx = CustomerContext(
        visit_count=    5,
        recent=         [{"created_at": "2026-05-15T12:00:00+00:00",
                          "items_json": [], "total_cents": 6500}],
        usual_eligible= False,
        name=           "Michael",
        email=          "michael@example.com",
    )
    # Must NOT raise (the regression we are guarding against).
    prompt = build_system_prompt(_beauty_store(), customer_context=ctx)
    assert "CUSTOMER CONTEXT" in prompt
    assert "Michael" in prompt
    assert "Prior visits: 5" in prompt


def test_beauty_prompt_skips_crm_block_for_anonymous_caller():
    """visit_count==0 / ctx is None must NOT inject the CRM block —
    matches the order-path semantics so empty blocks don't pollute the
    prompt with stray '=== CUSTOMER CONTEXT ===' headers.
    (visit_count=0 또는 None → CRM 블록 skip)"""
    from app.services.crm import CustomerContext
    anon = CustomerContext(
        visit_count=0, recent=[], usual_eligible=False, name=None, email=None,
    )
    p_none = build_system_prompt(_beauty_store(), customer_context=None)
    p_anon = build_system_prompt(_beauty_store(), customer_context=anon)
    for p in (p_none, p_anon):
        assert "CUSTOMER CONTEXT" not in p


def test_beauty_prompt_injects_emergency_transfer_keywords():
    """Emergency keywords from templates/beauty/emergency_rules.yaml must
    surface in the prompt as auto-fire instructions for transfer_to_manager.
    Otherwise the LLM only escalates when the caller asks for the manager
    explicitly (live regression Call 6 — severe scalp burn answered with
    a polite medical deferral, no auto-transfer).
    (emergency 키워드 → 자동 transfer trigger inject)"""
    prompt = build_system_prompt(_beauty_store())
    # Must mention transfer_to_manager as auto-fire (not just listed as a tool).
    assert "transfer_to_manager" in prompt
    # At least one of the high-severity English keywords must surface so the
    # model knows what to look for. Don't enforce all of them — the yaml is
    # the source of truth and may evolve.
    severity_keywords = ["anaphylaxis", "chemical burn", "severe reaction", "scalp burn"]
    surfaced = [k for k in severity_keywords if k.lower() in prompt.lower()]
    assert surfaced, (
        "No severity keywords from emergency_rules.yaml surfaced in prompt — "
        "transfer_to_manager will not auto-fire on the next severe-reaction call"
    )
