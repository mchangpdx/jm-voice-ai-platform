# services/bridge — JM Bridge Server (Layer B)
# (services/bridge — JM Bridge Server: AI ↔ POS ↔ Payment Gateway 거래 자동화 코어)
#
# Architecture: see docs/architecture/end-to-end-sequences.md
# This is the "vault" of the platform — every transaction passes through here.
#
# Five non-negotiable safety properties (per spec):
#   1. Idempotency at every external call
#   2. Webhook signature verification before any state change
#   3. Explicit state machine — no ad-hoc state mutation
#   4. Append-only audit trail (bridge_events)
#   5. Reconciliation cron for stuck states
