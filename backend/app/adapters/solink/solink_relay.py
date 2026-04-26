# Solink CCTV relay adapter — Layer 4 External Bridge
# (Solink CCTV 릴레이 어댑터 — Layer 4 외부 브리지)

import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


class SolinkRelay:
    """Fire-and-Forget relay bridge to Solink CCTV webhook endpoint.
    Forwards security events asynchronously with RLS tenant routing via X-Tenant-ID header.
    (Solink CCTV 웹훅에 보안 이벤트를 비동기적으로 전달하는 Fire-and-Forget 릴레이 브리지)
    """

    def __init__(self, api_url: str, api_key: str, timeout: int = 8) -> None:
        # Store Solink API configuration (Solink API 설정 저장)
        self.api_url = api_url.rstrip("/")  # Remove trailing slash for clean URL concat (후행 슬래시 제거)
        self.api_key = api_key
        self.timeout = timeout

    async def relay_event(self, event_data: dict, tenant_id: str) -> dict:
        """Forward a security event to the Solink webhook endpoint.
        Adds X-Tenant-ID header for RLS routing. Catches all httpx errors gracefully.
        (보안 이벤트를 Solink 웹훅으로 전달. RLS 라우팅을 위한 X-Tenant-ID 헤더 추가. httpx 오류는 로깅)

        Returns:
            dict with relay_id (UUID) and queued_at (ISO 8601 UTC timestamp)
        """
        relay_id = str(uuid4())  # Generate relay ID upfront for tracking (추적용 릴레이 ID 사전 생성)
        queued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # ISO 8601 UTC (UTC ISO 8601)

        headers = {
            "Authorization": f"Bearer {self.api_key}",  # Solink bearer auth (Solink 베어러 인증)
            "X-Tenant-ID": tenant_id,  # RLS routing header (RLS 라우팅 헤더)
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_url}/events",
                    headers=headers,
                    json=event_data,
                )
                response.raise_for_status()  # Raise on 4xx/5xx responses (4xx/5xx 응답 시 예외 발생)

        except httpx.TimeoutException as exc:
            # Log timeout — do not propagate to caller (타임아웃 로깅 — 호출자에게 전파 금지)
            logger.error("SolinkRelay.relay_event timed out for tenant %s: %s", tenant_id, exc)

        except httpx.HTTPStatusError as exc:
            # Log HTTP error — do not propagate to caller (HTTP 오류 로깅 — 호출자에게 전파 금지)
            logger.error(
                "SolinkRelay.relay_event HTTP error %s for tenant %s: %s",
                exc.response.status_code,
                tenant_id,
                exc,
            )

        return {"relay_id": relay_id, "queued_at": queued_at}
