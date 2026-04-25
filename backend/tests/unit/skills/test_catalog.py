# Tests for Catalog Navigator skill — Layer 2 Universal Shared Skill
# (카탈로그 네비게이터 스킬 테스트 — Layer 2 범용 공유 스킬)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.menu_item import MenuItem
from app.skills.catalog.schemas import MenuItemOut
from app.skills.catalog.service import get_menu


@pytest.mark.asyncio
async def test_get_menu_returns_items_for_tenant(mock_db):
    # Mock DB returns 1 item for "tenant-a", assert correct name and tenant_id
    # (mock DB가 "tenant-a"에 대해 1개 항목 반환, 이름과 tenant_id 검증)
    item = MenuItem(
        variant_id="var-001",
        tenant_id="tenant-a",
        item_id="item-001",
        name="Classic Burger",
        category="Burgers",
        price=1099,
        stock_quantity=50,
        promoted_at=None,
    )

    # Simulate scalars().all() returning [item] (scalars().all()가 [item]을 반환하도록 시뮬레이션)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [item]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_menu("tenant-a", mock_db)

    assert len(result) == 1
    assert result[0].name == "Classic Burger"
    assert result[0].tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_get_menu_returns_empty_for_unknown_tenant(mock_db):
    # Mock DB returns [] for unknown tenant, assert result is empty list
    # (알 수 없는 tenant에 대해 빈 리스트 반환 검증)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_menu("unknown-tenant", mock_db)

    assert result == []


@pytest.mark.asyncio
async def test_get_menu_query_filters_by_tenant_id(mock_db):
    # Assert db.execute was called exactly once (RLS 준수: db.execute 정확히 1회 호출 검증)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    await get_menu("tenant-b", mock_db)

    mock_db.execute.assert_called_once()


def test_menu_item_out_schema_from_orm():
    # MenuItemOut can be populated from ORM model attributes via from_attributes=True
    # (from_attributes=True를 통해 ORM 모델 속성으로 MenuItemOut 생성 검증)
    item = MenuItem(
        variant_id="var-002",
        tenant_id="tenant-c",
        item_id="item-002",
        name="Garden Salad",
        category="Salads",
        price=899,
        stock_quantity=30,
        promoted_at=None,
    )

    out = MenuItemOut.model_validate(item)

    assert out.variant_id == "var-002"
    assert out.item_id == "item-002"
    assert out.name == "Garden Salad"
    assert out.category == "Salads"
    assert out.price == 899
    assert out.stock_quantity == 30


def test_menu_item_out_schema_from_dict():
    # MenuItemOut can be created from a plain dict (dict에서 MenuItemOut 생성 검증)
    data = {
        "variant_id": "var-003",
        "item_id": "item-003",
        "name": "Fries",
        "category": "Sides",
        "price": 399,
        "stock_quantity": 100,
    }

    out = MenuItemOut(**data)

    assert out.price == 399
    assert out.name == "Fries"
