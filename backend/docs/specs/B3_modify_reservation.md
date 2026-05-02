# B3 — `modify_reservation` Specification

**Phase**: 2-C.B3 (production launch blocker — Maple gap closer)
**Owner**: Bridge Server, Restaurant vertical
**Status**: spec → TDD tests → implementation
**Last updated**: 2026-05-02

---

## 1. Why

A customer who just made a reservation through the voice agent very
often follows up within 30–120 seconds with one of:

- "Actually, can we make it 7pm instead?"
- "Hold on — change it to 6 people."
- "Move it to tomorrow night, same time."
- "Add my husband — make it party of 4."

Without a modify path, the customer has to (a) refuse and force a
hang-up + redial + cancel-and-rebook (which we also can't do yet — that's
B4), or (b) leave the wrong reservation standing. Both are unacceptable
for a launch-grade restaurant phone agent.

Maple Inc. (competitor) ships modify_booking with depth 8/10
(OpenTable-backed). JM is currently 0/10 in this category. B3 closes
the single largest pre-launch reservation gap (#3 in the 35-scenario
restaurant survey, after B1 modify_order and B2 cancel_order).

---

## 2. Domain model (DDD)

| Concept | Type | Source of truth |
|---------|------|-----------------|
| `Reservation` | Aggregate root | `reservations` table |
| `ReservationDateTime` | Value object (date + time, TZ-aware) | `reservations.reservation_time` (timestamptz) |
| `PartySize` | Value object (1-20) | `reservations.party_size` |
| `CustomerName` | Value object | `reservations.customer_name` |
| `Notes` | Value object (special requests) | `reservations.notes` |
| `Status` | Enum | `reservations.status`: `confirmed` / `cancelled` / `fulfilled` / `no_show` |
| `ReservationModificationService` | Domain service | `app.services.bridge.flows.modify_reservation` |
| `BusinessHoursPolicy` | Domain service | `app.skills.scheduler.reservation` (existing helpers) |

`modify_reservation` is a **command** on a `Reservation` aggregate. It
mutates `ReservationDateTime`, `PartySize`, `CustomerName`, and/or `Notes`
in place and emits a `ReservationModified` domain event (audit row in
`reservation_events` if present, else log-only in v1). `Status` is
**invariant** under modification — only the four mutable fields change.

**Note on storage divergence from B1/B2**: orders live in
`bridge_transactions` (vertical='restaurant', pos_object_type='order'),
but reservations live in their own `reservations` table (legacy from
Phase 2-A). B3 v1 modifies the `reservations` table directly to keep
the change footprint small and avoid touching the make_reservation
write path. A future migration to `bridge_transactions` is out of
scope.

---

## 3. Preconditions / postconditions / invariants

### Preconditions (the bridge enforces all of these)

1. There exists a single most-recent `Reservation` for `(store_id,
   customer_phone)` in `status='confirmed'` — **most-recent policy**:
   `ORDER BY created_at DESC LIMIT 1`.
2. The caller's `caller_phone_e164` is server-side-derived (Retell
   `from_number`) — never trusted from Gemini args.
3. `reservation_time` is at least **30 minutes in the future** at the
   moment of the modify call. Otherwise → `reservation_too_late`.
4. The new payload (`new_*` fields) is **a full snapshot** — Gemini sends
   ALL four mutable fields; unchanged ones equal the current value. The
   bridge computes a diff to populate the audit event.
5. The new `reservation_time` (if changed) falls within
   `business_hours` for the new date. Otherwise → `outside_business_hours`.
6. The new `party_size` (if changed) is `1 ≤ party_size ≤ 20`. Otherwise
   → `party_too_large` (or `validation_failed` for ≤ 0).
7. The new `customer_name` (if changed) passes `is_placeholder_name()`
   from `flows.py` (rejects 'Customer', 'Guest', '(unknown)', etc.).
8. `user_explicit_confirmation == True` AND `force_tool_use == True`
   (AUTO-fire gate from F-2.E applies).

### Postconditions (on success)

- `reservations.{customer_name, reservation_time, party_size, notes}` are
  updated to the new values (only if they differ from current).
- `reservations.updated_at` is now (DB trigger or explicit `UPDATE`).
- A log line `reservation_modified store=… reservation_id=… diff=…` is
  written at WARNING level so it surfaces under uvicorn.
- Email confirmation is **re-sent via the email fallback path** (Twilio
  TCR pending — same path as `make_reservation` initial confirmation
  uses today). SMS path is deferred until TCR clears.

### Invariants

