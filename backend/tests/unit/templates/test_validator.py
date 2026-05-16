"""Unit tests for the 9-layer Vertical Template Framework validator.
(9-layer 프레임워크 validator — Phase 1.3 단위 테스트)

Tests run against the real cafe/pizza/mexican/kbbq templates so a regression
in any of those folders surfaces here. Synthetic tmp_path templates cover
the lenient/missing/parse-error branches.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.templates._base import validator as v


# ── Real templates ──────────────────────────────────────────────────────────


def test_load_template_cafe_has_all_nine_layers():
    """Cafe ships all 9 layers after Phase 1.4.
    (cafe — Phase 1.4 후 9-layer 모두 채워진 상태 검증)
    """
    t = v.load_template("cafe")
    assert t["vertical"] == "cafe"
    assert t["kind"] == "order"
    assert t["persona_name"] == "Aria"
    assert "en" in t["multilingual"]
    # historical 4 layers
    assert t["safety_rules"] is not None
    assert t["catalog"] is not None
    assert t["option_groups"] is not None
    assert isinstance(t["persona_prompt"], str)
    # new 5 layers — added Phase 1.4
    assert t["intake_flow"]     is not None
    assert t["scheduler"]       is not None
    assert t["emergency_rules"] is not None
    assert t["crm_followup"]    is not None
    assert t["pricing_policy"]  is not None
    # intake_flow content sanity
    assert t["intake_flow"]["kind"] == "order"
    phase_ids = [p["id"] for p in t["intake_flow"]["phases"]]
    assert phase_ids == ["CART", "TOTAL", "NAME", "EMAIL", "RECITAL"]
    # scheduler: cafe is pickup-only
    assert t["scheduler"]["slot_kind"] == "none"
    # pricing model
    assert t["pricing_policy"]["model"] == "per_item"


def test_load_template_unknown_vertical_warns_but_returns_structure():
    """Unknown vertical → warn issue + every layer None, never raises."""
    t = v.load_template("does_not_exist_vertical")
    assert t["kind"] is None
    assert t["persona_name"] is None
    assert t["multilingual"] == []
    assert t["safety_rules"] is None
    issues = [i for i in t["issues"] if i.layer == "_meta"]
    assert len(issues) == 1
    assert "not registered" in issues[0].message
    assert issues[0].severity == "warn"


def test_kind_resolution_for_all_registered_verticals():
    """Every vertical in vertical_kinds.yaml resolves to a known kind.
    (등록된 vertical 전체가 valid kind로 매핑되는지 확인)
    """
    data = v._load_vertical_kinds()
    for name in (data["verticals"] or {}).keys():
        t = v.load_template(name)
        assert t["kind"] in ("order", "service", "service_with_dispatch"), (
            f"{name} resolved to invalid kind {t['kind']}"
        )


def test_beauty_kind_is_service():
    """Beauty MVP target: vertical 'beauty' must resolve to kind 'service'."""
    t = v.load_template("beauty")
    assert t["kind"] == "service"
    assert t["persona_name"] == "Luna"
    assert "ko" in t["multilingual"]


# ── Lenient on tmp_path templates ───────────────────────────────────────────


@pytest.fixture
def synthetic_templates(tmp_path: Path, monkeypatch):
    """Point the validator at a tmp_path templates dir with one vertical.
    (validator의 _TEMPLATES_DIR를 tmp_path로 monkeypatch)
    """
    tdir = tmp_path / "templates"
    base = tdir / "_base"
    base.mkdir(parents=True)
    (base / "vertical_kinds.yaml").write_text(yaml.safe_dump({
        "kinds": {
            "service": {"description": "x"},
        },
        "verticals": {
            "demo": {"kind": "service", "persona_name": "Demo", "multilingual": ["en"]},
        },
    }))
    (tdir / "demo").mkdir()
    monkeypatch.setattr(v, "_TEMPLATES_DIR", tdir)
    monkeypatch.setattr(v, "_BASE_DIR", base)
    v._load_vertical_kinds.cache_clear()
    yield tdir
    v._load_vertical_kinds.cache_clear()


def test_missing_files_do_not_raise(synthetic_templates):
    """Vertical with no yaml files at all — every layer None, no error issues."""
    t = v.load_template("demo")
    assert t["safety_rules"] is None
    assert t["intake_flow"]  is None
    assert not v.has_errors(t)


def test_parse_error_yields_warn_issue(synthetic_templates):
    """Malformed yaml emits a warn issue, not an exception."""
    (synthetic_templates / "demo" / "intake_flow.yaml").write_text("[: this is :: not yaml")
    t = v.load_template("demo")
    warns = [i for i in t["issues"] if i.layer == "intake_flow"]
    assert len(warns) == 1
    assert warns[0].severity == "warn"


def test_catalog_service_kind_warns_when_duration_missing(synthetic_templates):
    """For kind=service items, missing duration_min triggers warn."""
    catalog = {
        "categories": [
            {"id": "hair", "items": [
                {"id": "cut", "en": "Haircut", "price": 45.0},   # no duration_min
            ]}
        ]
    }
    (synthetic_templates / "demo" / "menu.yaml").write_text(yaml.safe_dump(catalog))
    t = v.load_template("demo")
    warns = [i for i in t["issues"] if i.layer == "catalog" and "duration_min" in i.path]
    assert len(warns) == 1


def test_safety_rules_high_confidence_without_reason_warns(synthetic_templates):
    """confidence ≥ 0.90 without 'reason' triggers a warn — spec.md §3."""
    rules = {"patterns": [
        {"keywords": ["foo"], "add_allergens": ["x"], "confidence": 0.97},  # missing reason
        {"keywords": ["bar"], "add_allergens": ["y"], "confidence": 0.50},  # ok — low conf
    ]}
    (synthetic_templates / "demo" / "allergen_rules.yaml").write_text(yaml.safe_dump(rules))
    t = v.load_template("demo")
    warns = [i for i in t["issues"]
             if i.layer == "safety_rules" and "reason" in i.path]
    assert len(warns) == 1
    assert "patterns[0]" in warns[0].path


def test_intake_flow_phases_must_have_id(synthetic_templates):
    """Each phase needs an id."""
    flow = {"phases": [{"label": "Cart phase"}, {"id": "TOTAL"}]}
    (synthetic_templates / "demo" / "intake_flow.yaml").write_text(yaml.safe_dump(flow))
    t = v.load_template("demo")
    warns = [i for i in t["issues"]
             if i.layer == "intake_flow" and "phases[0].id" in i.path]
    assert len(warns) == 1


def test_scheduler_unknown_slot_kind_warns(synthetic_templates):
    """slot_kind outside the allowed enum emits a warn."""
    sched = {"slot_kind": "alien_kind"}
    (synthetic_templates / "demo" / "scheduler.yaml").write_text(yaml.safe_dump(sched))
    t = v.load_template("demo")
    warns = [i for i in t["issues"]
             if i.layer == "scheduler" and "slot_kind" in i.path]
    assert len(warns) == 1


def test_top_level_must_be_mapping(synthetic_templates):
    """A yaml that parses but is a list at root → error issue."""
    (synthetic_templates / "demo" / "scheduler.yaml").write_text("- not\n- a\n- mapping")
    t = v.load_template("demo")
    errs = [i for i in t["issues"]
            if i.layer == "scheduler" and i.severity == "error"]
    assert len(errs) == 1


# ── Convenience accessors ───────────────────────────────────────────────────


def test_validate_layer_filters_by_name(synthetic_templates):
    (synthetic_templates / "demo" / "scheduler.yaml").write_text("- bad")
    t = v.load_template("demo")
    sched_issues = v.validate_layer(t, "scheduler")
    assert all(i.layer == "scheduler" for i in sched_issues)
    assert v.validate_layer(t, "safety_rules") == []


def test_has_errors_true_when_any_error(synthetic_templates):
    (synthetic_templates / "demo" / "scheduler.yaml").write_text("- bad")
    t = v.load_template("demo")
    assert v.has_errors(t)


def test_has_errors_false_when_only_warns():
    """Real cafe template — should have only warns (or nothing), never errors."""
    t = v.load_template("cafe")
    assert not v.has_errors(t), f"cafe template has errors: {t['issues']}"
