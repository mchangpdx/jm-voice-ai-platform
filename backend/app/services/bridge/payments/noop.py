# Bridge Server — NoOp Payment Adapter
# (Bridge Server — NoOp 결제 어댑터)
#
# Used today (no real gateway configured) and for any free transaction
# (e.g. a reservation that doesn't require a deposit).
#
# Behavior:
#   amount_cents == 0  → returns {paid: True, ...} → caller marks transaction paid immediately
#   amount_cents > 0   → returns {paid: False, reason: no_payment_gateway_configured}
#                        → caller must handle (typically: log + mark transaction failed
#                        or fall back to manual handling)

from __future__ import annotations

import secrets
from typing import Any, Optional

from app.services.bridge.payments.base import PaymentAdapter


class NoOpPaymentAdapter(PaymentAdapter):
    """No-op adapter — supports zero-amount transactions only.
    (NoOp 어댑터 — 0원 트랜잭션만 지원)
    """

    def is_enabled(self) -> bool:
        return False

    async def create_session(
        self,
        *,
        amount_cents:   int,
        transaction_id: str,
        purpose:        str,
        return_url:     Optional[str] = None,
        webhook_url:    Optional[str] = None,
    ) -> dict[str, Any]:
        if amount_cents == 0:
            return {
                "paid":         True,
                "pay_url":      None,
                "session_id":   f"noop_{secrets.token_hex(8)}",
                "amount_cents": 0,
            }
        return {
            "paid":         False,
            "pay_url":      None,
            "session_id":   None,
            "amount_cents": amount_cents,
            "reason":       "no_payment_gateway_configured",
        }

    def verify_webhook(self, *, raw_body: bytes, signature: Optional[str]) -> bool:
        # NoOp gateway never sends webhooks; verifying any payload would be a
        # security violation (someone is forging webhook traffic against us).
        return False
