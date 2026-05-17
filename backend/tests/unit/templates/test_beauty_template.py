"""Phase 4.3 + 4.4 — Beauty vertical template integration tests.
(Phase 4.3 + 4.4 — Beauty 템플릿 통합 테스트)

Loads the real `backend/app/templates/beauty/` directory through the
9-layer validator and exercises end-to-end behavior:

  - load_template returns a populated VerticalTemplate (no errors)
  - vertical_kinds registers beauty as kind=service with Luna persona
  - All 9 layers parse and carry the expected top-level shape
  - scheduler.resources has ≥1 stylist with specialties
  - menu.items every row has service_kind + duration_min set
  - list_stylists returns the actual roster (no mock — real yaml load)
  - format_resources filters by real specialty ids

These assertions catch yaml typos, missing required keys, and schema
drift between the template and the consuming skill code.
"""
from __future__ import annotations

import pytest

from app.skills.appointment.list_stylists import list_stylists
from app.templates._base.validator import (
    has_errors,
    load_template,
    validate_layer,
)


# ── load_template happy path ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def beauty():
    """Real on-disk template load — shared across all assertions."""
    return load_template("beauty")


def test_beauty_template_has_no_errors(beauty):
    """Validator must surface zero hard errors (warns are acceptable).
    (validator error 0건 — beauty MVP 활성화 전제)"""
    errors = [i for i in beauty.get("issues", []) if i.severity == "error"]
    assert errors == [], f"unexpected validator errors: {errors}"
    assert has_errors(beauty) is False


def test_beauty_vertical_kind_metadata(beauty):
    assert beauty["vertical"] == "beauty"
    assert beauty["kind"] == "service"
    assert beauty["persona_name"] == "Luna"
    assert beauty["multilingual"] == ["en", "es", "ko", "ja", "zh"]


# ── All 9 layers present ────────────────────────────────────────────────────


@pytest.mark.parametrize("layer", [
    "safety_rules", "catalog", "option_groups", "persona_prompt",
    "intake_flow", "scheduler", "emergency_rules", "crm_followup",
    "pricing_policy",
])
def test_every_layer_loaded(beauty, layer):
    """Each of the 9 layers must yield non-None content. Lenient loading
    would have silently returned None for missing files — this catches
    typos in filenames before they cascade into runtime bugs.
    (9 layer 전부 non-None 보장)"""
    val = beauty.get(layer)
    assert val is not None, f"layer {layer} returned None — missing file?"


def test_persona_prompt_mentions_luna(beauty):
    prompt = beauty["persona_prompt"]
    assert "Luna" in prompt
    assert "{store_name}" in prompt, "persona must keep the store_name placeholder"


# ── scheduler.yaml — stylist resources ──────────────────────────────────────


def test_scheduler_slot_kind_is_stylist(beauty):
    assert beauty["scheduler"]["slot_kind"] == "stylist"


def test_scheduler_has_at_least_one_stylist(beauty):
    resources = beauty["scheduler"].get("resources") or []
    assert len(resources) >= 1
    for r in resources:
        assert r.get("id"), "stylist must have an id"
        assert r.get("en"), "stylist must have an English display name"
        specs = r.get("specialties") or []
        assert isinstance(specs, list) and len(specs) >= 1, (
            f"stylist {r.get('id')} needs at least one specialty for list_stylists filter"
        )


# ── menu.yaml — service catalog ─────────────────────────────────────────────


def test_menu_items_every_row_has_service_kind_and_duration(beauty):
    """Service-kind verticals must specify both service_kind AND duration_min
    on every menu row — service_lookup + book_appointment depend on these.
    (모든 service row에 service_kind + duration_min 보장)"""
    items = beauty["catalog"].get("items") or []
    assert len(items) >= 1
    for item in items:
        assert item.get("service_kind"), f"item {item.get('id')} missing service_kind"
        assert item.get("duration_min"), f"item {item.get('id')} missing duration_min"
        assert item.get("base_price") is not None, f"item {item.get('id')} missing base_price"


