# JM Beauty Salon — Live Verification Call Analysis (5 calls)

**Date**: 2026-05-18
**Store**: JM Beauty Salon (`34f44792-b200-450e-aeed-cbaaa1c7ff6e`)
**Number**: `+1-971-606-8979`
**Branch tip**: `968db05` + uncommitted Phase 5 wiring fixes
**Calls**: 5 (CA2bc67e8b, CAdb94554b, CA97a9ff7a, CA218629c6, CAbe3f3c66)
**Aggregate**: 568.0 s · 35 user turns · 7 tool calls · 3 appointments inserted

---

## 1. Headline finding (read this first)

**`build_system_prompt(beauty_store)` injects 30,334 bytes of overwhelmingly
order-vertical text**, then appends *one* `INTAKE FLOW` block at the end.
Token counts inside the live Beauty prompt:

| Token | Count | Should be |
|---|---:|---|
| `reservation` | 52 | 0 (restaurant term) |
| `order` | 98 | 0 |
| `create_order` | 16 | 0 |
| `make_reservation` | 7 | 0 |
| `cancel_order` | 14 | 0 |
| `recent_orders` | 5 | 0 |
| `party` | 9 | 0 (restaurant party-size) |
| `book_appointment` | **2** | many |
| `service_lookup` | **1** | many |
| `stylist` | **5** | many |
| `appointment` | **4** | many |
| `INTAKE FLOW` | 1 | ≥1 ✓ |

The dispatcher correctly hands the model only the 7 `SERVICE_KIND_TOOLS`,
but the prompt itself teaches the model an order-vertical world. Every
hallucination in this batch traces back to this gap. The Phase 3.6
split is half-done — tools are vertical-aware, the prompt builder is not.

---

## 2. Per-call summary

| # | Call SID | Lang | Dur | Turns | Verdict | Key issue |
|---|---|---|---:|---:|---|---|
| 2 | CA2bc67e8b | EN | 144 s | 12 | ✅ Booked | Asked for email — appointment-flow should not require email |
| 3 | CAdb94554b | EN | 102 s | 8 | ⚠️ Booked but mis-recited | "Confirming a **reservation** for Michael, **party of one**" |
| 4 | CA97a9ff7a | KO | 131 s | 9 | ⚠️ Booked but price=$0 + dropped stylist Q | EN greeting on KO call; price lost in args; final turn ignored stylist question |
| 5 | CA218629c6 | EN→ZH STT | 41 s | 3 | ❌ Cancel failed | `recent_orders` fired instead of `cancel_appointment`; "your number" wording for caller-ID |
| 6 | CAbe3f3c66 | EN | 55 s | 3 | ⚠️ Late escalation | `severe_chemical_reaction` rule did NOT auto-fire `transfer_to_manager` — only fired after explicit "Can I talk to your manager?" |

DB confirms 3 new `appointments` rows (id=121, 122, 123). Call 5 did not
cancel id=121 even though caller-ID matched. Call 6 ended with a manual
manager phone read-out, not an actual transfer.

---

## 3. Critical issues with severity + root cause

### 🔴 C1 — Order-vertical prompt poisoning (root cause of C2/C3/C5)
**Severity**: Highest
**Calls affected**: 3, 4, 5
**Evidence**: prompt token census in §1.
**Root cause**: `build_system_prompt` was written for order verticals
(cafe / pizza / mexican / kbbq). Phase 1.6 added an additive INTAKE FLOW
block but did NOT remove the order-vertical CART/TOTAL/NAME/EMAIL/RECITAL
section, the `create_order` / `make_reservation` / `cancel_order` /
`recent_orders` tool docs, or the "party of N" reservation recital
template. Service stores get all of it plus an INTAKE FLOW block at
position 99.5 %.
**Fix sketch**: branch `build_system_prompt` on `store.vertical_kind`.
For service-kind stores: skip ORDER tool docs, skip reservation recital
template, skip `recent_orders` instructions, use `appointment` /
`stylist` / `service` vocabulary throughout. Estimated 2-4 h.

