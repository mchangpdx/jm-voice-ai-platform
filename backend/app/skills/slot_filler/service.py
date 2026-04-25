# Slot Filler service — identifies missing slots and returns next voice prompt
# (슬롯 필러 서비스 — 누락된 슬롯을 식별하고 다음 음성 프롬프트 반환)

from app.skills.slot_filler.schemas import (
    ORDER_SLOTS,
    RESERVATION_SLOTS,
    Intent,
    SlotCheckResult,
)

# Map each intent to its ordered slot definition (의도별 슬롯 맵 연결)
_SLOT_MAP: dict[Intent, dict[str, str]] = {
    Intent.RESERVATION: RESERVATION_SLOTS,
    Intent.ORDER: ORDER_SLOTS,
}


def check_slots(intent: Intent, collected: dict) -> SlotCheckResult:
    # Identify which required slots are missing and determine the next prompt
    # (누락된 필수 슬롯을 확인하고 다음 프롬프트 결정)
    slots = _SLOT_MAP[intent]

    # A slot is considered filled when its key is present with a truthy value
    # (키가 존재하고 참 값을 가질 때 슬롯이 채워진 것으로 간주)
    missing = [key for key in slots if not collected.get(key)]

    return SlotCheckResult(
        missing=missing,
        next_prompt=next_prompt(missing, slots),
        complete=len(missing) == 0,
    )


def next_prompt(missing: list[str], slots: dict[str, str] | None = None) -> str | None:
    # Return the prompt for the first missing slot, or None if list is empty
    # (첫 번째 누락 슬롯의 프롬프트 반환, 리스트가 비어 있으면 None 반환)
    if not missing:
        return None
    if slots is None:
        return None
    return slots.get(missing[0])
