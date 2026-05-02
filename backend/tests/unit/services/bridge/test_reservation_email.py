# Reservation email composer + dispatcher TDD
# (예약 확정 이메일 작성기 + 발송기 테스트 — TCR 펜딩 동안 fallback 채널)
#
# Modeled after pay_link_email tests but with reservation-specific shape:
#   - No items table, no total — reservation summary card instead
#   - Indigo + amber color tone (vs orders' slate + green) for visual distinction
#   - send_reservation_email shape mirrors send_pay_link_email
#
# Tests written BEFORE implementation. Red until reservation_email.py lands.

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_send_reservation_email_skips_when_no_recipient():
    """Empty 'to' must short-circuit before touching SMTP."""
    from app.services.bridge import reservation_email

    fake_send = AsyncMock()
    with patch.object(reservation_email, "send_html_email", new=fake_send):
        result = await reservation_email.send_reservation_email(
            to            = "",
            customer_name = "Aaron Chang",
            store_name    = "JM Cafe",
            party_size    = 4,
            date_human    = "Friday, May 8",
            time_12h      = "7:30 PM",
            reservation_id= 252,
        )
    assert result["sent"] is False
    assert result.get("skipped") is True
    fake_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_reservation_email_dispatches_via_smtp_adapter():
    """Happy path — composes subject + html + plain, hands off to send_html_email."""
    from app.services.bridge import reservation_email

    fake_send = AsyncMock(return_value={"sent": True, "result": "ok"})
    with patch.object(reservation_email, "send_html_email", new=fake_send):
        result = await reservation_email.send_reservation_email(
            to            = "aaron@example.com",
            customer_name = "Aaron Chang",
            store_name    = "JM Cafe",
            party_size    = 4,
            date_human    = "Friday, May 8",
            time_12h      = "7:30 PM",
            reservation_id= 252,
            notes         = "window seat please",
        )
    assert result["sent"] is True
    fake_send.assert_awaited_once()
    call_kwargs = fake_send.await_args.kwargs
    assert call_kwargs["to"] == "aaron@example.com"
    # Subject prefixes with store + indicates a reservation (not an order)
    assert "JM Cafe" in call_kwargs["subject"]
    assert "Reservation" in call_kwargs["subject"]
    # Plain text fallback present
    assert isinstance(call_kwargs.get("plain"), str)
    assert len(call_kwargs["plain"]) > 0


def test_compose_reservation_email_html_includes_summary_fields():
    """HTML body must include party / date / time / customer name / store name."""
    from app.services.bridge.reservation_email import compose_reservation_email_html

    html = compose_reservation_email_html(
        customer_name = "Aaron Chang",
        store_name    = "JM Cafe",
        party_size    = 4,
        date_human    = "Friday, May 8",
        time_12h      = "7:30 PM",
        notes         = "window seat please",
        reservation_id= 252,
    )
    assert "Aaron Chang" in html
    assert "JM Cafe" in html
    assert "party of 4" in html.lower() or "Party of 4" in html
    assert "Friday, May 8" in html
    assert "7:30 PM" in html
    assert "window seat please" in html


def test_compose_reservation_email_html_uses_indigo_amber_tone():
    """Reservation email must use the indigo + amber tone, NOT the order
    email's slate + green tone — visual distinction for customers who get
    both kinds. Sentinel hex codes anchor the design choice."""
    from app.services.bridge.reservation_email import compose_reservation_email_html

    html = compose_reservation_email_html(
        customer_name = "Aaron Chang",
        store_name    = "JM Cafe",
        party_size    = 2,
        date_human    = "Sunday, May 3",
        time_12h      = "6:00 PM",
        notes         = "",
        reservation_id= 999,
    )
    # Indigo hero (deep indigo gradient) — sentinel #312e81
    assert "#312e81" in html or "#4338ca" in html
    # Amber accent (welcome / calendar tone) — sentinel #d97706
    assert "#d97706" in html or "#f59e0b" in html
    # Make sure we did NOT accidentally render the order palette
    assert "#16a34a" not in html       # order CTA green
    assert "#86efac" not in html       # order hero eyebrow green


def test_compose_reservation_email_html_omits_notes_section_when_empty():
    """Notes is optional — empty string should not produce a stray label."""
    from app.services.bridge.reservation_email import compose_reservation_email_html

    html = compose_reservation_email_html(
        customer_name = "Aaron Chang",
        store_name    = "JM Cafe",
        party_size    = 2,
        date_human    = "Sunday, May 3",
        time_12h      = "6:00 PM",
        notes         = "",
        reservation_id= 999,
    )
    # No "Special requests" label should appear when notes is empty
    assert "Special requests" not in html
    assert "Notes:" not in html


def test_compose_reservation_email_text_is_plain_and_complete():
    """Plain-text alternative must include the key facts in a single paragraph
    + the reservation id for support reference."""
    from app.services.bridge.reservation_email import compose_reservation_email_text

    plain = compose_reservation_email_text(
        customer_name = "Aaron Chang",
        store_name    = "JM Cafe",
        party_size    = 4,
        date_human    = "Friday, May 8",
        time_12h      = "7:30 PM",
        reservation_id= 252,
    )
    assert "Aaron Chang" in plain
    assert "JM Cafe" in plain
    assert "party of 4" in plain.lower() or "Party of 4" in plain
    assert "Friday, May 8" in plain
    assert "7:30 PM" in plain
    # No HTML leaked
    assert "<" not in plain and ">" not in plain
