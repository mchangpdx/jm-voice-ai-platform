# Phase 2-C.B4 — Reservation confirmation email composer + dispatcher
# (Phase 2-C.B4 — 예약 확정 이메일 작성 + 발송기 — TCR 펜딩 동안 fallback 채널)
#
# Modern, responsive HTML reservation email used as the TCR-fallback channel
# while Twilio A2P 10DLC approval is pending. Mirrors the order pay-link
# email's layout (single-column 600px, system fonts, mobile-stacked card)
# but uses a distinct INDIGO + AMBER palette so customers receiving both
# kinds of emails can tell at a glance which is which.
#
# Color tone — visual disambiguation from order email:
#   - Order email:        slate hero (#0f172a) + green CTA (#16a34a) — money/payment cue
#   - Reservation email:  indigo hero (#312e81 → #4338ca) + amber accent (#d97706)
#                         — welcome / calendar cue, no money
#
# Dispatch semantics (B4): the voice handler defers send until WS
# disconnect so only the FINAL state of the reservation (after any
# in-call modifies / cancels) results in exactly one email. This module
# is unaware of that — it just composes + ships when called.

from __future__ import annotations

import logging
from typing import Any, Optional

from app.adapters.email.smtp import send_html_email
from app.core.config import settings

log = logging.getLogger(__name__)


