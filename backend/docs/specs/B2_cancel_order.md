# B2 — `cancel_order` Specification

**Phase**: 2-C.2 (production launch blocker)
**Owner**: Bridge Server, Restaurant vertical
**Status**: spec → TDD tests → implementation
**Last updated**: 2026-05-02

---

## 1. Why

Live: call_faba29762 (5-1 16:32) — customer placed a small Americano,
order routed `fire_immediate`, customer asked to add a Cafe Latte 30
seconds later. The Fix #2 patch correctly returned `order_too_late`
and the bot suggested cancel-and-replace. The customer said "Okay. You
can cancel it." — and the bot, having no `cancel_order` tool, eventually
hallucinated **"I've gone ahead and cancelled that for you."** The
order was NOT cancelled. The customer hung up believing nothing would
charge / nothing would arrive at the kitchen; in reality Loyverse had
the receipt and the bridge transaction was still in `FIRED_UNPAID`.

Same pattern observed in earlier triage logs whenever a customer
changed their mind. Without a real cancel path the agent has three bad
options: (a) refuse and force a manager call, (b) hallucinate success,
(c) silently leave the order live. All three break trust.

This is **the next pre-public-launch blocker** (per
`memory/project_migration_status.md` — B2 is item 1 in the deferred
list).

---

## 2. Domain model (DDD)

| Concept | Type | Source of truth |
|---------|------|-----------------|
| `BridgeTransaction` | Aggregate root | `bridge_transactions` table |
| `LifecycleState` | Enum (state machine) | `bridge_transactions.state` |
| `OrderCancellationService` | Domain service | `app.services.bridge.flows.cancel_order` |
| `StateMachine` | Invariant guard | `app.services.bridge.state_machine` |

`cancel_order` is a **command** on a `BridgeTransaction` aggregate. It
transitions `LifecycleState` to `CANCELED` and emits a state-transition
audit event. **Items are NOT mutated** — the cancellation preserves the
historical record of what was ordered. POS-side cleanup (Loyverse
`void receipt`) is deferred to V2; for V1 the bot tells the customer to
notify staff at pickup-window arrival when the order was already
fired_unpaid.

---

## 3. Preconditions / postconditions / invariants

### Preconditions (the bridge enforces all of these)

1. There exists a single most-recent `BridgeTransaction` for `(store_id,
   caller_phone, pos_object_type='order')` in state ∈ `{PENDING,
   PAYMENT_SENT, FIRED_UNPAID}` created within the last 5 minutes.
   (`_find_modifiable_order` is reused — Fix #2 already widened it to
   include `fired_unpaid`.)
2. The caller's `caller_phone_e164` is server-side-derived (Retell
   `from_number`) — never trusted from Gemini args.
3. `user_explicit_confirmation == True` AND `force_tool_use == True`
   (the AUTO-fire gate from F-2.E applies here too, with a cancel-
   specific recital).

### Postconditions (on success)

- `bridge_transactions.state` transitioned to `CANCELED`.
- `bridge_transactions.updated_at` is now.
- `bridge_events` has a new row written by `transactions.advance_state`:
  `event_type='state_transition'`, `from_state=<prior>`,
  `to_state='canceled'`, `actor='tool_call:cancel_order'`,
  `source='voice'`.
- **No POS write in V1** (Loyverse receipt remains; bot tells customer
  to inform staff at counter if the order was `fired_unpaid`).
- **No new pay link sent.** Existing `/pay/{tx_id}` route refuses
  payment for cancelled transactions (already handled by
  `pay_link.py:84` — `terminal_state` short-circuit).

### Invariants

- `transaction_id`, `customer_phone`, `store_id`, `vertical`,
  `pos_object_type`, `payment_lane` unchanged.
- `items_json`, `total_cents`, `pos_object_id` unchanged
  (cancellation preserves the historical record).

### Failure modes (each gets its own `ai_script_hint`)

