# JM Voice AI Platform — Automation Audit & Beauty Pre-Call Coverage

**Date**: 2026-05-18
**Scope**: (1) POS webhook automation state, (2) end-to-end new-store
onboarding automation rate (32-item census), (3) JM Beauty Salon
pre-live functional inventory + 5 turn-by-turn verification scripts.
**Branch tip**: `968db05` + uncommitted `_load_store_by_id` industry/
vertical_kind SELECT fix (Phase 3.6 wiring gap caught at activation).

---

## 1. POS Webhook Automation — Partial (Loyverse only)

| Direction | Status | Note |
|---|---|---|
| **Us → Loyverse** (menu push) | ✅ **Automated** | `push_menu_to_loyverse()` — wizard Step 5 opt-in toggle |
| **Us → Loyverse** (real-time order injection) | ✅ **Automated** | `loyverse_relay.relay_order()` fires on every confirmed order |
| **Loyverse → Us** (inbound webhook URL **registration**) | ❌ **Manual** | Operator must register in Loyverse Back Office. No `POST /webhooks` subscribe call in our code |
| **Loyverse → Us** (items / customers / inventory receiver) | ✅ **Automated** | `/api/webhooks/loyverse/{item,customers,inventory}` endpoints live |
| **SumUp PG webhook** | ❌ **Not implemented** | Separate sprint |
| **Quantic POS** | ❌ **Not implemented** | 2nd vertical (FSR) target |
| **Twilio voice webhook** | ✅ **Automated (A5)** | `update_voice_webhook()` — exercised live 2026-05-18 |

**Bottom line**: Twilio voice fully automated, Loyverse outbound fully
automated, Loyverse inbound webhook URL registration is the remaining
manual step on the POS side.

---

## 2. New Store Onboarding — 32-Item Census, **65.6 %** Automated

Weighting: full auto = 1.0, partial / operator-interactive = 0.5,
manual / missing = 0.0.

| # | Step | Status | Score |
|---|---|---|---:|
| **Infra prep (external)** | | | |
| 1 | Twilio number purchase | ❌ Manual (Twilio Console) | 0 |
| 2 | Loyverse API key + OAuth | ❌ Manual (operator) | 0 |
| **Wizard Steps 1-5 (operator UI)** | | | |
| 3 | Step 1 menu source upload (URL / PDF / screenshot) | ⚠️ Interactive | 0.5 |
| 4 | Step 2 AI extraction (Vision / OCR) | ✅ Auto | 1 |
| 5 | Step 3 item edit + normalize | ⚠️ Operator review | 0.5 |
| 6 | Step 4 modifier groups detection | ✅ Auto | 1 |
| 7 | Step 5 dry-run preview | ✅ Auto | 1 |
| 8 | `business_hours` input | ⚠️ Operator input | 0.5 |
| 9 | `manager_phone` input | ⚠️ Operator input | 0.5 |
| 10 | `vertical` selection | ⚠️ Operator input | 0.5 |
| **Finalize backend** | | | |
| 11 | DB `stores` INSERT | ✅ Auto | 1 |
| 12 | `menu_items` + `modifier_groups` + options seed | ✅ Auto | 1 |
| 13 | JWT → `owner_id` force (A2) | ✅ Auto | 1 |
| 14 | JWT → `agency_id` auto-lookup (A2) | ✅ Auto | 1 |
| 15 | Vertical default persona `system_prompt` (A6) | ✅ Auto | 1 |
| 16 | `business_hours` column set (A3) | ✅ Auto | 1 |
| 17 | `menu_cache` rebuild | ✅ Auto | 1 |
| 18 | `is_active=true` | ✅ Auto | 1 |
| 19 | **`vertical_kind` auto-set** | ❌ **`db_seeder` gap** ⚠️ | 0 |
| **POS integration** | | | |
| 20 | Loyverse menu push (outbound) | ✅ Auto (opt-in) | 1 |
| 21 | **Loyverse INBOUND webhook URL registration** | ❌ **Manual** | 0 |
| 22 | POS order injection (real time) | ✅ Auto | 1 |
| 23 | SumUp PG integration | ❌ Not implemented | 0 |
| **Voice routing** | | | |
| 24 | phone → store_id (DB lookup) | ✅ Auto | 1 |
| 25 | Twilio voice webhook auto-provision (A5) | ✅ Auto | 1 |
| 26 | Twilio URL per-env override (ngrok / prod) | ⚠️ ngrok hardcoded | 0.5 |
| **Multilingual** | | | |
| 27 | menu yaml `supported_langs` auto (vertical_kinds.yaml) | ✅ Auto | 1 |
| 28 | `system_prompt` multilingual block injection | ⚠️ Partial | 0.5 |
| **Frontend UX** | | | |
| 29 | Sidebar refetch on finalize (A4 CustomEvent) | ✅ Auto | 1 |
| 30 | **Step 6 Test Call auto outbound** | ❌ **Placeholder** | 0 |
| **Post-activation** | | | |
| 31 | Verification call (1) | ❌ Manual | 0 |
| 32 | Tier 2 audit log | ✅ Auto | 1 |

