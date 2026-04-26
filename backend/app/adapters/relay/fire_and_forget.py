# Fire-and-Forget async task scheduler (비차단 백그라운드 태스크 스케줄러)
# Layer 4 — External Bridge Relay Engine (Layer 4 — 외부 브리지 릴레이 엔진)

import asyncio
import logging

logger = logging.getLogger(__name__)


async def fire_and_forget(coro) -> None:
    """Schedule a coroutine as a non-blocking background task.
    Exceptions are caught and logged — never propagate to the caller.
    (코루틴을 비차단 백그라운드 태스크로 스케줄링. 예외는 로깅만 함)
    """

    async def _safe_run():
        # Wrap execution to catch and log all exceptions without crashing caller
        # (모든 예외를 잡아 로깅하고 호출자 충돌 방지)
        try:
            await coro
        except Exception as exc:
            logger.error("fire_and_forget task failed: %s", exc)

    asyncio.create_task(_safe_run())  # Schedule task — returns immediately (즉시 반환)