| Reason | When | Customer-facing line |
|--------|------|----------------------|
| `cancel_no_target` | precondition #1 fails (no in-flight tx in last 5 min) | "I don't see an active order to cancel — is there something else I can help with?" |
| `cancel_already_canceled` | tx exists but state == `CANCELED` | "That order has already been cancelled." |
| `cancel_already_paid` | tx state ∈ {`PAID`, `FULFILLED`, `REFUNDED`, `NO_SHOW`} | "That order has already been paid for. Let me connect you with our manager for a refund." |
| `cancel_failed` | `state_machine.InvalidTransition` raised, or DB write fails | "Sorry, I had trouble cancelling that. Let me connect you with our manager." |

`PAID` / `FULFILLED` / `REFUNDED` / `NO_SHOW` lookups require a
**broader probe** than `_find_modifiable_order` (which only returns
`pending|payment_sent|fired_unpaid`). To detect "already paid" with
a clean error message, we add a **secondary probe**
`_find_recent_settled_order` that looks for terminal states in the same
5-min window. Without this the customer hits `cancel_no_target` —
technically correct but unhelpful.

---

## 4. Tool schema (Voice Engine ↔ Gemini)

```python
CANCEL_ORDER_TOOL_DEF = {
    "function_declarations": [{
        "name": "cancel_order",
        "description": (
            "Cancel an in-flight pickup order before it's paid. "
            "Use ONLY when the customer EXPLICITLY says 'cancel my "
            "order', 'cancel that', 'never mind, cancel it'. "
            "PRECONDITIONS: (a) the customer has clearly stated cancel "
            "intent, (b) you have recited 'Just to confirm — you want "
            "to cancel your order for X for $Y — is that right?', "
            "(c) the customer has said an explicit verbal yes. "
            "Do NOT pass customer_phone, customer_name, customer_email, "
            "or items — the system identifies the order via the inbound "
            "caller ID. If no in-flight order exists, the bridge will "
            "respond accordingly and you must NOT retry."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_explicit_confirmation": {
                    "type": "boolean",
                    "description": (
                        "True ONLY after explicit verbal yes to the "
                        "cancel recital."
                    ),
                },
            },
            "required": ["user_explicit_confirmation"],
        },
    }],
}
```

`customer_phone`, `customer_name`, `customer_email`, `items` are
**deliberately absent** from the schema — the bridge looks the order up
from the existing transaction via caller-id. Items are not needed
because cancellation operates on the transaction as a whole. This kills
phone-hallucination at the source and prevents Gemini from inventing a
fake order to cancel.

---

## 5. Bridge flow (`flows.cancel_order`)

```python
async def cancel_order(*, store_id, caller_phone_e164, call_log_id):
    # 1. Find target transaction (in-flight states).
    target = await _find_modifiable_order(
        store_id        = store_id,
        customer_phone  = caller_phone_e164,
    )

    # 2. If no in-flight, look for a recently settled one to give a
    #    precise error rather than the generic 'no order' line.
    if not target:
        settled = await _find_recent_settled_order(
            store_id        = store_id,
            customer_phone  = caller_phone_e164,
        )
        if settled and settled["state"] == State.CANCELED:
            return {"success": False, "reason": "cancel_already_canceled",
                    "transaction_id": settled["id"],
                    "ai_script_hint": "cancel_already_canceled"}
        if settled and settled["state"] in (State.PAID, State.FULFILLED,
                                             State.REFUNDED, State.NO_SHOW):
            return {"success": False, "reason": "cancel_already_paid",
                    "transaction_id": settled["id"],
                    "state":          settled["state"],
                    "ai_script_hint": "cancel_already_paid"}
        return {"success": False, "reason": "cancel_no_target",
                "ai_script_hint": "cancel_no_target"}

    # 3. State guard. _find_modifiable_order returns pending /
    #    payment_sent / fired_unpaid (Fix #2). All three are valid
    #    cancel sources — the state machine allows the edge.
    prior_state = target["state"]
    if not state_machine.can_transition(prior_state, State.CANCELED):
        # Defensive — should never fire given the SQL filter.
        log.error("cancel_order: cannot transition tx=%s %s → canceled",
                  target["id"], prior_state)
        return {"success": False, "reason": "cancel_failed",
                "transaction_id": target["id"],
                "ai_script_hint": "cancel_failed"}

    # 4. Persist via state machine. transactions.advance_state writes
    #    the bridge_events audit row in the same call.
    try:
        await transactions.advance_state(
            transaction_id = target["id"],
            to_state       = State.CANCELED,
            source         = "voice",
            actor          = "tool_call:cancel_order",
            extra_fields   = {},
        )
    except Exception as exc:
        log.error("cancel_order: advance_state failed tx=%s: %s",
                  target["id"], exc)
        return {"success": False, "reason": "cancel_failed",
                "transaction_id": target["id"],
                "ai_script_hint": "cancel_failed"}

    # 5. Return success. lane / items / total preserved for the voice
    #    handler's session snapshot + script formatter.
    return {
        "success":         True,
        "transaction_id":  target["id"],
        "lane":            target.get("payment_lane"),
        "state":           State.CANCELED,
        "prior_state":     prior_state,
        "total_cents":     int(target.get("total_cents") or 0),
        "items":           target.get("items_json") or [],
        "ai_script_hint":  ("cancel_success_fired" if prior_state == State.FIRED_UNPAID
                            else "cancel_success"),
    }
```