def test_menu_categories_cover_core_services(beauty):
    cat_ids = {c.get("id") for c in (beauty["catalog"].get("categories") or [])}
    # Core surface MVP needs: haircut + color + nails are the wedge.
    assert {"haircut", "color", "nails"}.issubset(cat_ids)


# ── intake_flow — service kind ──────────────────────────────────────────────


def test_intake_flow_uses_service_phase_set(beauty):
    """Service vertical intake must use SERVICE_SELECT / STYLIST / TIME_SLOT
    / CONFIRM rather than the order CART/TOTAL/RECITAL set.
    (service vertical phase set 강제)"""
    phase_ids = [p.get("id") for p in (beauty["intake_flow"].get("phases") or [])]
    assert "SERVICE_SELECT" in phase_ids
    assert "STYLIST" in phase_ids
    assert "TIME_SLOT" in phase_ids
    assert "CONFIRM" in phase_ids


def test_intake_flow_has_no_layer_errors(beauty):
    issues = validate_layer(beauty, "intake_flow")
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []


# ── pricing_policy — 24h late-cancel matches cancel_appointment ─────────────


def test_late_cancel_window_matches_skill_default(beauty):
    """pricing_policy.late_cancel_fee.free_window_hours must agree with
    skills.appointment.cancel._LATE_CANCEL_WINDOW_HOURS so the recital
    surfaced to the client matches the hint the dispatcher emits.
    (정책 yaml과 skill code 정합성 — 24h 일치)"""
    from app.skills.appointment.cancel import _LATE_CANCEL_WINDOW_HOURS
    policy = beauty["pricing_policy"].get("late_cancel_fee") or {}
    assert policy.get("free_window_hours") == _LATE_CANCEL_WINDOW_HOURS


def test_late_cancel_fee_is_enabled_with_a_pct(beauty):
    policy = beauty["pricing_policy"]["late_cancel_fee"]
    assert policy.get("enabled") is True
    assert 0 < policy.get("pct_of_service") <= 1.0


# ── list_stylists end-to-end against the real template ─────────────────────


@pytest.mark.asyncio
async def test_list_stylists_returns_real_roster():
    """No mocks — real load_template("beauty") feeds list_stylists.
    Validates the wiring from yaml → format_resources → response.
    (mock 없는 end-to-end — yaml → list_stylists 응답까지)"""
    out = await list_stylists(vertical="beauty")
    assert out["success"] is True
    assert out["ai_script_hint"] == "stylists_listed"
    assert out["slot_kind"] == "stylist"
    assert len(out["stylists"]) >= 1
    names = {s["name"] for s in out["stylists"]}
    # The scheduler.yaml seed ships Maria + Yuna + Sophia + Aria.
    assert {"Maria", "Yuna", "Sophia", "Aria"}.issubset(names)


@pytest.mark.asyncio
async def test_list_stylists_specialty_filter_matches_real_menu_id():
    """Filter by a real menu item id (balayage) — Maria's specialties
    list it. This cross-checks scheduler.resources.specialties against
    menu.items.id so a renamed service doesn't silently break list_stylists.
    (scheduler specialty id ↔ menu item id 교차 검증)"""
    out = await list_stylists(vertical="beauty", specialty_filter="balayage")
    assert out["ai_script_hint"] == "stylists_listed"
    names = {s["name"] for s in out["stylists"]}
    assert "Maria" in names


@pytest.mark.asyncio
async def test_list_stylists_missing_specialty_filter_returns_no_match():
    """A filter that no roster member lists must return the dedicated
    no_match hint (not the configured-but-empty hint).
    (filter miss → no_match, roster 있지만 매치 없음)"""
    out = await list_stylists(vertical="beauty", specialty_filter="welding")
    assert out["ai_script_hint"] == "no_stylists_match_filter"
    assert out["stylists"] == []