- `reservation_id` unchanged.
- `customer_phone` unchanged (caller-id never overwritten).
- `store_id` unchanged.
- `status` unchanged (`confirmed` stays `confirmed`).
- `created_at` unchanged.

### Failure modes (each gets its own `ai_script_hint`)

| Reason | `ai_script_hint` | Customer-facing wording |
|---|---|---|
| No active reservation found | `reservation_no_target` | "I don't see an active reservation under your number — would you like to make one?" |
| `reservation_time` < now + 30min | `reservation_too_late` | "That reservation starts in less than 30 minutes — I can't change it now. I can cancel it and we can rebook?" |
| New time outside business hours | `outside_business_hours` | "Sorry, that time is outside our hours. We're open [hours]. Want to try another time?" |
| `party_size` > 20 | `party_too_large` | "We don't seat parties over 20 by phone — let me connect you with our manager." |
| Placeholder name | `validation_failed` | "I'm missing your name — could you tell me the name on the reservation?" |
| Diff is empty (full payload == current) | `reservation_noop` | "Your reservation is unchanged at [original]. What would you like to change?" |
| Bad date/time format | `validation_failed` | "Sorry, I didn't catch the date — could you say it again?" |

---

## 4. Tool schema (Voice Engine ↔ Gemini)

**File**: `backend/app/skills/scheduler/reservation.py` (alongside
`RESERVATION_TOOL_DEF`).

```python
MODIFY_RESERVATION_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "modify_reservation",
            "description": (
                "Update a customer's just-made reservation. "
                "FULL-PAYLOAD CONTRACT: send ALL four mutable fields as a "
                "complete snapshot — for fields the customer is NOT changing, "
                "send the original value (which you recited earlier). "
                "Caller-id locates the most-recent confirmed reservation; "
                "DO NOT include reservation_id or customer_phone in args. "
                "INVARIANTS I1-I3 apply: every value MUST come from THIS "
                "call's transcript; no placeholders for customer_name. "
                "Only call AFTER the customer has verbally confirmed the "
                "updated reservation summary with an explicit 'yes'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": "Set true ONLY after the customer says yes to your updated summary.",
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Full name on the reservation. Send the SAME value as before if not changed.",
                    },
                    "reservation_date": {
                        "type": "string",
                        "description": "YYYY-MM-DD. Send the SAME value as before if not changed.",
                    },
                    "reservation_time": {
                        "type": "string",
                        "description": "24-hour HH:MM. Send the SAME value as before if not changed.",
                    },
                    "party_size": {
                        "type": "integer",
                        "description": "Party size 1-20. Send the SAME value as before if not changed.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Special requests. Send the SAME value as before if not changed; empty string if none.",
                    },
                },
                "required": ["user_explicit_confirmation",
                             "customer_name", "reservation_date",
                             "reservation_time", "party_size"],
            },
        }
    ]
}
```

**Note on full-payload vs delta**: B1 modify_order chose full-payload
(send the COMPLETE new items list, not a delta). B3 mirrors this for
consistency — fewer tool-args edge cases (Gemini doesn't have to
"remember" what was unchanged), and the diff computation lives entirely
in the bridge. Customer decision (2026-05-02): full payload.

---

## 5. Bridge flow (`flows.modify_reservation`)

**File**: `backend/app/services/bridge/flows.py` (next to `modify_order`).

```python
async def modify_reservation(
    *,
    store_id: str,
    args: dict[str, Any],
    caller_phone_e164: str,
    call_log_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Update a just-made reservation (party size, time, date, name, notes).
    Most-recent policy: same caller + same store + status='confirmed',
    ORDER BY created_at DESC LIMIT 1.
    """
    # 1. Validate args (full payload — all 5 required fields present)
    # 2. Reject placeholder customer_name (is_placeholder_name)
    # 3. Validate party_size (1-20)
    # 4. Combine new_date + new_time → reservation_time_iso (raises on bad format)
    # 5. Locate target reservation (caller-id, status='confirmed', most-recent)
    #    → if none: reservation_no_target
    # 6. State guard: new reservation_time_iso vs now + 30min
    #    → if too soon: reservation_too_late
    # 7. Cross-check business_hours for the new date
    #    → if outside: outside_business_hours
    # 8. Compute diff: which of {customer_name, reservation_time, party_size, notes}
    #    actually changed vs current row.
    #    → if no diff: reservation_noop
    # 9. UPDATE reservations row with new values (only changed columns)
    # 10. Log warning("reservation_modified id=%s diff=%s", id, diff_dict)
    # 11. Re-send email confirmation (existing Twilio email fallback path)
    # 12. Return:
    #     {
    #       "success": True,
    #       "reservation_id": <id>,
    #       "diff": {<field>: {old, new}, ...},
    #       "new_summary": "party of N, <date_human> at <time_12h>",
    #       "ai_script_hint": "modify_success",
    #     }
```

