# CRM — phone-keyed customer recognition (Layer 2: Universal Shared Skill)
# (CRM — 전화번호 기반 고객 인식, Layer 2 공용 스킬)

from app.services.crm.customer_lookup import (
    CustomerContext,
    customer_lookup,
    redact_email,
    redact_phone,
)

__all__ = [
    "CustomerContext",
    "customer_lookup",
    "redact_email",
    "redact_phone",
]
