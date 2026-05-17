"""Phase 3.6 — vertical-aware tool dispatch unit tests.
(Phase 3.6 — vertical 분기 tool dispatch 단위 테스트)

Anchors the contract that order-kind verticals (cafe / pizza / mexican /
kbbq / sushi / chinese / etc.) receive EXACTLY the 10 historical tools,
in EXACTLY the historical order, while service-kind verticals receive
the 7-tool appointment surface. Any drift in either list fails the
regression alarm before reaching a live call.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest

# The `openai` SDK isn't installed in the unit-test sandbox (only the
# runtime venv has it). Module import is otherwise side-effect-free for
# our purposes — stub it so realtime_voice imports cleanly here.
# (openai SDK 없는 환경에서 module import 우회 — stub 주입)
sys.modules.setdefault("openai", MagicMock(AsyncOpenAI=MagicMock))


@pytest.fixture(scope="module")
def rv():
    """Import realtime_voice once for the module."""
    return importlib.import_module("app.api.realtime_voice")


# ── ORDER_KIND_TOOLS — frozen 10-tool contract ──────────────────────────────


def test_order_kind_tools_have_exactly_ten_entries(rv):
    """The order tool table is load-bearing for every cafe/pizza/mexican/kbbq
    store in production. Any add/remove here must be a deliberate, reviewed
    change — this assertion is the canary.
    (10개 tool — production order vertical 전체 의존, 변경 금지)"""
    assert len(rv.ORDER_KIND_TOOLS) == 10


def test_order_kind_tools_preserve_historical_order(rv):
    """Order matters because earlier patches anchor on index positions
    (e.g. retell mirror, test fixtures). Phase 3.6 guarantees this list
    is unchanged vs the pre-3.6 _GEMINI_TOOL_DEFS shipped 2026-05-12.
    (순서 보존 — 인덱스 의존 코드/픽스처가 깨지지 않음)"""
    names = [t["function_declarations"][0]["name"] for t in rv.ORDER_KIND_TOOLS]
    assert names == [
        "create_order",
        "modify_order",
        "cancel_order",
        "make_reservation",
        "modify_reservation",
        "cancel_reservation",
        "allergen_lookup",
        "recall_order",
        "recent_orders",
        "transfer_to_manager",
    ]


def test_gemini_tool_defs_alias_points_at_order(rv):
    """Legacy `_GEMINI_TOOL_DEFS` import must keep returning the order
    list — external imports that haven't migrated to the store-aware
    accessor depend on it staying stable.
    (legacy alias — 외부 import 호환 보장)"""
    assert rv._GEMINI_TOOL_DEFS is rv.ORDER_KIND_TOOLS


def test_openai_realtime_tools_alias_matches_order(rv):
    """`OPENAI_REALTIME_TOOLS` legacy constant must convert ORDER_KIND_TOOLS
    in the same shape get_openai_tools_for_store produces for order stores.
    (legacy OPENAI list — order vertical과 동일)"""
    order_store_tools = rv.get_openai_tools_for_store({"vertical_kind": "order"})
    assert len(rv.OPENAI_REALTIME_TOOLS) == len(order_store_tools)
    legacy_names = [t["name"] for t in rv.OPENAI_REALTIME_TOOLS]
    fresh_names  = [t["name"] for t in order_store_tools]
    assert legacy_names == fresh_names


# ── SERVICE_KIND_TOOLS — 7-tool appointment surface ─────────────────────────


def test_service_kind_tools_have_exactly_seven_entries(rv):
    assert len(rv.SERVICE_KIND_TOOLS) == 7


def test_service_kind_tools_set_is_correct(rv):
    """Set equality — covers 5 appointment + 2 shared."""
    names = {t["function_declarations"][0]["name"] for t in rv.SERVICE_KIND_TOOLS}
    assert names == {
        "book_appointment",
        "modify_appointment",
        "cancel_appointment",
        "service_lookup",
        "list_stylists",
        "allergen_lookup",
        "transfer_to_manager",
    }


def test_service_tools_do_not_leak_order_tools(rv):
    """A service-kind store must NOT see create_order / make_reservation
    / cancel_order in its tool table — that would break the wedge between
    food and appointment surfaces.
    (service vertical에 order tool 노출 금지)"""
    names = {t["function_declarations"][0]["name"] for t in rv.SERVICE_KIND_TOOLS}
    forbidden = {"create_order", "modify_order", "cancel_order",
                 "make_reservation", "modify_reservation",
                 "cancel_reservation", "recall_order", "recent_orders"}
    assert names.isdisjoint(forbidden)


# ── get_tool_defs_for_store — vertical_kind routing ─────────────────────────


@pytest.mark.parametrize("kind", ["order", "ORDER", None, "", "unknown_kind"])
def test_get_tool_defs_routes_non_service_to_order(rv, kind):
    """order / unknown / missing kinds all fall through to ORDER_KIND_TOOLS.
    Default-safe — a new vertical that forgets to register vertical_kind
    keeps working with the order tool surface.
    (default ORDER — 미등록 vertical 안전 fallback)"""
    store = {"vertical_kind": kind}
    assert rv.get_tool_defs_for_store(store) is rv.ORDER_KIND_TOOLS


@pytest.mark.parametrize("kind", ["service", "SERVICE",
                                    "service_with_dispatch",
                                    "service_with_anything_else"])
def test_get_tool_defs_routes_service_kinds(rv, kind):
    """Any kind starting with 'service' lands on SERVICE_KIND_TOOLS.
    Includes service_with_dispatch (auto repair / home services), which
    share the appointment surface today.
    (service-prefix vertical → SERVICE)"""
    store = {"vertical_kind": kind}
    assert rv.get_tool_defs_for_store(store) is rv.SERVICE_KIND_TOOLS


def test_get_tool_defs_for_cafe_store_returns_full_order_list(rv):
    """End-to-end identity check for a real cafe store row — must yield
    the same 10 tool defs as the module-level ORDER_KIND_TOOLS constant,
    in the same order.
    (cafe store → ORDER 10 tool, 동일 순서)"""
    cafe = {"id": "store-uuid", "name": "JM Cafe", "vertical_kind": "order"}
    out  = rv.get_tool_defs_for_store(cafe)
    assert out == rv.ORDER_KIND_TOOLS
    # Identity, not just equality — guarantees no copy/reorder happened.
    assert out is rv.ORDER_KIND_TOOLS


def test_get_openai_tools_for_cafe_matches_legacy_constant(rv):
    cafe = {"vertical_kind": "order"}
    out  = rv.get_openai_tools_for_store(cafe)
    assert [t["name"] for t in out] == [t["name"] for t in rv.OPENAI_REALTIME_TOOLS]


def test_get_openai_tools_for_beauty_emits_seven_tools(rv):
    beauty = {"vertical_kind": "service", "industry": "beauty"}
    out    = rv.get_openai_tools_for_store(beauty)
    assert len(out) == 7
    assert {t["name"] for t in out} == {
        "book_appointment", "modify_appointment", "cancel_appointment",
        "service_lookup", "list_stylists",
        "allergen_lookup", "transfer_to_manager",
    }
