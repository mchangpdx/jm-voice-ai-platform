# Phase 2-B.1.10 — SMS pay link composer + dispatcher
# (Phase 2-B.1.10 — SMS 결제 링크 작성 + 발송)
#
# Lane-aware copy: fire_immediate reassures the customer that the kitchen
# already has the order; pay_first makes clear payment must complete for
# the order to start. Same Twilio adapter the reservation flow uses.
#
# Design (mirrors send_reservation_confirmation):
#   - Fire-and-forget: SMS failure must NOT block the voice path.
#   - send_pay_link does NOT wrap itself in asyncio.create_task — the caller
#     decides when the task is detached so the unit test can await it.

from __future__ import annotations

import logging
from typing import Any

from app.adapters.twilio.sms import send_sms
from app.core.config import settings

log = logging.getLogger(__name__)


def build_pay_link(transaction_id: str, *, base_url: str = "") -> str:
    """Absolute URL the customer taps to settle the bridge transaction.
    (고객이 탭할 결제 링크 절대 URL)

    base_url falls back to settings.public_base_url. Trailing slash on the
    base is stripped so the path concatenation is deterministic.
    """
    base = (base_url or settings.public_base_url).rstrip("/")
    return f"{base}/api/payment/mock/{transaction_id}"


def compose_pay_link_message(
    *,
    store_name:  str,
    total_cents: int,
    link:        str,
    lane:        str,
) -> str:
    """Customer-facing SMS body. Lane-aware phrasing.
    (lane별 문구 — fire_immediate는 안심, pay_first는 결제 우선 강조)
    """
    dollars = f"${total_cents / 100:.2f}"

    if lane == "fire_immediate":
        return (
            f"{store_name}: Thanks! Your order ({dollars}) is in the kitchen. "
            f"Tap to pay before pickup or pay at the counter: {link}"
        )

    # pay_first (default — also used when lane is missing or unknown)
    return (
        f"{store_name}: Tap to pay {dollars} and we'll start your order: {link}"
    )


async def send_pay_link(
    *,
    to:              str,
    store_name:      str,
    total_cents:     int,
    transaction_id:  str,
    lane:            str,
) -> dict[str, Any]:
    """High-level: build link + compose body + send via Twilio.
    (고수준 통합 — 링크 + 본문 + Twilio 전송)

    Skips cleanly when no phone number is given. Returns the same shape as
    send_sms so callers can log the result uniformly.
    """
    if not to:
        return {"sent": False, "reason": "no_phone"}

    link = build_pay_link(transaction_id)
    body = compose_pay_link_message(
        store_name  = store_name,
        total_cents = total_cents,
        link        = link,
        lane        = lane,
    )
    return await send_sms(to=to, body=body)