**Helpers reused** (no new code):
- `validate_reservation_args` (existing)
- `combine_date_time`, `format_time_12h`, `format_date_human` (existing)
- `normalize_phone_us` (existing)
- `is_placeholder_name` (from `flows.py`, B1 shared constant)

---

## 6. Voice Engine integration (`voice_websocket.py`)

### 6a. Tool registration

In session init: `tools=[..., MODIFY_RESERVATION_TOOL_DEF, ...]` alongside
existing tools.

### 6b. AUTO-FIRE recital builder (line ~1075)

Add a new branch after `cancel_order`:

```python
elif tool_name == "modify_reservation":
    # Recite the full updated reservation summary built from tool_args
    # (full payload → all fields are present in args)
    name  = (tool_args.get("customer_name") or "").strip() or "you"
    date  = format_date_human(tool_args.get("reservation_date") or "")
    time_ = format_time_12h(tool_args.get("reservation_time") or "")
    party = int(tool_args.get("party_size") or 0)
    if is_placeholder_name(name):
        name = "you"
    recital = (f"Just to confirm — your updated reservation is for "
               f"{name}, party of {party}, on {date} at {time_} "
               f"— is that right?")
```

### 6c. Tool dispatcher branch (line ~1500)

```python
elif tool_name == "modify_reservation":
    bridge_result = await bridge_flows.modify_reservation(
        store_id          = store_id,
        args              = tool_args,
        caller_phone_e164 = caller_phone_e164,
        call_log_id       = call_log_id,
    )
    hint   = bridge_result.get("ai_script_hint", "validation_failed")
    script = MODIFY_RESERVATION_SCRIPT_BY_HINT.get(hint, "Sorry, I couldn't make that change.")
    yield script
```

### 6d. System prompt rule 4 extension

Extend the existing `4. RESERVATIONS (make_reservation)` rule:

```
4. RESERVATIONS — make_reservation / modify_reservation:
   ... (existing make_reservation rules)
   MODIFY: when the customer EXPLICITLY says they want to change a
   just-made reservation ('change the time to 7', 'make it 6 people
   instead', 'move it to tomorrow'), call modify_reservation with
   the FULL updated payload (send the unchanged fields too, with
   their original values). After modify success the booking is FINAL —
   never re-call. Hesitation alone ('wait', 'hold on') is NOT a modify.
   INFO UPDATES ARE NOT MODIFY: same carve-out as rule 6 — email/phone
   updates do not trigger modify_reservation.
```

### 6e. INVARIANTS reuse

I1 (items) doesn't apply (no items in reservations). I2 (customer name)
applies as-is — `is_placeholder_name` already guards this in the
bridge. I3 (status truthfulness) applies — never say "your reservation
has been changed" before the tool returns success.

---

## 7. Customer-facing scripts (`order.py:MODIFY_RESERVATION_SCRIPT_BY_HINT`)

**File**: `backend/app/skills/order/order.py` (alongside existing
script maps).

```python
MODIFY_RESERVATION_SCRIPT_BY_HINT: dict[str, str] = {
    "modify_success":         "Got it — your reservation is updated to {new_summary}. We'll see you then.",
    "reservation_no_target":  "I don't see an active reservation under your number — would you like to make one?",
    "reservation_too_late":   "That reservation starts in less than 30 minutes — I can't change it now. I can cancel it and we can rebook?",
    "reservation_noop":       "Your reservation is unchanged at {original_summary}. What would you like to change?",
    "outside_business_hours": "Sorry, that time is outside our hours. We're open {business_hours}. Want to try another time?",
    "party_too_large":        "We don't seat parties over 20 by phone — let me connect you with our manager.",
    "validation_failed":      "I'm missing something — could you tell me the new date, time, and party size?",
}
```

The `{new_summary}` and `{original_summary}` placeholders are formatted
in the dispatcher using `bridge_result.new_summary` /
`bridge_result.original_summary`.

---

## 8. Test plan (TDD — written before any production code)

### Bridge tests (`tests/unit/services/bridge/test_modify_reservation.py`)

