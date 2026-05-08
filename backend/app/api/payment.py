# Phase 2-B.1.9 — Pay link route
# (Phase 2-B.1.9 — 결제 링크 라우트)
#
# GET /api/payment/mock/{transaction_id}
#   Mock payment gateway callback. Browsers (the customer's phone) hit this
#   URL when they tap the SMS pay link. Today the gateway is a stub: any
#   GET succeeds. The real Maverick HPP redirect lands in Phase 2-F and will
#   replace the mock with a signed webhook.
#
# All actual state work lives in app.services.bridge.pay_link.settle_payment;
# this route only translates the result into an HTML page the browser shows.

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services.bridge import transactions
from app.services.bridge.no_show_sweep import sweep_no_shows
from app.services.bridge.pay_link import settle_payment

log = logging.getLogger(__name__)

router = APIRouter(tags=["Payment"])


# ── HTML page builders (inline CSS only, broad-compat email/browser) ─────────
# Pattern ported from the legacy jm-saas-platform demo. Inline CSS avoids
# external stylesheet dependencies that some mobile browsers strip.

def _success_page(
    tx_id:        str,
    status:       str,
    items:        list | None = None,
    total_cents:  int = 0,
) -> str:
    """Page shown for status='paid' or 'already_paid'.
    (정상 결제 / 멱등 재요청 시 표시 페이지 — items + total 포함)

    items / total_cents drive an inline receipt block so the customer
    sees exactly what they paid for, mirroring how a Maverick / Stripe
    receipt page would present it. Empty items falls back to the older
    minimal layout.
    (영수증 블록 — items 비어있으면 기존 최소 레이아웃)
    """
    sub_msg = (
        "Your order has been confirmed and sent to the kitchen."
        if status == "paid" else
        "We've already received this payment. Your order is on its way."
    )

    receipt_block = ""
    if items and total_cents > 0:
        line_rows = []
        for it in items:
            try:
                qty   = int(it.get("quantity") or 1)
                nm    = (it.get("name") or "item").strip()
                # Phase 7-A.D Wave A.2-G — prefer effective_price so the
                # receipt subtotal matches what was actually charged. Fall
                # back to base price for legacy items pre-Phase-7-A.C.
                # (effective_price 우선 — modifier surcharge 반영된 subtotal)
                unit  = float(it.get("effective_price") or it.get("price") or 0)
                line_total = unit * qty
            except (AttributeError, ValueError, TypeError):
                continue

            # Modifier breakdown rendered under the item name.
            # (item 이름 아래 modifier 표시 — 영수증 정확성)
            modifier_lines = it.get("modifier_lines") or []
            mod_html = ""
            if modifier_lines:
                parts = []
                for ml in modifier_lines:
                    label = (ml.get("label") or "").strip()
                    if not label:
                        continue
                    try:
                        delta = float(ml.get("price_delta") or 0)
                    except (TypeError, ValueError):
                        delta = 0.0
                    if delta:
                        sign = "+" if delta > 0 else "-"
                        parts.append(f"{label} ({sign}${abs(delta):.2f})")
                    else:
                        parts.append(label)
                if parts:
                    mod_html = (
                        '<div style="font-size:12px;color:#6b7280;margin-top:2px;'
                        'line-height:1.4;">' + " · ".join(parts) + '</div>'
                    )

            line_rows.append(
                f'<tr><td style="padding:6px 0;color:#374151;font-size:14px;text-align:left;">'
                f'{qty} × {nm}{mod_html}</td>'
                f'<td style="padding:6px 0;color:#374151;font-size:14px;text-align:right;'
                f'font-variant-numeric:tabular-nums;vertical-align:top;">${line_total:.2f}</td></tr>'
            )
        rows_html = "".join(line_rows)
        receipt_block = (
            '<div style="background:#fff;border:1px solid #d1fae5;border-radius:8px;'
            'padding:18px 22px;margin-bottom:24px;text-align:left;">'
            '<div style="font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;margin-bottom:10px;">Receipt</div>'
            '<table style="width:100%;border-collapse:collapse;">'
            f'{rows_html}'
            '<tr><td colspan="2" style="border-top:1px dashed #d1fae5;padding-top:8px;"></td></tr>'
            '<tr>'
            '<td style="padding-top:6px;color:#15803d;font-size:15px;font-weight:bold;">Total paid</td>'
            f'<td style="padding-top:6px;color:#15803d;font-size:15px;font-weight:bold;text-align:right;font-variant-numeric:tabular-nums;">${total_cents/100:.2f}</td>'
            '</tr>'
            '</table>'
            '</div>'
        )
    elif total_cents > 0:
        # Items unavailable but we still know the total — show it alone.
        # (items 없어도 total 단독 표시)
        receipt_block = (
            '<div style="background:#fff;border:1px solid #d1fae5;border-radius:8px;'
            'padding:18px 22px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center;">'
            '<span style="color:#15803d;font-size:15px;font-weight:bold;">Total paid</span>'
            f'<span style="color:#15803d;font-size:15px;font-weight:bold;font-variant-numeric:tabular-nums;">${total_cents/100:.2f}</span>'
            '</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Payment Successful</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background-color:#f0fdf4;display:flex;align-items:center;justify-content:center;min-height:100vh;">
  <div style="background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);padding:48px 40px;max-width:480px;width:90%;text-align:center;">
    <div style="width:72px;height:72px;background:#22c55e;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:36px;line-height:72px;">
      &#x2705;
    </div>
    <h1 style="margin:0 0 12px;font-size:26px;font-weight:bold;color:#15803d;">Payment Successful!</h1>
    <p style="margin:0 0 28px;font-size:16px;color:#374151;line-height:1.6;">{sub_msg}</p>
    {receipt_block}
    <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:14px 20px;margin-bottom:28px;">
      <span style="font-size:13px;color:#6b7280;display:block;margin-bottom:4px;">Order ID</span>
      <span style="font-size:14px;font-weight:bold;color:#166534;font-family:monospace;">{tx_id}</span>
    </div>
    <p style="margin:0;font-size:14px;color:#9ca3af;">Thank you for your order.</p>
  </div>
</body>
</html>"""


def _error_page(tx_id: str, reason: str) -> str:
    """Page shown for status='not_found' / 'terminal_state' / unknown errors.
    (결제 실패 / 만료된 링크 표시 페이지)
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Payment Error</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background-color:#fef2f2;display:flex;align-items:center;justify-content:center;min-height:100vh;">
  <div style="background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);padding:48px 40px;max-width:480px;width:90%;text-align:center;">
    <div style="width:72px;height:72px;background:#ef4444;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:36px;line-height:72px;">
      &#x274C;
    </div>
    <h1 style="margin:0 0 12px;font-size:26px;font-weight:bold;color:#b91c1c;">Payment Could Not Be Confirmed</h1>
    <p style="margin:0 0 28px;font-size:16px;color:#374151;line-height:1.6;">
      We were unable to confirm your payment. Please contact the store and provide your order ID.
    </p>
    <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;padding:14px 20px;margin-bottom:28px;">
      <span style="font-size:13px;color:#6b7280;display:block;margin-bottom:4px;">Order ID</span>
      <span style="font-size:14px;font-weight:bold;color:#991b1b;font-family:monospace;">{tx_id}</span>
    </div>
    <p style="margin:0;font-size:13px;color:#9ca3af;">Reason: {reason}</p>
  </div>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/api/payment/mock/{transaction_id}", response_class=HTMLResponse)
async def mock_payment_callback(transaction_id: str) -> HTMLResponse:
    """Mock pay link landing page.
    (목 결제 링크 랜딩 페이지)

    Uses settle_payment for all state work. This route's only job is to
    pick the right HTML page based on the result. Idempotent — a second
    tap returns the success page without re-running side effects.

    Note (security): in production this endpoint must be replaced with a
    signed Maverick webhook. The mock route is intentionally trivial so a
    customer can complete the full voice → kitchen → payment loop end to
    end during demos.
    (보안 주의: 프로덕션에선 Maverick HMAC 웹훅으로 교체 필수)
    """
    log.info("Mock pay link tapped | tx=%s", transaction_id)

    result: dict[str, Any] = await settle_payment(transaction_id=transaction_id)
    status = result.get("status", "")

    # Pull the transaction once so the success page can show the
    # itemised receipt + total. Fetch is best-effort: if it fails we
    # fall back to the simpler page so the customer never sees an
    # error page just because the read-side flaked.
    # (영수증 표시용 — 실패 시 최소 레이아웃으로 폴백)
    receipt_items: list = []
    receipt_total: int = 0
    if status in ("paid", "already_paid", "paid_pos_pending"):
        try:
            tx_row = await transactions.get_transaction(transaction_id)
            if tx_row:
                items_raw = tx_row.get("items_json")
                if isinstance(items_raw, list):
                    receipt_items = items_raw
                receipt_total = int(tx_row.get("total_cents") or 0)
        except Exception as exc:
            log.warning("receipt fetch failed tx=%s: %s", transaction_id, exc)

    if status in ("paid", "already_paid"):
        return HTMLResponse(
            _success_page(transaction_id, status,
                          items=receipt_items, total_cents=receipt_total),
            status_code=200,
        )

    if status == "paid_pos_pending":
        # The customer paid; the kitchen will see it once reconciliation
        # retries the POS write. Show the success page — from the payer's
        # perspective the transaction is closed.
        # (결제 완료 — POS 재시도는 reconciliation이 처리, 사용자에겐 성공)
        return HTMLResponse(
            _success_page(transaction_id, "paid",
                          items=receipt_items, total_cents=receipt_total),
            status_code=200,
        )

    if status == "not_found":
        return HTMLResponse(
            _error_page(transaction_id, "Order not found. The link may have expired."),
            status_code=404,
        )

    if status == "terminal_state":
        return HTMLResponse(
            _error_page(transaction_id, "This order is already closed."),
            status_code=410,   # Gone
        )

    return HTMLResponse(
        _error_page(transaction_id,
                    f"Unable to process payment: {result.get('error', 'unknown')}"),
        status_code=500,
    )


@router.post("/api/internal/no-show-sweep")
async def run_no_show_sweep() -> dict[str, Any]:
    """Trigger one no-show sweep pass.
    (no-show 청소 1회 실행)

    Intended for the cron worker (or operator dashboard) to call. Each pass
    is bounded (≤100 rows) so a runaway backlog doesn't block the request.
    Returning structured counts lets the caller decide whether to schedule
    another pass immediately.
    (cron/대시보드용 — 한 번에 최대 100건 처리, 카운트 반환)
    """
    return await sweep_no_shows()