### 🔴 C2 — `recent_orders` tool fires on a service store (Call 5)
**Severity**: High (cancel flow completely blocked)
**Evidence**: `06:42:29 [tool] CALL name=recent_orders ... DONE ok=True`
on a store whose dispatcher correctly returned `SERVICE_KIND_TOOLS` (7).
**Root cause two-layer**:
  1. Prompt mentions `recent_orders` 5×, training the LLM to call it.
  2. `_dispatch_tool_call` has no vertical guard — `if tool_name == "recent_orders":` branch runs regardless of store vertical. So even
     when the tool isn't in OpenAI's exposed list, if the LLM hallucinates
     a call, our dispatcher honors it.
**Fix sketch**:
  - C1 fix removes the prompt-side training.
  - Add a defense-in-depth guard at the dispatcher top: if `tool_name`
    not in `{t["function_declarations"][0]["name"] for t in
    get_tool_defs_for_store(store_row)}`, return `unsupported_tool` with
    a hint that surfaces a polite "I can't do that on this line" reply.
**Impact**: Beauty cancel flow nonexistent until fixed.

### 🟠 C3 — "Reservation" / "party of N" leaked into appointment recital (Call 3)
**Severity**: Medium (booking succeeds but operator confidence drops)
**Evidence**: turn 6 agent: *"Confirming a **reservation** for Michael,
**party of one**, next Saturday at 11 AM for a balayage with Maria"*.
**Root cause**: Same as C1. Prompt has 52 `reservation` mentions + 9
`party` mentions, all teaching restaurant recital style.
**Fix**: covered by C1.

### 🟠 C4 — Korean booking price lost in args (Call 4)
**Severity**: Medium
**Evidence**: DB row `id=123` Gel Manicure `price=0.0`. Tool dispatched
with `args_keys=[..., 'price', ...]` per log, but persisted price is 0.
**Suspected root cause**: LLM extracted "50달러" verbally but failed to
emit the numeric price in the `book_appointment` tool args (Korean
number parsing edge case). Need to inspect the raw tool args to
confirm whether `0` was sent or `None` and our validator coerced.
**Fix sketch**: tighten `validate_appointment_args` so a 0/missing
price falls back to a `service_lookup` re-read by `service_name`
inside `insert_appointment`, instead of silently persisting 0.

### 🟠 C5 — Greeting always English regardless of caller language (Call 4)
**Severity**: Medium
**Evidence**: Korean call's turn 0 agent: *"JM Beauty Salon, how can I
help you today?"* — even though our multilingual policy lists KO / JA /
ZH for Beauty (per session decision).
**Root cause**: Greeting is hard-coded (`_GREETING_PROMPT`) and fires
before the caller has spoken, so language can't yet be detected. The
recovery — switching to the caller's language on turn 1 — does work
(turn 1 agent replied in Korean). The greeting itself stays EN.
**Fix options**:
  - Accept current behavior (industry-standard — most multi-lingual
    voice agents greet in English then mirror).
  - Or: maintain a per-store `default_greeting_lang` column and
    parameterize the greeting.

