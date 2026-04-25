# Schemas for Slot Filler skill — enums, slot maps, and result model
# (슬롯 필러 스킬 스키마 — 열거형, 슬롯 맵, 결과 모델)

from enum import Enum

from pydantic import BaseModel


class Intent(str, Enum):
    # Supported dialog intents mapped to POS_TOOLS in legacy gemini.js
    # (레거시 gemini.js의 POS_TOOLS에 매핑된 지원 다이얼로그 의도)
    RESERVATION = "reservation"
    ORDER = "order"


# Ordered slot maps — insertion order determines prompt sequence
# (순서 보장 슬롯 맵 — 삽입 순서가 프롬프트 순서를 결정함)
RESERVATION_SLOTS: dict[str, str] = {
    "customer_name": "Could you please share your name?",
    "customer_phone": "What's the best phone number to reach you?",
    "customer_email": "And your email address?",
    "reservation_date": "What date would you like to reserve? (YYYY-MM-DD)",
    "reservation_time": "What time? (HH:MM, 24-hour format)",
    "party_size": "How many guests will be joining?",
}

ORDER_SLOTS: dict[str, str] = {
    "customer_name": "Could you please share your name?",
    "customer_phone": "What's the best phone number to reach you?",
    "customer_email": "And your email address?",
    "items": "What items would you like to order?",
    "user_explicit_confirmation": "Can you confirm your order with a clear 'Yes'?",
}


class SlotCheckResult(BaseModel):
    # Result of slot completeness check for a given intent
    # (특정 의도에 대한 슬롯 완성도 확인 결과)
    missing: list[str]
    next_prompt: str | None
    complete: bool
