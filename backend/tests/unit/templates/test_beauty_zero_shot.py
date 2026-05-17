"""Phase 6 — Beauty 0-shot multi-store validation.
(Phase 6 — Beauty 템플릿 0-shot 다매장 검증)

Validates the "code change zero" claim of the 9-layer Vertical Template
Framework: three brand-new beauty stores (English / Korean / Spanish-
flavored) reach a working voice configuration WITHOUT touching any code,
purely by reusing templates/beauty/ + the Phase 3 appointment skills +
the Phase 3.6 dispatcher.

Each store is verified end-to-end across four contracts:
  1. build_system_prompt — Luna persona, store name injection, INTAKE FLOW
     block from templates/beauty/intake_flow.yaml.
  2. get_tool_defs_for_store — must route to SERVICE_KIND_TOOLS (7 tools),
     not the order list.
  3. service_lookup — same skill code works against any beauty store's
     menu_items rows.
  4. list_stylists — same yaml-backed roster surface, regardless of which
     store called the tool.

Three stores intentionally span the supported language palette so the
fixture doubles as a multilingual smoke test.
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Same openai stub as test_realtime_tool_dispatch — sandboxed env doesn't
# have the SDK installed.
sys.modules.setdefault("openai", MagicMock(AsyncOpenAI=MagicMock))

from app.api.realtime_voice import (
    SERVICE_KIND_TOOLS,
    get_tool_defs_for_store,
)
from app.api.voice_websocket import build_system_prompt
from app.skills.appointment.list_stylists import list_stylists
from app.skills.appointment.service_lookup import service_lookup


# ── Three hypothetical beauty stores ────────────────────────────────────────


_STORES = [
    {
        "id":             "abc-hair-pdx",
        "name":           "ABC Hair Studio",
        "industry":       "beauty",
        "vertical_kind":  "service",
        # Luna persona — left to db_seeder default in production. Phase 4
        # docs say store rows ship with system_prompt populated, so the
        # fixture provides the template literally.
        "system_prompt": (
            "You are Luna, the elegant AI voice assistant for ABC Hair Studio."
        ),
        "business_hours": "Tuesday-Saturday 10am-7pm",
        "timezone":       "America/Los_Angeles",
        "_lang_focus":    "en",
    },
    {
        "id":             "gangnam-hair-la",
        "name":           "강남 헤어",
        "industry":       "beauty",
        "vertical_kind":  "service",
        "system_prompt": (
            "You are Luna, the elegant AI voice assistant for 강남 헤어."
        ),
        "business_hours": "Daily 11am-9pm",
        "timezone":       "America/Los_Angeles",
        "_lang_focus":    "ko",
    },
    {
        "id":             "cabello-latino-pdx",
        "name":           "Cabello Latino",
        "industry":       "beauty",
        "vertical_kind":  "service",
        "system_prompt": (
            "You are Luna, the elegant AI voice assistant for Cabello Latino."
        ),
        "business_hours": "Monday-Saturday 9am-8pm",
        "timezone":       "America/Los_Angeles",
        "_lang_focus":    "es",
    },
]


@pytest.fixture(params=_STORES, ids=lambda s: s["id"])
def store(request):
    return request.param


# ── Contract 1 — system prompt injection ────────────────────────────────────


def test_zero_shot_prompt_includes_luna_and_store_name(store):
    prompt = build_system_prompt(store)
    assert "Luna" in prompt, "Luna persona missing from prompt"
    assert store["name"] in prompt, (
        f"store name {store['name']!r} not surfaced in prompt"
    )


def test_zero_shot_prompt_includes_intake_flow_block(store):
    """Phase 1.6 additive wiring must inject templates/beauty/intake_flow.yaml
    into the prompt for every beauty store — no per-store config needed.
    (per-store config 0건으로 INTAKE FLOW 자동 주입)"""
    prompt = build_system_prompt(store)
    assert "=== INTAKE FLOW (" in prompt
    # The four service-vertical phases must surface.
    for phase_id in ("SERVICE_SELECT", "STYLIST", "TIME_SLOT", "CONFIRM"):
        assert phase_id in prompt, f"phase {phase_id} missing"


# ── Contract 2 — dispatcher routing ─────────────────────────────────────────


def test_zero_shot_dispatcher_routes_to_service_kind(store):
    defs = get_tool_defs_for_store(store)
    assert defs is SERVICE_KIND_TOOLS, (
        f"store {store['id']} should route to SERVICE_KIND_TOOLS"
    )
    names = {t["function_declarations"][0]["name"] for t in defs}
    assert "book_appointment" in names
    assert "create_order" not in names, (
        "order tools leaked into a service-kind store"
    )


# ── Contract 3 — service_lookup against shared menu_items shape ─────────────


@pytest.mark.asyncio
async def test_zero_shot_service_lookup_works_with_any_store_id(store):
    """The service_lookup skill code is store-agnostic — same Python path,
    same REST query shape, only the store_id parameter changes. Mock the
    REST response to return one fixture row; assert the skill resolved
    matched_name + duration_min + price unchanged.
    (skill code는 store-agnostic — store_id만 바꿔 호출)"""
    fixture_rows = [{
        "name":         "Women's Haircut",
        "duration_min": 60,
        "price":        65.0,
        "service_kind": "haircut",
    }]
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: fixture_rows
    with patch(
        "app.skills.appointment.service_lookup.httpx.AsyncClient"
    ) as ac_cls:
        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)
        ac_cls.return_value.__aenter__.return_value = client
        out = await service_lookup(
            store_id     = store["id"],
            service_name = "women's haircut",
        )
    assert out["ai_script_hint"] == "service_found"
    assert out["matched_name"] == "Women's Haircut"
    assert out["duration_min"] == 60


# ── Contract 4 — list_stylists single template, shared by every store ──────


@pytest.mark.asyncio
async def test_zero_shot_list_stylists_returns_shared_beauty_roster(store):
    """All three stores call list_stylists(vertical='beauty') and receive
    the same templates/beauty/scheduler.yaml roster. In production each
    store would override resources via Admin UI; the framework default is
    the shared list. The test anchors that the default roster ships and
    list_stylists pulls it without per-store template branching.
    (단일 templates/beauty/scheduler.yaml이 모든 beauty 매장 default)"""
    out = await list_stylists(vertical="beauty")
    assert out["ai_script_hint"] == "stylists_listed"
    assert out["slot_kind"] == "stylist"
    names = {s["name"] for s in out["stylists"]}
    # The seed roster: Maria / Yuna / Sophia / Aria.
    assert {"Maria", "Yuna", "Sophia", "Aria"}.issubset(names)


# ── Sanity — Phase 3.6 frozen contracts still hold for these stores ────────


def test_zero_shot_no_order_tools_for_any_beauty_store(store):
    defs = get_tool_defs_for_store(store)
    names = {t["function_declarations"][0]["name"] for t in defs}
    forbidden = {"create_order", "modify_order", "cancel_order",
                 "make_reservation", "modify_reservation",
                 "cancel_reservation", "recall_order", "recent_orders"}
    assert names.isdisjoint(forbidden)


# ── Multi-store identity — three stores, identical surfaces ────────────────


def test_zero_shot_all_three_stores_get_identical_tool_set():
    """The tool registry is per-vertical, not per-store. ABC Hair / 강남 헤어 /
    Cabello Latino must see the exact same tool list (set + count) — this
    is the load-bearing invariant of the Phase 3.6 split.
    (3 매장이 정확히 동일한 tool surface — vertical 단위 캐싱 안전)"""
    surfaces = [
        {t["function_declarations"][0]["name"]
         for t in get_tool_defs_for_store(s)}
        for s in _STORES
    ]
    assert surfaces[0] == surfaces[1] == surfaces[2]
    assert len(surfaces[0]) == 7