### 🟠 C6 — `severe_chemical_reaction` did not auto-trigger `transfer_to_manager` (Call 6)
**Severity**: Medium (safety)
**Evidence**: turn 1 caller mentioned "severe allergic reaction" + "scalp
burning" — both keywords in `emergency_rules.yaml` `severe_chemical_reaction`.
Agent gave a polite medical-deferral reply but did NOT auto-fire
`transfer_to_manager`. Tool only fired when caller asked "Can I talk to
your manager?" in turn 2.
**Root cause**: `emergency_rules.yaml` is loaded by the validator but
nothing in `build_system_prompt` injects its trigger keywords into the
LLM prompt as auto-fire instructions. The yaml is currently
documentation, not behavior.
**Fix sketch**: inject `emergency_rules` rule summaries into the prompt
("Trigger transfer_to_manager IMMEDIATELY when caller says: anaphylaxis
/ chemical burn / severe reaction / scalp burning ...").

### 🟡 C7 — `book_appointment` recital includes "party of N" (Call 3)
**Severity**: Low (subset of C3)
**Already covered**: C3.

### 🟡 C8 — Email NATO recital required for appointment (Call 2 + 3 + 4)
**Severity**: Low (over-collection)
**Evidence**: Calls 2, 3, 4 all asked for customer email + NATO recital,
which is the order-vertical flow for pay-link delivery. Beauty
appointments don't need email at booking time — caller ID + name + slot
suffice. Adds ~30 s of friction per call.
**Fix**: covered by C1 (service-kind intake_flow should not require
EMAIL phase).

### 🟡 C9 — `recent_orders` reply leaked "your number" wording (Call 5)
**Severity**: Low
**Evidence**: turn 1 agent: *"I don't see any recent **orders** under
your number."* — "orders" is the wrong noun for an appointment store.
**Fix**: covered by C1.

---

## 4. Multilingual hallucination deep dive

User flagged Korean / other-language hallucinations. Detailed read:

**Call 4 (Korean) — actual hallucinations**:
- ❌ turn 1 agent: *"이름이랑 전화번호는 **지금 전화번호로 확인했고**"* — fabricated. The
  caller never provided a phone; agent inferred from caller-ID. Phrasing
  makes it sound like the caller already gave it.
- ❌ turn 8 agent: *"예약이 완료되었습니다."* — fired `book_appointment`
  while the caller was mid-sentence asking *"내일 매니큐어 담당자가
  스페셜리스트가 누구죠?"* (who's the manicure specialist tomorrow?).
  The agent ignored the stylist question and confirmed the booking.
  Caller turn 9 responded *"예, 무슨 말이에요 이게? 오케이, 네버마인드."*
  (yes, what are you saying? OK, never mind) — frustration signal.
- ❌ DB row price=0 (see C4).

**Call 5 (EN with ZH STT artifact)**:
- ❌ caller turn 3 transcribed as *"哦,可以再往來拜。"* — this is the
  STT model mis-decoding *"oh, OK that's all then bye"* (or similar) as
  Chinese. Not the bot's hallucination but a STT failure on a
  short / quiet utterance. Acceptable for whisper-mini on PSTN.

**Call 4 — what worked well in Korean**:
- ✅ Name capture (장형석) verbatim, no Anglicization.
- ✅ NATO recital readback in mixed Korean+English (*"C as in Charlie ...
  맞나요?"*).
- ✅ Service / time / duration / price recited in Korean.
- ✅ Final confirmation prompt in Korean.

**Summary**: The Korean *language* handling is solid. The Korean *booking*
fails on (a) price=0 persistence (C4) and (b) ignored mid-sentence
follow-up question (consequence of C1 — prompt biases toward closing the
order ASAP, no "answer pending questions before book" rule for service
verticals).

---

## 5. What actually worked

- ✅ Phase 3.6 dispatcher routing: every call logged `tools=7/kind=service`.
- ✅ phone → store_id (`+19716068979` → JM Beauty Salon) every call.
- ✅ `service_lookup`: 4/4 fuzzy matches correct.
- ✅ `list_stylists(specialty_filter='balayage')` → Maria, 28 ms (Call 3).
- ✅ `book_appointment` async insert: 3/3 succeeded, 494 / 492 / 526 ms.
- ✅ `transfer_to_manager`: did fire when explicitly requested.
- ✅ Caller-ID auto-inject on Korean call (no phone re-ask).

---

## 6. Fix priority ranking

| # | Issue | Severity | Effort | Order |
|---|---|---|---:|---:|
| 1 | C1 + C3 + C7 + C8 + C9 — vertical-aware `build_system_prompt` | 🔴 Highest | 2-4 h | 1 |
| 2 | C2 — dispatcher vertical guard (defense in depth) | 🔴 High | ~30 min | 2 |
| 3 | C6 — `emergency_rules` keyword injection into prompt | 🟠 Medium | ~1 h | 3 |
| 4 | C4 — price re-fetch fallback in `insert_appointment` | 🟠 Medium | ~30 min | 4 |
| 5 | C5 — per-store `default_greeting_lang` | 🟡 Low | ~1 h | 5 |

**Estimated total to make Beauty production-quality**: 5-7 h.

---

## 7. Recommended next action (single decision)

**Fix #1 (C1) first** — vertical-aware prompt builder. It collapses 5 of
the 9 observed issues (C1 / C3 / C7 / C8 / C9) and unblocks every
Korean / Spanish / Japanese / Chinese booking. Without this, retesting
Beauty calls would surface the same restaurant-vocabulary problems and
the same wasted email-NATO turns.

After #1, ship #2 (dispatcher guard — fast and high-leverage), then
re-run the 5-scenario script to score Beauty for live release.

---

*Snapshot 2026-05-18. JM Beauty Salon live on `+1-971-606-8979`. Three
appointments persisted (id 121 / 122 / 123). One cancel flow failed
(no row touched). One severe-reaction escalation late by 1 turn.*
