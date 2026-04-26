# Loyverse POS relay adapter — Layer 4 External Bridge
# (Loyverse POS 릴레이 어댑터 — Layer 4 외부 브리지)

import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


class LoyverseRelay:
    """Fire-and-Forget relay bridge to Loyverse POS API.
    Forwards order data asynchronously with RLS tenant routing via X-Tenant-ID header.
    (Loyverse POS API에 주문 데이터를 비동기적으로 전달하는 Fire-and-Forget 릴레이 브리지)
    """

    def __init__(self, api_url: str, api_key: str, timeout: int = 8) -> None:
        # Store Loyverse API configuration (Loyverse API 설정 저장)
        self.api_url = api_url.rstrip("/")  # Remove trailing slash for clean URL concat (후행 슬래시 제거)
        self.api_key = api_key
        self.timeout = timeout

    async def relay_order(self, order_data: dict, tenant_id: str) -> dict:
        """Forward an order to Loyverse POS /receipts endpoint.
        Adds X-Tenant-ID header for RLS routing. Catches all httpx errors gracefully.
        (주문을 Loyverse POS /receipts 엔드포인트로 전달. RLS 라우팅을 위한 X-Tenant-ID 헤더 추가. httpx 오류는 로깅)

        Returns:
            dict with relay_id (UUID), loyverse_receipt_id (None — filled async), and queued_at (ISO 8601 UTC)
        """
        relay_id = str(uuid4())  # Generate relay ID upfront for tracking (추적용 릴레이 ID 사전 생성)
        queued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # ISO 8601 UTC (UTC ISO 8601)

        headers = {
            "Authorization": f"Bearer {self.api_key}",  # Loyverse bearer auth (Loyverse 베어러 인증)
            "X-Tenant-ID": tenant_id,  # RLS routing header (RLS 라우팅 헤더)
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_url}/receipts",
                    headers=headers,
                    json=order_data,
                )
                response.raise_for_status()  # Raise on 4xx/5xx responses (4xx/5xx 응답 시 예외 발생)

        except httpx.TimeoutException as exc:
            # Log timeout — do not propagate to caller (타임아웃 로깅 — 호출자에게 전파 금지)
            logger.error("LoyverseRelay.relay_order timed out for tenant %s: %s", tenant_id, exc)

        except httpx.HTTPStatusError as exc:
            # Log HTTP error — do not propagate to caller (HTTP 오류 로깅 — 호출자에게 전파 금지)
            logger.error(
                "LoyverseRelay.relay_order HTTP error %s for tenant %s: %s",
                exc.response.status_code,
                tenant_id,
                exc,
            )

        return {
            "relay_id": relay_id,
            "loyverse_receipt_id": None,  # Filled asynchronously after Loyverse confirms (Loyverse 확인 후 비동기 업데이트)
            "queued_at": queued_at,
        }
