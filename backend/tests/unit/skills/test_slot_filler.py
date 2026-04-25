# Tests for Slot Filler skill — Layer 2 Universal Shared Skill
# (슬롯 필러 스킬 테스트 — Layer 2 범용 공유 스킬)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import pytest

from app.skills.slot_filler.schemas import Intent
from app.skills.slot_filler.service import check_slots, next_prompt


def test_check_slots_reservation_all_filled():
    # All 6 reservation fields present → complete=True, no missing, no next_prompt
    # (예약 필드 6개 모두 존재 → complete=True, missing 없음, next_prompt 없음)
    collected = {
        "customer_name": "Alice",
        "customer_phone": "555-1234",
        "customer_email": "alice@example.com",
        "reservation_date": "2026-05-01",
        "reservation_time": "18:30",
        "party_size": 4,
    }
    result = check_slots(Intent.RESERVATION, collected)

    assert result.complete is True
    assert result.missing == []
    assert result.next_prompt is None


def test_check_slots_reservation_missing_fields():
    # Only customer_name given → missing includes customer_phone, next_prompt is phone prompt
    # (customer_name만 제공된 경우 → missing에 customer_phone 포함, next_prompt는 전화번호 요청)
    collected = {"customer_name": "Bob"}
    result = check_slots(Intent.RESERVATION, collected)

    assert result.complete is False
    assert "customer_phone" in result.missing
    assert result.next_prompt == "What's the best phone number to reach you?"


def test_check_slots_empty_collected():
    # Empty dict → complete=False, first prompt asks for name
    # (빈 dict → complete=False, 첫 번째 프롬프트는 이름 요청)
    result = check_slots(Intent.RESERVATION, {})

    assert result.complete is False
    assert result.next_prompt == "Could you please share your name?"


def test_next_prompt_empty_missing_returns_none():
    # next_prompt with empty list → None (모든 슬롯이 채워진 경우 → None 반환)
    result = next_prompt([])

    assert result is None


def test_check_slots_order_requires_confirmation():
    # All order fields except user_explicit_confirmation → complete=False, confirmation missing
    # (user_explicit_confirmation 제외 주문 필드 모두 입력 → complete=False, 확인 필드 누락)
    collected = {
        "customer_name": "Carol",
        "customer_phone": "555-5678",
        "customer_email": "carol@example.com",
        "items": ["burger", "fries"],
    }
    result = check_slots(Intent.ORDER, collected)

    assert result.complete is False
    assert "user_explicit_confirmation" in result.missing
