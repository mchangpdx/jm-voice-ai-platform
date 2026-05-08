# Session Summary — 2026-05-07 (Phase 7-A.D)

**Theme**: Modifier system completeness + voice quality fixes
**Duration**: full day
**Commits**: 9 (`34d154c` … `1ee3eb5`)
**Tests added**: ~50 unit tests; full regression 489–572/572 pass across multiple checkpoints

---

## 1. Phase Overview

| Phase | Commit | Scope |
|---|---|---|
| 7-A | `34d154c` | (prior session) JM Cafe production menu + modifier DB + sync freeze |
| 7-A.B | `ae2efb2` | Voice agent modifier recognition + dynamic allergen compute |
| 7-A.C | `22cea0a` | Modifier serialization on order line (`effective_price`) |
| 7-A.D | `7c160fc` | Close POS round-trip (D1 Loyverse price + D2 recital + D3 modify + D4 required-ask) |
| 7-A.D hot-fix | `c329afd` | Recital gate + all-modifier capture + email letter-by-letter |
| 7-A.D Q1+Q2 | `76d495a` | VAD switch to server_vad/1200ms + barge-in debounce + email simplification |
| 7-A.D Wave A | `f393ebf` | Prompt compaction + INVARIANTS recency placement |
| 7-A.D Wave A.1 | `86b95c8` | STT-arg consistency hot fixes (Bugs A/B/C/D) |
| 7-A.D Wave A.2 | `1ee3eb5` | Recital gate strict + menu_cache sync + letter-by-letter ASK + receipt modifier breakdown |

---

## 2. Bugs Closed

### Originally identified (call CA90b88e... 2026-05-07 12:14 — pre-Phase-7-A.B)
- ❌ `iced oat latte` rejected 4 times → customer hangup → **Phase 7-A.B SOLVED**

### Phase 7-A.B verification (call CA61eaa299b... 13:33 — post-7-A.B)
- ✅ Composite drink recognition working
- ❌ Order booked $5.50 instead of $7.25 (modifier surcharge missing) → **Phase 7-A.C SOLVED**

### Phase 7-A.C+D verification (call CA9c22bb95... 18:29 — post-7-A.D)
Bugs surfaced after Phase 7-A.C/D ship:
- **R1**: Order recital SKIPPED before create_order → **hot fix c329afd partial**, then **Wave A.2-E full SOLVED**
- **Issue 3**: size:large dropped from selected_modifiers despite being spoken → **Wave A.1 SOLVED via code= prefix in MENU MODIFIERS**
- **Issue 4**: NATO email B→C silent substitution → **partial** (NATO-SOURCE GATE + LETTER-BY-LETTER ASK improved)

### Quality regression triage (4 calls 16:52-17:00)
Customer feedback on call CA55035ea4: "communication is not good"
- Barge-in clears at 1.0/turn unconditionally → **Q1 SOLVED via server_vad/1200ms + bot_speaking debounce**
- Letter-by-letter spelling fragmented to 4+ turns → **Q1 SOLVED**
- Letter-by-letter ASK clause amplifying VAD fragmentation → **Q2 SOLVED via revert to single NATO readback**

### Wave A.1 verification (call CAc4250831 18:29 — post-Q1+Q2+Wave A)
- **Bug A** size capture failure → **Wave A.1 SOLVED**
- **Bug B** $8.00 vs $7.75 math hallucination → **Wave A.1 SOLVED via PRICE MATH bullet**
- **Bug C** Whisper 'Chin' → bot args 'Tran' → **Wave A.1 SOLVED via ARGS-NAME GATE**
- **Bug D** STT 'simit' → bot NATO 'D-Y-M-E-E-T' → **Wave A.1 partial** (NATO-SOURCE GATE)

### Wave A.1 verification (call CA0459df13 19:08 — post-Wave-A.1)
- **Bug A/C** verified solved; **Bug B** verified solved
- **Bug E** (new): RECITAL GATE bypassed (recital + tool in same response) → **Wave A.2-E SOLVED**
- **Bug F** (new): menu_cache vs menu_items $0.50 mismatch → **Wave A.2-F SOLVED via deactivating Medium/Large legacy variants on 12 sized drinks (21 rows)**
- **Bug D**: still partial → **Wave A.2-D partially helped via LETTER-BY-LETTER ASK fallback**
- **Bug G** (request): pay link email + receipt page hid modifier choices → **Wave A.2-G SOLVED via modifier_lines persisted in items_json + email/receipt rendering**

### Wave A.2 verification (calls CA30358613 19:37, CA99939c84 19:46 — post-Wave-A.2)
- ✅ Bug A/B/C/E/F/G all verified solved live
- ⚠️ Bug D persists (NATO ↔ args drift) — **inherent STT limitation**, will resolve naturally when TCR SMS approved
- ⚠️ **Latency observed**: create_order tool ~3.2s consistently. Bottleneck identified — 9 serial REST calls. **Wave A.3 candidate** for next session.

---

## 3. Architecture / Data Changes