**Total: 21.0 / 32 = 65.6 %**

### Critical gaps (live-activation blockers, in order of severity)

1. **#19 `vertical_kind` not set in `db_seeder`** ⭐
   Service-kind verticals (beauty / spa / barber / auto / home) fall
   through to ORDER tools because `_resolve_store_id` returns a row
   whose `vertical_kind` is NULL → `get_tool_defs_for_store` defaults to
   `ORDER_KIND_TOOLS`. JM Beauty Salon 2026-05-18 activation needed a
   manual `PATCH` to unblock. **~5 min fix** in `db_seeder.finalize_store`.

2. **#21 Loyverse inbound webhook registration manual**
   Menu changes in Loyverse don't sync until an operator pastes the
   webhook URL into Loyverse Back Office. `POST` to the Loyverse
   developer API (`/developer/v1.0/webhooks`) is straightforward but
   not wired.

3. **#30 Step 6 Test Call placeholder**
   No auto outbound call from the wizard. Operator must dial manually.

4. **#26 ngrok URL hardcoded**
   `webhook_url = "https://jmtechone.ngrok.app/twilio/voice/inbound"`
   in `admin/onboarding.py:299`. Production needs env var.

5. **#1 Twilio number purchase manual**
   `AvailablePhoneNumbers` API can purchase by area code in one call;
   not wired.

### What full automation would look like

Fixing the 5 critical gaps above lifts the score to:
21.0 + 5.0 = **26.0 / 32 = 81 %**.

Items #2 (Loyverse OAuth), #3/#5 (operator review of menu), #8-10
(business_hours / manager_phone / vertical inputs), #31 (verification
call), #23 (SumUp not implemented) remain operator-touch by design —
no realistic automation path inside one sprint.

Practical ceiling = ~85 % auto, ~15 % operator-touch.

---

## 3. JM Beauty Salon — Pre-Live Functional Inventory

### 3.1 Active tools on this store (`SERVICE_KIND_TOOLS`, 7 tools)

| Tool | Purpose | Trigger |
|---|---|---|
| `book_appointment` | Create appointment | 5-phase intake complete + explicit "yes" |
| `modify_appointment` | Full-payload diff update | Same caller ID match |
| `cancel_appointment` | Cancel + 24 h late-fee hint | "cancel" keyword + recital |
| `service_lookup` | Quote duration + price | Service name spoken (mandatory before book) |
| `list_stylists` | Roster lookup, optional specialty filter | "who's available" / stylist name spoken |
| `allergen_lookup` | Chemical sensitivity / dye allergy lookup | "PPD allergy" / "dye reaction" |
| `transfer_to_manager` | Escalate to manager | Severe trigger fired |

### 3.2 5-Phase intake flow

INTAKE → SERVICE_SELECT → STYLIST → TIME_SLOT → CONFIRM (recital + book_appointment)

### 3.3 Emergency rules (5, all auto-detected)

1. `severe_chemical_reaction` — anaphylaxis / scalp burn / chemical burn keywords → `transfer_to_manager`
2. `previous_reaction_to_dye` — patch test offer
3. `late_cancel_attempt` (< 24 h) — policy notice
4. `same_day_walk_in_request` — next-slot offer
5. `double_booking_request` — book primary first, offer second

### 3.4 Service catalog (18 services across 5 categories)

