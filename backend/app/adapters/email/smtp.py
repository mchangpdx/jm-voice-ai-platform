# Phase 2-B.1.10b — SMTP email adapter (Gmail App Password compatible)
# (Phase 2-B.1.10b — SMTP 이메일 어댑터 — Gmail App Password 호환)
#
# Ports the legacy jm-saas-platform/src/utils/mailer.js pattern to Python.
# Used as a TCR-fallback delivery channel for pay links until Twilio TCR
# approves SMS. Same fire-and-forget shape as Twilio adapter:
#   - Skip silently when SMTP creds are missing (dev safety)
#   - Never raise out to the caller — email failure must not block voice
#
# Why aiosmtplib (not smtplib): the Voice WS handler is async and runs
# many short-lived sends; sync smtplib would either block the event loop
# or force us to thread-pool every send. aiosmtplib is the standard
# async SMTP client for FastAPI codebases.

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

import aiosmtplib

from app.core.config import settings

log = logging.getLogger(__name__)


def _is_configured() -> bool:
    """True iff SMTP credentials are present. Module-callable so the higher
    level send_pay_link_email can short-circuit without importing settings.
    (SMTP 인증 정보 존재 여부 — 미설정이면 send 호출 자체 스킵)
    """
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


async def send_html_email(
    *,
    to:       str,
    subject:  str,
    html:     str,
    plain:    str = "",
) -> dict[str, Any]:
    """Send a multipart HTML email. Fire-and-forget: returns the result
    dict instead of raising so callers can log uniformly.
    (HTML 이메일 발송 — fire-and-forget, 실패해도 raise 안 함)

    Returns:
        {sent: bool, skipped?: True, reason?: str, error?: str}
    """
    if not to:
        return {"sent": False, "skipped": True, "reason": "no_recipient"}
    if not _is_configured():
        log.warning("SMTP not configured — skipping email to %s", to)
        return {"sent": False, "skipped": True, "reason": "smtp_not_configured"}

    msg = EmailMessage()
    msg["From"]    = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    msg["To"]      = to
    msg["Subject"] = subject
    # Plain-text fallback first (RFC 2046 — clients pick the last suitable part).
    # An auto-generated plain version keeps the email out of spam folders that
    # downgrade pure-HTML messages.
    # (text/plain → text/html — 일부 스팸 필터가 plain 없는 메일 강등)
    msg.set_content(plain or "Open this email in an HTML-capable mail client.")
    msg.add_alternative(html, subtype="html")

    try:
        # `start_tls=True` is the right toggle for Gmail's port 587 (STARTTLS).
        # `use_tls=True` would attempt TLS on connect, which is port 465 only.
        # (Gmail 587 = STARTTLS / 465 = use_tls)
        result = await aiosmtplib.send(
            msg,
            hostname  = settings.smtp_host,
            port      = settings.smtp_port,
            username  = settings.smtp_user,
            password  = settings.smtp_pass,
            start_tls = (not settings.smtp_secure),
            use_tls   = settings.smtp_secure,
            timeout   = 15,
        )
        log.info("email sent | to=%s | subject=%r", to, subject)
        return {"sent": True, "result": str(result)}
    except Exception as exc:
        # Non-fatal — order is already saved; email failure must not block flow
        log.error("email send failed | to=%s | err=%s", to, exc)
        return {"sent": False, "error": str(exc)}
