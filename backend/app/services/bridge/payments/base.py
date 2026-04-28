# Bridge Server — Payment Adapter base interface
# (Bridge Server — 결제 어댑터 베이스 인터페이스)
#
# Concrete adapters today: NoOpPaymentAdapter (free transactions, no gateway)
# Concrete adapters future: MaverickPaymentAdapter (HPP create + webhook verify)
#
# create_session(amount_cents, transaction_id, purpose) is intentionally generic
# enough to absorb any payment model (HPP redirect, embedded, RPC, etc).

from __future__ import annotations

from typing import Any, Optional


class PaymentAdapter:
    """Abstract payment adapter interface.
    (결제 어댑터 추상 인터페이스)
    """

    def is_enabled(self) -> bool:
        """Whether real money can be collected through this adapter.
        (이 어댑터로 실제 결제 가능 여부)
        """
        raise NotImplementedError

    async def create_session(
        self,
        *,
        amount_cents:   int,
        transaction_id: str,
        purpose:        str,                  # 'full'|'deposit'|'balance'|'addon'|'tip'|'estimate'
        return_url:     Optional[str] = None,
        webhook_url:    Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a payment session and return:
            {paid, pay_url, session_id, amount_cents, [reason]}
        - paid=True for amount_cents=0 or instant-charge gateways
        - pay_url is the URL to send to the customer (None if paid=True)
        - session_id is gateway-specific; stored in bridge_payments
        (결제 세션 생성 후 위 형식으로 반환)
        """
        raise NotImplementedError

    def verify_webhook(self, *, raw_body: bytes, signature: Optional[str]) -> bool:
        """Verify the gateway webhook signature on the EXACT raw bytes received.
        (수신된 raw 바이트에 대한 gateway webhook 서명 검증)
        """
        raise NotImplementedError
