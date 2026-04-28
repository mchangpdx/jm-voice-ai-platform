# Bridge Server — Maverick Payment Adapter (PLACEHOLDER until spec arrives)
# (Bridge Server — Maverick 결제 어댑터: 스펙 도착 전까지 PLACEHOLDER)
#
# Future implementation (after Maverick spec):
#   - create_session: POST /hpp/sessions to Maverick → return pay_url + session_id
#   - verify_webhook: HMAC-SHA256(merchant_secret, raw_body) — uses
#     bridge.webhook_signature.verify_maverick_signature for the actual check
#
# Today this class exists ONLY to make the factory pattern type-check and to
# fail loudly if anyone wires it before the spec lands. NotImplementedError on
# create_session is intentional.

from __future__ import annotations

from typing import Any, Optional

from app.core.config import settings
from app.services.bridge.payments.base import PaymentAdapter
from app.services.bridge.webhook_signature import verify_maverick_signature


class MaverickPaymentAdapter(PaymentAdapter):
    """Maverick HPP gateway adapter. NOT YET IMPLEMENTED — awaits official spec.
    (Maverick HPP gateway 어댑터 — 공식 스펙 도착 전까지 미구현)
    """

    def is_enabled(self) -> bool:
        # Once we have keys + spec, return True
        return bool(getattr(settings, "maverick_api_key", "")) and \
               bool(getattr(settings, "maverick_enabled", False))

    async def create_session(
        self,
        *,
        amount_cents:   int,
        transaction_id: str,
        purpose:        str,
        return_url:     Optional[str] = None,
        webhook_url:    Optional[str] = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "MaverickPaymentAdapter.create_session: awaiting official Maverick API spec. "
            "Until the spec arrives, the factory should return NoOpPaymentAdapter."
        )

    def verify_webhook(self, *, raw_body: bytes, signature: Optional[str]) -> bool:
        secret = getattr(settings, "maverick_webhook_secret", "")
        return verify_maverick_signature(raw_body, signature, secret)
