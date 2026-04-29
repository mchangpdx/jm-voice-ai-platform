# Phase 2-B.1.10 — SMS pay link composer + dispatcher TDD
# (Phase 2-B.1.10 — SMS 결제 링크 작성 + 발송 TDD)
#
# compose_pay_link_message(store_name, total_cents, link, lane) returns
# the customer-facing SMS body. Lane-aware so fire_immediate sounds
# different from pay_first.
#
# build_pay_link(transaction_id, base_url) returns the absolute URL the
# customer taps. Uses settings.public_base_url by default.
#
# send_pay_link(to, store_name, total_cents, transaction_id, lane) is the
# fire-and-forget high-level API the create_order tool handler calls.

import pytest
from unittest.mock import AsyncMock, patch


def test_build_pay_link_includes_tx_id_in_path():
    from app.services.bridge.pay_link_sms import build_pay_link
    url = build_pay_link("abc-123", base_url="https://example.com")
    assert url == "https://example.com/api/payment/mock/abc-123"


def test_build_pay_link_strips_trailing_slash_on_base():
    from app.services.bridge.pay_link_sms import build_pay_link
    url = build_pay_link("abc-123", base_url="https://example.com/")
    assert url == "https://example.com/api/payment/mock/abc-123"


def test_compose_message_fire_immediate_says_in_kitchen():
    """fire_immediate copy reassures the customer that the order is already
    being made; pay link is for convenience.
    (fire_immediate: 이미 키친에 들어갔다고 안심시킴)
    """
    from app.services.bridge.pay_link_sms import compose_pay_link_message
    body = compose_pay_link_message(
        store_name="JM Cafe", total_cents=900,
        link="https://x.test/api/payment/mock/abc",
        lane="fire_immediate",
    )
    assert "JM Cafe" in body
    assert "$9.00"   in body
    assert "https://x.test/api/payment/mock/abc" in body
    assert "kitchen" in body.lower()


def test_compose_message_pay_first_asks_for_payment_first():
    """pay_first copy makes clear payment must happen for the order to start.
    (pay_first: 결제해야 주문 시작됨을 명시)
    """
    from app.services.bridge.pay_link_sms import compose_pay_link_message
    body = compose_pay_link_message(
        store_name="JM Cafe", total_cents=2500,
        link="https://x.test/api/payment/mock/abc",
        lane="pay_first",
    )
    assert "$25.00" in body
    assert "https://x.test/api/payment/mock/abc" in body
    # Either "tap" or "pay" wording — not both required, but at least one
    assert ("tap" in body.lower()) or ("pay" in body.lower())


@pytest.mark.asyncio
async def test_send_pay_link_calls_send_sms_with_composed_body():
    """High-level send: composes URL + body and delegates to send_sms.
    (고수준 send_pay_link: URL+본문 조합 후 send_sms 위임)
    """
    from app.services.bridge import pay_link_sms as mod

    captured: dict = {}

    async def fake_send_sms(*, to, body):
        captured["to"]   = to
        captured["body"] = body
        return {"sent": True, "sid": "SMxxx"}

    with patch.object(mod, "send_sms", new=AsyncMock(side_effect=fake_send_sms)), \
         patch.object(mod.settings, "public_base_url", "https://x.test"):

        result = await mod.send_pay_link(
            to              = "+15035550100",
            store_name      = "JM Cafe",
            total_cents     = 1200,
            transaction_id  = "tx-77",
            lane            = "fire_immediate",
        )

    assert result["sent"] is True
    assert captured["to"] == "+15035550100"
    assert "https://x.test/api/payment/mock/tx-77" in captured["body"]
    assert "JM Cafe" in captured["body"]
    assert "$12.00"  in captured["body"]


@pytest.mark.asyncio
async def test_send_pay_link_skips_when_phone_missing():
    """No phone ⇒ skip cleanly with a structured reason.
    (전화번호 없으면 우아하게 스킵)
    """
    from app.services.bridge.pay_link_sms import send_pay_link

    result = await send_pay_link(
        to="", store_name="X", total_cents=100,
        transaction_id="t", lane="pay_first",
    )
    assert result["sent"] is False
    assert result["reason"] == "no_phone"
