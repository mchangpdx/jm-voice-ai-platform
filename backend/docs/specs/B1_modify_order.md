# B1 — `modify_order` Specification

**Phase**: 2-C.1 (production launch blocker)
**Owner**: Bridge Server, Restaurant vertical
**Status**: spec → TDD tests → implementation
**Last updated**: 2026-04-29

---

## 1. Why

A customer who just placed an order through the voice agent very often
follows up within 30–120 seconds with one of:

- "Can you add a croissant to that?"
- "Actually, make it two lattes instead of one."
- "Drop the donut from my order."
- "Can I add an espresso shot?"

Without a modify path, the only options are (a) refuse and force the
customer to cancel-and-re-place, which the AI currently can't do either,
or (b) let the original order stand wrong — both unacceptable for a
production cafe deployment. This is one of the highest-frequency P0
scenarios in the restaurant phone survey (#2 in the 35-scenario list).

---

## 2. Domain model (DDD)

| Concept | Type | Source of truth |
|---------|------|-----------------|
| `BridgeTransaction` | Aggregate root | `bridge_transactions` table |
| `OrderItems` | Value object inside a transaction | `bridge_transactions.items_json` |
| `TotalCents` | Derived value (Σ price × qty) | `bridge_transactions.total_cents` |
| `LifecycleState` | Enum (state machine) | `bridge_transactions.state` |
| `PaymentLane` | Enum (`pay_first` / `fire_immediate`) | `bridge_transactions.payment_lane` |
| `OrderModificationService` | Domain service | `app.services.bridge.flows.modify_order` |
| `MenuCatalog` | Read model | `menu_items` table (via `resolve_items_against_menu`) |

`modify_order` is a **command** on a `BridgeTransaction` aggregate. It
mutates `OrderItems` (and the derived `TotalCents`) in place and appends
an `OrderItemsModified` domain event to `bridge_events`. Lifecycle state
is **invariant** under modification — only items change.

---

## 3. Preconditions / postconditions / invariants

### Preconditions (the bridge enforces all of these)

1. There exists a single most-recent `BridgeTransaction` for `(store_id,
   caller_phone, pos_object_type='order')` in state ∈ `{PENDING,
   PAYMENT_SENT}` created within the last 5 minutes.
2. The caller's `caller_phone_e164` is server-side-derived (Retell
   `from_number`) — never trusted from Gemini args.
3. The new `items` list is non-empty and every entry resolves against
   `menu_items` (exact case-insensitive or fuzzy ≥ 0.85).
4. Every resolved item passes the stock check (`stock_quantity` NULL or
   ≥ requested qty).
5. `user_explicit_confirmation == True` AND `force_tool_use == True` (the
   AUTO-fire gate from F-2.E applies here too).

### Postconditions (on success)

- `bridge_transactions.items_json` is the new resolved list.
- `bridge_transactions.total_cents` is the new sum (price × qty).
- `bridge_transactions.updated_at` is now.
- `bridge_events` has a new row: `event_type='items_modified'`,
  `actor='tool_call:modify_order'`, `from_state == to_state` = current
  state, `payload_json` snapshot of `{old_items, new_items, old_total,
  new_total}`.
- The pay link route already reads `total_cents` at click-time so **no
  new SMS / email is sent** — the existing link reflects the new total.

### Invariants

- `transaction_id` unchanged.
- `customer_phone` unchanged.
- `store_id`, `vertical`, `pos_object_type`, `payment_lane` unchanged.
- `state` unchanged (PENDING stays PENDING; PAYMENT_SENT stays
  PAYMENT_SENT).
