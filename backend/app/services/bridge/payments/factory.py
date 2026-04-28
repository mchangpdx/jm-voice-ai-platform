# Bridge Server — Payment Adapter factory
# (Bridge Server — 결제 어댑터 팩토리)
#
# Selects the correct adapter at runtime based on environment configuration.
# Default: NoOp (zero-config, safe). Once Maverick is enabled in .env, the
# factory swaps to MaverickPaymentAdapter without any caller-side changes.

from __future__ import annotations

from app.core.config import settings
from app.services.bridge.payments.base import PaymentAdapter
from app.services.bridge.payments.noop import NoOpPaymentAdapter
from app.services.bridge.payments.maverick import MaverickPaymentAdapter


def get_payment_adapter() -> PaymentAdapter:
    """Return the currently-configured payment adapter.
    (현재 환경 설정에 맞는 결제 어댑터 반환)

    Selection logic:
      - settings.maverick_enabled is True AND maverick_api_key set → Maverick
      - otherwise                                                    → NoOp
    """
    if getattr(settings, "maverick_enabled", False) and getattr(settings, "maverick_api_key", ""):
        return MaverickPaymentAdapter()
    return NoOpPaymentAdapter()
