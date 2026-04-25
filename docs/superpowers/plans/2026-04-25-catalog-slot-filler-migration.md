# Catalog Navigator + Slot Filler Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the `check_menu` Catalog Navigator and slot-collection logic from the Node.js legacy platform (`~/jm-saas-platform`) into Python FastAPI skills at `backend/app/skills/{catalog,slot_filler}/`.

**Architecture:** Models live in `backend/app/models/` and extend `TenantBase`, which enforces `tenant_id` on every table. Skill modules in `backend/app/skills/` contain pure business logic — no HTTP, no direct DB I/O beyond the async session parameter. All async I/O uses SQLAlchemy 2.0's `AsyncSession`.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (async + `asyncpg`), Pydantic 2.x, pytest 8.x + pytest-asyncio 0.24

---

## Legacy Source Reference

| Legacy file | What to migrate |
|---|---|
| `/src/services/llm/gemini.js` — `check_menu` tool | Catalog service query logic |
| `/src/jobs/cronJobs.js` — `syncMenuFromLoyverse` | Menu item schema (field names) |
| `/src/websocket/llmServer.js` — reservation handler | Slot definitions and confirmation gate |
| `/src/services/llm/gemini.js` — `POS_TOOLS` | Slot field names, required fields, prompts |

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/pytest.ini` | pytest-asyncio `auto` mode + pythonpath |
| Create | `backend/tests/conftest.py` | Shared `mock_db` fixture |
| Create | `backend/app/models/base.py` | `TenantBase` abstract class |
| Create | `backend/app/models/menu_item.py` | `MenuItem` SQLAlchemy model |
| Create | `backend/app/skills/catalog/schemas.py` | `MenuItemOut` Pydantic response schema |
| Create | `backend/app/skills/catalog/service.py` | `get_menu()` async function |
| Create | `backend/tests/unit/skills/test_catalog.py` | Catalog service unit tests |
| Create | `backend/app/skills/slot_filler/schemas.py` | `Intent`, slot dicts, `SlotCheckResult` |
| Create | `backend/app/skills/slot_filler/service.py` | `check_slots()`, `next_prompt()` |
| Create | `backend/tests/unit/skills/test_slot_filler.py` | Slot filler unit tests |

---

## Task 1: Test Infrastructure + TenantBase

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/tests/conftest.py`
- Create: `backend/app/models/base.py`

- [ ] **Step 1: Create `backend/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
pythonpath = .
```

- [ ] **Step 2: Create `backend/tests/conftest.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_db() -> AsyncSession:
    # Reusable async DB session mock (재사용 가능한 비동기 DB 세션 목)
    session = AsyncMock(spec=AsyncSession)
    return session
```

- [ ] **Step 3: Create `backend/app/models/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantBase(Base):
    # Abstract base enforcing tenant_id on every table (모든 테이블에 tenant_id 강제하는 추상 베이스)
    __abstract__ = True
    tenant_id: Mapped[str] = mapped_column(index=True, nullable=False)
```

- [ ] **Step 4: Verify pytest is importable**

```bash
cd backend && .venv/bin/pytest --collect-only 2>&1 | head -10
```

Expected: no errors, "0 tests collected" (no test files yet).

- [ ] **Step 5: Commit**

```bash
git add backend/pytest.ini backend/tests/conftest.py backend/app/models/base.py \
        backend/tests/unit/__init__.py backend/tests/unit/skills/__init__.py \
        backend/tests/unit/core/__init__.py backend/tests/integration/__init__.py \
        backend/tests/fixtures/__init__.py
git commit -m "chore: add test infrastructure, pytest config, and TenantBase"
```

---

## Task 2: MenuItem Model + Catalog Tests (failing)

**Files:**
- Create: `backend/app/models/menu_item.py`
- Create: `backend/tests/unit/skills/test_catalog.py`

**Legacy reference:** field names come from `menu_items` table in `/src/jobs/cronJobs.js` — `variant_id`, `item_id`, `name`, `category`, `price` (cents), `stock_quantity`, `promoted_at`. `store_id` is renamed to `tenant_id` for RLS compliance.

- [ ] **Step 1: Create `backend/app/models/menu_item.py`**

```python
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import TenantBase


class MenuItem(TenantBase):
    __tablename__ = "menu_items"

    variant_id: Mapped[str] = mapped_column(primary_key=True)
    item_id: Mapped[str]
    name: Mapped[str]
    category: Mapped[str]
    price: Mapped[int]  # US cents (미국 센트 단위)
    stock_quantity: Mapped[int]
    promoted_at: Mapped[datetime | None] = mapped_column(default=None)
```

