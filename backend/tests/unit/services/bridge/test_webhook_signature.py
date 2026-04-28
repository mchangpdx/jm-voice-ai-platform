# Bridge Server — Maverick webhook signature verification
# (Bridge Server — Maverick 웹훅 서명 검증)
#
# Spec §3.2: HMAC-SHA256(merchant_secret, raw_body) hex digest sent in X-Maverick-Signature.
# Unsigned or signature-mismatch webhooks MUST return 401 and trigger NO state change.
# This is the single biggest attack surface — no signature, no trust.

import hashlib
import hmac
import json
import pytest


SECRET = "merchant_secret_test"


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_verifies():
    from app.services.bridge.webhook_signature import verify_maverick_signature

    body = json.dumps({"event": "payment_succeeded", "txn": "TX1"}).encode()
    sig  = _sign(SECRET, body)
    assert verify_maverick_signature(body, sig, SECRET) is True


def test_tampered_body_rejects():
    from app.services.bridge.webhook_signature import verify_maverick_signature

    original_body  = json.dumps({"amount": 1000}).encode()
    sig            = _sign(SECRET, original_body)
    tampered_body  = json.dumps({"amount": 9999999}).encode()
    assert verify_maverick_signature(tampered_body, sig, SECRET) is False


def test_wrong_secret_rejects():
    from app.services.bridge.webhook_signature import verify_maverick_signature

    body = json.dumps({"x": 1}).encode()
    sig  = _sign("attacker_guessed_secret", body)
    assert verify_maverick_signature(body, sig, SECRET) is False


def test_missing_signature_rejects():
    from app.services.bridge.webhook_signature import verify_maverick_signature

    body = b"{}"
    assert verify_maverick_signature(body, "", SECRET) is False
    assert verify_maverick_signature(body, None, SECRET) is False


def test_uses_constant_time_compare():
    """Timing attack protection — implementation should use hmac.compare_digest."""
    import inspect
    from app.services.bridge import webhook_signature
    src = inspect.getsource(webhook_signature)
    assert "compare_digest" in src, "MUST use hmac.compare_digest to defend against timing attacks"
