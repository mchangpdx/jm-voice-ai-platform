# CRM Wave 1 — customer_context prompt block unit tests (Tier 2, P1–P5)
# (CRM Wave 1 — system prompt customer_context 블록 단위 테스트)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.voice_websocket import (
    _format_last_visit,
    _render_customer_context_block,
    _summarize_recent_items,
    build_system_prompt,
)
from app.services.crm import CustomerContext


# ── Test fixtures ─────────────────────────────────────────────────────────────

STORE = {
    "id":              "PDX-cafe-01",
    "system_prompt":   "You are the host at JM Cafe.",
    "menu_cache":      "Latte $5.00\nDrip $3.50",
    "modifier_section": "",
    "business_hours":  "8am-6pm",
}


def _ctx(visit_count: int = 1, *, recent=None,
         usual_eligible: bool = False,
         name: str | None = "Jamie",
         email: str | None = "jamie@x.com") -> CustomerContext:
    return CustomerContext(
        visit_count    = visit_count,
        recent         = recent or [],
        usual_eligible = usual_eligible,
        name           = name,
        email          = email,
    )


def _yesterday_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


# ── P1: customer_context=None → byte-identical to pre-CRM build ───────────────

def test_p1_none_context_is_byte_identical_to_default():
    a = build_system_prompt(STORE)
    b = build_system_prompt(STORE, customer_context=None)
    assert a == b
    assert "CUSTOMER CONTEXT" not in b
    assert "CRM RULES" not in b


# ── P2: visit_count=0 → no block injected ─────────────────────────────────────

def test_p2_visit_count_zero_skips_block():
    ctx = _ctx(visit_count=0, recent=[], name=None, email=None)
    a = build_system_prompt(STORE)
    b = build_system_prompt(STORE, customer_context=ctx)
    assert a == b
    assert "CUSTOMER CONTEXT" not in b


# ── P3: visit_count=1, no usual ───────────────────────────────────────────────

def test_p3_one_visit_renders_welcome_back_no_usual():
    ctx = _ctx(
        visit_count=1,
        recent=[{
            "created_at": _yesterday_iso(),
            "items_json": [{"name": "iced oat latte", "quantity": 1,
                            "modifier_lines": [{"label": "Iced"}, {"label": "Oat"}]}],
            "total_cents": 650,
        }],
        usual_eligible=False,
    )
    p = build_system_prompt(STORE, customer_context=ctx)
    assert "=== CUSTOMER CONTEXT" in p
    assert "Name: Jamie" in p
    assert "Welcome back" in p
    assert "Visits: 1" in p
    assert "yesterday" in p
    assert "Email on file: jamie@x.com" in p
    assert "Usual eligible: NO" in p
    assert "Would you like the usual" not in p
    # INVARIANTS still present and AFTER the customer block
    assert "=== CORE TRUTHFULNESS INVARIANTS" in p
    assert p.find("=== CUSTOMER CONTEXT") < p.find("=== CORE TRUTHFULNESS INVARIANTS")


# ── P4: visit_count=2, usual_eligible=True → usual offer line present ─────────

def test_p4_usual_eligible_renders_usual_offer():
    same_items = [{"name": "iced oat latte", "quantity": 1,
                   "modifier_lines": [{"label": "Iced"}, {"label": "Oat"}]}]
    ctx = _ctx(
        visit_count=2,
        recent=[
            {"created_at": _yesterday_iso(),
             "items_json": same_items, "total_cents": 650},
            {"created_at": "2026-05-02",
             "items_json": same_items, "total_cents": 650},
        ],
        usual_eligible=True,
    )
    p = build_system_prompt(STORE, customer_context=ctx)
    assert "Usual eligible: YES" in p
    assert "Would you like the usual" in p
    assert "iced oat latte" in p
    # The usual offer should reference the rendered items, not be malformed
    assert "Would you like the usual, " in p  # comma-separated


# ── P5: visit_count=2, items differ → usual_eligible=False, no usual ──────────

def test_p5_two_visits_different_items_no_usual():
    ctx = _ctx(
        visit_count=2,
        recent=[
            {"created_at": _yesterday_iso(),
             "items_json": [{"name": "latte", "quantity": 1}],
             "total_cents": 500},
            {"created_at": "2026-05-02",
             "items_json": [{"name": "drip", "quantity": 1}],
             "total_cents": 350},
        ],
        usual_eligible=False,
    )
    p = build_system_prompt(STORE, customer_context=ctx)
    assert "Usual eligible: NO" in p
    assert "Would you like the usual" not in p


# ── Helper unit tests (pure functions) ────────────────────────────────────────

