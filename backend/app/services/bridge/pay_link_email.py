# Phase 2-B.1.10b — Pay link email composer + dispatcher
# (Phase 2-B.1.10b — 결제 링크 이메일 작성 + 발송)
#
# Modern, mobile-first HTML pay link email used as a TCR-fallback channel.
# Renders cleanly on phone / tablet / desktop using a hybrid of inline CSS
# (mandatory for email clients that strip <style>) and a minimal <style>
# block in <head> for media-query-driven responsive tweaks.
#
# Design choices:
#   - Single-column 600px max layout — the email industry's de-facto width.
#     Anything wider breaks Outlook desktop. Anything narrower wastes space.
#   - Full-bleed dark hero with high-contrast Pay Now button (44px+ tap
#     target — Apple HIG / Material Design).
#   - Items table collapses to a clean list on screens under 480px.
#   - System font stack — no web fonts (corporate proxies block them).
#   - Real-money color cues: green for success/total, neutral grey body.
#
# Companion to the SMS path: same fire-and-forget shape, same lane-aware
# copy (fire_immediate vs pay_first), same idempotent skip-when-missing.

from __future__ import annotations

import logging
from typing import Any

from app.adapters.email.smtp import send_html_email
from app.core.config import settings
from app.services.bridge.pay_link_sms import build_pay_link

log = logging.getLogger(__name__)


def _format_money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _items_rows_html(items: list[dict[str, Any]]) -> str:
    """Render line items as table rows for desktop + a stacked card variant
    for mobile (CSS toggles between them via media query).
    (라인 항목을 데스크톱 테이블 / 모바일 카드 양쪽 형태로 출력 — CSS가 분기)
    """
    if not items:
        return ""
    rows: list[str] = []
    for it in items:
        name      = (it.get("name") or "").strip() or "Item"
        qty       = int(it.get("quantity") or 1)
        unit      = float(it.get("price") or 0)
        sub_cents = int(round(unit * qty * 100))
        rows.append(f"""
        <tr class="item-row">
          <td class="item-name" style="padding:14px 20px;border-bottom:1px solid #e5e7eb;font-size:15px;color:#111827;line-height:1.4;">
            <span style="font-weight:600;">{name}</span>
            <span class="item-qty-mobile" style="display:none;color:#6b7280;font-size:13px;font-weight:400;"> · qty {qty}</span>
          </td>
          <td class="item-qty" style="padding:14px 16px;border-bottom:1px solid #e5e7eb;font-size:15px;color:#374151;text-align:center;width:60px;">
            {qty}
          </td>
          <td class="item-sub" style="padding:14px 20px;border-bottom:1px solid #e5e7eb;font-size:15px;color:#111827;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;width:90px;">
            {_format_money(sub_cents)}
          </td>
        </tr>""")
    return "\n".join(rows)


