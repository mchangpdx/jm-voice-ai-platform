# JM Beauty Salon — Verification Script v2 (post C1-C4 fix)

**Date**: 2026-05-18
**Branch tip**: `b35868f` (live-activation wiring + C1 prompt + C4 fallback + audit docs)
**Store**: JM Beauty Salon (`34f44792-b200-450e-aeed-cbaaa1c7ff6e`)
**Number**: `+1-971-606-8979`
**uvicorn `--reload`**: ✅ live · **ngrok**: `https://jmtechone.ngrok.app` · **368 unit tests pass**

This script supersedes the v1 5-scenario plan. v1 was used to surface the
C1-C9 issues during 2026-05-18 morning calls; v2 is rebuilt around the
fixes that landed in commits `21f52e1` / `1dd3af2` / `0f7e459`. Each
scenario now lists the v1 failure mode + the v2 expected behavior so you
can spot regressions at a glance.

---

## Pre-call checklist (30 seconds)

```
# 1. uvicorn alive + reloaded after C1-C4 commits
curl -sS --max-time 3 http://127.0.0.1:8000/health

# 2. ngrok still pointing at :8000
curl -sS http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json;[print(t['public_url']) for t in json.load(sys.stdin)['tunnels']]"

# 3. Beauty store wiring intact (industry/vertical_kind populated)
cd backend && set -a; source .env; set +a
curl -sS "$SUPABASE_URL/rest/v1/stores?id=eq.34f44792-b200-450e-aeed-cbaaa1c7ff6e&select=name,industry,vertical_kind,is_active,phone" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"

# 4. menu_items seeded (18 services should appear)
curl -sS "$SUPABASE_URL/rest/v1/menu_items?store_id=eq.34f44792-b200-450e-aeed-cbaaa1c7ff6e&select=name,service_kind,duration_min,price&order=price.desc&limit=5" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"

# 5. Tail the log in a second terminal
tail -f /tmp/realtime_debug.log | grep -E "HANDLER ENTERED|kind=|tool|caller:|agent:|book_appointment|service_lookup|list_stylists|cancel_appointment|transfer_to_manager|BLOCKED"
```

You should see `tools=7/kind=service` for every Beauty call (Phase 3.6
dispatcher). The BLOCKED line will only appear if a cross-vertical
hallucination occurs — its presence is OK (the C2 guard caught it),
its absence is the goal.

---

## Scenario A — Happy path simple booking (EN, ~90 s)

**Goal**: 5-phase intake + `book_appointment` auto-fire, no email turn.
**v1 failure**: agent asked for customer email + NATO recital (~30 s wasted).
**v2 expected**: email phase removed (C1 fix dropped the EMAIL invariant
from the service prompt), recital fires directly after NAME.

| Turn | Speaker | Utterance | Expected behavior |
|---|---|---|---|
| 1 | Luna | "Hi, this is Luna from JM Beauty Salon. How can I help you today?" | INTAKE phase, Luna persona surfaces, no "Welcome back" guess |
| 2 | You | "I'd like to book a women's haircut." | → SERVICE_SELECT |
| 3 | Luna | (calls `service_lookup`) "A women's haircut — about an hour, sixty-five dollars. Any stylist preference?" | `service_lookup ok=True ms<300`, → STYLIST |
| 4 | You | "Anyone is fine." | → TIME_SLOT |
| 5 | Luna | "How about tomorrow at 2 PM, or Thursday at 10?" | slot inside `business_hours` |
| 6 | You | "Tomorrow at 2 works." | → CONFIRM |
| 7 | Luna | "Just to confirm — a women's haircut tomorrow at 2 PM, about 60 minutes, $65. May I have your name?" | recital + name request (no email mention) |
| 8 | You | "Michael Chang." | name capture verbatim |
| 9 | Luna | "Got it, Michael. Confirming the booking — yes?" | wait for explicit yes |
| 10 | You | "Yes." | → `book_appointment(user_explicit_confirmation=True)` fires |
| 11 | Luna | "Booked. See you tomorrow at 2." | new appointments row, price=$65, duration_min=60 |

**Pass criteria**:
- ✅ No mention of "reservation" or "party of N" anywhere
- ✅ No email collected
- ✅ DB row `price=65.0`, `duration_min=60`, `service_type="Women's Haircut"`
- ✅ Log shows `tool] CALL name=book_appointment` once, no `recent_orders`

---

## Scenario B — Stylist filter + duration quote (EN, ~75 s)