class TestSummarizeItems:
    def test_empty(self):
        assert _summarize_recent_items(None) == "(no items)"
        assert _summarize_recent_items([]) == "(no items)"

    def test_single_item_no_modifiers(self):
        out = _summarize_recent_items([{"name": "latte", "quantity": 1}])
        assert out == "latte"

    def test_quantity_prefix_when_gt_one(self):
        out = _summarize_recent_items([{"name": "muffin", "quantity": 3}])
        assert out == "3x muffin"

    def test_modifier_labels_appended(self):
        out = _summarize_recent_items([{
            "name": "latte", "quantity": 1,
            "modifier_lines": [{"label": "Iced"}, {"label": "Oat"}],
        }])
        assert out == "latte (Iced, Oat)"

    def test_invalid_dict_filtered(self):
        out = _summarize_recent_items([
            "garbage",
            {"name": "latte", "quantity": 1},
        ])
        assert out == "latte"


class TestFormatLastVisit:
    def test_today(self):
        now = datetime.now(timezone.utc).isoformat()
        assert _format_last_visit(now) == "today"

    def test_yesterday(self):
        y = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert _format_last_visit(y) == "yesterday"

    def test_n_days_ago(self):
        n = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        assert _format_last_visit(n) == "7 days ago"

    def test_z_suffix_iso(self):
        # Some serializers use 'Z' instead of '+00:00'
        ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
        assert _format_last_visit(ts) == "2 days ago"

    def test_garbage_returns_empty_string(self):
        assert _format_last_visit(None) == ""
        assert _format_last_visit("") == ""
        assert _format_last_visit("not a date") == ""
        assert _format_last_visit(12345) == ""  # type: ignore[arg-type]

    def test_clock_skew_future_returns_today(self):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        assert _format_last_visit(future) == "today"


# ── Render block direct unit tests (extra coverage) ───────────────────────────

class TestRenderBlock:
    def test_none_returns_empty_string(self):
        assert _render_customer_context_block(None) == ""

    def test_visit_count_zero_returns_empty_string(self):
        ctx = CustomerContext(visit_count=0, recent=[], usual_eligible=False,
                              name=None, email=None)
        assert _render_customer_context_block(ctx) == ""

    def test_no_email_omits_email_line(self):
        ctx = _ctx(visit_count=1, email=None,
                   recent=[{"created_at": _yesterday_iso(),
                            "items_json": [{"name": "x", "quantity": 1}],
                            "total_cents": 100}])
        out = _render_customer_context_block(ctx)
        assert "Email on file" not in out
        # Bug #2 fix: no email → no plain-text email confirmation rule either
        assert "BEFORE create_order" not in out

    def test_email_on_file_renders_plain_text_confirmation_rule(self):
        # Bug #2 fix (2026-05-08): when email is on file, the prompt MUST
        # instruct the agent to read the address aloud before create_order.
        # Without this, agents skip NATO recital AND never speak the address,
        # so customers can't catch a stale CRM cache email.
        ctx = _ctx(visit_count=2, email="cymeet@gmail.com",
                   recent=[{"created_at": _yesterday_iso(),
                            "items_json": [{"name": "latte", "quantity": 1}],
                            "total_cents": 500}])
        out = _render_customer_context_block(ctx)
        assert "BEFORE create_order" in out
        assert "cymeet@gmail.com" in out
        assert "should I send the receipt there" in out
        assert "fall back to NATO recital" in out

    def test_no_name_omits_name_line(self):
        ctx = _ctx(visit_count=1, name=None,
                   recent=[{"created_at": _yesterday_iso(),
                            "items_json": [{"name": "x", "quantity": 1}],
                            "total_cents": 100}])
        out = _render_customer_context_block(ctx)
        assert "Name:" not in out

    def test_recent_block_numbers_orders(self):
        ctx = _ctx(visit_count=3, recent=[
            {"created_at": "2026-05-05", "items_json": [{"name": "a"}], "total_cents": 100},
            {"created_at": "2026-05-04", "items_json": [{"name": "b"}], "total_cents": 200},
            {"created_at": "2026-05-03", "items_json": [{"name": "c"}], "total_cents": 300},
        ])
        out = _render_customer_context_block(ctx)
        assert "1. 2026-05-05" in out
        assert "2. 2026-05-04" in out
        assert "3. 2026-05-03" in out
        assert "$1.00" in out and "$2.00" in out and "$3.00" in out


# FIX-B (2026-05-09) — decomposition rule injection in build_system_prompt.
# Live regression: caller asked for "iced oat latte" → agent rejected as
# "combined drink not on menu" even though Café Latte + iced + oat exist
# as base + modifiers. Rule must inject when modifier_section is present
# and stay omitted when there are no modifiers (would be misleading guidance).
# (FIX-B — modifier_section 있을 때만 분해 룰 inject)