def _summary_card_html(
    *,
    party_size: int,
    date_human: str,
    time_12h:   str,
    notes:      str,
) -> str:
    """Render the reservation summary as a labeled card. Notes section
    is conditionally appended so an empty value doesn't produce a stray
    "Special requests:" label.
    (예약 요약 카드 — notes는 있을 때만 노출)
    """
    notes_block = ""
    if notes and notes.strip():
        notes_block = f"""
        <tr>
          <td style="padding:14px 20px 18px;border-top:1px solid #e0e7ff;">
            <p style="margin:0 0 4px;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#6366f1;font-weight:600;">
              Special requests
            </p>
            <p style="margin:0;font-size:15px;color:#1f2937;line-height:1.5;">
              {notes.strip()}
            </p>
          </td>
        </tr>"""
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="border:1px solid #e0e7ff;border-radius:10px;border-collapse:separate;overflow:hidden;background:#eef2ff;">
      <tr>
        <td style="padding:18px 20px 6px;">
          <p style="margin:0 0 4px;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#6366f1;font-weight:600;">
            Party size
          </p>
          <p style="margin:0 0 14px;font-size:18px;color:#1e1b4b;font-weight:700;">
            Party of {party_size}
          </p>
        </td>
      </tr>
      <tr>
        <td style="padding:0 20px 6px;">
          <p style="margin:0 0 4px;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#6366f1;font-weight:600;">
            Date
          </p>
          <p style="margin:0 0 14px;font-size:18px;color:#1e1b4b;font-weight:700;">
            {date_human}
          </p>
        </td>
      </tr>
      <tr>
        <td style="padding:0 20px 18px;">
          <p style="margin:0 0 4px;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#6366f1;font-weight:600;">
            Time
          </p>
          <p style="margin:0;font-size:18px;color:#1e1b4b;font-weight:700;">
            {time_12h}
          </p>
        </td>
      </tr>
      {notes_block}
    </table>"""


def compose_reservation_email_html(
    *,
    customer_name:  str,
    store_name:     str,
    party_size:     int,
    date_human:     str,
    time_12h:       str,
    notes:          str,
    reservation_id: int,
) -> str:
    """Modern, responsive HTML reservation confirmation. Renders correctly
    on iOS Mail, Gmail (web + app), Outlook desktop, Apple Mail. Uses the
    indigo + amber palette to distinguish from the order pay-link email.
    (모던 반응형 HTML — indigo + amber 팔레트로 주문 메일과 시각 구분)
    """
    customer = (customer_name or "").strip() or "there"
    summary  = _summary_card_html(
        party_size = party_size,
        date_human = date_human,
        time_12h   = time_12h,
        notes      = notes,
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <meta name="color-scheme" content="light only" />
  <meta name="supported-color-schemes" content="light only" />
  <title>{store_name} — Reservation</title>
  <style>
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; }}
    a {{ text-decoration: none; }}

    @media only screen and (max-width: 480px) {{
      .container        {{ width: 100% !important; padding: 0 !important; }}
      .card             {{ border-radius: 0 !important; box-shadow: none !important; }}
      .hero             {{ padding: 32px 22px !important; }}
      .hero h1          {{ font-size: 22px !important; }}
      .body-pad         {{ padding: 24px 20px !important; }}
    }}

    @media only screen and (min-width: 481px) and (max-width: 768px) {{
      .container        {{ width: 92% !important; max-width: 600px; }}
    }}

    @media (prefers-color-scheme: dark) {{
      body              {{ background-color: #1e1b4b !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f5f3ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif;">
  <!-- Preheader: shows in inbox preview, hidden in body. -->
  <div style="display:none;max-height:0;overflow:hidden;color:transparent;line-height:0;">
    Reservation confirmed — party of {party_size} on {date_human} at {time_12h}.
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#f5f3ff;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;">

          <!-- Card wrapper -->
          <tr>
            <td>
              <table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(49,46,129,0.08);">

                <!-- Hero -->
                <tr>
                  <td class="hero" style="background:linear-gradient(135deg,#312e81 0%,#4338ca 100%);padding:38px 32px;text-align:center;color:#ffffff;">
                    <p style="margin:0 0 6px;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#fcd34d;font-weight:600;">
                      Reservation Confirmed
                    </p>
                    <h1 style="margin:0;font-size:24px;font-weight:700;line-height:1.3;color:#ffffff;">
                      {store_name}
                    </h1>
                  </td>
                </tr>

                <!-- Body -->
                <tr>
                  <td class="body-pad" style="padding:32px 32px 8px;">
                    <p style="margin:0 0 8px;font-size:16px;color:#1e1b4b;font-weight:600;">
                      Hi {customer},
                    </p>
                    <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.6;">
                      We're looking forward to seeing you. Here are your reservation details — feel free
                      to save this email for reference.
                    </p>
                  </td>
                </tr>

                <!-- Reservation summary card -->
                <tr>
                  <td style="padding:0 24px;">
                    {summary}
                  </td>
                </tr>

                <!-- Amber footer accent -->
                <tr>
                  <td align="center" style="padding:28px 32px 8px;">
                    <p style="margin:0 0 6px;font-size:14px;color:#d97706;font-weight:600;">
                      Need to make changes?
                    </p>
                    <p style="margin:0;font-size:13px;color:#6b7280;line-height:1.6;">
                      Just give us a call back and we'll update your booking.
                    </p>
                  </td>
                </tr>

                <!-- Reference line -->
                <tr>
                  <td style="padding:24px 32px 32px;text-align:center;">
                    <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
                      Reservation reference: #{reservation_id}
                    </p>
                  </td>
                </tr>

              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding:18px 16px 8px;">
              <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
                This email was sent by {store_name} via {settings.smtp_from_name}.<br />
                Need help? Reply to this email and the team will get back to you.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def compose_reservation_email_text(
    *,
    customer_name:  str,
    store_name:     str,
    party_size:     int,
    date_human:     str,
    time_12h:       str,
    reservation_id: int,
) -> str:
    """Plain-text alternative for clients that strip HTML and for spam-filter
    deliverability. Same warm tone as the HTML body.
    (HTML 차단 클라이언트 + 스팸 필터 대응 plain-text 대체본)
    """
    customer = (customer_name or "").strip() or "there"
    return (
        f"Hi {customer}, your reservation at {store_name} is confirmed: "
        f"party of {party_size} on {date_human} at {time_12h}.\n\n"
        f"We're looking forward to seeing you — give us a call back if "
        f"you need to make any changes.\n\n"
        f"Reservation reference: #{reservation_id}\n\n"
        f"— {settings.smtp_from_name}\n"
    )


async def send_reservation_email(
    *,
    to:             str,
    customer_name:  str,
    store_name:     str,
    party_size:     int,
    date_human:     str,
    time_12h:       str,
    reservation_id: int,
    notes:          str = "",
) -> dict[str, Any]:
    """High-level: compose subject/body + dispatch via SMTP. Mirrors
    send_pay_link_email's shape so the voice handler can call it the
    same way under asyncio.create_task.
    (고수준 — pay_link_email과 동일 시그니처 패턴, fire-and-forget)
    """
    if not to:
        return {"sent": False, "skipped": True, "reason": "no_recipient"}

    subject = f"Reservation Confirmed — {store_name}"
    html = compose_reservation_email_html(
        customer_name  = customer_name,
        store_name     = store_name,
        party_size     = party_size,
        date_human     = date_human,
        time_12h       = time_12h,
        notes          = notes,
        reservation_id = reservation_id,
    )
    plain = compose_reservation_email_text(
        customer_name  = customer_name,
        store_name     = store_name,
        party_size     = party_size,
        date_human     = date_human,
        time_12h       = time_12h,
        reservation_id = reservation_id,
    )
    return await send_html_email(to=to, subject=subject, html=html, plain=plain)