`_find_modifiable_order` is reused as-is (Fix #2 already widened the
SQL to include `fired_unpaid`). A new `_find_recent_settled_order`
helper is added — same shape, terminal-state filter — only invoked when
the in-flight probe returned None, so it adds at most one extra HTTP
round-trip on cancel attempts that miss.

---

## 6. Voice Engine integration (`voice_websocket.py`)

- Register `CANCEL_ORDER_TOOL_DEF` alongside `RESERVATION_TOOL_DEF`,
  `ORDER_TOOL_DEF`, `MODIFY_ORDER_TOOL_DEF` in `_stream_gemini_response`.
- AUTO-fire gate: extend the `tool_name in (...)` tuples to include
  `"cancel_order"` (4 spots — gate, dedup sigs, dispatcher, recital
  builder).
- Cancel-specific recital: instead of "Just to confirm, that's X for
  Y", use "Just to confirm — you want to cancel your order for X for
  $Y — is that right?". Pulls items + total from
  `session["last_order_items"]` / `session["last_order_total"]` (already
  populated by create_order / modify_order success paths).
- Tool roundtrip: branch on `tool_name == "cancel_order"` →
  `bridge_flows.cancel_order(...)` → emit `result["message"]` verbatim.
- The caller-id override does NOT apply (cancel_order has no
  customer_phone in its schema).

System prompt rule **7 (new)** — append to the existing rule list:

> 7. CANCEL ORDER (cancel_order): If the customer EXPLICITLY says
>    "cancel my order", "cancel that", "never mind, cancel it", recite
>    "Just to confirm — you want to cancel your order for [items] for
>    $[total] — is that right?". On the explicit yes, call cancel_order
>    with user_explicit_confirmation=true. NEVER say "I've cancelled
>    that for you" without actually calling cancel_order — this is a
>    truthfulness invariant. If the bridge says the order is already
>    paid, apologize and offer manager transfer; do NOT promise a
>    refund yourself.

---

## 7. Customer-facing scripts (`order.py:CANCEL_ORDER_SCRIPT_BY_HINT`)

