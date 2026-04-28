# Bridge Server — Webhook signature verification
# (Bridge Server — 웹훅 서명 검증)
#
# Spec §3.2: HMAC-SHA256(merchant_secret, raw_body), hex-encoded, sent in
# X-Maverick-Signature header. Constant-time compare to defend against timing attacks.
#
# CRITICAL: this is the only line of defense between an attacker and a forged
# "payment_succeeded" webhook that triggers a free POS write. Verification is
# non-optional. The handler MUST reject and return 401 on any verification failure.

from __future__ import annotations

import hashlib
import hmac
from typing import Optional


def verify_maverick_signature(
    raw_body: bytes,
    received_signature: Optional[str],
    merchant_secret: str,
) -> bool:
    """Verify HMAC-SHA256 signature on a Maverick webhook payload.
    (Maverick 웹훅 페이로드의 HMAC-SHA256 서명 검증)

    Returns True only if the signature is present, well-formed, and matches.
    Constant-time comparison via hmac.compare_digest defeats timing attacks.

    NOTE: caller MUST pass the EXACT raw bytes received on the wire — not a
    re-serialized JSON, since field-order and whitespace differences would
    invalidate an otherwise-valid signature.
    """
    if not received_signature:
        return False
    if not merchant_secret:
        return False

    expected = hmac.new(
        merchant_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time compare — never use ==
    return hmac.compare_digest(expected, received_signature)