| # | Scenario | Expected |
|---|---|---|
| T1 | No reservation under caller's phone | `success=False`, `reason=no_reservation_to_modify`, `ai_script_hint=reservation_no_target` |
| T2 | Reservation in `status='cancelled'` | Same as T1 (most-recent confirmed only) |
| T3 | `reservation_time` < now + 30 min | `reason=reservation_too_late` |
| T4 | New `party_size = 25` | `reason=party_too_large` |
| T5 | New `party_size = 0` | `reason=validation_failed` |
| T6 | New time outside business hours | `reason=outside_business_hours` |
| T7 | All `new_*` equal current values | `reason=reservation_noop` |
| T8 | Only `party_size` changed | `success=True`, diff shows party_size only |
| T9 | `customer_name='Customer'` (placeholder) | `reason=validation_failed` |
| T10 | Multiple active reservations under caller — most-recent only is targeted | `success=True`, only most-recent row updated |
| T11 | Idempotent re-hit (same args twice within 5 min) | Second call returns `reservation_noop` (diff is empty after first commit) |
| T12 | Date format invalid (`'tomorrow'` not YYYY-MM-DD) | `reason=validation_failed` |

### Voice integration tests (`tests/unit/adapters/test_modify_reservation_voice.py`)

| # | Scenario | Expected |
|---|---|---|
| V1 | AUTO-FIRE recital builder produces full reservation summary | Recital matches `Just to confirm — your updated reservation is for [name], party of [N], on [date] at [time] — is that right?` |
| V2 | Recital with placeholder name → falls back to "you" | Recital says "for you" |
| V3 | Dispatcher invokes `bridge_flows.modify_reservation` on `tool_name == "modify_reservation"` | Mock bridge called once with correct args |
| V4 | System prompt rule 4 includes modify_reservation guidance | `modify_reservation` and `INFO UPDATES ARE NOT MODIFY` both present |

**Total: 12 bridge + 4 voice = 16 RED tests** before any production code.

---

## 9. Out of scope (deferred)

- **OpenTable / Resy / SevenRooms sync** — Phase 2-D (post-launch).
- **Slot availability check** (conflict with another reservation) —
  v2; v1 trusts the customer's chosen time.
- **Waitlist** — separate feature, not part of B3.
- **Table assignment / section** — never been in scope.
- **SMS confirmation re-send** — Twilio TCR still pending; v1 uses
  email fallback only.
- **Migration to `bridge_transactions`** — defer indefinitely; B3 keeps
  the legacy `reservations` table.
- **Reservation modify cooldown** (suppress reflexive re-fires after a
  modify outcome) — deferred to v2 if log shows the issue.

---

## 10. Risks / open questions

| Risk | Mitigation |
|---|---|
| Customer says "change the time to 7" — is that 7am or 7pm? | System prompt rule 4 already requires explicit AM/PM in customer speech for make_reservation; reuse the same guidance for modify. |
| Same caller has multiple confirmed reservations (different stores or different days) | Most-recent policy via `created_at DESC LIMIT 1` — customer decision (2026-05-02). |
| Email confirmation flooding the inbox after rapid back-to-back modifies | Suppress re-send on `reservation_noop`. Future: per-reservation rate limit. |
| Gemini sends partial payload (e.g. omits `notes`) despite full-payload contract | Bridge defaults missing fields to current values — equivalent to "no change" for that field. Validation only on present required fields. |
| Customer names a date in the past ('Yesterday') | `combine_date_time` + business_hours guard rejects with `validation_failed`. |
| `created_at` ordering breaks when DB clock skews | Acceptable v1; reservations are typed seconds apart so ties are extremely rare. |

---

## Decisions locked (2026-05-02, customer-confirmed)

| # | Decision |
|---|---|
| 1 | **30-minute cutoff** for `reservation_too_late` — hard-coded in v1. |
| 2 | **Full payload** — Gemini sends all 5 mutable fields as a snapshot, bridge computes diff. |
| 3 | **Email fallback only** — SMS path deferred until Twilio TCR approval. |
| 4 | **Most-recent policy** — `ORDER BY created_at DESC LIMIT 1` for target identification. |

---

## Implementation order

1. ✅ This spec doc (current step).
2. Write 16 RED tests (12 bridge + 4 voice).
3. Implement `flows.modify_reservation` until T1-T12 GREEN.
4. Implement voice integration until V1-V4 GREEN.
5. Add `MODIFY_RESERVATION_SCRIPT_BY_HINT` map.
6. System prompt rule 4 extension.
7. Live-call validation: 1 test call covering modify happy path + each failure mode + INFO UPDATE carve-out.
8. PDF archive: `docs/test-scenarios/<date>/reservation_modify_<date>_T<hhmm>.{html,pdf}`.
