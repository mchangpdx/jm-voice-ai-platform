# Twilio Numbers adapter — provision voice webhook on an Incoming Phone Number.
# (Twilio 번호 어댑터 — Incoming Phone Number의 Voice 웹훅 설정)
#
# Why: wizard finalize wants to be zero-touch end-to-end. Without this,
# the operator still has to log into the Twilio console and paste the
# voice webhook URL for every new pilot store — the one remaining
# manual step after agency_id / business_hours / persona auto-set.
#
# Design (CLAUDE.md alignment):
#   * Fire-and-forget tolerant — caller wraps in try/except and surfaces
#     a manual fallback in next_steps if the API fails.
#   * No twilio SDK dependency — direct httpx, matches sms.py style.
#   * Graceful skip when TWILIO_ACCOUNT_SID/AUTH_TOKEN unset (dev).
#
# Twilio REST:
#   GET  /2010-04-01/Accounts/{Sid}/IncomingPhoneNumbers.json?PhoneNumber=+1...
#        → returns the IncomingPhoneNumber resource(s); use .sid for the patch
#   POST /2010-04-01/Accounts/{Sid}/IncomingPhoneNumbers/{PhoneSid}.json
#        form-encoded: VoiceUrl, VoiceMethod (default POST)
#   auth: HTTP Basic (AccountSid, AuthToken)
#
# Live trigger: every wizard finalize since 2026-05-12 surfaced the
# same "set Twilio webhook for {phone}" step in next_steps — this is
# the adapter that finally lets us drop it.

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


_TWILIO_SID   = settings.twilio_account_sid
_TWILIO_TOKEN = settings.twilio_auth_token
_API_BASE     = "https://api.twilio.com/2010-04-01"


async def _lookup_phone_sid(
    client:       httpx.AsyncClient,
    phone_e164:   str,
) -> str | None:
    """Resolve a +E.164 number to its Twilio IncomingPhoneNumber SID.

    The PATCH endpoint is keyed by SID, not by the phone string. Twilio
    surfaces the SID via the list endpoint with a PhoneNumber filter.
    Returns None when the number isn't owned by this account (e.g. the
    operator typed a personal cell into the wizard by mistake) so the
    caller can fall back to manual setup instead of pretending success.
    (E.164 → SID 룩업; 매장 번호가 계정 소유가 아니면 None 반환)
    """
    url = f"{_API_BASE}/Accounts/{_TWILIO_SID}/IncomingPhoneNumbers.json"
    resp = await client.get(
        url,
        params={"PhoneNumber": phone_e164},
        auth=(_TWILIO_SID, _TWILIO_TOKEN),
    )
    if resp.status_code != 200:
        log.warning(
            "Twilio numbers lookup failed %s for %s: %s",
            resp.status_code, phone_e164, resp.text[:200],
        )
        return None
    body = resp.json()
    rows = body.get("incoming_phone_numbers") or []
    if not rows:
        return None
    sid = rows[0].get("sid")
    return sid if isinstance(sid, str) and sid else None


async def update_voice_webhook(
    phone_e164:   str,
    webhook_url:  str,
    method:       str = "POST",
) -> dict[str, Any]:
    """Point a Twilio number's Voice webhook at `webhook_url`.

    Returns a dict shaped like the SMS adapter so the wizard's
    finalize handler can surface the outcome alongside the loyverse
    push result:
        {"ok": True,  "sid": "PN...", "voice_url": "..."}
        {"ok": False, "reason": "...", "error": "..."}
    The caller is responsible for adding a manual-fallback line to
    next_steps when ok=False — we never raise from this function.
    (실패 시 raise 없이 dict로 안내, caller가 next_steps에 manual 추가)
    """
    if not phone_e164 or not phone_e164.startswith("+"):
        return {"ok": False, "reason": "invalid_phone", "phone": phone_e164}
    if not webhook_url:
        return {"ok": False, "reason": "no_webhook_url"}
    if not (_TWILIO_SID and _TWILIO_TOKEN):
        log.info("Twilio webhook update skipped (not configured) phone=%s", phone_e164)
        return {"ok": False, "reason": "twilio_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            phone_sid = await _lookup_phone_sid(client, phone_e164)
            if not phone_sid:
                return {
                    "ok":     False,
                    "reason": "phone_not_owned_by_account",
                    "phone":  phone_e164,
                }
            patch_url = (
                f"{_API_BASE}/Accounts/{_TWILIO_SID}"
                f"/IncomingPhoneNumbers/{phone_sid}.json"
            )
            resp = await client.post(
                patch_url,
                data={"VoiceUrl": webhook_url, "VoiceMethod": method.upper()},
                auth=(_TWILIO_SID, _TWILIO_TOKEN),
            )
    except httpx.HTTPError as exc:
        log.error("Twilio webhook update HTTP error for %s: %s", phone_e164, exc)
        return {"ok": False, "reason": "network", "error": str(exc)}

    if resp.status_code in (200, 201):
        body = resp.json()
        log.info(
            "Twilio webhook updated phone=%s sid=%s -> %s",
            phone_e164, phone_sid, webhook_url,
        )
        return {
            "ok":        True,
            "sid":       phone_sid,
            "voice_url": body.get("voice_url") or webhook_url,
        }

    log.warning(
        "Twilio webhook update failed %s for %s: %s",
        resp.status_code, phone_e164, resp.text[:200],
    )
    return {
        "ok":     False,
        "reason": f"http_{resp.status_code}",
        "error":  resp.text[:200],
    }
