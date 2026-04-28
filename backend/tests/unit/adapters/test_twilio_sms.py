# Twilio SMS adapter — TDD tests
# (Twilio SMS 어댑터 TDD 테스트)

import pytest
from unittest.mock import AsyncMock, patch


# ── Message composition (pure, no I/O) ────────────────────────────────────────

def test_compose_reservation_message_includes_all_fields():
    from app.adapters.twilio.sms import compose_reservation_message
    msg = compose_reservation_message(
        store_name="JM Cafe",
        customer_name="Michael Chang",
        date_human="Tuesday, April 28",
        time_12h="7:00 PM",
        party_size=4,
    )
    assert "JM Cafe" in msg
    # First-name-only is intentional UX — short, friendlier in SMS register
    assert "Michael" in msg
    assert "Tuesday, April 28" in msg
    assert "7:00 PM" in msg
    assert "4" in msg


def test_compose_reservation_message_under_160_chars_when_possible():
    """Single SMS segment is 160 chars. Short stores stay under that."""
    from app.adapters.twilio.sms import compose_reservation_message
    msg = compose_reservation_message(
        store_name="JM Cafe",
        customer_name="Mike",
        date_human="Tue Apr 28",
        time_12h="7 PM",
        party_size=2,
    )
    assert len(msg) <= 160


# ── send_sms (mocked Twilio REST API) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_sms_skips_silently_when_no_credentials():
    """No credentials = development env. Must not raise, must not send."""
    from app.adapters.twilio import sms

    with patch.object(sms, "_TWILIO_SID", ""), \
         patch.object(sms, "_TWILIO_TOKEN", ""), \
         patch.object(sms, "_TWILIO_FROM", ""), \
         patch("app.adapters.twilio.sms.httpx.AsyncClient") as MockClient:

        result = await sms.send_sms(to="+15037079566", body="hi")

        assert result["sent"] is False
        assert result["reason"] == "twilio_not_configured"
        MockClient.assert_not_called()


@pytest.mark.asyncio
async def test_send_sms_posts_to_twilio_with_correct_payload():
    from app.adapters.twilio import sms

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: {"sid": "SMabc123", "status": "queued"}

    with patch.object(sms, "_TWILIO_SID",   "ACtest123"), \
         patch.object(sms, "_TWILIO_TOKEN", "tok_test"), \
         patch.object(sms, "_TWILIO_FROM",  "+15555550100"), \
         patch("app.adapters.twilio.sms.httpx.AsyncClient") as MockClient:

        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        result = await sms.send_sms(to="+15037079566", body="Reservation confirmed")

        assert result["sent"] is True
        assert result["sid"] == "SMabc123"

        url = instance.post.call_args.args[0]
        assert "ACtest123" in url and "Messages.json" in url

        data = instance.post.call_args.kwargs["data"]
        assert data["To"]   == "+15037079566"
        assert data["From"] == "+15555550100"
        assert data["Body"] == "Reservation confirmed"


@pytest.mark.asyncio
async def test_send_sms_returns_failure_on_twilio_error():
    from app.adapters.twilio import sms

    fake_resp = AsyncMock()
    fake_resp.status_code = 400
    fake_resp.text = '{"code":21211,"message":"Invalid To phone"}'

    with patch.object(sms, "_TWILIO_SID",   "ACtest"), \
         patch.object(sms, "_TWILIO_TOKEN", "tok"), \
         patch.object(sms, "_TWILIO_FROM",  "+15555550100"), \
         patch("app.adapters.twilio.sms.httpx.AsyncClient") as MockClient:

        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        result = await sms.send_sms(to="+1bad", body="x")

        assert result["sent"] is False
        assert "21211" in result.get("error", "") or "400" in result.get("error", "")


@pytest.mark.asyncio
async def test_send_sms_uses_basic_auth_with_sid_and_token():
    from app.adapters.twilio import sms

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: {"sid": "SM1", "status": "queued"}

    with patch.object(sms, "_TWILIO_SID",   "ACtest"), \
         patch.object(sms, "_TWILIO_TOKEN", "tok_secret"), \
         patch.object(sms, "_TWILIO_FROM",  "+15555550100"), \
         patch("app.adapters.twilio.sms.httpx.AsyncClient") as MockClient:

        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        await sms.send_sms(to="+1503", body="x")

        # Twilio auth via httpx auth=(sid, token)
        auth_arg = instance.post.call_args.kwargs.get("auth")
        assert auth_arg == ("ACtest", "tok_secret")


# ── send_reservation_confirmation (high-level, fire-and-forget) ──────────────

@pytest.mark.asyncio
async def test_send_reservation_confirmation_skips_when_no_phone():
    from app.adapters.twilio.sms import send_reservation_confirmation

    result = await send_reservation_confirmation(
        to="",
        store_name="JM Cafe",
        customer_name="Michael",
        date_human="Tue Apr 28",
        time_12h="7 PM",
        party_size=4,
    )
    assert result["sent"] is False
    assert result["reason"] == "no_phone"


@pytest.mark.asyncio
async def test_send_reservation_confirmation_calls_send_sms_with_composed_body():
    from app.adapters.twilio import sms as sms_mod

    with patch.object(sms_mod, "send_sms", new=AsyncMock(return_value={"sent": True, "sid": "SM1"})) as m:
        result = await sms_mod.send_reservation_confirmation(
            to="+15037079566",
            store_name="JM Cafe",
            customer_name="Michael Chang",
            date_human="Tuesday, April 28",
            time_12h="7:00 PM",
            party_size=4,
        )

    assert result["sent"] is True
    body = m.call_args.kwargs["body"]
    assert "JM Cafe" in body
    assert "7:00 PM" in body
