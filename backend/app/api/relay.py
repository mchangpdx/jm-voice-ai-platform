# Relay Bridge API router — Layer 4 Fire-and-Forget external bridges
# (릴레이 브리지 API 라우터 — Layer 4 Fire-and-Forget 외부 브리지)

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.adapters.loyverse.loyverse_relay import LoyverseRelay
from app.adapters.relay.fire_and_forget import fire_and_forget
from app.adapters.solink.solink_relay import SolinkRelay
from app.core.auth import get_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/api/relay", tags=["Relay Bridge"])


# ── Request/Response Schemas ─────────────────────────────────────────────────


class SolinkEventPayload(BaseModel):
    """Solink CCTV security event payload (Solink CCTV 보안 이벤트 페이로드)."""

    event_type: str = Field(
        ...,
        description="Security event type (보안 이벤트 유형)",
        pattern="^(motion_detected|door_open|door_close|alarm_triggered)$",
    )
    camera_id: str = Field(..., description="Unique camera identifier (카메라 고유 식별자)")
    location: str = Field(..., description="Physical location label (물리적 위치 레이블)")
    timestamp: str = Field(..., description="ISO 8601 event timestamp (ISO 8601 이벤트 타임스탬프)")
    metadata: Optional[dict] = Field(default=None, description="Optional event metadata (선택적 이벤트 메타데이터)")


class RelayAck(BaseModel):
    """Acknowledgement response for Fire-and-Forget relay operations.
    (Fire-and-Forget 릴레이 작업에 대한 확인 응답)
    """

    accepted: bool = Field(..., description="Whether the relay was accepted (릴레이 수락 여부)")
    relay_id: str = Field(..., description="Server-generated UUID for this relay job (서버 생성 릴레이 UUID)")
    queued_at: str = Field(..., description="ISO 8601 timestamp when job was queued (작업 큐 등록 시각)")


class LoyverseOrderItem(BaseModel):
    """Single line item in a Loyverse order (Loyverse 주문의 단일 항목)."""

    variant_id: str = Field(..., description="Loyverse variant UUID (Loyverse 상품 변형 UUID)")
    quantity: int = Field(..., ge=1, description="Quantity ordered — minimum 1 (최소 주문 수량 1)")


class LoyverseOrderPayload(BaseModel):
    """Loyverse POS order payload (Loyverse POS 주문 페이로드)."""

    items: List[LoyverseOrderItem] = Field(..., description="List of order items (주문 항목 목록)")
    table_number: Optional[str] = Field(default=None, description="Optional table number (선택적 테이블 번호)")
    note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional order note — max 500 chars (선택적 주문 메모 — 최대 500자)",
    )


class LoyverseOrderAck(BaseModel):
    """Acknowledgement response for Loyverse order relay (Loyverse 주문 릴레이 확인 응답)."""

    accepted: bool = Field(..., description="Whether the order relay was accepted (주문 릴레이 수락 여부)")
    relay_id: str = Field(..., description="Server-generated UUID for this relay job (서버 생성 릴레이 UUID)")
    loyverse_receipt_id: Optional[str] = Field(
        default=None,
        description="Loyverse receipt ID — null until async relay completes (비동기 릴레이 완료 전까지 null)",
    )
    queued_at: str = Field(..., description="ISO 8601 timestamp when job was queued (작업 큐 등록 시각)")


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/solink/event", status_code=202, response_model=RelayAck)
async def relay_solink_event(
    payload: SolinkEventPayload,
    tenant_id: str = Depends(get_tenant_id),
) -> RelayAck:
    """Forward a Solink security event asynchronously (Fire-and-Forget).
    Generates relay_id first, returns 202 immediately, then fires actual relay in background.
    (Solink 보안 이벤트를 비동기적으로 전달. relay_id를 먼저 생성하고 즉시 202 반환 후 백그라운드에서 릴레이)
    """
    # Generate relay_id and queued_at upfront — included in 202 response
    # (relay_id와 queued_at을 먼저 생성 — 202 응답에 포함)
    relay_id = str(uuid.uuid4())
    queued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    relay = SolinkRelay(
        api_url=settings.solink_api_url,
        api_key=settings.solink_api_key,
        timeout=settings.relay_timeout_seconds,
    )

    # Fire the actual HTTP relay call in background — non-blocking
    # (실제 HTTP 릴레이 호출을 백그라운드에서 실행 — 비차단)
    await fire_and_forget(relay.relay_event(payload.model_dump(), tenant_id))

    # Return immediately — relay is in background (즉시 반환 — 릴레이는 백그라운드 처리)
    return RelayAck(accepted=True, relay_id=relay_id, queued_at=queued_at)


@router.post("/loyverse/order", status_code=202, response_model=LoyverseOrderAck)
async def relay_loyverse_order(
    payload: LoyverseOrderPayload,
    tenant_id: str = Depends(get_tenant_id),
) -> LoyverseOrderAck:
    """Submit an order to Loyverse POS asynchronously (Fire-and-Forget).
    Generates relay_id first, returns 202 immediately, then fires actual relay in background.
    (주문을 Loyverse POS에 비동기적으로 전달. relay_id를 먼저 생성하고 즉시 202 반환 후 백그라운드에서 릴레이)
    """
    # Generate relay_id and queued_at upfront — included in 202 response
    # (relay_id와 queued_at을 먼저 생성 — 202 응답에 포함)
    relay_id = str(uuid.uuid4())
    queued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    relay = LoyverseRelay(
        api_url=settings.loyverse_api_url,
        api_key=settings.loyverse_api_key,
        timeout=settings.relay_timeout_seconds,
    )

    # Serialize items to dicts for JSON transport (항목을 JSON 전송용 딕셔너리로 직렬화)
    order_data = payload.model_dump()

    # Fire the actual HTTP relay call in background — non-blocking
    # (실제 HTTP 릴레이 호출을 백그라운드에서 실행 — 비차단)
    await fire_and_forget(relay.relay_order(order_data, tenant_id))

    # Return immediately — loyverse_receipt_id is None until async relay completes
    # (즉시 반환 — loyverse_receipt_id는 비동기 릴레이 완료 전까지 None)
    return LoyverseOrderAck(
        accepted=True,
        relay_id=relay_id,
        loyverse_receipt_id=None,
        queued_at=queued_at,
    )
