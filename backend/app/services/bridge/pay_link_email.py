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


def _format_delta(delta: float) -> str:
    """Render a price_delta with a sign so customers don't misread a discount."""
    if not delta:
        return ""
    sign = "+" if delta > 0 else "-"
    return f"{sign}${abs(delta):.2f}"


_GROUP_LABEL = {
    "size":         "Size",
    "temperature":  "Temperature",
    "temp":         "Temperature",
    "milk":         "Milk",
    "syrup":        "Syrup",
    "foam":         "Foam",
    "shot":         "Shot",
    "extra":        "Extra",
    "topping":      "Topping",
    "sweetener":    "Sweetener",
    "ice":          "Ice",
}


def _humanize_group(group: str) -> str:
    """'milk' → 'Milk', 'temperature' → 'Temperature' for receipt display.
    (group 코드 → 사람 읽기 좋은 라벨)
    """
    if not group:
        return ""
    g = group.strip().lower()
    return _GROUP_LABEL.get(g, g.replace("_", " ").title())


def _modifier_text_html(modifier_lines: list[dict[str, Any]]) -> str:
    """Modifier breakdown — one row per modifier with optional group label
    on the left, value+delta on the right. Compatible with Gmail/Outlook/
    iOS Mail (no flex/grid; pure inline styles).

    (item 이름 아래 modifier 표시 — modifier별 1줄, 깔끔한 row 레이아웃)

    Phase 7-A.D Wave A.2-G: items_json carries modifier_lines populated by
    services/menu/match.resolve_items_against_menu. Each entry has a
    display label, group code, option code, and signed price_delta.
    Empty list → no rows.
    """
    if not modifier_lines:
        return ""
    rows: list[str] = []
    for ml in modifier_lines:
        label = (ml.get("label") or "").strip()
        if not label:
            continue
        group = _humanize_group(ml.get("group") or "")
        try:
            delta = float(ml.get("price_delta") or 0)
        except (TypeError, ValueError):
            delta = 0.0
        delta_html = ""
        if delta:
            delta_color = "#15803d" if delta > 0 else "#9ca3af"
            delta_html = (
                f'<span style="margin-left:8px;color:{delta_color};font-size:12px;'
                f'font-weight:500;font-variant-numeric:tabular-nums;">'
                f'{_format_delta(delta)}</span>'
            )
        if group:
            label_html = (
                f'<span style="display:inline-block;min-width:88px;color:#94a3b8;'
                f'font-size:11px;font-weight:600;letter-spacing:0.04em;'
                f'text-transform:uppercase;">{group}</span>'
                f'<span style="color:#475569;font-size:13px;font-weight:500;">'
                f'{label}</span>{delta_html}'
            )
        else:
            label_html = (
                f'<span style="color:#475569;font-size:13px;font-weight:500;">'
                f'{label}</span>{delta_html}'
            )
        rows.append(
            f'<div style="padding:4px 0;line-height:1.5;">{label_html}</div>'
        )
    if not rows:
        return ""
    return (
        f'<div style="margin-top:10px;padding:10px 12px;background:#f8fafc;'
        f'border-left:3px solid #cbd5e1;border-radius:4px;">{"".join(rows)}</div>'
    )


def _items_rows_html(items: list[dict[str, Any]]) -> str:
    """Render line items as a card per item — name + qty pill on top, modifier
    panel underneath, subtotal in the corner. Email-client safe (table+inline).
    (라인 항목 카드형 — 항목별 명확 분리, modifier panel로 가독성 ↑)

    Phase 7-A.D Wave A.2-G: subtotal uses effective_price (base + Σ
    modifier price_delta) when present. Each modifier line renders on
    its own row inside a soft-grey panel so customers can verify
    size/milk/syrup at a glance instead of scanning a dot-separated
    string.
    """
    if not items:
        return ""
    rows: list[str] = []
    last_idx = len(items) - 1
    for idx, it in enumerate(items):
        name = (it.get("name") or "").strip() or "Item"
        qty  = int(it.get("quantity") or 1)
        try:
            unit = float(it.get("effective_price") or it.get("price") or 0)
        except (TypeError, ValueError):
            unit = float(it.get("price") or 0)
        sub_cents      = int(round(unit * qty * 100))
        unit_cents     = int(round(unit * 100))
        modifier_block = _modifier_text_html(it.get("modifier_lines") or [])

        # Quantity pill — tiny rounded badge next to item name. qty=1 hides
        # the badge so single-item orders stay clean.
        qty_pill = ""
        if qty > 1:
            qty_pill = (
                f'<span style="display:inline-block;margin-left:10px;padding:2px 9px;'
                f'background:#e0f2fe;color:#075985;border-radius:999px;font-size:12px;'
                f'font-weight:700;letter-spacing:0.02em;">×{qty}</span>'
            )

        # When qty > 1 we also show the unit price under the subtotal so the
        # customer can double-check the math without doing it in their head.
        unit_line = ""
        if qty > 1:
            unit_line = (
                f'<div style="margin-top:2px;color:#94a3b8;font-size:11px;'
                f'font-weight:500;font-variant-numeric:tabular-nums;">'
                f'{_format_money(unit_cents)} each</div>'
            )

        # Bottom border between cards, removed for the last entry so it
        # joins the table footer cleanly.
        border = "" if idx == last_idx else "border-bottom:1px solid #e5e7eb;"

        rows.append(f"""
        <tr>
          <td style="padding:18px 20px;{border}" class="item-cell">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td valign="top" style="padding-right:12px;">
                  <div style="font-size:16px;font-weight:600;color:#0f172a;line-height:1.35;">
                    {name}{qty_pill}
                  </div>
                </td>
                <td valign="top" align="right" style="white-space:nowrap;">
                  <div style="font-size:16px;font-weight:700;color:#0f172a;font-variant-numeric:tabular-nums;line-height:1.35;">
                    {_format_money(sub_cents)}
                  </div>
                  {unit_line}
                </td>
              </tr>
            </table>
            {modifier_block}
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

                <!-- Order summary card — 1 row per item with quantity pill,
                     modifier panel underneath, subtotal in the corner. Cleaner
                     than a Item|Qty|Subtotal table when items have many
                     modifiers (cafe latte with size + temp + milk + foam). -->
                <tr>
                  <td style="padding:0 24px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                           style="border:1px solid #e5e7eb;border-radius:12px;border-collapse:separate;overflow:hidden;background:#ffffff;">
                      <tr>
                        <td style="padding:14px 20px;background:#f9fafb;border-bottom:1px solid #e5e7eb;">
                          <span style="font-size:12px;letter-spacing:0.06em;text-transform:uppercase;color:#475569;font-weight:700;">
                            Order summary
                          </span>
                        </td>
                      </tr>
                      <tbody>
                        {rows}
                      </tbody>
                      <tfoot>
                        <tr>
                          <td style="padding:18px 20px;background:#f9fafb;border-top:1px solid #e5e7eb;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                              <tr>
                                <td valign="middle" style="font-size:13px;color:#475569;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;">
                                  Total
                                </td>
                                <td valign="middle" align="right" class="total-amount" style="font-size:22px;font-weight:700;color:#15803d;font-variant-numeric:tabular-nums;line-height:1;">
                                  {total}
                                </td>
                              </tr>
                            </table>
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