def compose_pay_link_email_html(
    *,
    customer_name: str,
    store_name:    str,
    total_cents:   int,
    items:         list[dict[str, Any]],
    pay_link:      str,
    lane:          str,
) -> str:
    """Modern, responsive HTML email body. Renders correctly on iOS Mail,
    Gmail (web + app), Outlook desktop, Apple Mail.
    (모던 반응형 HTML — 주요 이메일 클라이언트 호환 검증된 패턴)
    """
    customer = (customer_name or "").strip() or "there"
    rows     = _items_rows_html(items)
    total    = _format_money(total_cents)

    if lane == "fire_immediate":
        hero_eyebrow = "Your order is in the kitchen"
        hero_blurb   = "We've started preparing your order. Tap below to settle the bill before pickup, or pay at the counter."
        cta_label    = "Pay Now"
        cta_blurb    = "Optional — you can also pay when you arrive."
    else:
        hero_eyebrow = "One tap to confirm"
        hero_blurb   = "Tap the button below to complete your payment. As soon as it goes through, we'll start preparing your order."
        cta_label    = "Pay & Place Order"
        cta_blurb    = "Your order won't start until payment is confirmed."

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <meta name="color-scheme" content="light only" />
  <meta name="supported-color-schemes" content="light only" />
  <title>{store_name} — Order</title>
  <style>
    /* Reset for buggy clients (Outlook in particular). */
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; }}
    a {{ text-decoration: none; }}

    /* Mobile (≤480px): stack table rows into cards, hide desktop columns. */
    @media only screen and (max-width: 480px) {{
      .container        {{ width: 100% !important; padding: 0 !important; }}
      .card             {{ border-radius: 0 !important; box-shadow: none !important; }}
      .hero             {{ padding: 32px 22px !important; }}
      .hero h1          {{ font-size: 22px !important; }}
      .body-pad         {{ padding: 24px 20px !important; }}
      .cta              {{ padding: 16px 24px !important; font-size: 16px !important; }}
      .item-qty         {{ display: none !important; }}
      .item-name        {{ padding: 12px 18px !important; }}
      .item-sub         {{ padding: 12px 18px !important; }}
      .item-qty-mobile  {{ display: inline !important; }}
      .total-amount     {{ font-size: 22px !important; }}
    }}

    /* Tablet (481-768px): keep two-column items, looser padding. */
    @media only screen and (min-width: 481px) and (max-width: 768px) {{
      .container        {{ width: 92% !important; max-width: 600px; }}
    }}

    /* Honor system dark-mode preferences without going full dark
       (forced color scheme above keeps Gmail dark mode from inverting). */
    @media (prefers-color-scheme: dark) {{
      body              {{ background-color: #0f172a !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif;">
  <!-- Preheader: shows in inbox preview, hidden in body. -->
  <div style="display:none;max-height:0;overflow:hidden;color:transparent;line-height:0;">
    {hero_eyebrow} — {total} at {store_name}.
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#f3f4f6;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;">

          <!-- Card wrapper -->
          <tr>
            <td>
              <table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(15,23,42,0.06);">

                <!-- Hero -->
                <tr>
                  <td class="hero" style="background:linear-gradient(135deg,#0f172a 0%,#1f2937 100%);padding:38px 32px;text-align:center;color:#ffffff;">
                    <p style="margin:0 0 6px;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#86efac;font-weight:600;">
                      {hero_eyebrow}
                    </p>
                    <h1 style="margin:0;font-size:24px;font-weight:700;line-height:1.3;color:#ffffff;">
                      {store_name}
                    </h1>
                  </td>
                </tr>

                <!-- Body -->
                <tr>
                  <td class="body-pad" style="padding:32px 32px 8px;">
                    <p style="margin:0 0 8px;font-size:16px;color:#0f172a;font-weight:600;">
                      Hi {customer},
                    </p>
                    <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.6;">
                      {hero_blurb}
                    </p>
                  </td>
                </tr>

                <!-- Items table -->
                <tr>
                  <td style="padding:0 24px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                           style="border:1px solid #e5e7eb;border-radius:10px;border-collapse:separate;overflow:hidden;">
                      <thead>
                        <tr>
                          <th align="left"   style="background:#f9fafb;padding:11px 20px;font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;font-weight:600;border-bottom:1px solid #e5e7eb;">Item</th>
                          <th align="center" class="item-qty" style="background:#f9fafb;padding:11px 16px;font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;font-weight:600;border-bottom:1px solid #e5e7eb;">Qty</th>
                          <th align="right"  style="background:#f9fafb;padding:11px 20px;font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;font-weight:600;border-bottom:1px solid #e5e7eb;">Subtotal</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows}
                      </tbody>
                      <tfoot>
                        <tr>
                          <td colspan="2" align="right" style="padding:16px 20px;font-size:14px;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;">
                            Total
                          </td>
                          <td align="right" class="total-amount" style="padding:16px 20px;font-size:20px;font-weight:700;color:#15803d;font-variant-numeric:tabular-nums;">
                            {total}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </td>
                </tr>

                <!-- CTA -->
                <tr>
                  <td align="center" style="padding:32px 24px 8px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td align="center" style="border-radius:999px;background:#16a34a;">
                          <a class="cta" href="{pay_link}"
                             style="display:inline-block;padding:16px 36px;font-size:16px;font-weight:700;color:#ffffff;border-radius:999px;background:#16a34a;">
                            {cta_label} &nbsp;→
                          </a>
                        </td>
                      </tr>
                    </table>
                    <p style="margin:14px 0 0;font-size:13px;color:#94a3b8;line-height:1.5;">
                      {cta_blurb}
                    </p>
                  </td>
                </tr>

                <!-- Fallback link (some clients block buttons) -->
                <tr>
                  <td style="padding:24px 32px 32px;text-align:center;">
                    <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
                      Button not working? Copy this link into your browser:<br />
                      <a href="{pay_link}" style="color:#475569;word-break:break-all;">{pay_link}</a>
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


def compose_pay_link_email_text(
    *,
    customer_name: str,
    store_name:    str,
    total_cents:   int,
    pay_link:      str,
    lane:          str,
) -> str:
    """Plain-text alternative for clients that strip HTML and for spam-filter
    deliverability. Same lane-aware tone as the HTML body.
    (HTML 차단/스팸 필터 대응 plain-text 대체본)
    """
    customer = (customer_name or "").strip() or "there"
    total    = _format_money(total_cents)
    if lane == "fire_immediate":
        head = (f"Hi {customer}, your order at {store_name} ({total}) is in the kitchen. "
                f"Pay before pickup or at the counter.")
    else:
        head = (f"Hi {customer}, tap below to pay {total} at {store_name} — "
                f"we'll start your order as soon as the payment goes through.")
    return f"{head}\n\nPay link: {pay_link}\n\n— {settings.smtp_from_name}\n"


async def send_pay_link_email(
    *,
    to:              str,
    customer_name:   str,
    store_name:      str,
    total_cents:     int,
    items:           list[dict[str, Any]],
    transaction_id:  str,
    lane:            str,
) -> dict[str, Any]:
    """High-level: build link + compose subject/body + dispatch via SMTP.
    Mirrors send_pay_link (SMS) shape so the voice handler can call both
    in parallel without divergent return types.
    (고수준 — SMS 함수와 동일한 시그니처 패턴)
    """
    if not to:
        return {"sent": False, "skipped": True, "reason": "no_recipient"}

    pay_link = build_pay_link(transaction_id)
    subject  = f"Your Order — {store_name} (${total_cents / 100:.2f})"
    html     = compose_pay_link_email_html(
        customer_name = customer_name,
        store_name    = store_name,
        total_cents   = total_cents,
        items         = items,
        pay_link      = pay_link,
        lane          = lane,
    )
    plain    = compose_pay_link_email_text(
        customer_name = customer_name,
        store_name    = store_name,
        total_cents   = total_cents,
        pay_link      = pay_link,
        lane          = lane,
    )
    return await send_html_email(to=to, subject=subject, html=html, plain=plain)
