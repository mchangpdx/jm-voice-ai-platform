# Bridge Server — Idempotency key derivation
# (Bridge Server — 멱등성 키 생성)
#
# Two scopes:
#   1. Inbound tool_call (Gemini → Bridge): protect against Retell barge-in
#      double-submits. Same store + phone + intent + canonicalized args → same key.
#   2. Inbound webhook (Maverick → Bridge): same maverick_txn_id is processed once.
#
# All keys are deterministic SHA-256 hashes of canonical JSON, hex-encoded.
# Caller stores the key in bridge_payments.idempotency_key (UNIQUE constraint at DB).

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_json(obj: Any) -> bytes:
    """Stable, key-sorted JSON for hashing.
    (해시용 안정적·키 정렬 JSON)
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def key_from_tool_call(
    store_id:       str,
    customer_phone: str,
    intent:         str,
    intent_args:    dict,
) -> str:
    """Derive idempotency key for an inbound tool_call from Gemini.
    (Gemini의 tool_call에 대한 멱등성 키 생성)

    Same (store, phone, intent, canonical_args) → same key. Used to short-circuit
    duplicate tool calls that arise from Retell barge-in or webhook retries.
    """
    payload = {
        "scope":         "tool_call",
        "store_id":      store_id,
        "customer_phone": customer_phone,
        "intent":        intent,
        "intent_args":   intent_args,
    }
    h = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return f"tc_{h}"


def key_from_webhook(maverick_txn_id: str) -> str:
    """Derive idempotency key for a Maverick webhook event.
    (Maverick 웹훅 이벤트 멱등성 키 생성)

    The Maverick transaction ID is itself globally unique within the gateway,
    so we use it directly with a short prefix for readability in logs.
    """
    return f"mvr_{maverick_txn_id}"