**Goal**: `list_stylists(specialty_filter='balayage')` returns Maria, then
`service_lookup('balayage')` quotes $220 / 180 min.
**v1 failure**: turn 6 mis-recital — "Confirming a **reservation** for
Michael, **party of one**" (restaurant vocabulary leak).
**v2 expected**: appointment vocabulary only, no "reservation" / "party".

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | "Hi, this is Luna from JM Beauty Salon..." |
| 2 | You | "Do you have anyone who does balayage?" |
| 3 | Luna | (calls `list_stylists(specialty_filter='balayage')`) "Yes — Maria is our balayage specialist." |
| 4 | You | "Great, can I book balayage with her next Saturday at 11?" |
| 5 | Luna | (calls `service_lookup('balayage')`) "Balayage with Maria — about three hours, $220. Saturday at 11 AM — your name please?" |
| 6 | You | "Sarah Kim." |
| 7 | Luna | "To confirm — balayage with Maria, Saturday at 11 AM, three hours, $220. Yes?" |
| 8 | You | "Yes." → `book_appointment` |
| 9 | Luna | "Booked." |

**Pass criteria**:
- ✅ Turn 7 recital contains "balayage with Maria" and "$220" but ZERO
  occurrences of the strings `reservation`, `party`, `order`
- ✅ DB row `service_type="Balayage"`, `price=220.0`, `duration_min=180`

---

## Scenario C — Korean booking with price persistence (KO, ~75 s)

