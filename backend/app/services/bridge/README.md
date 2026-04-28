# Bridge Server (Layer B)

> **Status**: Phase 2-B.0 skeleton (state machine + idempotency + signature verification)
> **Spec**: [docs/architecture/end-to-end-sequences.md](../../../../docs/architecture/end-to-end-sequences.md)

The Bridge Server is the **vault** of the platform — every transaction passes
through it. Layer A (voice) produces structured intent; Layer C (Quantic POS,
Maverick GW) handles persistence and payment. Bridge Server orchestrates between
them and owns:

- Pending transaction creation
- Maverick HPP session creation
- Twilio SMS dispatch with one-time pay URL
- Webhook receipt + signature verification + idempotency
- State machine enforcement
- Audit trail (append-only)
- Reconciliation cron

## Files in this module

| File                    | Responsibility                                         | Status |
|-------------------------|--------------------------------------------------------|--------|
| `state_machine.py`      | State enum, valid edges, `transition()` with audit     | ✅ done |
| `idempotency.py`        | Deterministic key derivation (tool_call + webhook)     | ✅ done |
| `webhook_signature.py`  | HMAC-SHA256 constant-time verification                 | ✅ done |
| `transactions.py`       | CRUD + state advance for `bridge_transactions`         | TODO  |
| `payments.py`           | Maverick adapter (HPP create + webhook handler)        | TODO  |
| `vertical_adapter.py`   | Per-vertical thin shims (restaurant/home/beauty/auto)  | TODO  |
| `reconciliation.py`     | Cron: stuck pendings, missing webhooks                 | TODO  |
| `api.py`                | FastAPI router (`POST /bridge/intent`, `POST /bridge/webhook/maverick`) | TODO |

## Five non-negotiable safety properties (per spec §3)

1. **Idempotency** — `idempotency.py` derives deterministic keys; DB has UNIQUE
   constraint on `bridge_payments.idempotency_key`. No duplicate writes possible.
2. **Webhook signature verification** — `webhook_signature.py` uses
   `hmac.compare_digest` for constant-time comparison. Forged webhooks return 401.
3. **State machine** — `state_machine.py` enforces `_VALID_TRANSITIONS`. Invalid
   transitions raise `InvalidTransition`. No path bypasses this.
4. **Audit trail** — every `transition()` call returns an event dict that the
   caller persists to `bridge_events`. Append-only, never updated.
5. **Reconciliation** — cron job (TODO) syncs Maverick state for stuck pendings
   every 5 minutes.

## State graph

```
pending ──────► payment_sent ──────► paid ──────► fulfilled
   │                  │                │             │
   ▼                  ▼                ▼             ▼
canceled          canceled          refunded      refunded
                  failed
```

Refund is the only retro edge. Every other transition is forward-only.

## Test coverage (today)

```
tests/unit/services/bridge/
├─ test_state_machine.py     17 tests  (transitions, terminal states, idempotent self-edges)
├─ test_idempotency.py        6 tests  (deterministic + canonical + scope-distinct)
└─ test_webhook_signature.py  5 tests  (valid, tamper, wrong-secret, missing, timing-safe)
                            ─────
                            28 tests, all green
```

## Next implementation steps

| # | Step                                         | Effort  |
|---|----------------------------------------------|---------|
| 1 | Run `migrate_bridge_server.sql` on Supabase  | 5 min   |
| 2 | `transactions.py` — CRUD + state advance     | 2-3 h   |
| 3 | `payments.py` — Maverick adapter (TDD)       | 1 day   |
| 4 | `vertical_adapter.py` — restaurant first     | 0.5 day |
| 5 | `api.py` — wire into FastAPI                 | 0.5 day |
| 6 | Replace `insert_reservation` direct write    | 0.5 day |
| 7 | E2E live test (call → SMS → POS)             | manual  |
| 8 | `reconciliation.py` cron                     | 0.5 day |

## Decisions still open (need founder)

1. Quantic API auth scheme + endpoint list (white-label tier)
2. Maverick HMAC scheme details (header name, replay window, secret rotation)
3. Idempotency key strategy (client UUID vs server-derived hash)
4. Per-store secret isolation (vault-backed)

See spec §9 for full list.