- `pos_object_id` unchanged (always empty before payment for `pay_first`;
  `fire_immediate` is rejected by precondition #1 above).

### Failure modes (each gets its own `ai_script_hint`)

| Reason | When | Customer-facing line |
|--------|------|----------------------|
| `no_order_to_modify` | precondition #1 fails (no in-flight tx) | "I don't see an active order to modify — would you like to start a new one?" |
| `order_too_late` | tx exists but state ∈ {`FIRED_UNPAID`, `PAID`, `FULFILLED`} | "The kitchen has already started that order — I can't change it now. Want me to cancel and place a new one?" |
| `validation_failed` | empty items list / placeholder name | "I'm missing something — could you confirm the items again?" |
| `unknown_item` | new items has a menu miss | "I'm sorry, we don't have [X] today — anything else from the menu?" |
| `sold_out` | item exists but stock insufficient | "We're sold out of [X] — could I get you something else?" |

---

## 4. Tool schema (Voice Engine ↔ Gemini)

```python
MODIFY_ORDER_TOOL_DEF = {
    "function_declarations": [{
        "name": "modify_order",
        "description": (
            "Update the items on an in-flight pickup order, before payment. "
            "Use ONLY when the customer explicitly asks to add, remove, or "
            "change items on an order they JUST PLACED in this same call. "
            "PRECONDITIONS: (a) the customer has clearly stated the change, "
            "(b) you have recited the FULL UPDATED order back with the new "
            "totals, (c) the customer has said an explicit verbal yes. "
            "The 'items' list REPLACES the current order entirely — pass "
            "the COMPLETE final list, not a delta. Do NOT include "
            "customer_phone — the system uses the inbound caller ID. Do NOT "
            "invent menu items or placeholders."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_explicit_confirmation": {"type": "boolean"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":     {"type": "string"},
                            "quantity": {"type": "integer"},
                        },
                        "required": ["name", "quantity"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["user_explicit_confirmation", "items"],
        },
    }],
}
```

`customer_phone`, `customer_name`, `customer_email` are **deliberately
absent** from the schema — the bridge looks them up from the existing
transaction via caller-id lookup. This kills phone-hallucination at the
source.

---

## 5. Bridge flow (`flows.modify_order`)

```python
async def modify_order(*, store_id, args, caller_phone_e164, call_log_id):
    # 1. Validate args
    raw_items = _coerce_items(args)
    if not raw_items:
        return {"success": False, "reason": "validation_failed",
                "ai_script_hint": "validation_failed", ...}

    # 2. Find target transaction
    target = await _find_modifiable_order(store_id, caller_phone_e164)
    if not target:
        return {"success": False, "reason": "no_order_to_modify",
                "ai_script_hint": "modify_no_target", ...}

    # 3. Verify state
    if target["state"] not in (State.PENDING, State.PAYMENT_SENT):
        return {"success": False, "reason": "order_too_late",
                "ai_script_hint": "modify_too_late", ...}

    # 4. Resolve items
    resolved = await resolve_items_against_menu(
        store_id=store_id, items=raw_items)
    unknown = [r for r in resolved if r.get("missing")]
    if unknown:
        return {"success": False, "reason": "unknown_item",
                "unavailable": unknown, "ai_script_hint": "rejected", ...}
    sold_out = [r for r in resolved if not r.get("sufficient_stock", True)]
    if sold_out:
        return {"success": False, "reason": "sold_out",
                "unavailable": sold_out, "ai_script_hint": "rejected", ...}

    # 5. Compute new total
    new_total = _sum_total_cents(resolved)

    # 6. Persist
    await transactions.update_items_and_total(
        transaction_id=target["id"],
        items=resolved,
        total_cents=new_total,
    )
    await transactions.append_audit(
        transaction_id=target["id"],
        event_type="items_modified",
        actor="tool_call:modify_order",
        source="voice",
        payload={
            "old_items": target.get("items_json") or [],
            "new_items": resolved,
            "old_total": target.get("total_cents", 0),
            "new_total": new_total,
        },
    )

    # 7. Return — no pay link resend (link auto-reflects new total)
    return {
        "success":         True,
        "transaction_id":  target["id"],
        "lane":            target.get("payment_lane"),
        "state":           target["state"],
        "total_cents":     new_total,
        "items":           resolved,
        "ai_script_hint":  "modify_success",
    }
```

`_find_modifiable_order` is the same shape as `_find_recent_duplicate`
but state-filter is `(pending, payment_sent)` only (`fired_unpaid` /
`paid` / `fulfilled` are explicitly excluded so the bridge can return
`order_too_late`).

---

## 6. Voice Engine integration (`voice_websocket.py`)

- Register `MODIFY_ORDER_TOOL_DEF` alongside `RESERVATION_TOOL_DEF` and
  `ORDER_TOOL_DEF` in `_stream_gemini_response`.
- Apply the AUTO-fire gate (already in F-2.E) to `modify_order` too.
- Apply the caller-id override to `modify_order` if (somehow) Gemini
  passes `customer_phone` — but the schema doesn't have that field, so
  this is belt-and-suspenders.
- Tool roundtrip: branch on `tool_name == "modify_order"` →
  `bridge_flows.modify_order(...)` → emit `result["message"]` verbatim.

System prompt rule **6 (new)** — append to the existing 9-rule list:

> 6. MODIFY ORDER (modify_order): If the customer asks to change an
>    order they just placed (add an item, remove one, change a quantity)
>    AND the order has not yet been paid for, recite the FULL updated
>    order with the new total ("Updated to two cafe lattes and one
>    croissant for $15.97 — is that right?"). On the explicit yes, call
>    modify_order with the COMPLETE new items list. The same payment
>    link automatically reflects the new total — do NOT promise a new
>    link. If the bridge says the kitchen already started, apologize
>    and offer to cancel and re-place.

---

## 7. Customer-facing scripts (`order.py:MODIFY_ORDER_SCRIPT_BY_HINT`)

```python
MODIFY_ORDER_SCRIPT_BY_HINT = {
    "modify_success": (
        "Updated — your new total is ${total}. The same payment link "
        "still works."
    ),
    "modify_no_target": (
        "I don't see an active order to modify. Would you like to start "
        "a new one?"
    ),
    "modify_too_late": (
        "The kitchen has already started that order — I can't change it "
        "now. I can cancel it and place a fresh one if you'd like."
    ),
    "rejected": (
        # Reuses the existing rejected script for unknown_item / sold_out
        "I'm sorry — one or more items aren't available right now. "
        "Would you like to try something else?"
    ),
    "validation_failed": (
        "I'm missing something to update the order — let me ask once "
        "more so I get it right."
    ),
}
```

The success line includes the live total — the voice handler does the
`{total}` substitution from `bridge_result["total_cents"]` (Phase F-2
already reads `result["message"]` verbatim, so we expand the placeholder
in the handler before yielding).

---

## 8. Test plan (TDD — written before any production code)

Tests live in `tests/unit/services/bridge/test_modify_order.py` and
`tests/unit/api/test_voice_websocket_modify.py`.

| # | Case | Inputs | Expected |
|---|------|--------|----------|
| T1 | Happy path | tx in PENDING, new items resolve | success=True, items_json + total_cents updated, audit row written |
| T2 | No target | no recent in-flight tx for caller | success=False, reason=no_order_to_modify, no DB write |
| T3 | Too late | tx in FIRED_UNPAID | success=False, reason=order_too_late, no DB write |
| T4 | Unknown item | new items has 'unicorn pie' | success=False, reason=unknown_item, no DB write |
| T5 | Sold out | item exists but stock=0 | success=False, reason=sold_out, no DB write |
| T6 | Empty items | args.items = [] | success=False, reason=validation_failed |
| T7 | Same items (no-op) | new items == old items | success=True (idempotent UPDATE — bytes identical) |
| T8 | AUTO-fire gate | force_tool_use=False | tool body never runs; recital yielded |
| T9 | Tool description | schema parses + matches DDD shape | (offline lint) |

T1–T7 are pure flows tests with mocked httpx. T8 is voice-layer.

---

## 9. Out of scope (deferred)

- **fire_immediate modify** — Loyverse VOID + recreate flow. Refused
  with `order_too_late` for now.
- **Modify across multiple in-flight orders** for the same caller — we
  always pick the most recent.
- **Item-level history audit** beyond a single before/after snapshot.
- **Modify_reservation** — same shape, separate B3 spec.
- **Customer self-modify via web** — not in scope, voice only.

---

## 10. Risks / open questions

- (resolved) Should we resend the pay link? **No.** `/pay/{tx_id}` reads
  `total_cents` at click time, so the live link auto-updates.
- (resolved) Should modify trigger a state change? **No.** State is an
  invariant under modification.
- (open, low) What if a customer modifies AFTER tapping the email link
  but before the Stripe-mock callback returns? Race: the customer pays
  the old total, then we update items. Mitigation: reject modify when
  `state == PAYMENT_SENT` AND a payment session is active. Defer to a
  later spec — observed frequency near zero in cafe orders.
- (open, low) Fuzzy-match drift — modify trusts the same fuzzy threshold
  (0.85) as create. If the catalog adds two items that fuzzy-overlap,
  we may hit a wrong item silently. Mitigation: log every fuzzy match
  via `_mon` (already done).
