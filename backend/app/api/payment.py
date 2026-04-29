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

from app.services.bridge.no_show_sweep import sweep_no_shows
from app.services.bridge.pay_link import settle_payment

log = logging.getLogger(__name__)

router = APIRouter(tags=["Payment"])


# ── HTML page builders (inline CSS only, broad-compat email/browser) ─────────
# Pattern ported from the legacy jm-saas-platform demo. Inline CSS avoids
# external stylesheet dependencies that some mobile browsers strip.

def _success_page(tx_id: str, status: str) -> str:
    """Page shown for status='paid' or 'already_paid'.
    (정상 결제 / 멱등 재요청 시 표시 페이지)
    """
    sub_msg = (
        "Your order has been confirmed and sent to the kitchen."
        if status == "paid" else
        "We've already received this payment. Your order is on its way."
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

    if status in ("paid", "already_paid"):
        return HTMLResponse(_success_page(transaction_id, status), status_code=200)

    if status == "paid_pos_pending":
        # The customer paid; the kitchen will see it once reconciliation
        # retries the POS write. Show the success page — from the payer's
        # perspective the transaction is closed.
        # (결제 완료 — POS 재시도는 reconciliation이 처리, 사용자에겐 성공)
        return HTMLResponse(_success_page(transaction_id, "paid"), status_code=200)

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
