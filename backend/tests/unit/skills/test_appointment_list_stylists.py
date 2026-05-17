"""Phase 3.5 — list_stylists tool unit tests.
(Phase 3.5 — list_stylists 단위 테스트)

Covers:
  - Tool def shape (specialty_filter optional, no required fields)
  - format_resources pure helper (lenient drops + case-insensitive filter)
  - list_stylists flow against the template loader:
      * no scheduler.yaml → no_stylists_configured
      * scheduler with empty resources → no_stylists_configured
      * scheduler with resources, no filter → stylists_listed
      * scheduler with resources, filter that matches → stylists_listed
      * scheduler with resources, filter that misses → no_stylists_match_filter
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.skills.appointment.list_stylists import (
    LIST_STYLISTS_TOOL_DEF,
    format_resources,
    list_stylists,
)


# ── Tool def shape ──────────────────────────────────────────────────────────


def test_tool_def_shape():
    decls = LIST_STYLISTS_TOOL_DEF["function_declarations"]
    assert len(decls) == 1
    fn = decls[0]
    assert fn["name"] == "list_stylists"
    params = fn["parameters"]
    # specialty_filter is optional — required must be empty
    assert params.get("required", []) == []
    assert "specialty_filter" in params["properties"]


# ── format_resources ───────────────────────────────────────────────────────


def test_format_resources_handles_none():
    assert format_resources(None) == []


def test_format_resources_handles_non_list():
    assert format_resources("not a list") == []  # type: ignore[arg-type]


def test_format_resources_drops_non_dict_entries():
    resources = [
        {"id": "maria", "en": "Maria", "specialties": ["balayage"]},
        "invalid",
        None,
        {"id": "yuna", "en": "Yuna", "specialties": ["color", "haircut"]},
    ]
    out = format_resources(resources)  # type: ignore[arg-type]
    assert len(out) == 2
    assert out[0]["name"] == "Maria"
    assert out[1]["name"] == "Yuna"


def test_format_resources_filter_case_insensitive():
    resources = [
        {"id": "maria", "en": "Maria", "specialties": ["Balayage", "Color"]},
        {"id": "yuna",  "en": "Yuna",  "specialties": ["Haircut"]},
    ]
    out = format_resources(resources, specialty_filter="BALAYAGE")
    assert len(out) == 1
    assert out[0]["name"] == "Maria"


def test_format_resources_empty_filter_returns_all():
    resources = [
        {"id": "maria", "en": "Maria", "specialties": ["balayage"]},
        {"id": "yuna",  "en": "Yuna",  "specialties": ["haircut"]},
    ]
    assert len(format_resources(resources, specialty_filter="")) == 2
    assert len(format_resources(resources, specialty_filter="   ")) == 2


def test_format_resources_carries_capacity():
    resources = [{"id": "chair1", "en": "Chair 1", "capacity": 2,
                  "specialties": ["haircut"]}]
    out = format_resources(resources)
    assert out[0]["capacity"] == 2


# ── list_stylists flow ─────────────────────────────────────────────────────


def _patch_template(scheduler):
    """Patch load_template to return a template with the given scheduler."""
    template = {
        "vertical":  "beauty",
        "scheduler": scheduler,
        "issues":    [],
    }
    return patch(
        "app.skills.appointment.list_stylists.load_template",
        return_value=template,
    )


@pytest.mark.asyncio
async def test_no_scheduler_returns_no_stylists_configured():
    with _patch_template(None):
        out = await list_stylists(vertical="beauty")
    assert out["success"] is True
    assert out["ai_script_hint"] == "no_stylists_configured"
    assert out["stylists"] == []


@pytest.mark.asyncio
async def test_empty_resources_returns_no_stylists_configured():
    sched = {"slot_kind": "stylist", "resources": []}
    with _patch_template(sched):
        out = await list_stylists(vertical="beauty")
    assert out["ai_script_hint"] == "no_stylists_configured"
    assert out["slot_kind"] == "stylist"


@pytest.mark.asyncio
async def test_roster_returned_when_resources_present():
    sched = {
        "slot_kind": "stylist",
        "resources": [
            {"id": "maria", "en": "Maria", "specialties": ["balayage"]},
            {"id": "yuna",  "en": "Yuna",  "specialties": ["haircut"]},
        ],
    }
    with _patch_template(sched):
        out = await list_stylists(vertical="beauty")
    assert out["ai_script_hint"] == "stylists_listed"
    assert {s["name"] for s in out["stylists"]} == {"Maria", "Yuna"}


@pytest.mark.asyncio
async def test_filter_match_returns_listed_hint():
    sched = {
        "slot_kind": "stylist",
        "resources": [
            {"id": "maria", "en": "Maria", "specialties": ["balayage"]},
            {"id": "yuna",  "en": "Yuna",  "specialties": ["haircut"]},
        ],
    }
    with _patch_template(sched):
        out = await list_stylists(vertical="beauty", specialty_filter="balayage")
    assert out["ai_script_hint"] == "stylists_listed"
    assert len(out["stylists"]) == 1
    assert out["stylists"][0]["name"] == "Maria"


@pytest.mark.asyncio
async def test_filter_miss_returns_no_match_hint():
    sched = {
        "slot_kind": "stylist",
        "resources": [
            {"id": "maria", "en": "Maria", "specialties": ["balayage"]},
        ],
    }
    with _patch_template(sched):
        out = await list_stylists(vertical="beauty", specialty_filter="oil_change")
    assert out["ai_script_hint"] == "no_stylists_match_filter"
    assert out["stylists"] == []