class TestDecompositionRule:
    def _store_with_modifiers(self, mod_section: str = "(modifier list...)") -> dict:
        return {
            "id":               "PDX-cafe-01",
            "system_prompt":    "You are the host at JM Cafe.",
            "menu_cache":       "Café Latte $5.00\nDrip $3.50",
            "modifier_section": mod_section,
            "business_hours":   "8am-6pm",
        }

    def test_modifier_section_present_injects_decomposition_rule(self):
        out = build_system_prompt(self._store_with_modifiers())
        assert "DECOMPOSITION RULE" in out
        assert "iced oat latte" in out
        assert "Café Latte (iced + oat milk)" in out
        # Rule must come AFTER the modifier list (references it)
        assert out.find("(modifier list...)") < out.find("DECOMPOSITION RULE")

    def test_no_modifier_section_omits_decomposition_rule(self):
        # When the store has no modifiers configured, the rule shouldn't
        # appear — there's nothing to decompose into.
        out = build_system_prompt(self._store_with_modifiers(mod_section=""))
        assert "DECOMPOSITION RULE" not in out

    def test_decomposition_rule_covers_5_languages(self):
        out = build_system_prompt(self._store_with_modifiers())
        # English, Korean, Japanese, Chinese, Spanish — all 5 cafe-policy
        # supported languages must have at least one example.
        assert "iced oat latte" in out                  # English
        assert "큰 사이즈 아이스 오트 라떼" in out          # Korean
        assert "アイスのオーツラテ" in out                  # Japanese
        assert "热的燕麦拿铁" in out                       # Chinese
        assert "café con leche de avena grande" in out  # Spanish


# ── 2026-05-17 greeting fix — store_name in CRM block ────────────────────────
# Live trigger: CAe2c214… / CAe516… — returning callers heard "Welcome
# back, Michael!" with no store identity. CRM block's greeting rule now
# requires the store_name in the FIRST sentence; both the response.create
# greeting AND the LLM's prompt-driven recovery line must surface it.

class TestStoreNameInGreetingRule:
    def test_returning_caller_block_embeds_store_name_in_greeting(self):
        store = {"name": "JM Taco",
                 "system_prompt": "You are Sofia, the AI voice assistant for JM Taco.",
                 "menu_cache": "", "modifier_section": "", "business_hours": ""}
        ctx = _ctx(visit_count=3, name="Michael Chang")
        out = build_system_prompt(store, customer_context=ctx)
        assert "Welcome back to JM Taco" in out
        # Verbatim-MUST clause keeps the LLM from dropping the store name
        # when paraphrasing the greeting.
        assert '"JM Taco" MUST appear verbatim' in out

    def test_returning_caller_block_falls_back_when_store_name_missing(self):
        # Anonymous store row (e.g. dev fixture w/o name) — still produce
        # a valid greeting line rather than crashing on an f-string with
        # an empty store name.
        store = {"name": "",
                 "system_prompt": "You are the host.",
                 "menu_cache": "", "modifier_section": "", "business_hours": ""}
        ctx = _ctx(visit_count=2, name="Pat")
        out = build_system_prompt(store, customer_context=ctx)
        assert 'Welcome back, {name}!' in out
        assert "MUST appear verbatim" not in out  # only fires when store_name set

    def test_new_caller_unaffected_by_store_name_fix(self):
        # No customer_context → no CRM block — store_name fix MUST NOT
        # accidentally leak the greeting rule into first-time-call prompts.
        store = {"name": "JM Taco",
                 "system_prompt": "You are Sofia for JM Taco.",
                 "menu_cache": "", "modifier_section": "", "business_hours": ""}
        out = build_system_prompt(store, customer_context=None)
        assert "CUSTOMER CONTEXT" not in out
        assert "Welcome back" not in out


class TestPersonaNameExtraction:
    """The greeting_instruction's "You are <Persona>" header is derived
    from store.system_prompt; the helper must handle the 3 shapes that
    show up in the wild (vertical default, operator override, blank)."""

    def test_extracts_first_name_from_vertical_default_prompt(self):
        from app.api.realtime_voice import _extract_persona_name
        prompt = "You are Sofia, the AI voice assistant for JM Taco. Speak naturally."
        assert _extract_persona_name(prompt) == "Sofia"

    def test_returns_empty_when_pattern_does_not_match(self):
        from app.api.realtime_voice import _extract_persona_name
        assert _extract_persona_name("Random operator prompt.") == ""

    def test_handles_none_and_empty(self):
        from app.api.realtime_voice import _extract_persona_name
        assert _extract_persona_name(None) == ""
        assert _extract_persona_name("") == ""
