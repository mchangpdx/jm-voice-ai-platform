# Tests for fire_and_forget utility (fire_and_forget 유틸리티 테스트)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch

# Inject required env vars before importing app modules (앱 모듈 임포트 전 환경 변수 주입)
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("GEMINI_API_KEY", "placeholder-gemini-key")


@pytest.mark.asyncio
async def test_fire_and_forget_schedules_coroutine():
    """fire_and_forget schedules a coroutine as a background task.
    The task runs and completes without blocking the caller.
    (코루틴이 백그라운드 태스크로 스케줄링되고 호출자를 차단하지 않아야 함)
    """
    from app.adapters.relay.fire_and_forget import fire_and_forget

    executed = []

    async def sample_coro():
        # Record execution to verify the task ran (실행 여부 기록)
        executed.append(True)

    await fire_and_forget(sample_coro())
    # Yield control to the event loop so background task executes (이벤트 루프에 제어권 양도)
    await asyncio.sleep(0)

    assert len(executed) == 1, "Background task should have executed once"


@pytest.mark.asyncio
async def test_fire_and_forget_catches_exceptions_without_crashing():
    """Exceptions inside fire_and_forget background task are caught and logged.
    The caller must not receive the exception — non-blocking guarantee.
    (백그라운드 태스크 내 예외는 로깅되고 호출자에게 전파되지 않아야 함)
    """
    from app.adapters.relay.fire_and_forget import fire_and_forget

    async def failing_coro():
        # Simulate a relay failure (릴레이 실패 시뮬레이션)
        raise RuntimeError("Simulated relay network failure")

    # Should not raise — caller gets control back immediately
    # (예외를 발생시키지 않아야 함 — 호출자는 즉시 제어권을 받아야 함)
    with patch("app.adapters.relay.fire_and_forget.logger") as mock_logger:
        await fire_and_forget(failing_coro())
        # Allow event loop to run the background task (이벤트 루프가 백그라운드 태스크 실행하도록 허용)
        await asyncio.sleep(0)

        # Logger.error must have been called with the exception info (에러 로깅 확인)
        mock_logger.error.assert_called_once()
        error_args = mock_logger.error.call_args[0]
        assert "fire_and_forget" in error_args[0]


@pytest.mark.asyncio
async def test_fire_and_forget_is_non_blocking():
    """Caller gets control back immediately — does not await the coroutine.
    We verify this by using a slow coroutine and checking the caller returns fast.
    (호출자는 즉시 제어권을 받아야 함 — 코루틴을 기다리지 않아야 함)
    """
    from app.adapters.relay.fire_and_forget import fire_and_forget

    slow_started = []
    slow_completed = []

    async def slow_coro():
        # Long-running coroutine (장기 실행 코루틴)
        slow_started.append(True)
        await asyncio.sleep(10)  # 10 seconds — much longer than test timeout
        slow_completed.append(True)

    # fire_and_forget should return without waiting for slow_coro to finish
    # (slow_coro 완료를 기다리지 않고 반환해야 함)
    await fire_and_forget(slow_coro())

    # Caller got control back — slow task has not completed yet (호출자가 제어권 받음 — 느린 태스크 미완료)
    assert slow_completed == [], "Caller should not be blocked by the background task"