- [ ] **Step 2: Write failing test `backend/tests/unit/skills/test_catalog.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu_item import MenuItem
from app.skills.catalog.service import get_menu  # does not exist yet


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


async def test_get_menu_returns_items_for_tenant(mock_db):
    # get_menu only returns items belonging to the given tenant (해당 테넌트 항목만 반환)
    fake_items = [
        MenuItem(
            variant_id="var-001",
            tenant_id="tenant-a",
            item_id="item-001",
            name="Burger",
            category="Mains",
            price=1200,
            stock_quantity=10,
        )
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = fake_items
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_menu("tenant-a", mock_db)

    assert len(result) == 1
    assert result[0].name == "Burger"
    assert result[0].tenant_id == "tenant-a"


async def test_get_menu_returns_empty_for_unknown_tenant(mock_db):
    # Unknown tenant returns empty list (알 수 없는 테넌트는 빈 목록 반환)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_menu("unknown-tenant", mock_db)

    assert result == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/unit/skills/test_catalog.py -v
```

Expected: `ImportError: cannot import name 'get_menu' from 'app.skills.catalog.service'`

- [ ] **Step 4: Commit failing test**

```bash
git add backend/app/models/menu_item.py backend/tests/unit/skills/test_catalog.py
git commit -m "test(catalog): add failing unit tests for get_menu"
```

---

## Task 3: Catalog Service — Make Tests Pass

**Files:**
- Create: `backend/app/skills/catalog/schemas.py`
- Create: `backend/app/skills/catalog/service.py`

- [ ] **Step 1: Create `backend/app/skills/catalog/schemas.py`**

```python
from pydantic import BaseModel


class MenuItemOut(BaseModel):
    # Pydantic response schema for a single menu item (단일 메뉴 항목 응답 스키마)
    variant_id: str
    item_id: str
    name: str
    category: str
    price: int  # cents
    stock_quantity: int

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Create `backend/app/skills/catalog/service.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu_item import MenuItem


async def get_menu(tenant_id: str, db: AsyncSession) -> list[MenuItem]:
    # Fetch live menu items ordered by category then name (카테고리·이름순 실시간 메뉴 조회)
    result = await db.execute(
        select(MenuItem)
        .where(MenuItem.tenant_id == tenant_id)
        .order_by(MenuItem.category, MenuItem.name)
    )
    return result.scalars().all()
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/unit/skills/test_catalog.py -v
```

Expected:
```
PASSED tests/unit/skills/test_catalog.py::test_get_menu_returns_items_for_tenant
PASSED tests/unit/skills/test_catalog.py::test_get_menu_returns_empty_for_unknown_tenant
2 passed in 0.XXs
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/skills/catalog/schemas.py backend/app/skills/catalog/service.py
git commit -m "feat(catalog): implement get_menu Catalog Navigator skill"
```

---

## Task 4: Slot Filler Schemas + Tests (failing)

**Files:**
- Create: `backend/app/skills/slot_filler/schemas.py`
- Create: `backend/tests/unit/skills/test_slot_filler.py`

**Legacy reference:** Required fields from `/src/services/llm/gemini.js` `POS_TOOLS`:
- `make_reservation` → 6 fields + `user_explicit_confirmation`
- `create_order` → items, customer fields + `user_explicit_confirmation`

- [ ] **Step 1: Create `backend/app/skills/slot_filler/schemas.py`**

```python
from enum import Enum
from pydantic import BaseModel


class Intent(str, Enum):
    RESERVATION = "reservation"
    ORDER = "order"


# Ordered dict — first key gets the first prompt (순서 보장 딕셔너리 — 첫 번째 키가 첫 안내)
RESERVATION_SLOTS: dict[str, str] = {
    "customer_name": "Could you please share your name?",
    "customer_phone": "What's the best phone number to reach you?",
    "customer_email": "And your email address?",
    "reservation_date": "What date would you like to reserve? (YYYY-MM-DD)",
    "reservation_time": "What time? (HH:MM, 24-hour format)",
    "party_size": "How many guests will be joining?",
}

ORDER_SLOTS: dict[str, str] = {
    "customer_name": "Could you please share your name?",
    "customer_phone": "What's the best phone number to reach you?",
    "customer_email": "And your email address?",
    "items": "What items would you like to order?",
    "user_explicit_confirmation": "Can you confirm your order with a clear 'Yes'?",
}


class SlotCheckResult(BaseModel):
    missing: list[str]
    next_prompt: str | None
    complete: bool
```

- [ ] **Step 2: Write failing tests `backend/tests/unit/skills/test_slot_filler.py`**

```python
import pytest
from app.skills.slot_filler.service import check_slots, next_prompt  # does not exist yet
from app.skills.slot_filler.schemas import Intent


def test_check_slots_reservation_all_filled():
    # All slots present → complete=True (모든 슬롯 존재 시 완료 반환)
    collected = {
        "customer_name": "John",
        "customer_phone": "555-1234",
        "customer_email": "john@example.com",
        "reservation_date": "2026-05-01",
        "reservation_time": "19:00",
        "party_size": 4,
    }
    result = check_slots(Intent.RESERVATION, collected)
    assert result.complete is True
    assert result.missing == []
    assert result.next_prompt is None


