# Phase 2-B.1.10b — Pay link email TDD
# (Phase 2-B.1.10b — 결제 링크 이메일 TDD)

import pytest
from unittest.mock import AsyncMock, patch


# ── HTML composition ─────────────────────────────────────────────────────────

def test_compose_html_includes_link_and_total():
    from app.services.bridge.pay_link_email import compose_pay_link_email_html
    html = compose_pay_link_email_html(
        customer_name="Michael",
        store_name="JM Cafe",
        total_cents=1850,
        items=[{"name": "Latte", "quantity": 2, "price": 4.50}],
        pay_link="https://x.test/api/payment/mock/abc-123",
        lane="fire_immediate",
    )
    assert "https://x.test/api/payment/mock/abc-123" in html
    assert "$18.50" in html or "18.50" in html
    assert "Michael" in html
    assert "JM Cafe" in html


def test_compose_html_lane_aware_copy_fire_immediate():
    """fire_immediate copy reassures customer the kitchen is already cooking.
    (fire_immediate 메시지 — 키친에서 이미 조리 중임을 안심)
    """
    from app.services.bridge.pay_link_email import compose_pay_link_email_html
    html = compose_pay_link_email_html(
        customer_name="x", store_name="s", total_cents=900,
        items=[], pay_link="L", lane="fire_immediate",
    )
    assert "kitchen" in html.lower()
    assert "Pay Now" in html


def test_compose_html_lane_aware_copy_pay_first():
    """pay_first copy makes payment-then-cooking ordering explicit.
    (pay_first 메시지 — 결제 후 조리 시작 명시)
    """
    from app.services.bridge.pay_link_email import compose_pay_link_email_html
    html = compose_pay_link_email_html(
        customer_name="x", store_name="s", total_cents=900,
        items=[], pay_link="L", lane="pay_first",
    )
    assert "payment" in html.lower()
    assert "Pay & Place Order" in html


def test_compose_html_includes_responsive_media_query():
    """Mobile breakpoint must be present so iOS / Android Mail renders the
    stacked card layout. (모바일 미디어 쿼리 존재)
    """
    from app.services.bridge.pay_link_email import compose_pay_link_email_html
    html = compose_pay_link_email_html(
        customer_name="x", store_name="s", total_cents=0,
        items=[], pay_link="L", lane="pay_first",
    )
    assert "@media" in html and "max-width: 480px" in html


def test_compose_html_renders_each_item_row():
    from app.services.bridge.pay_link_email import compose_pay_link_email_html
    html = compose_pay_link_email_html(
        customer_name="x", store_name="s", total_cents=2500,
        items=[
            {"name": "Latte",  "quantity": 2, "price": 4.50},
            {"name": "Bagel",  "quantity": 1, "price": 7.00},
        ],
        pay_link="L", lane="pay_first",
    )
    assert "Latte" in html and "Bagel" in html
    assert "$9.00" in html or "9.00" in html        # 2 × 4.50 line subtotal
    assert "$7.00" in html or "7.00" in html


def test_compose_text_fallback_carries_link():
    from app.services.bridge.pay_link_email import compose_pay_link_email_text
    txt = compose_pay_link_email_text(
        customer_name="Michael", store_name="JM Cafe",
        total_cents=1200, pay_link="https://x.test/p/abc", lane="fire_immediate",
    )
    assert "https://x.test/p/abc" in txt
    assert "Michael" in txt
    assert "$12.00" in txt


# ── send_pay_link_email ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_pay_link_email_skips_when_no_recipient():
    from app.services.bridge.pay_link_email import send_pay_link_email
    result = await send_pay_link_email(
        to="", customer_name="x", store_name="s",
        total_cents=100, items=[], transaction_id="t", lane="pay_first",
    )
    assert result["sent"] is False
    assert result["reason"] == "no_recipient"


@pytest.mark.asyncio
async def test_send_pay_link_email_calls_smtp_send():
    """High-level wires composer to SMTP send.
    (composer + send_html_email 위임 검증)
    """
    from app.services.bridge import pay_link_email as mod

    captured: dict = {}

    async def fake_send(*, to, subject, html, plain):
        captured["to"]      = to
        captured["subject"] = subject
        captured["html"]    = html
        captured["plain"]   = plain
        return {"sent": True}

    with patch.object(mod, "send_html_email", new=AsyncMock(side_effect=fake_send)):
        result = await mod.send_pay_link_email(
            to              = "user@example.com",
            customer_name   = "Michael",
            store_name      = "JM Cafe",
            total_cents     = 1500,
            items           = [{"name": "Latte", "quantity": 1, "price": 15.00}],
            transaction_id  = "tx-1",
            lane            = "fire_immediate",
        )

    assert result["sent"] is True
    assert captured["to"] == "user@example.com"
    assert "JM Cafe" in captured["subject"]
    assert "$15.00" in captured["subject"]
    assert "tx-1"   in captured["html"]
    assert "tx-1"   in captured["plain"]


# ── SMTP adapter behaviour ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_smtp_adapter_skips_when_unconfigured():
    """Missing SMTP creds ⇒ skip with reason='smtp_not_configured'. Critical
    so dev / CI environments don't crash. (SMTP 미설정 시 graceful skip)
    """
    from app.adapters.email import smtp as mod

    with patch.object(mod.settings, "smtp_host", ""), \
         patch.object(mod.settings, "smtp_user", ""), \
         patch.object(mod.settings, "smtp_pass", ""):
        result = await mod.send_html_email(
            to="user@example.com", subject="x", html="<p>x</p>",
        )
    assert result["sent"] is False
    assert result["reason"] == "smtp_not_configured"


@pytest.mark.asyncio
async def test_smtp_adapter_returns_error_dict_on_exception():
    """SMTP failure must NOT raise — caller is fire-and-forget.
    (SMTP 실패 시 raise 금지 — 호출자 fire-and-forget)
    """
    from app.adapters.email import smtp as mod

    with patch.object(mod.settings, "smtp_host", "smtp.test"), \
         patch.object(mod.settings, "smtp_user", "u"), \
         patch.object(mod.settings, "smtp_pass", "p"), \
         patch.object(mod.aiosmtplib, "send",
                      new=AsyncMock(side_effect=RuntimeError("server down"))):
        result = await mod.send_html_email(
            to="user@example.com", subject="x", html="<p>x</p>",
        )
    assert result["sent"] is False
    assert "server down" in result["error"]
