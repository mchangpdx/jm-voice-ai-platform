# Twilio SMS adapter — fire-and-forget customer notifications via Twilio REST API
# (Twilio SMS 어댑터 — Twilio REST API로 fire-and-forget 고객 알림)
#
# Design (CLAUDE.md alignment):
#   - Fire-and-forget: SMS failure must NOT block the caller (reservation succeeds even
#     if SMS fails). Callers wrap with asyncio.create_task or accept the failure result.
#   - Graceful skip when credentials are not set (dev/staging environments).
#   - No twilio SDK dependency — direct httpx POST to Messages.json. Lighter, fewer
#     transitive deps, consistent with the rest of our adapter style.
#
# Twilio REST: POST https://api.twilio.com/2010-04-01/Accounts/{Sid}/Messages.json
#   form-encoded: From, To, Body
#   auth: HTTP Basic (AccountSid, AuthToken)

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# Module-level so tests can patch.object cleanly
_TWILIO_SID   = settings.twilio_account_sid
_TWILIO_TOKEN = settings.twilio_auth_token
_TWILIO_FROM  = settings.twilio_from_number


def compose_reservation_message(
    store_name:    str,
    customer_name: str,
    date_human:    str,
    time_12h:      str,
    party_size:    int,
) -> str:
    """Compose a confirmation SMS body. Single-segment friendly when names are short.
    (확인 SMS 본문 작성 — 짧은 이름이면 단일 세그먼트로 유지)
    """
    # Just the customer's first name keeps the message tight
    first_name = customer_name.split()[0] if customer_name else ""
    return (
        f"Hi {first_name}, your reservation at {store_name} is confirmed: "
        f"party of {party_size} on {date_human} at {time_12h}. See you then!"
    )


async def send_sms(to: str, body: str) -> dict[str, Any]:
    """Low-level: POST to Twilio Messages.json. Returns {sent, sid|error, reason}.
    (저수준: Twilio Messages.json POST. {sent, sid|error, reason} 반환)
    """
    if not (_TWILIO_SID and _TWILIO_TOKEN and _TWILIO_FROM):
        log.info("SMS skipped (Twilio not configured) to=%s body=%r", to, body[:60])
        return {"sent": False, "reason": "twilio_not_configured"}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{_TWILIO_SID}/Messages.json"
    data = {"From": _TWILIO_FROM, "To": to, "Body": body}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data=data, auth=(_TWILIO_SID, _TWILIO_TOKEN))
    except Exception as exc:
        log.error("Twilio SMS HTTP error: %s", exc)
        return {"sent": False, "error": f"network: {exc}"}

    if resp.status_code in (200, 201):
        sid = resp.json().get("sid")
        log.info("SMS sent sid=%s to=%s", sid, to)
        return {"sent": True, "sid": sid}

    log.warning("Twilio SMS failed %s: %s", resp.status_code, resp.text[:200])
    return {"sent": False, "error": f"{resp.status_code}: {resp.text[:120]}"}


async def send_reservation_confirmation(
    to:            str,
    store_name:    str,
    customer_name: str,
    date_human:    str,
    time_12h:      str,
    party_size:    int,
) -> dict[str, Any]:
    """High-level: compose + send. Use under asyncio.create_task for fire-and-forget.
    (고수준: 작성 + 전송. fire-and-forget을 위해 asyncio.create_task로 감싸 사용)
    """
    if not to:
        return {"sent": False, "reason": "no_phone"}

    body = compose_reservation_message(
        store_name=store_name,
        customer_name=customer_name,
        date_human=date_human,
        time_12h=time_12h,
        party_size=party_size,
    )
    return await send_sms(to=to, body=body)