- **Haircut** — Women's $65 / 60 m · Men's $45 / 30 m · Kids $30 / 30 m · Blowout $50 / 45 m
- **Color** — Single $95 / 90 m · Root touch-up $75 / 60 m · Highlights $160 / 150 m · **Balayage $220 / 180 m**
- **Treatment** — Deep condition $45 / 30 m · **Keratin $250 / 150 m** · Scalp $55 / 45 m
- **Nails** — Classic manicure $35 / 30 m · Gel $50 / 45 m · Classic pedi $45 / 45 m · Spa pedi $70 / 60 m
- **Spa** — Signature facial $120 / 60 m · Express facial $75 / 30 m · Brow wax $25 / 15 m

### 3.5 Stylists (4, with specialty cross-references to menu IDs)

| Stylist | Specialties |
|---|---|
| **Maria** | balayage / highlights / root_touchup / color_single / treatment_keratin |
| **Yuna** | haircut_women / haircut_men / haircut_kids / blowout / treatment_deep_condition |
| **Sophia** | manicure_classic / manicure_gel / pedicure_classic / pedicure_spa / nail_art |
| **Aria** | facial_signature / facial_express / waxing_brow / waxing_lip / waxing_full |

### 3.6 Modifier groups (5)

`hair_length`, `toner`, `blow_dry`, `polish`, `facial_addon`

### 3.7 Policies

- Late-cancel: < 24 h = **50 % fee**, no-show = **100 %**
- Deposit: balayage / highlights / keratin / color_single = **30 % non-refundable**
- Languages: EN / ES / KO / JA / ZH

---

## 4. Verification Scripts — 5 Turn-by-Turn Scenarios

### Scenario A — Happy path simple booking (EN, ~90 s)

**Goal**: 5-phase intake + `book_appointment` auto fire

| Turn | Speaker | Utterance | Expected behavior |
|---|---|---|---|
| 1 | Luna | "Hi, this is Luna from JM Beauty Salon. How can I help you today?" | INTAKE phase, store name + Luna persona |
| 2 | You | "I'd like to book a women's haircut, please." | → SERVICE_SELECT |
| 3 | Luna | (calls `service_lookup`) "A women's haircut — about an hour, sixty-five dollars. Do you have a stylist preference?" | `service_lookup` fires, → STYLIST |
| 4 | You | "Anyone is fine." | → TIME_SLOT |
| 5 | Luna | "How about tomorrow at 2 PM, or Thursday at 10?" | slot inside `business_hours` |
| 6 | You | "Tomorrow at 2 works." | → CONFIRM |
| 7 | Luna | "Just to confirm — a women's haircut tomorrow at 2 PM, about 60 minutes, $65. May I have your name?" | recital + name request |
| 8 | You | "Michael Chang." | name capture |
| 9 | Luna | "Got it, Michael. Confirming the booking — yes?" | wait for explicit yes |
| 10 | You | "Yes." | → `book_appointment(user_explicit_confirmation=True)` fires |
| 11 | Luna | "Booked. We'll see you tomorrow at 2." | new row in `appointments` table |

**Verify**: `tail /tmp/realtime_debug.log` → `book_appointment` tool
call + DB `appointments` new row.

### Scenario B — Stylist preference + service_lookup (EN, ~60 s)

**Goal**: `list_stylists` filter + Maria match

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | "Hi, this is Luna from JM Beauty Salon..." |
| 2 | You | "Do you have anyone who does balayage?" |
| 3 | Luna | (calls `list_stylists(specialty_filter='balayage')`) "Yes — Maria is our balayage specialist." |
| 4 | You | "Great, can I book balayage with her next Saturday at 11?" |
| 5 | Luna | (calls `service_lookup('balayage')`) "Balayage with Maria — that's about 3 hours, $220. Saturday is one of our busier days — does 11 AM still work for you?" |
| 6 | You | "Yes." |
| 7 | Luna | "And your name?" |
| 8 | You | "Sarah Kim." |
| 9 | Luna | "To confirm — balayage with Maria, Saturday at 11 AM, 3 hours, $220. Yes?" |
| 10 | You | "Yes." → `book_appointment` |

### Scenario C — Korean booking (~75 s)

