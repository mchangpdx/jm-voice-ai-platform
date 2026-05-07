# Phase 5 #26 — Tier-3 severe-allergy manager alert (V0+).
# (Phase 5 #26 — Tier 3 중증 알레르기 매니저 알림 — V0+)
#
# Fired when the bot's verbal "let me connect you with our manager" line
# triggers (EpiPen / anaphylaxis / celiac / etc. keyword class). Sends a
# fire-and-forget email to the operator-configured recipient list so the
# manager can follow up with the caller after the call ends.
#
# V0+ scope (this module):
#   - env-var recipient list (TIER3_ALERT_EMAILS, comma-separated)
#   - email channel only (TCR-independent — works without Twilio SMS approval)
#   - email-to-SMS gateways supported (e.g. 5031234567@vtext.com)
#   - parallel fan-out per recipient (one-recipient failure ≠ silent total loss)
#
# V2 evolution:
#   - per-store column on `stores` (manager_alert_emails)
#   - _resolve_manager_emails() prefers store value, falls back to env
#   - schema migration + saas-platform admin UI in coordinated session
#
# Why email-only for V0+:
#   - Twilio TCR / 10DLC approval pending — SMS is currently throttled
#   - SMTP infra already battle-tested via pay_link_email
#   - email-to-SMS carrier gateways give SMS delivery without TCR
#   - additional channels (Telegram, Slack) layer cleanly on top later

from __future__ import annotations

import asyncio
import html as html_lib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.adapters.email.smtp import send_html_email
from app.core.config import settings

log = logging.getLogger(__name__)


def _resolve_manager_emails(store: Optional[dict] = None) -> list[str]:
    """Return the list of email recipients for a Tier-3 alert.

    V0+ behaviour: env-var only. The `store` argument is accepted now so
    that V2 can swap implementations without changing call-sites:

        # V2 will become:
        # raw = (store or {}).get("manager_alert_emails") or settings.tier3_alert_emails
        # ...

    (V0+ — 환경변수만 사용. store 인자는 V2 호환 자리표시자)
    """
    raw = settings.tier3_alert_emails or ""
    return [e.strip() for e in raw.split(",") if e.strip()]


def _excerpt(text: str, max_chars: int = 240) -> str:
    """Trim a transcript line to a safe display length.
    (transcript 한 줄 안전 길이로 절단)
    """
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def compose_tier3_alert_html(
    *,
    store_name:         str,
    caller_phone:       str,
    triggered_keyword:  str,
    transcript_excerpt: str,
    call_sid:           str = "",
    timestamp_iso:      str = "",
) -> str:
    """Build the alert email body. Single-column, plain HTML — readable on
    any client AND through email-to-SMS gateways (which strip most styles).
    Keep it short — carrier gateways often truncate to ~160 chars.
    (간결한 HTML — 이메일/캐리어 SMS 게이트웨이 양쪽 호환)
    """
    safe_store     = html_lib.escape(store_name or "Unknown store")
    safe_keyword   = html_lib.escape(triggered_keyword or "severe-allergy keyword")
    safe_phone     = html_lib.escape(caller_phone or "unknown caller")
    safe_excerpt   = html_lib.escape(transcript_excerpt or "")
    safe_sid       = html_lib.escape(call_sid or "")
    safe_ts        = html_lib.escape(timestamp_iso or "")
    return f"""<html><body style="font-family:system-ui,-apple-system,Arial,sans-serif;font-size:14px;color:#111;">
<p><strong>⚠️ Tier-3 Severe-Allergy Alert</strong></p>
<p><strong>Store:</strong> {safe_store}<br>
<strong>Caller:</strong> {safe_phone}<br>
<strong>Trigger:</strong> {safe_keyword}<br>
<strong>Time (UTC):</strong> {safe_ts}<br>
{f'<strong>Call SID:</strong> {safe_sid}<br>' if safe_sid else ''}</p>
<p><strong>What the caller said:</strong><br>
<em>"{safe_excerpt}"</em></p>
<p>The bot has handed the call off verbally. Please follow up with the caller
to verify allergen safety directly.</p>
</body></html>"""