### DB
- `menu_items` — 21 Medium/Large legacy variants set `is_available=false` on JM Cafe (12 sized drinks). Modifier system size price_delta now solely drives sized pricing.
- `stores.menu_cache` — regenerated from current `is_available=true` rows.
- `items_json` schema (within `bridge_transactions`):
  - new field: `effective_price` (base + Σ price_delta)
  - new field: `selected_modifiers: [{group, option}]`
  - new field: `modifier_lines: [{label, group, option, price_delta}]` — render-friendly for receipts
- Phase A — `loyverse_item_id` phantom column dropped (prior session).

### Code — services layer
- `services/menu/modifiers.py` (NEW Phase 7-A.B) — `fetch_modifier_groups`, `format_modifier_block` with `code=Display` rendering
- `services/menu/allergen_compute.py` (NEW Phase 7-A.B) — `compute_effective_allergens` (base ⊖ remove ⊕ add)
- `services/menu/match.py` — added `is_available=eq.true` filter (Wave A.2-F); per-line `effective_price` + `modifier_lines` enrichment

### Code — bridge layer
- `services/bridge/flows.py` — `total_cents` uses `effective_price`; `_items_key` includes modifier signature
- `services/bridge/pos/loyverse.py` — line `price` reads `effective_price` first
- `services/bridge/pay_link_email.py` — `_items_rows_html` uses `effective_price` + renders `modifier_lines` block

### Code — API layer
- `api/realtime_voice.py` — modifier preload + dispatcher passes `selected_modifiers`; VAD switch to `server_vad/silence=1200ms`; barge-in debounce via `bot_speaking` flag
- `api/voice_websocket.py` `build_system_prompt` — Wave A compaction (28,286→20,000 chars on synthetic store; ~24,453 on production); INVARIANTS moved to recency zone with top-of-prompt anchor; rule 5 ORDERS rewritten as checklist with NATO-SOURCE GATE / ARGS-NAME GATE / PRICE MATH / RECITAL GATE / SAME-RESPONSE TOOL BAN / LETTER-BY-LETTER ASK clauses
- `api/payment.py` `_success_page` — same modifier breakdown rendering as email

### Code — skills
- `skills/menu/allergen.py` — `selected_modifiers` parameter on `allergen_lookup` + dynamic effective allergen path
- `skills/order/order.py` — `create_order` and `modify_order` tool defs accept `selected_modifiers` per item

---

## 4. Live Verification Trail

| Call | Time | Outcome |
|---|---|---|
| CA90b88e... | 12:14 | Pre-7-A.B baseline. `iced oat latte` rejected 4× → hangup. |
| CA61eaa299b | 13:33 | Phase 7-A.B verified. Composite drink ordered. $5.50 underbill. |
| CA9c22bb95 | 18:29 | Phase 7-A.D verified. R1+I3+I4 surfaced. |
| CA55035ea4 | 16:52 | Quality regression. "communication is not good" → hangup. |
| 3 more 16:55-17:00 | — | Quality regression confirmed. |
| CAc4250831 | 18:29 | Q1+Q2+Wave A verified. Bug A→D surfaced. |
| CA0459df13 | 19:08 | Wave A.1 verified. Bug E+F+G surfaced. |
| CA30358613 | 19:37 | Wave A.2 verified. 5/6 PASS. |
| CA99939c84 | 19:46 | Wave A.2 final verification. Latency 3.2s identified. |

Each call outcome documented in chat trace.

---

## 5. Known Issues Remaining

### High priority (next session)
1. **Wave A.3 — Latency**: create_order ~3.2s. Strategies A+B (prefetch loyverse store/payment_type + reuse modifier_index) → 2.2s. Strategy C (bot acknowledges while tool runs) → ~0s perceived.
2. **Bug D — Email accuracy**: NATO ↔ args drift. Best fix is TCR SMS approval (deprecates email primary).

### Medium priority
3. **CRM Wave 1**: phone-keyed customer lookup at call start (Step 4 from earlier)
4. **JM BBQ adapter**: KBBQ AYCE × 2 stores (PDX Phase 1 priority)

### Deferred
- D5 (Loyverse line_modifiers structured POST) — Phase 7-A.E
- D6 (server-side is_required hard gate) — Phase 8
- E series (5-lang modifier display, recall_order modifier mention)
- F series (admin UI for modifier toggle, modifier analytics)

---

## 6. Numbers

- Total commits: 9
- Files touched: 12 unique
- Tests added: ~50
- Production prompt: 28,286 → 24,453 chars (-13.5%)
- Tool latency: 3.2s identified (next-session priority)
- Live calls verified: 9
- Production POS receipts created (test): #0099 → #0103 (5 successful Loyverse pushes)

---

## 7. Backend State at Session End

- Branch: `feature/openai-realtime-migration`
- Last commit: `1ee3eb5`
- uvicorn `--reload` running (PID 32433)
- ngrok: `https://bipectinate-cheerily-akilah.ngrok-free.dev`
- Twilio +1-503-994-1265 → Realtime 100%
- DB JM Cafe: 26 menu_items active (12 sized + 14 non-sized) + 9 modifier_groups + 39 options
- VAD: server_vad/silence=1200ms
- System prompt: 24,453 chars production