**Goal**: Multilingual + Korean name capture

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | (EN) "Hi, this is Luna from JM Beauty Salon..." |
| 2 | You | "안녕하세요, 내일 오후 3시에 매니큐어 예약하고 싶어요." |
| 3 | Luna | (KO) "네, 매니큐어요. 클래식 ($35, 30분) 아니면 젤 매니큐어 ($50, 45분) 중 어떤 걸로 하시겠어요?" |
| 4 | You | "젤로요." |
| 5 | Luna | "특별히 원하시는 분 있으세요? 소피아가 네일 전문이에요." |
| 6 | You | "소피아 좋아요." |
| 7 | Luna | "내일 오후 3시, 소피아와 젤 매니큐어, 45분, $50 맞으세요?" |
| 8 | You | "이름은 이수진입니다. 네 맞아요." |
| 9 | Luna | "예약 완료되었습니다. 내일 뵐게요." → `book_appointment` |

### Scenario D — Late cancel (< 24 h, ~45 s)

**Goal**: `cancel_appointment` 24 h policy hint

**Prereq**: Right after Scenario A, same caller ID re-call (Twilio
matches).

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | "Hi Michael, welcome back. How can I help?" |
| 2 | You | "I need to cancel my haircut for tomorrow." |
| 3 | Luna | "Of course — to confirm, you want to cancel your women's haircut tomorrow at 2 PM, right?" |
| 4 | You | "Yes." → `cancel_appointment` fires |
| 5 | Luna | "I've cancelled that. Note: since it's within our 24-hour window, our 50% late-cancel fee applies — you'll get an email from the salon." |

`is_late_cancel=True`, hint = `cancel_appointment_late_cancel`.

### Scenario E — Severe chemical reaction → transfer (~30 s)

**Goal**: `emergency_rules` trigger + `transfer_to_manager` fire

| Turn | Speaker | Utterance |
|---|---|---|
| 1 | Luna | "Hi, this is Luna from JM Beauty Salon..." |
| 2 | You | "I had a severe allergic reaction to a hair dye last week, my scalp is still burning." |
| 3 | Luna | "I'm so sorry to hear that. Your safety comes first — let me get you to our salon manager right away." |
| 4 | (transfer) | | dial manager phone |

`severe_chemical_reaction` rule fires → `transfer_to_manager`.

---

## 5. Recommended Call Order & Monitoring

**A → B → D (D right after A) → C → E** · Total ~5 minutes.

**Monitoring (separate terminal)**:
```
tail -f /tmp/realtime_debug.log | grep -E "HANDLER ENTERED|tool|caller:|agent:|book_appointment|service_lookup|list_stylists|cancel_appointment|transfer_to_manager"
```

**DB verification queries** (after each call):
```bash
# Latest appointment
curl -sS "$SUPABASE_URL/rest/v1/appointments?store_id=eq.34f44792-b200-450e-aeed-cbaaa1c7ff6e&order=created_at.desc&limit=3" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" | python3 -m json.tool

# Latest call_log
curl -sS "$SUPABASE_URL/rest/v1/call_logs?store_id=eq.34f44792-b200-450e-aeed-cbaaa1c7ff6e&order=start_time.desc&limit=3" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" | python3 -m json.tool
```

---

## 6. Open Items After This Pass

| Item | Owner | Effort |
|---|---|---|
| Commit `_load_store_by_id` industry / vertical_kind SELECT fix | dev | already applied, needs commit |
| Add `vertical_kind` set in `db_seeder.finalize_store` (#19) | dev | ~5 min |
| Loyverse `POST /developer/v1.0/webhooks` subscribe wrapper (#21) | dev | ~1 h |
| Step 6 Test Call backend outbound endpoint (#30) | dev | ~2 h |
| ngrok URL → env var `PUBLIC_BASE_URL` (#26) | dev | ~15 min |
| Twilio `AvailablePhoneNumbers` purchase wrapper (#1) | dev | ~1 h |
| Beauty live calls — 5 scenarios above | operator | ~5 min |

---

*Snapshot 2026-05-18. Branch `feature/openai-realtime-migration` tip
`968db05`. JM Beauty Salon row `34f44792-b200-450e-aeed-cbaaa1c7ff6e`
live on `+1-971-606-8979` → `https://jmtechone.ngrok.app/twilio/voice/inbound`.*
