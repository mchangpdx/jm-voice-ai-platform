# B4 — `cancel_reservation` Specification

**Phase**: 2-C.B4 (production launch blocker — Maple parity gap closer)
**Owner**: Bridge Server, Restaurant vertical
**Status**: spec → TDD tests → implementation
**Last updated**: 2026-05-02

---

## 1. Why

After B3 modify_reservation shipped, the only remaining reservation-side
gap is **cancel**. Live observed in call_0ed08f83 (turn 26, 11:51 PT):
when `modify_reservation` returned `reservation_too_late`, the bot
correctly offered cancel as the next option ("I can cancel it and we
can rebook?") — but no `cancel_reservation` tool exists yet, so the
bot can only acknowledge and offer manager transfer. The customer is
stranded with a reservation they can't change AND can't cancel.

Same pattern when the customer simply changes their mind:

- "Actually, never mind — go ahead and cancel that reservation."
- "We can't make it tonight after all, please cancel."
- "Cancel my reservation for tomorrow."

Without a real cancel path the agent has three bad options: (a) refuse
and force a manager call, (b) hallucinate success ("I've cancelled that
for you"), (c) silently leave the reservation standing and produce a
no-show. All three break trust. **Same failure class as B2 cancel_order
before it shipped.**

Maple Inc. (competitor) ships `cancel_booking` with depth 8/10
(OpenTable-backed). JM is currently 0/10 on this dimension. B4 closes
the **last** pre-launch reservation gap and fully resolves the Issue χ
guard wording in system prompt rule 4 (which currently says
"cancel_reservation tool does not exist yet (B4 pending)").

---

## 2. Domain model (DDD)

| Concept | Type | Source of truth |
|---------|------|-----------------|
| `Reservation` | Aggregate root | `reservations` table |
| `Status` | Enum | `reservations.status`: `confirmed` / `cancelled` / `fulfilled` / `no_show` |
| `ReservationCancellationService` | Domain service | `app.services.bridge.flows.cancel_reservation` |

`cancel_reservation` is a **command** on a `Reservation` aggregate. It
transitions `Status` from `confirmed` → `cancelled` and writes a single
WARNING-level audit log line. Other mutable fields
(`customer_name`, `reservation_time`, `party_size`, `notes`) are
**preserved** so the historical record of what was booked stays intact
— same invariant as B2 cancel_order keeps `items_json` /
`total_cents`.

**Storage divergence — same as B3**: reservations live in the legacy
`reservations` table (Phase 2-A). B4 v1 mutates that table directly
via REST PATCH. Migration to `bridge_transactions` is out of scope.

---

## 3. Preconditions / postconditions / invariants

### Preconditions (the bridge enforces all of these)

1. There exists a single most-recent `Reservation` for `(store_id,
   customer_phone)` in `status='confirmed'` — **most-recent policy**:
   `ORDER BY created_at DESC LIMIT 1`. Helper `_find_modifiable_reservation`
   from B3 is reused as-is.
2. The caller's `caller_phone_e164` is server-side-derived (Retell
   `from_number`) — never trusted from Gemini args.
3. `user_explicit_confirmation == True` AND `force_tool_use == True`
   (the AUTO-fire gate from F-2.E applies, with a cancel-specific
   recital sourced from `session["last_reservation_summary"]`).

### Postconditions (on success)

- `reservations.status` transitioned to `'cancelled'`.
- `reservations.updated_at` is now (DB trigger or explicit `UPDATE`).
- A log line `reservation_cancelled id=… prior_status=confirmed` is
  written at WARNING level so it surfaces under uvicorn.
- **No external side effect in V1** — no SMS / email cancel
  confirmation goes out (deferred until Twilio TCR clears + email
  template lands; matches B2 V1's deferred Loyverse void approach).

### Invariants

- `id` (reservation_id) unchanged.
- `customer_phone`, `customer_name`, `store_id` unchanged.
- `reservation_time`, `party_size`, `notes` unchanged
  (cancellation preserves the historical record).
- `created_at` unchanged.

### Failure modes (each gets its own `ai_script_hint`)

**Decision (locked 2026-05-02): Option α — always allow cancel.**
No too-late guard for cancellation. Once a reservation cannot be
modified (B3 `reservation_too_late`), cancel must remain available so
the customer is not stranded and the slot can be reclaimed by the
restaurant. There is no kitchen-fire-style irreversible side effect
on a reservation, so the 30-min cutoff that B3 enforces does not apply.

| Reason | When | Customer-facing line |
|--------|------|----------------------|
| `cancel_reservation_no_target` | precondition #1 fails (no confirmed reservation in DB) | "I don't see an active reservation under your number — is there something else I can help with?" |
| `cancel_reservation_already_canceled` | reservation exists but status == `'cancelled'` | "That reservation has already been cancelled." |
| `cancel_reservation_failed` | DB PATCH fails / unexpected exception | "Sorry, I had trouble cancelling that. Let me connect you with our manager." |

`cancel_reservation_already_canceled` requires a **secondary probe**
`_find_recent_reservation_any_status` because `_find_modifiable_reservation`
filters on `status='confirmed'` — without the secondary probe the
customer hits the generic `no_target` line even when a row exists.
This mirrors B2's `_find_recent_settled_order` pattern.

`cancel_reservation_already_fulfilled` and `_no_show` are not modeled
as distinct hints in V1 — both fall under `cancel_reservation_no_target`
because the typical voice-call window (within minutes of booking) makes
fulfilled / no_show effectively impossible to encounter. If we ever
need precision, it can be added in V2.

---

## 4. Tool schema (Voice Engine ↔ Gemini)

**File**: `backend/app/skills/scheduler/reservation.py` (alongside
`RESERVATION_TOOL_DEF` and `MODIFY_RESERVATION_TOOL_DEF`).

```python
CANCEL_RESERVATION_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "cancel_reservation",
            "description": (
                "Cancel a customer's just-made reservation. "
                "Use ONLY when the customer EXPLICITLY says 'cancel my "
                "reservation', 'cancel that reservation', 'cancel the "
                "booking', or accepts a cancel offer after "
                "reservation_too_late. "
                "PRECONDITIONS: "
                "(a) the customer has clearly stated cancel intent for the "
                "    RESERVATION (not an order), "
                "(b) you have recited 'Just to confirm — you want to cancel "
                "    your reservation for [party of N, day Month D at HH:MM] "
                "    — is that right?' using the reservation summary from "
                "    this call's most recent successful make_reservation "
                "    or modify_reservation, "
                "(c) the customer has said an explicit verbal yes to that "
                "    recital. "
                "Do NOT pass customer_phone, customer_name, reservation_id, "
                "or any other field — the system identifies the target via "
                "the inbound caller ID. NEVER say 'I've cancelled that for "
                "you' without actually calling this tool. If no active "
                "reservation exists, the bridge will respond accordingly "
                "and you must NOT retry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set to true ONLY after the customer has verbally "
                            "said 'yes' to your cancel-reservation recital. "
                            "False or missing = do not call."
                        ),
                    },
                },
                "required": ["user_explicit_confirmation"],
            },
        }
    ]
}
```

`customer_phone`, `customer_name`, `reservation_id`, `reservation_date`,
etc. are **deliberately absent** — the bridge looks the reservation up
from the caller-id. This kills phone-hallucination at the source and
prevents Gemini from inventing a reservation to cancel.

---

## 5. Bridge flow (`flows.cancel_reservation`)

**File**: `backend/app/services/bridge/flows.py` (next to
`modify_reservation`).

```python
async def cancel_reservation(
    *,
    store_id:          str,
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
) -> dict[str, Any]:
    """Cancel the most-recent confirmed reservation for this caller.
    (이 caller의 최근 confirmed 예약 취소 — Phase 2-C.B4)
    """
    # 1. Locate target (most-recent confirmed only).
    target = await _find_modifiable_reservation(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )

    # 2. If no in-flight, look for an already-cancelled most-recent row
    #    so we can return cancel_reservation_already_canceled rather
    #    than the generic no_target line. Mirrors B2's settled probe.
    if not target:
        recent = await _find_recent_reservation_any_status(
            store_id       = store_id,
            customer_phone = caller_phone_e164,
        )
        if recent and recent.get("status") == "cancelled":
            return {
                "success":        False,
                "reason":         "cancel_reservation_already_canceled",
                "reservation_id": recent["id"],
                "ai_script_hint": "cancel_reservation_already_canceled",
            }
        return {
            "success":        False,
            "reason":         "cancel_reservation_no_target",
            "ai_script_hint": "cancel_reservation_no_target",
        }

    # 3. PATCH status → 'cancelled'. _update_reservation_status is a new
    #    minimal helper that only writes status (vs B3's diff helper).
    ok = await _update_reservation_status(
        reservation_id = target["id"],
        new_status     = "cancelled",
    )
    if not ok:
        log.error("cancel_reservation: PATCH failed id=%s", target["id"])
        return {
            "success":        False,
            "reason":         "cancel_reservation_failed",
            "reservation_id": target["id"],
            "ai_script_hint": "cancel_reservation_failed",
        }

    log.warning("reservation_cancelled id=%s prior_status=%s",
                target["id"], target.get("status"))

    # 4. Build human summary for the voice handler's success line.
    cancelled_summary = _format_reservation_summary(target)

    return {
        "success":           True,
        "reservation_id":    target["id"],
        "prior_status":      target.get("status"),
        "cancelled_summary": cancelled_summary,
        "ai_script_hint":    "cancel_reservation_success",
    }
```

**Helpers**:
- `_find_modifiable_reservation` (reused as-is from B3 — status='confirmed' filter)
- `_find_recent_reservation_any_status` (NEW — same SQL, `status` filter dropped, LIMIT 1)
- `_update_reservation_status` (NEW — minimal PATCH writing only `status`; see note below)
- `_format_reservation_summary(row)` (NEW pure helper — `f"party of {N} on {date_human} at {time_12h}"`)

**Note on `_update_reservation_status`**: B3's `_update_reservation`
takes a diff dict shaped like `{column: {old, new}}`. Reusing it for
cancel would force callers to construct a fake diff — clearer to add a
single-purpose helper that PATCHes one column. Both helpers share the
same Supabase REST shape and headers.

---

## 6. Voice Engine integration (`voice_websocket.py`)

### 6a. Tool registration

In `_stream_gemini_response` session init: add `CANCEL_RESERVATION_TOOL_DEF`
to the `tools=[...]` list alongside `RESERVATION_TOOL_DEF`,
`MODIFY_RESERVATION_TOOL_DEF`, `ORDER_TOOL_DEF`, `MODIFY_ORDER_TOOL_DEF`,
`CANCEL_ORDER_TOOL_DEF`.

### 6b. AUTO-FIRE gate — extend the tool tuple (line ~1047)

```python
if tool_name in ("create_order", "make_reservation", "modify_order",
                 "cancel_order", "modify_reservation",
                 "cancel_reservation") and not force_tool_use:
```

### 6c. AUTO-FIRE recital builder branch (line ~1178)

Add a new branch parallel to `cancel_order`. Cancel tool args carry no
reservation data (caller-id lookup only), so pull the summary from the
session snapshot populated by the most recent successful
`make_reservation` / `modify_reservation`.

```python
elif tool_name == "cancel_reservation":
    sess_summary = (session or {}).get("last_reservation_summary") or ""
    if sess_summary:
        recital = (f"Just to confirm — you want to cancel your reservation "
                   f"for {sess_summary} — is that right?")
    else:
        recital = ("Just to confirm — you want to cancel your reservation "
                   "— is that right?")
```

The empty-snapshot branch is the equivalent of B2's "no in-flight
order" fallback — bridge will return `cancel_reservation_no_target`
right after the FORCE TOOL fires.

### 6d. Tool dispatcher branch (line ~1637, after `modify_reservation`)

```python
elif tool_name == "cancel_reservation":
    bridge_result = await bridge_flows.cancel_reservation(
        store_id          = store_id,
        caller_phone_e164 = caller_phone_e164,
        call_log_id       = call_log_id,
    )
    hint = bridge_result.get("ai_script_hint", "cancel_reservation_failed")
    template = CANCEL_RESERVATION_SCRIPT_BY_HINT.get(
        hint,
        "Sorry, I had trouble cancelling that. Let me connect you with our manager.",
    )
    try:
        script = template.format(
            cancelled_summary=bridge_result.get("cancelled_summary",
                                                "your reservation"),
        )
    except (KeyError, IndexError):
        script = template
    result = {
        "success":        bool(bridge_result.get("success")),
        "reservation_id": bridge_result.get("reservation_id"),
        "prior_status":   bridge_result.get("prior_status"),
        "reason":         bridge_result.get("reason"),
        "message":        script,
        "error":          bridge_result.get("error", ""),
    }
    # Snapshot reset on success — the reservation is gone, don't recite
    # it again on a follow-up cancel attempt.
    if session is not None and bridge_result.get("success"):
        session["last_reservation_summary"] = ""
```

### 6e. `session["last_reservation_summary"]` — set on
make/modify success (mirrors `last_order_items`)

Two write sites:

1. After `make_reservation` bridge success
   (around line 1265, in the `if bridge_result.get("success"):` branch):
   ```python
   if session is not None:
       try:
           session["last_reservation_summary"] = (
               f"party of {int(tool_args.get('party_size') or 0)} "
               f"on {format_date_human(tool_args['reservation_date'])} "
               f"at {format_time_12h(tool_args['reservation_time'])}"
           )
       except Exception:
           pass
   ```

2. After `modify_reservation` bridge success — refresh from `tool_args`
   (the modify dispatcher already has full payload):
   ```python
   if session is not None and bridge_result.get("success"):
       try:
           session["last_reservation_summary"] = (
               f"party of {int(tool_args.get('party_size') or 0)} "
               f"on {format_date_human(tool_args.get('reservation_date',''))} "
               f"at {format_time_12h(tool_args.get('reservation_time',''))}"
           )
       except Exception:
           pass
   ```

3. Initialize the field in the `sess = {...}` dict at line ~1750:
   ```python
   "last_reservation_summary": "",
   ```

### 6f. System prompt rule 4 update — Issue χ resolution

Current rule 4 says (commit `af590fa`):
> AFTER reservation_too_late: ... cancel_reservation tool does not
> exist yet (B4 pending); until it lands, just acknowledge and offer
> to transfer to a manager.

Replace with:
> AFTER reservation_too_late: when the bridge returns
> reservation_too_late, your message must OFFER cancel as an option
> ("I can cancel it for you instead — would you like that?"). DO NOT
> auto-fire cancel_reservation. Wait for the customer's EXPLICIT
> verbal yes ('yes, cancel it', 'cancel the reservation', 'go ahead
> and cancel'). A bare 'oh, okay' or 'I see' or 'hmm' after a too-late
> rejection is NOT a cancel intent. ALSO: the cancel_order tool
> applies ONLY to pickup orders — never use cancel_order for a
> reservation. Use cancel_reservation.

Add a new rule entry (rule 4b — same numeric, separate paragraph or
bullet) **after** the modify/info-update paragraphs, **before** rule 5:

> CANCEL RESERVATION (cancel_reservation): Call this ONLY when the
> customer EXPLICITLY says 'cancel my reservation', 'cancel that
> reservation', 'cancel the booking', or 'yes, cancel it' in response
> to a too-late offer. BEFORE calling, recite ONCE: 'Just to confirm —
> you want to cancel your reservation for [party of N on day Month D
> at HH:MM] — is that right?' using the reservation summary from this
> call's most recent successful make_reservation or modify_reservation
> tool result — NOT from any rejected attempt. On the explicit verbal
> yes, call cancel_reservation with user_explicit_confirmation=true.
> NEVER say 'I've cancelled that for you', 'cancelled', 'gone ahead
> and cancelled' UNLESS cancel_reservation returned success — this is
> a TRUTHFULNESS INVARIANT (same severity as I1/I2/I3). After
> cancel_reservation_success, the call is essentially over — close
> with the tool's message verbatim and stop. cancel_reservation does
> NOT cancel pickup orders; cancel_order does NOT cancel reservations
> — pick the right tool by which one was just made.

### 6g. INVARIANTS reuse

I1 (items) doesn't apply (no items in cancel_reservation args).
I2 (customer name) doesn't apply (no customer_name in args).
I3 (status truthfulness) applies as-is — never say "your reservation
has been cancelled" before the tool returns success.

---

## 7. Customer-facing scripts (`order.py:CANCEL_RESERVATION_SCRIPT_BY_HINT`)

**File**: `backend/app/skills/order/order.py` (alongside existing
script maps).

```python
CANCEL_RESERVATION_SCRIPT_BY_HINT: dict[str, str] = {
    "cancel_reservation_success": (
        "Got it — your reservation for {cancelled_summary} has been "
        "cancelled. Hope to see you another time!"
    ),
    "cancel_reservation_no_target": (
        "I don't see an active reservation under your number. Is there "
        "something else I can help with?"
    ),
    "cancel_reservation_already_canceled": (
        "That reservation has already been cancelled. Anything else I "
        "can help with?"
    ),
    "cancel_reservation_failed": (
        "Sorry, I had trouble cancelling that. Let me connect you with "
        "our manager to sort it out."
    ),
}
```

The `{cancelled_summary}` placeholder is `.format()`-substituted in the
dispatcher with the value the bridge returns.

---

## 8. Test plan (TDD — written before any production code)

### Bridge tests (`tests/unit/services/bridge/test_cancel_reservation.py`)

| # | Scenario | Expected |
|---|---|---|
| T1 | No reservation under caller's phone (both probes empty) | `success=False`, `reason=cancel_reservation_no_target`, `ai_script_hint=cancel_reservation_no_target`, no PATCH |
| T2 | Already cancelled (modifiable probe empty, recent probe returns cancelled row) | `success=False`, `reason=cancel_reservation_already_canceled`, `ai_script_hint=cancel_reservation_already_canceled`, no PATCH |
| T3 | Happy path — confirmed → cancelled | `success=True`, `prior_status='confirmed'`, `cancelled_summary` non-empty, `ai_script_hint=cancel_reservation_success`, PATCH called once with status=cancelled |
| T4 | Most-recent policy — multiple confirmed, only newest is cancelled | `success=True`, `reservation_id` matches the newer row |
| T5 | Idempotent re-hit — second call after success returns already_canceled | First call success; second call (probe returns cancelled row) returns `cancel_reservation_already_canceled` |
| T6 | DB PATCH returns False | `success=False`, `reason=cancel_reservation_failed` |
| T7 | Too-late allowed (Option α) — reservation 5 min away → still cancellable | `success=True`. No reservation_too_late guard exists in cancel path. |

### Voice integration tests (`tests/unit/adapters/test_cancel_reservation_voice.py`)

| # | Scenario | Expected |
|---|---|---|
| V1 | `CANCEL_RESERVATION_TOOL_DEF` exported, schema has only `user_explicit_confirmation` (no phone/name/id) | Importable; required==["user_explicit_confirmation"] |
| V2 | `CANCEL_RESERVATION_SCRIPT_BY_HINT` covers all 4 hints | All 4 keys present, each non-empty |
| V3 | AUTO-FIRE recital builder uses `session["last_reservation_summary"]` | Recital contains the summary; on empty session → generic "your reservation" fallback |
| V4 | System prompt rule 4 mentions `cancel_reservation` and the Issue χ guard wording is updated (no longer "tool does not exist yet") | `cancel_reservation` in prompt; "does not exist" NOT in the cancel_reservation paragraph |
| V5 | After successful `make_reservation` bridge call, `session["last_reservation_summary"]` is populated (integration smoke at the helper level) | The summary builder formats `party of N on <date> at <time>` correctly |

**Total: 7 bridge + 5 voice = 12 RED tests** before any production code.

---

## 9. Out of scope (deferred)

- **OpenTable / Resy / SevenRooms cancel sync** — Phase 2-D (post-launch).
- **SMS / email cancel confirmation to customer** — Twilio TCR pending;
  email template not yet built. V1 relies on the verbal in-call
  confirmation only.
- **Manager dashboard "cancelled today" widget** — separate feature.
- **Migration to `bridge_transactions`** — defer indefinitely; B4 keeps
  the legacy `reservations` table.
- **Reservation cancel cooldown** (suppress reflexive re-fires) —
  deferred to v2 if log shows the issue. (B3 didn't need one in
  practice; cancel hits a single tool only.)
- **Distinguishing fulfilled / no_show targets** — V1 collapses both
  into `cancel_reservation_no_target` because they're effectively
  unreachable in a typical voice-call window.

---

## 10. Risks / open questions

| Risk | Mitigation |
|---|---|
| Customer says "cancel" by mistake | AUTO-fire gate + cancel-specific recital ("you want to cancel your reservation for [summary] — is that right?") + FORCE TOOL signal (post-confirmation yes) — same triple-gate that protects make_reservation / modify_reservation. |
| Customer says "cancel" but the bot was talking about an order, not a reservation | System prompt 6f explicitly disambiguates — cancel_order vs cancel_reservation by which tool was just used. Ambiguity in mixed flows (order + reservation in same call) is mitigated by the recital, which names the reservation summary; if it doesn't match what the customer expected, they say "no, the order". |
| `session["last_reservation_summary"]` empty on first cancel attempt (no prior make/modify in this call) | Recital falls back to generic "your reservation"; bridge looks the row up via caller-id and either succeeds or returns `cancel_reservation_no_target`. Both outcomes are acceptable — the generic recital still serves as an explicit confirmation gate. |
| Multiple confirmed reservations under same phone (different stores or different days) | Most-recent policy via `created_at DESC LIMIT 1`. Same as B3. |
| Customer cancels and immediately re-books in the same call | After cancel success we wipe `last_reservation_summary`. A subsequent `make_reservation` will repopulate it. |
| Race: cancel arrives while a modify is mid-flight | Both go through the same most-recent confirmed row. The later one wins. PATCH is atomic at the row level. |
| `reservations.status` enum doesn't include 'cancelled' | Verified via Phase 2-A schema and DB CHECK migrations — `cancelled` is one of {confirmed, cancelled, fulfilled, no_show}. No migration needed. |

---

## Decisions locked (2026-05-02, customer-confirmed this session)

| # | Decision |
|---|---|
| 1 | **Option α — always allow cancel** (no too-late guard). Reservations have no irreversible kitchen-side effect; freeing the slot is a win for the restaurant. |
| 2 | **`session["last_reservation_summary"]` field** added — mirrors `last_order_items` pattern. Populated on make/modify success, wiped on cancel success. |
| 3 | **Caller-id only schema** — no phone/name/id in args, kills hallucination class. |
| 4 | **No SMS/email cancel confirmation in V1** — verbal in-call confirmation only. |
| 5 | **`fulfilled` / `no_show` collapse into `no_target`** — V1 simplification; precision deferred. |

---

## Implementation order

1. ✅ This spec doc (current step).
2. Write 12 RED tests (7 bridge + 5 voice).
3. Implement `flows.cancel_reservation` + helpers until T1-T7 GREEN.
4. Implement voice integration until V1-V5 GREEN.
5. Add `CANCEL_RESERVATION_SCRIPT_BY_HINT` map.
6. System prompt rule 4 update (Issue χ resolution + new cancel_reservation rule).
7. Live-call validation — full English turn-by-turn scenario covering happy
   path + each failure mode + post-too-late cancel + re-cancel idempotency.
8. PDF archive: `docs/test-scenarios/<date>/reservation_cancel_<date>_T<hhmm>.{html,pdf}`.
