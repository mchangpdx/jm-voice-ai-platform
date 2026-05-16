# Phase 2-B.1.10b — Standalone email send test
# (Phase 2-B.1.10b — 이메일 발송 단독 테스트 스크립트)
#
# Run from the backend/ directory so the .venv + .env are picked up:
#     cd /Users/mchangpdx/jm-voice-ai-platform/backend
#     .venv/bin/python scripts/test_send_email.py
#
# What it does:
#   1. Builds a sample fire_immediate-lane order (2 Latte + 1 Bagel = $18.50).
#   2. Calls send_pay_link_email() — same path used by the voice flow.
#   3. Prints the adapter's result dict.
#
# Expected outputs:
#   {'sent': True, ...}       ← Gmail accepted; check the inbox.
#   {'sent': False, 'error': 'Authentication failed: ...'}
#                             ← App Password wrong or has spaces. Re-issue.
#   {'sent': False, 'error': 'Connection refused / timeout'}
#                             ← Network blocks SMTP 587 (corporate Wi-Fi etc).
#
# Edit RECIPIENT below if you want to send to a different mailbox.

import asyncio
import sys
from pathlib import Path

# Make `app` importable regardless of cwd. Without this, running the script
# from backend/scripts/ puts only that subdir on sys.path and the `app`
# package is invisible. (스크립트 실행 시 sys.path에 backend/ 디렉토리 명시 추가)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.bridge.pay_link_email import send_pay_link_email


# Recipient — change to whichever inbox you want to receive the test email.
# (수신자 — 받고 싶은 이메일 주소로 변경)
RECIPIENT = "mchang@jmtechone.com"


async def main() -> None:
    result = await send_pay_link_email(
        to             = "cymeet@gmail.com",
        customer_name  = "Michael",
        store_name     = "JM Cafe",
        total_cents    = 1850,
        items          = [
            {"name": "Latte", "quantity": 2, "price": 4.50},
            {"name": "Bagel", "quantity": 1, "price": 9.50},
        ],
        transaction_id = "demo-tx-001",
        lane           = "fire_immediate",
    )
    print("send result:", result)


if __name__ == "__main__":
    asyncio.run(main())
