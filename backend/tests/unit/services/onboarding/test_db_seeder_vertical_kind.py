"""Phase 3.6 wiring gap fix (audit #19) — db_seeder.finalize_store must
seed `stores.vertical_kind` from vertical_kinds.yaml so the realtime
dispatcher routes service vs order tools correctly on new stores.
(자동화 audit #19 fix — finalize 시 vertical_kind 자동 채움 회귀 가드)

Live trigger 2026-05-18: JM Beauty Salon was activated via PATCH and the
dispatcher fell back to ORDER_KIND_TOOLS because vertical_kind was NULL,
forcing service_lookup → service_not_found → transfer_to_manager loop on
the first verification call. The fix wires _resolve_kind_and_meta into the
finalize_store store_payload; these tests anchor that wiring.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.onboarding.db_seeder import finalize_store


def _patch_seed_chain():
    """Patch every IO-bound seeder helper finalize_store calls so the test
    only exercises the store_payload composition path.
    (DB IO 헬퍼 전부 mock — payload 구성만 검증)"""
    return [
        patch(
            "app.services.onboarding.db_seeder.seed_store",
            new=AsyncMock(return_value="store-uuid-xyz"),
        ),
        patch(
            "app.services.onboarding.db_seeder.seed_menu_items",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.services.onboarding.db_seeder.seed_modifier_groups",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.services.onboarding.db_seeder.seed_modifier_options",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.onboarding.db_seeder.wire_items_to_modifier_groups",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.onboarding.db_seeder.rebuild_menu_cache",
            new=AsyncMock(return_value=""),
        ),
    ]


def _capture_seed_store_payload():
    """Returns (patches, captured) where captured['payload'] is set when
    seed_store is invoked, so each test can inspect what finalize built.
    (seed_store에 전달된 payload를 캡처해서 검증)"""
    captured: dict = {}

    async def _capturing_seed_store(client, payload):
        captured["payload"] = payload
        return "store-uuid-xyz"

    patches = _patch_seed_chain()
    # Replace the seed_store patch with the capturing variant.
    patches[0] = patch(
        "app.services.onboarding.db_seeder.seed_store",
        new=AsyncMock(side_effect=_capturing_seed_store),
    )
    return patches, captured


@pytest.mark.asyncio
@pytest.mark.parametrize("vertical,expected_kind", [
    ("beauty",        "service"),
    ("home_services", "service_with_dispatch"),
    ("auto_repair",   "service_with_dispatch"),
    ("cafe",          "order"),
    ("pizza",         "order"),
    ("kbbq",          "order"),
    ("mexican",       "order"),
])
async def test_finalize_seeds_vertical_kind_from_yaml(vertical, expected_kind):
    """Every registered vertical lands in stores.vertical_kind with the
    kind from templates/_base/vertical_kinds.yaml.
    (등록된 vertical은 yaml의 kind로 자동 set)"""
    patches, captured = _capture_seed_store_payload()
    for p in patches: p.start()
    try:
        await finalize_store(
            store_name           = "Test Store",
            phone_number         = "+15555550100",
            manager_phone        = "+15555550199",
            vertical             = vertical,
            menu_yaml            = {"items": []},
            modifier_groups_yaml = {"groups": {}},
        )
    finally:
        for p in patches: p.stop()

    payload = captured.get("payload") or {}
    assert payload.get("vertical_kind") == expected_kind, (
        f"vertical={vertical} should map to kind={expected_kind!r}, "
        f"got {payload.get('vertical_kind')!r}"
    )


@pytest.mark.asyncio
async def test_finalize_omits_vertical_kind_for_unknown_vertical():
    """Unknown vertical → NULL column (no key in payload). The realtime
    dispatcher defaults to ORDER when vertical_kind is missing, which is
    the safe fallback. Adds an explicit guarantee against a future kind
    resolver bug that returns garbage strings.
    (미등록 vertical은 vertical_kind 키 자체를 빼서 NULL로 저장)"""
    patches, captured = _capture_seed_store_payload()
    for p in patches: p.start()
    try:
        await finalize_store(
            store_name           = "Mystery Store",
            phone_number         = "+15555550101",
            manager_phone        = "+15555550199",
            vertical             = "no_such_vertical",
            menu_yaml            = {"items": []},
            modifier_groups_yaml = {"groups": {}},
        )
    finally:
        for p in patches: p.stop()

    payload = captured.get("payload") or {}
    assert "vertical_kind" not in payload


@pytest.mark.asyncio
async def test_finalize_industry_and_vertical_kind_both_set():
    """`industry` and `vertical_kind` are independent columns and finalize
    must populate BOTH — `industry` is the human-readable vertical name
    (matches templates dir + persona key), `vertical_kind` is the
    coarse-grained routing label (order vs service vs dispatch).
    (industry + vertical_kind 둘 다 set — 서로 다른 용도)"""
    patches, captured = _capture_seed_store_payload()
    for p in patches: p.start()
    try:
        await finalize_store(
            store_name           = "Beauty Test",
            phone_number         = "+15555550102",
            manager_phone        = "+15555550199",
            vertical             = "beauty",
            menu_yaml            = {"items": []},
            modifier_groups_yaml = {"groups": {}},
        )
    finally:
        for p in patches: p.stop()

    payload = captured.get("payload") or {}
    assert payload.get("industry")      == "beauty"
    assert payload.get("business_type") == "beauty"
    assert payload.get("vertical_kind") == "service"