```python
CANCEL_ORDER_SCRIPT_BY_HINT = {
    "cancel_success": (
        "Got it — your order has been cancelled. No charge will go "
        "through. Sorry for the trouble!"
    ),
    "cancel_success_fired": (
        # FIRED_UNPAID branch — kitchen has the receipt; staff need a
        # heads-up since V1 doesn't auto-void Loyverse.
        "Got it — your order has been cancelled on our side. The "
        "kitchen had already started, so when you're nearby please "
        "let our team at the counter know so they can clear it. No "
        "charge will go through."
    ),
    "cancel_no_target": (
        "I don't see an active order to cancel. Is there something "
        "else I can help with?"
    ),
    "cancel_already_canceled": (
        "That order has already been cancelled. Is there anything "
        "else I can help with?"
    ),
    "cancel_already_paid": (
        "That order has already been paid for. Let me connect you "
        "with our manager so they can help with a refund."
    ),
    "cancel_failed": (
        "Sorry, I had trouble cancelling that. Let me connect you "
        "with our manager to sort it out."
    ),
}
```

No `{total}` substitution needed — cancel scripts don't quote the
total. (The recital quotes it from session snapshot, before the tool
call.)

---

## 8. Test plan (TDD — written before any production code)

Tests live in `tests/unit/services/bridge/test_cancel_order.py`.

| # | Case | Inputs | Expected |
|---|------|--------|----------|
| T1 | Happy path PENDING → CANCELED | tx in PENDING | success=True, state='canceled', ai_script_hint='cancel_success', advance_state called once |
| T2 | Happy path PAYMENT_SENT → CANCELED | tx in PAYMENT_SENT | success=True, ai_script_hint='cancel_success' |
| T3 | Happy path FIRED_UNPAID → CANCELED (kitchen alert script) | tx in FIRED_UNPAID | success=True, ai_script_hint='cancel_success_fired' |
| T4 | No in-flight, no settled either | both probes empty | success=False, reason='cancel_no_target', no DB write |
| T5 | Already cancelled | settled probe returns CANCELED row | success=False, reason='cancel_already_canceled', no DB write |
| T6 | Already paid (PAID) | settled probe returns PAID row | success=False, reason='cancel_already_paid', no DB write |
| T7 | Already fulfilled | settled probe returns FULFILLED row | success=False, reason='cancel_already_paid' |
| T8 | advance_state raises | mock raises | success=False, reason='cancel_failed', no crash |
| T9 | state machine refuses (defensive) | impossible state arrives | success=False, reason='cancel_failed' |
| T10 | Invariants preserved on success | items_json + total_cents in return | items + total from existing row, unchanged |

T1–T10 are pure flows tests with mocked httpx and mocked
`transactions.advance_state`. Voice-layer integration is exercised by
the live Phase C call.

---

## 9. Out of scope (deferred)

- **Loyverse void receipt API** (V2) — V1 tells the customer to notify
  staff at the counter when cancelling a `fired_unpaid` order. V2 will
  call Loyverse `void receipt` automatically.
- **Refund flow for PAID orders** (V2) — V1 transfers to a manager.
  PAID → REFUNDED transitions exist in the state machine but require
  Maverick payment-side integration.
- **Cancel-and-replace as a single tool** — out of scope. V1 is two
  tools: cancel_order, then create_order.
- **`cancel_reservation`** (B4) — same shape, separate spec.
- **Customer self-cancel via web** — voice only.

---

## 10. Risks / open questions

- (mitigated) **Customer says "cancel" by mistake.** AUTO-fire gate +
  cancel-specific recital ("you want to cancel your order for X for $Y
  — is that right?") + FORCE TOOL signal (post-confirmation yes) — the
  same triple-gate that protects create_order.
- (V1 limitation, documented) **FIRED_UNPAID cancel doesn't void
  Loyverse.** Bot script tells the customer to notify staff at counter.
  V2 fixes via Loyverse void API.
- (open, low) **Race: customer cancels AFTER tapping pay link but
  BEFORE callback returns.** Mitigation: pay_link.py:84 already
  refuses payment for terminal states (`canceled`, `no_show`); the
  payment session will fail with `terminal_state` and the customer
  sees an error page. Deferred to a later spec — observed frequency
  near zero.
- (open, low) **Multiple in-flight orders for same caller** —
  `_find_modifiable_order` returns the most recent only. Cancel
  affects that one. V2 may add disambiguation if customers start
  placing multiple orders per call.