def compose_tier3_alert_text(
    *,
    store_name:         str,
    caller_phone:       str,
    triggered_keyword:  str,
    transcript_excerpt: str,
    call_sid:           str = "",
    timestamp_iso:      str = "",
) -> str:
    """Plain-text body — also the rendering used by carrier email-to-SMS
    gateways (which drop HTML entirely and truncate). Keep it punchy.
    (SMS 게이트웨이용 plain — 짧고 핵심 정보 우선)
    """
    parts = [
        f"⚠️ Tier-3 Allergy Alert — {store_name}",
        f"Caller: {caller_phone}",
        f"Trigger: {triggered_keyword}",
    ]
    if call_sid:
        parts.append(f"Call: {call_sid}")
    if transcript_excerpt:
        parts.append(f'Said: "{transcript_excerpt}"')
    parts.append("Please follow up.")
    return "\n".join(parts)


async def send_tier3_alert(
    *,
    store_name:         str,
    caller_phone:       str,
    triggered_keyword:  str,
    transcript_excerpt: str,
    call_sid:           str = "",
    store:              Optional[dict] = None,
) -> dict[str, Any]:
    """High-level: resolve recipients + compose + dispatch in parallel.
    Fire-and-forget shape — never raises so a failed alert can't crash the
    voice flow. Caller wraps with asyncio.create_task.
    (고수준 — recipients resolve + compose + 병렬 dispatch, 실패해도 raise 안 함)

    Returns:
        {sent: bool, recipients: int, results: list[dict] | None,
         skipped?: True, reason?: str}
    """
    recipients = _resolve_manager_emails(store)
    if not recipients:
        log.warning("tier3 alert: no recipients configured (TIER3_ALERT_EMAILS empty) — skipped")
        return {"sent": False, "skipped": True, "reason": "no_recipients", "recipients": 0}

    excerpt    = _excerpt(transcript_excerpt)
    timestamp  = datetime.now(timezone.utc).isoformat(timespec="seconds")
    subject    = f"⚠️ Tier-3 Severe-Allergy Alert — {store_name or 'Store'}"
    html       = compose_tier3_alert_html(
        store_name         = store_name,
        caller_phone       = caller_phone,
        triggered_keyword  = triggered_keyword,
        transcript_excerpt = excerpt,
        call_sid           = call_sid,
        timestamp_iso      = timestamp,
    )
    plain      = compose_tier3_alert_text(
        store_name         = store_name,
        caller_phone       = caller_phone,
        triggered_keyword  = triggered_keyword,
        transcript_excerpt = excerpt,
        call_sid           = call_sid,
        timestamp_iso      = timestamp,
    )

    # Fan-out: parallel dispatch — one bad recipient never starves the rest.
    # gather(return_exceptions=True) so a single SMTP error doesn't propagate.
    # (병렬 발송 — 한 명 실패해도 다른 명에게 영향 없음)
    tasks   = [send_html_email(to=r, subject=subject, html=html, plain=plain) for r in recipients]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Normalise exceptions into the same shape send_html_email returns,
    # so the caller's logging path stays uniform.
    norm: list[dict[str, Any]] = []
    for res in results:
        if isinstance(res, Exception):
            norm.append({"sent": False, "error": repr(res)})
        else:
            norm.append(res)

    sent_count = sum(1 for r in norm if r.get("sent"))
    log.warning("tier3 alert dispatched | store=%r | caller=%r | trigger=%r | "
                "recipients=%d | sent=%d",
                store_name, caller_phone, triggered_keyword,
                len(recipients), sent_count)
    return {
        "sent":       sent_count > 0,
        "recipients": len(recipients),
        "results":    norm,
    }