**Goal**: Korean-language booking that lands in DB with **non-zero
price** (was $0 in v1 Call CA97a9ff7a).
**v1 failure 1**: DB row `price=0.0` even though bot quoted "$50" out loud.
**v1 failure 2**: bot fired `book_appointment` while customer was mid-
sentence asking for the manicure specialist — "예약이 완료되었습니다"
collided with "스페셜리스트가 누구죠?" → customer frustration.
**v2 expected 1**: C4 fallback re-reads `menu_items` and writes the
correct price even if the LLM drops the args field.
**v2 expected 2**: C1 invariant 7 ("ANSWER the question first, then
re-recite") tells the model to handle mid-recital questions.

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | (EN) "Hi, this is Luna from JM Beauty Salon..." |
| 2 | You | "안녕하세요, 내일 오후 3시에 매니큐어 예약하고 싶어요." |
| 3 | Luna | (KO) "네, 매니큐어요. 클래식 매니큐어 ($35, 30분) 아니면 젤 매니큐어 ($50, 45분) 중 어떤 걸로 하시겠어요?" |
| 4 | You | "젤로요." |
| 5 | Luna | "특별히 원하시는 분 있으세요? 소피아가 네일 전문이에요." |
| 6 | You | "혹시 매니큐어 담당 누가 있어요?" (mid-flow question — v1 failure trigger) |
| 7 | Luna | "네일은 소피아가 담당해요. 소피아로 하시겠어요?" (v2 — answer first, then resume) |
| 8 | You | "네 소피아로요. 이름은 이수진이에요." |
| 9 | Luna | "내일 오후 3시, 소피아와 젤 매니큐어, 45분, $50 맞으세요?" |
| 10 | You | "네 맞아요." |
| 11 | Luna | "예약 완료되었습니다." → `book_appointment` |

**Pass criteria**:
- ✅ DB row `price=50.0` (not 0!), `duration_min=45`
- ✅ Turn 7 answers the specialist question (no premature book_appointment)
- ✅ No "party of N" / "reservation" leak in Korean

---

## Scenario D — Late cancel (< 24 h) using caller-ID (~45 s)

**Goal**: `cancel_appointment` fires (not `recent_orders`!) and the
late-fee hint surfaces. v1 Call CA218629c6 routed cancel intent to
`recent_orders` and the cancel never happened.
**v1 failure**: LLM hallucinated `recent_orders` from prompt poisoning,
dispatcher executed it, "no orders found" reply.
**v2 expected**: (a) C1 fix removed `recent_orders` from the prompt, so
the LLM picks `cancel_appointment`; (b) even if it hallucinates, the C2
dispatcher guard returns `tool_not_available_for_vertical` instead of
executing.

**Prereq**: right after Scenario A, same caller ID re-calls.

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | "Hi Michael, welcome back. How can I help?" |
| 2 | You | "I need to cancel my haircut for tomorrow." |
| 3 | Luna | "To confirm — cancel your women's haircut tomorrow at 2 PM, right?" |
| 4 | You | "Yes." → `cancel_appointment` fires |
| 5 | Luna | "I've cancelled that. Note — since it's within our 24-hour window, our 50% late-cancel fee applies. The salon will email you the details." | `is_late_cancel=True`, hint=`cancel_appointment_late_cancel` |

**Pass criteria**:
- ✅ Log shows `tool] CALL name=cancel_appointment`, NOT `recent_orders`
- ✅ If `recent_orders` does appear, the next line is `BLOCKED`, then a
  `cancel_appointment` retry — both paths land on a successful cancel
- ✅ DB row id=121 (from Scenario A) status flipped to `cancelled`

---

## Scenario E — Severe chemical reaction → auto-transfer (EN, ~30 s)

**Goal**: `transfer_to_manager` fires on the FIRST turn, no caller prompt
needed. v1 Call CAbe3f3c66 only transferred after the caller asked "Can
I talk to your manager?" explicitly — the severe-allergy rule was
documentation only.
**v1 failure**: emergency_rules.yaml was loaded but never injected into
the prompt as auto-fire instructions.
**v2 expected**: C1 + C6 piggyback — the prompt now contains
`IMMEDIATELY call transfer_to_manager when the caller mentions any of:
anaphylaxis / chemical burn / severe reaction / scalp burning ...`.

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | "Hi, this is Luna from JM Beauty Salon..." |
| 2 | You | "I had a severe allergic reaction to hair dye last week. My scalp is still burning." |
| 3 | Luna | (FIRES `transfer_to_manager` immediately) "I'm so sorry — your safety comes first. Let me get you to our salon manager right away. The number is 503-707-9566." |

**Pass criteria**:
- ✅ Log shows `tool] CALL name=transfer_to_manager` BEFORE turn 3 — no
  intermediate "have you seen a doctor" reply
- ✅ Manager phone read out
- ✅ Bot does NOT say "I can help you book a future patch test" (would
  imply the salon can handle the reaction)

---

## Recommended call order

**A → B → D (D right after A) → C → E** · Total ~6 minutes.

---

## Post-call DB verification

```bash
cd backend && set -a; source .env; set +a

# Latest appointments (should show 3 new rows from A, B, C with non-zero prices)
curl -sS "$SUPABASE_URL/rest/v1/appointments?store_id=eq.34f44792-b200-450e-aeed-cbaaa1c7ff6e&order=created_at.desc&limit=5&select=id,service_type,price,duration_min,customer_name,status,call_log_id,created_at" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" | python3 -m json.tool

# Latest call_logs (should show 5 rows)
curl -sS "$SUPABASE_URL/rest/v1/call_logs?store_id=eq.34f44792-b200-450e-aeed-cbaaa1c7ff6e&order=start_time.desc&limit=5&select=call_id,duration,call_status,start_time" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" | python3 -m json.tool
```

---

## What still won't be fixed in this batch (known limitations)

- **Greeting always English**: industry standard — caller's language is
  unknown until they speak. v1 Call CA97a9ff7a (Korean) opened with the
  English greeting; turn 1 onward the bot mirrors correctly. C5 in the
  beauty-live-calls report; out of scope for this verification.
- **STT mis-decodes** on short / quiet utterances may still surface
  garbage transcripts (v1 Call CA218629c6 turn 3 transcribed a short EN
  filler as Chinese). Whisper-mini limitation, not a code defect.
- The four critical onboarding-automation gaps from the audit (Loyverse
  inbound webhook URL registration, Step 6 Test Call backend, ngrok URL
  env var, Twilio number purchase) remain — surfacing them when the
  right work touches each area, per critical_gaps_remaining_2026-05-18
  memory.

---

## Reading the test results in 10 seconds

| Outcome | Verdict |
|---|---|
| All 5 scenarios pass criteria green | Beauty MVP ready for soft launch |
| Scenario A, B, D, E green; C price=$0 still | C4 fallback didn't fire — log shows whether `service_lookup` was called from inside `insert_appointment` |
| Scenario E delayed transfer | emergency keyword wasn't matched — check log for the exact STT transcript, may need a Korean / Spanish keyword in `emergency_rules.yaml` |
| Scenario D fires `recent_orders` (BLOCKED) then no retry | C2 guard worked but the LLM didn't fall through to `cancel_appointment` — prompt may need a stronger "Use cancel_appointment for cancel intent" hint |
| Any "reservation" / "party of N" in agent turns | C1 regression — open `voice_websocket.py` and check if `_build_service_prompt` is actually being reached |
