import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_db() -> AsyncSession:
    # Reusable async DB session mock (재사용 가능한 비동기 DB 세션 목)
    return AsyncMock(spec=AsyncSession)
