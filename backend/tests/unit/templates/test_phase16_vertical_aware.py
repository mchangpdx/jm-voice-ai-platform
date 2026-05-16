"""Phase 1.6 — build_system_prompt vertical-aware ADDITIVE wiring.
(Phase 1.6 — order-kind는 행동 변경 zero, service-kind는 intake_flow.yaml 주입)

The contract: for live order-kind verticals (cafe / pizza / mexican / kbbq)
the prompt MUST be unchanged. For service-kind verticals whose
intake_flow.yaml has phases, the prompt receives an additional INTAKE
FLOW block at the very end.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.api.voice_websocket import build_system_prompt
from app.templates._base import validator as v


# ── Order-kind verticals: no change ─────────────────────────────────────────


def _basic_store(industry: str, name: str = "Test Store") -> dict:
    return {
        "id":             f"test-{industry}",
        "name":           name,
        "industry":       industry,
        "business_type":  industry,
        "system_prompt":  "You are Persona, the AI assistant.",
        "business_hours": "Daily 9am-9pm",
    }


@pytest.mark.parametrize("industry", ["cafe", "pizza", "mexican", "kbbq"])
def test_order_kind_verticals_get_no_phase16_block(industry):
    """No INTAKE FLOW additive block for live food verticals.
    (라이브 음식점 vertical은 Phase 1.6 block 주입 안 됨)
    """
    store = _basic_store(industry)
    prompt = build_system_prompt(store)
    assert "=== INTAKE FLOW (" not in prompt, (
        f"{industry} (order kind) must not receive Phase 1.6 INTAKE FLOW block"
    )


def test_unknown_vertical_does_not_crash():
    """Unknown industry → no Phase 1.6 block, no exception."""
    store = _basic_store("no_such_vertical")
    prompt = build_system_prompt(store)
    assert "=== INTAKE FLOW (" not in prompt
    assert isinstance(prompt, str)


def test_empty_industry_does_not_crash():
    """Empty / missing industry → no crash."""
    store = {"id": "x", "name": "X", "system_prompt": "Y"}
    prompt = build_system_prompt(store)
    assert isinstance(prompt, str)


# ── Service-kind: block injected only when intake_flow has phases ───────────


def test_beauty_today_no_block_until_phase4_writes_yaml():
    """Beauty resolves to service kind but intake_flow.yaml is empty
    until Phase 4 writes it. Until then the additive block stays dormant.
    (Phase 4 전까지 Beauty는 intake_flow.yaml 미존재 → block dormant)
    """
    store = _basic_store("beauty")
    prompt = build_system_prompt(store)
    assert "=== INTAKE FLOW (" not in prompt


@pytest.fixture
def fake_service_template(tmp_path: Path, monkeypatch):
    """Stand up a synthetic 'demo_salon' service vertical with phases.
    (가상 service-kind vertical을 tmp_path에 만들고 validator 경로 redirect)
    """
    tdir = tmp_path / "templates"
    base = tdir / "_base"
    base.mkdir(parents=True)
    (base / "vertical_kinds.yaml").write_text(yaml.safe_dump({
        "kinds": {"service": {"description": "salon"}},
        "verticals": {
            "demo_salon": {
                "kind": "service",
                "persona_name": "Demo",
                "multilingual": ["en"],
            },
        },
    }))
    (tdir / "demo_salon").mkdir()
    (tdir / "demo_salon" / "intake_flow.yaml").write_text(yaml.safe_dump({
        "phases": [
            {"id": "INTAKE",       "label": "Intake",       "description": "Greet & learn."},
            {"id": "SERVICE",      "label": "Service Pick", "description": "Choose service."},
            {"id": "STYLIST",      "label": "Stylist",      "description": "Optional pick."},
            {"id": "TIME_SLOT",    "label": "Time Slot",    "description": "Pick a time."},
            {"id": "CONFIRM",      "label": "Confirm",      "description": "Recite & book."},
        ],
    }))
    monkeypatch.setattr(v, "_TEMPLATES_DIR", tdir)
    monkeypatch.setattr(v, "_BASE_DIR", base)
    v._load_vertical_kinds.cache_clear()
    yield tdir
    v._load_vertical_kinds.cache_clear()


def test_service_kind_with_intake_flow_yaml_injects_block(fake_service_template):
    """When a service-kind vertical has intake_flow.yaml with phases,
    the additive block appears at the end of the prompt.
    (service-kind + intake_flow.yaml 있으면 prompt 끝에 block 주입)
    """
    store = _basic_store("demo_salon", name="Demo Salon")
    prompt = build_system_prompt(store)
    assert "=== INTAKE FLOW (service vertical) ===" in prompt
    # All 5 phase ids appear
    for pid in ["INTAKE", "SERVICE", "STYLIST", "TIME_SLOT", "CONFIRM"]:
        assert f"PHASE {pid}" in prompt, f"phase {pid} missing from injected block"
    # Block sits at the very end (after the I1-I5 invariants).
    block_pos = prompt.find("=== INTAKE FLOW (")
    invariant_pos = prompt.find("Violations of I1/I2/I3/I4/I5")
    assert block_pos > invariant_pos, "Phase 1.6 block must come AFTER the invariants"


def test_service_kind_without_intake_flow_yaml_no_block(tmp_path, monkeypatch):
    """service-kind vertical with NO intake_flow.yaml → block stays dormant."""
    tdir = tmp_path / "templates"
    base = tdir / "_base"
    base.mkdir(parents=True)
    (base / "vertical_kinds.yaml").write_text(yaml.safe_dump({
        "kinds": {"service": {}},
        "verticals": {"empty_salon": {"kind": "service", "persona_name": "X", "multilingual": ["en"]}},
    }))
    (tdir / "empty_salon").mkdir()   # no intake_flow.yaml inside
    monkeypatch.setattr(v, "_TEMPLATES_DIR", tdir)
    monkeypatch.setattr(v, "_BASE_DIR", base)
    v._load_vertical_kinds.cache_clear()
    try:
        store = _basic_store("empty_salon")
        prompt = build_system_prompt(store)
        assert "=== INTAKE FLOW (" not in prompt
    finally:
        v._load_vertical_kinds.cache_clear()


def test_build_system_prompt_is_idempotent():
    """Two calls with the same store dict produce identical prompts.
    Guards against accidental in-place mutation of `store`.
    (같은 store dict 두 번 호출 → identical prompt — mutation 방지)
    """
    store = _basic_store("cafe")
    p1 = build_system_prompt(store)
    p2 = build_system_prompt(store)
    assert p1 == p2