def test_check_slots_reservation_missing_fields():
    # Missing fields → first missing field prompt returned (누락 필드 존재 시 첫 번째 안내 반환)
    collected = {"customer_name": "John"}
    result = check_slots(Intent.RESERVATION, collected)
    assert result.complete is False
    assert "customer_phone" in result.missing
    assert result.next_prompt == "What's the best phone number to reach you?"


def test_check_slots_empty_collected():
    # Entirely empty input returns first slot prompt (빈 입력 시 첫 번째 슬롯 안내 반환)
    result = check_slots(Intent.RESERVATION, {})
    assert result.complete is False
    assert result.next_prompt == "Could you please share your name?"


def test_next_prompt_empty_missing_returns_none():
    # No missing slots → None (누락 슬롯 없으면 None 반환)
    assert next_prompt([]) is None


def test_check_slots_order_requires_confirmation():
    # Order without explicit confirmation is incomplete (명시적 확인 없는 주문은 미완료)
    collected = {
        "customer_name": "Jane",
        "customer_phone": "555-9999",
        "customer_email": "jane@example.com",
        "items": [{"variant_id": "var-001", "quantity": 2}],
    }
    result = check_slots(Intent.ORDER, collected)
    assert result.complete is False
    assert "user_explicit_confirmation" in result.missing
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/unit/skills/test_slot_filler.py -v
```

Expected: `ImportError: cannot import name 'check_slots' from 'app.skills.slot_filler.service'`

- [ ] **Step 4: Commit failing tests**

```bash
git add backend/app/skills/slot_filler/schemas.py backend/tests/unit/skills/test_slot_filler.py
git commit -m "test(slot-filler): add failing unit tests for check_slots and next_prompt"
```

---

## Task 5: Slot Filler Service — Make Tests Pass

**Files:**
- Create: `backend/app/skills/slot_filler/service.py`

- [ ] **Step 1: Create `backend/app/skills/slot_filler/service.py`**

```python
from .schemas import Intent, RESERVATION_SLOTS, ORDER_SLOTS, SlotCheckResult

_SLOT_MAP: dict[Intent, dict[str, str]] = {
    Intent.RESERVATION: RESERVATION_SLOTS,
    Intent.ORDER: ORDER_SLOTS,
}


def check_slots(intent: Intent, collected: dict) -> SlotCheckResult:
    # Identify missing slots and build the next voice prompt (누락 슬롯 식별 후 다음 음성 안내 구성)
    slots = _SLOT_MAP[intent]
    missing = [key for key in slots if not collected.get(key)]
    return SlotCheckResult(
        missing=missing,
        next_prompt=next_prompt(missing, slots),
        complete=len(missing) == 0,
    )


def next_prompt(missing: list[str], slots: dict[str, str] | None = None) -> str | None:
    # Return prompt text for the first unfilled slot (첫 번째 미입력 슬롯의 안내 문구 반환)
    if not missing:
        return None
    if slots is None:
        return None
    return slots.get(missing[0])
```

- [ ] **Step 2: Run all unit tests**

```bash
cd backend && .venv/bin/pytest tests/unit/ -v
```

Expected:
```
PASSED tests/unit/skills/test_catalog.py::test_get_menu_returns_items_for_tenant
PASSED tests/unit/skills/test_catalog.py::test_get_menu_returns_empty_for_unknown_tenant
PASSED tests/unit/skills/test_slot_filler.py::test_check_slots_reservation_all_filled
PASSED tests/unit/skills/test_slot_filler.py::test_check_slots_reservation_missing_fields
PASSED tests/unit/skills/test_slot_filler.py::test_check_slots_empty_collected
PASSED tests/unit/skills/test_slot_filler.py::test_next_prompt_empty_missing_returns_none
PASSED tests/unit/skills/test_slot_filler.py::test_check_slots_order_requires_confirmation
7 passed in 0.XXs
```

- [ ] **Step 3: Verify coverage for skill modules**

```bash
cd backend && .venv/bin/pytest tests/unit/skills/ \
  --cov=app/skills/catalog --cov=app/skills/slot_filler \
  --cov-fail-under=85 -v
```

Expected: coverage ≥ 85%, no failures.

- [ ] **Step 4: Commit**

```bash
git add backend/app/skills/slot_filler/service.py
git commit -m "feat(slot-filler): implement check_slots and next_prompt Slot Filler skill"
```

---

## Self-Review Checklist

| Requirement | Covered by task |
|---|---|
| Scan legacy code | Done (pre-plan) |
| Base directory structure | Task 1 |
| `tenant_id` in all models | `TenantBase` in Task 1 |
| TDD — tests before implementation | Tasks 2 & 4 write tests first |
| Coverage ≥ 85% in skill modules | Task 5 Step 3 |
| English code + bilingual comments | All tasks |
| Catalog Navigator | Tasks 2 & 3 |
| Slot Filler | Tasks 4 & 5 |
| `variant_id` preserved in MenuItem | Task 2 (primary key) |
| Frequent commits | Every task has a commit step |
