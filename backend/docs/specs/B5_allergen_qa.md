# B5 — Allergen Q&A Specification

**Phase**: 2-C.B5 (production launch blocker — last reservation/order-side gap)
**Owner**: Bridge Server, Restaurant vertical
**Status**: spec → TDD tests → implementation
**Last updated**: 2026-05-02

---

## 1. Why

Per the 35-scenario restaurant survey + Maple competitive baseline,
allergen / dietary Q&A is the **most frequent** question category in
restaurant phone calls, ahead of orders and reservations. Maple Inc.
ships `allergen_lookup` with depth 8/10 (operator-curated allergen
matrix per menu item). JM is currently **0/10** on this dimension —
Gemini answers freely from system prompt context which is dangerous:

- "Does the Cafe Latte contain dairy?" → Gemini guesses "Yes, milk-based"
  — correct here, but for less obvious items it can hallucinate
  (matcha latte = "egg-free I think" → if oat milk variant has gluten,
  bot misreports → customer with celiac has anaphylactic reaction)
- "What's vegan?" → Gemini lists items without checking actual menu metadata
- "Gluten-free options?" → no deterministic answer

**Live observed risk**: morning B3 test session — bot freely answered
"Yes, our croissant is dairy-free" which is FALSE (butter). Customer
trust + legal exposure. This is the single largest **non-transactional**
phone scenario by frequency, and the only remaining pre-launch blocker
on the Maple parity sheet (alongside Manager Dashboard).

---

## 2. Domain model (DDD)

| Concept | Type | Source of truth |
|---------|------|-----------------|
| `MenuItem` | Aggregate root | `menu_items` table (Phase 2-B.1.7) |
| `AllergenMatrix` | Value object | `menu_items.allergens` (jsonb) — new column |
| `AllergenCategory` | Enum | `dairy / gluten / nuts / soy / shellfish / egg / fish / sesame` (FDA top-9 minus peanut split) |
| `DietaryTag` | Enum | `vegan / vegetarian / gluten_free / dairy_free / nut_free / kosher / halal` |
| `AllergenLookupService` | Domain service | `app.skills.menu.allergen.allergen_lookup` |
| `OperatorCurated` | Invariant | Allergens MUST come from operator-set DB column, not from LLM inference |

`allergen_lookup` is a **query** (read-only) over the `menu_items`
aggregate. It returns deterministic answers from the operator-curated
allergen matrix. The voice handler routes Q&A intents through this
tool; Gemini does NOT freely answer allergen/dietary questions.

**Storage**: extend the existing `menu_items` table with two jsonb
columns (no new table needed):
- `allergens` — array of allergen category strings (FDA top-9 set)
- `dietary_tags` — array of dietary tag strings

Operator backfills via Loyverse webhook (item description parsing) +
manual override via Manager Dashboard (future). v1 ships with manual
SQL backfill for JM Cafe + a default-empty fallback (item has no
allergen data → bot honestly says "I'm not sure, let me check with
the team — would you like to hold for a manager?").

---

## 3. Preconditions / postconditions / invariants

### Preconditions (the bridge / skill enforces all of these)

1. The `menu_items.allergens` and `menu_items.dietary_tags` columns
   exist and are jsonb (default `[]`).
2. The voice handler intercepts allergen/dietary intent BEFORE Gemini
   has a chance to freely answer — system prompt rule routes through
   `allergen_lookup` tool.
3. The lookup is store-scoped via RLS — `tenant_id` enforced on every
   query. Cross-store leakage is impossible.
4. When `allergens` is empty/null for a queried item, the bot does NOT
   say "free of X" — it says "I don't have allergen info on hand for
   that, I can transfer you to a manager."

### Postconditions (read-only, no DB mutation)

- The lookup returns a structured payload `{item_name, allergens,
  dietary_tags, confidence}` where confidence is `'curated'` if the row
  has explicit allergen data and `'unknown'` if columns are empty.
- The voice handler renders a concise, deterministic line — never
  combines multiple items in a single answer (one item per query),
  to avoid Gemini paraphrase risk.
- A WARNING-level log line `allergen_lookup store=… item=… result=…`
  per query so we can audit Q&A patterns.

### Invariants

- **OperatorCurated I0**: bot NEVER speaks allergen affirmation
  ("free of dairy", "no nuts") without the source row having that
  allergen explicitly absent in the operator-curated `allergens` array.
- **HonestUnknown I1**: when data is missing, bot acknowledges and
  offers manager transfer — never guesses.
- **OneItemPerQuery I2**: single tool call returns single item's data.
  Multi-item queries (e.g. "what's vegan on your menu?") route through
  a separate `dietary_filter` tool (deferred to v2).

### Failure modes (each gets its own `ai_script_hint`)

| Reason | When | Customer-facing line |
|--------|------|----------------------|
| `item_not_found` | menu fuzzy match returns no item with score ≥ 0.7 | "I don't see that on our menu — could you say it again, or would you like me to read what we have?" |
| `allergen_unknown` | item found but `allergens` and `dietary_tags` both empty | "I don't have allergen info on hand for the [item]. Want me to transfer you to a manager?" |
| `allergen_present` | queried allergen IS in the item's allergens array | "Yes, our [item] contains [allergen(s)]." |
| `allergen_absent` | queried allergen NOT in array AND row has explicit data | "Our [item] is [allergen]-free per our kitchen records." |
| `dietary_match` | queried dietary tag is in item's dietary_tags | "Yes, the [item] is [tag]." |
| `dietary_no_match` | item exists but tag not present in operator data | "The [item] isn't tagged [tag] — let me have the team double-check. Want me to transfer?" |

---

## 4. Tool schema (Voice Engine ↔ Gemini)

**File**: `backend/app/skills/menu/allergen.py` (NEW — alongside
existing `match.py`).

```python
ALLERGEN_LOOKUP_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "allergen_lookup",
            "description": (
                "Look up allergen and dietary information for ONE menu item. "
                "Use this WHENEVER the customer asks about ingredients, "
                "allergies, dairy, gluten, nuts, vegan, vegetarian, "
                "gluten-free, dairy-free, etc. NEVER answer allergen "
                "questions from your own knowledge — call this tool. "
                "Pass the menu item name as the customer said it; the "
                "system handles fuzzy matching. Pass the allergen or "
                "dietary tag the customer asked about (or empty string "
                "if they asked generically). The tool returns "
                "operator-curated data — speak its result VERBATIM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_name": {
                        "type": "string",
                        "description": (
                            "The menu item the customer asked about, as "
                            "they said it (e.g. 'cafe latte', 'croissant')."
                        ),
                    },
                    "allergen": {
                        "type": "string",
                        "description": (
                            "Specific allergen category if asked (one of: "
                            "dairy, gluten, nuts, soy, shellfish, egg, "
                            "fish, sesame). Empty string for generic "
                            "'what's in this' or for dietary tag queries."
                        ),
                    },
                    "dietary_tag": {
                        "type": "string",
                        "description": (
                            "Specific dietary tag if asked (one of: vegan, "
                            "vegetarian, gluten_free, dairy_free, nut_free, "
                            "kosher, halal). Empty string for allergen queries."
                        ),
                    },
                },
                "required": ["menu_item_name"],
            },
        }
    ]
}
```

**Why no caller-id / customer fields**: the lookup is global per store;
no PII needed. Same caller-id-only-when-needed principle as B4.

---

## 5. Skill flow (`allergen.allergen_lookup`)

**File**: `backend/app/skills/menu/allergen.py` (NEW).

```python
async def allergen_lookup(
    *,
    store_id:       str,
    menu_item_name: str,
    allergen:       str = "",
    dietary_tag:    str = "",
) -> dict[str, Any]:
    """Look up allergens / dietary tags for a single menu item.
    (단일 메뉴 항목의 allergen / dietary 조회 — Phase 2-C.B5)
    """
    # 1. Validate inputs (mutually exclusive — one of allergen/tag, not both)
    # 2. Fuzzy-match menu_item_name against menu_items rows for this store
    #    (reuse existing menu.match.resolve_items_against_menu helper, cutoff 0.7)
    # 3. If no match → item_not_found
    # 4. Fetch the matched row's allergens + dietary_tags arrays
    # 5. If both arrays empty → allergen_unknown (honest unknown)
    # 6. If allergen specified:
    #    - allergen in row.allergens → allergen_present
    #    - allergen not in row.allergens AND row has explicit data → allergen_absent
    # 7. If dietary_tag specified:
    #    - tag in row.dietary_tags → dietary_match
    #    - tag not in row.dietary_tags → dietary_no_match
    # 8. If neither (generic ingredient query):
    #    - return full allergens + dietary_tags lists (let voice handler render)
    # 9. Log warning("allergen_lookup store=%s item=%s a=%s d=%s result=%s",
    #                 store_id, matched_name, allergen, dietary_tag, hint)
    # 10. Return:
    #     {
    #       "success":         True,
    #       "matched_name":    str,
    #       "allergens":       list[str],
    #       "dietary_tags":    list[str],
    #       "queried_allergen":  str (echo for voice formatter),
    #       "queried_dietary":   str,
    #       "ai_script_hint":  one of (item_not_found / allergen_unknown /
    #                          allergen_present / allergen_absent /
    #                          dietary_match / dietary_no_match / generic),
    #     }
```

**Helpers reused**:
- `app.services.menu.match.fuzzy_match_item` (existing, cutoff 0.7 — slightly more permissive than create_order's 0.85 since we'd rather find SOMETHING than miss; risk is offering wrong item info, not wrong order)
- httpx + `_SUPABASE_HEADERS` + `_REST` (existing pattern)

---

## 6. Voice Engine integration (`voice_websocket.py`)

### 6a. Tool registration

In `_stream_gemini_response` session init: add `ALLERGEN_LOOKUP_TOOL_DEF`
to the `tools=[...]` list alongside reservation + order tools.

### 6b. NO AUTO-FIRE gate (read-only Q&A)

Unlike create_order/make_reservation/etc., allergen_lookup is read-only
and can fire on the FIRST mention without explicit confirmation —
the customer's question itself IS the trigger. Gate exclusion in line
~1047 tuple: do NOT include "allergen_lookup".

### 6c. Tool dispatcher branch (line ~1671, after `cancel_reservation`)

```python
elif tool_name == "allergen_lookup":
    skill_result = await allergen.allergen_lookup(
        store_id        = store_id,
        menu_item_name  = tool_args.get("menu_item_name", ""),
        allergen        = tool_args.get("allergen", ""),
        dietary_tag     = tool_args.get("dietary_tag", ""),
    )
    hint = skill_result.get("ai_script_hint", "item_not_found")
    template = ALLERGEN_SCRIPT_BY_HINT.get(
        hint, "Let me transfer you to a manager."
    )
    try:
        script = template.format(
            item        = skill_result.get("matched_name", "that item"),
            allergen    = skill_result.get("queried_allergen", ""),
            allergens   = ", ".join(skill_result.get("allergens", []))
                          or "no listed allergens",
            tag         = skill_result.get("queried_dietary", ""),
        )
    except (KeyError, IndexError):
        script = template
    result = {
        "success":      bool(skill_result.get("success")),
        "matched_name": skill_result.get("matched_name"),
        "allergens":    skill_result.get("allergens"),
        "dietary_tags": skill_result.get("dietary_tags"),
        "reason":       skill_result.get("reason"),
        "message":      script,
        "error":        skill_result.get("error", ""),
    }
```

### 6d. EpiPen / Severe-Allergy Auto-Handoff (Tier 3 trigger)

Per Hostie three-tier framework + 2026-05-02 domain research, certain
keywords in the customer's transcript indicate medical emergency or
severe sensitivity and MUST trigger immediate manager-handoff offer
(NOT an `allergen_lookup` tool call — escalation comes first):

**Trigger keywords** (case-insensitive, whole-word match):
`epipen`, `epi pen`, `epi-pen`, `anaphylaxis`, `anaphylactic`,
`life-threatening`, `life threatening`, `deathly allergic`,
`severely allergic`, `severe allergy`, `celiac`, `coeliac`,
`hospitalized`, `hospital`, `react badly`, `kill me`

**Helper**: `_has_severe_allergy_signal(transcript_user_turn: str) -> bool`
in `voice_websocket.py` — substring + word-boundary check on the
customer's most recent turn.

**Behavior** (in dispatcher, BEFORE allergen_lookup tool call):
- Detect signal in last user turn
- Yield: "I want to make sure we get this exactly right — let me
  connect you with our manager who can verify directly with the
  kitchen. One moment please."
- Skip `allergen_lookup` entirely (avoid even the curated answer —
  liability surface is too large for severe cases)
- v1: log warning + yield closing line (no live transfer in v1)
- v2: trigger Twilio Conference live transfer

**System prompt rule 12 reinforcement**: even if the dispatcher gate
fails (e.g. transcript chunked across turns), the LLM-side rule 12
must mention Tier 3 keywords and instruct manager offer.

### 6e. System prompt — new rule 12 (after rule 11 ESCALATION)

> 12. ALLERGEN / DIETARY QUESTIONS (allergen_lookup): When the customer
>     asks ANYTHING about ingredients, allergens, or dietary suitability
>     ("does the X have dairy?", "is the Y vegan?", "what's gluten-free?",
>     "is there nuts in Z?"), call allergen_lookup with the menu item
>     they named + the allergen or dietary_tag they asked about. NEVER
>     answer from your own knowledge — operator-curated data is the only
>     source of truth. If the tool returns allergen_unknown, speak the
>     'I don't have allergen info on hand' line VERBATIM and OFFER to
>     transfer to a manager. If the customer asks generically ("what's
>     in your croissant?"), pass empty allergen + empty dietary_tag and
>     let the tool return the full allergens list. NEVER claim an item
>     is "free of X" unless the tool explicitly returned allergen_absent.
>     This is a CUSTOMER SAFETY INVARIANT — the wrong answer can cause
>     anaphylactic reactions.
>     SEVERE-ALLERGY ESCALATION (Tier 3): if the customer says any of
>     'EpiPen', 'anaphylaxis', 'anaphylactic', 'life-threatening',
>     'deathly allergic', 'severely allergic', 'celiac', 'coeliac',
>     'hospitalized', 'react badly' — DO NOT call allergen_lookup.
>     Reply ONCE: 'I want to make sure we get this exactly right —
>     let me connect you with our manager who can verify directly
>     with the kitchen. One moment please.' Then stop. Even our
>     curated data carries trace-amount and cross-contamination
>     uncertainty that is not safe to communicate for severe cases.

---

## 7. Customer-facing scripts (`order.py:ALLERGEN_SCRIPT_BY_HINT`)

**File**: `backend/app/skills/order/order.py` (alongside existing maps).

```python
ALLERGEN_SCRIPT_BY_HINT: dict[str, str] = {
    "item_not_found": (
        "I don't see {item} on our menu — could you say it again, or "
        "would you like me to read what we have?"
    ),
    "allergen_unknown": (
        "I don't have allergen info on hand for the {item}. Want me to "
        "transfer you to a manager?"
    ),
    "allergen_present": (
        "Yes, our {item} contains {allergen}."
    ),
    "allergen_absent": (
        "Our {item} is {allergen}-free per our kitchen records."
    ),
    "dietary_match": (
        "Yes, our {item} is {tag}."
    ),
    "dietary_no_match": (
        "Our {item} isn't tagged {tag} — let me have the team "
        "double-check. Want me to transfer?"
    ),
    "generic": (
        "Our {item} contains {allergens}. Anything specific you'd "
        "like to know?"
    ),
}
```

The placeholders are `.format()`-substituted in the dispatcher. `{tag}`
is rendered as a human-readable string ("vegan" / "gluten-free" with
underscore-to-dash conversion in the dispatcher).

---

## 8. Test plan (TDD — written before any production code)

### Skill tests (`tests/unit/skills/menu/test_allergen.py`)

| # | Scenario | Expected |
|---|---|---|
| T1 | item_name not in menu → fuzzy match fails | `success=True`, `ai_script_hint='item_not_found'` |
| T2 | item found, both arrays empty | `ai_script_hint='allergen_unknown'` (honest unknown) |
| T3 | item found, allergen 'dairy' in row.allergens | `ai_script_hint='allergen_present'`, allergens list returned |
| T4 | item found, allergen 'nuts' NOT in row.allergens, row HAS data | `ai_script_hint='allergen_absent'` |
| T5 | item found, dietary 'vegan' in row.dietary_tags | `ai_script_hint='dietary_match'` |
| T6 | item found, dietary 'gluten_free' NOT in row.dietary_tags | `ai_script_hint='dietary_no_match'` |
| T7 | item found, no allergen + no dietary specified (generic) | `ai_script_hint='generic'`, full lists returned |
| T8 | RLS isolation — cross-store query returns nothing | `ai_script_hint='item_not_found'` (defensive) |
| T9 | Fuzzy match cutoff 0.7 — "lattay" matches "Cafe Latte" | matched_name='Cafe Latte' |
| T10 | Both allergen + dietary specified — allergen wins (mutually exclusive) | allergen branch returns |

### Voice integration tests (`tests/unit/adapters/test_allergen_voice.py`)

| # | Scenario | Expected |
|---|---|---|
| V1 | `ALLERGEN_LOOKUP_TOOL_DEF` exported with required `menu_item_name` only | Importable; required==["menu_item_name"] |
| V2 | `ALLERGEN_SCRIPT_BY_HINT` covers all 7 hints | All 7 keys present, each non-empty |
| V3 | System prompt rule 12 mentions allergen_lookup + customer safety invariant | "allergen_lookup" in prompt + "CUSTOMER SAFETY INVARIANT" |
| V4 | Dispatcher .format() substitutes {item} + {allergen} correctly | Mock skill returns; verify formatted script |
| V5 | NO AUTO-FIRE gate for allergen_lookup — fires on first mention without recital | gate tuple does NOT include "allergen_lookup" |
| V6 | `_has_severe_allergy_signal` true on EpiPen / anaphylaxis / celiac / etc | helper returns True; case-insensitive; word-boundary match (false on "I don't carry an epi-pen" partial — accept this false-positive bias) |
| V7 | Severe-allergy intercept happens BEFORE allergen_lookup | When signal detected in last user turn, dispatcher yields manager-transfer line and DOES NOT call allergen_lookup |
| V8 | System prompt rule 12 contains Tier 3 keyword list + manager-offer wording | sentinel keywords ('EpiPen', 'anaphylaxis', 'celiac') + 'connect you with our manager' present in prompt |

**Total: 10 skill + 8 voice = 18 RED tests** before any production code.

---

## 9. Out of scope (deferred to V2)

V1 is the safety-first MVP that closes the pre-launch gap. V2 expands
to feature parity with Maple's full allergen suite (1-2 weeks after
v1 ships):

- **Multi-item dietary filter** ("what's vegan?" returning a list) — v2;
  v1 routes one item at a time via `allergen_lookup`. New tool
  `dietary_filter` with whole-menu scan + RLS.
- **Allergen severity levels** ("trace amounts vs main ingredient") —
  v2; v1 binary present/absent per FDA top-9.
- **Cross-contamination warnings** ("processed in same facility as
  nuts", "shared fryer", "same cutting board") — v2; v1 ingredient-level
  only. New column `cross_contam_risk jsonb` + UI.
- **Ingredient substitution** ("can you make the latte with oat milk?")
  — v2; new `substitutions` table per menu_item with price delta.
- **Per-variant allergens** (decaf vs regular, oat milk vs whole) —
  v2; v1 single allergen array per menu_item row.
- **Manager dashboard allergen editor** — v2; v1 manual SQL backfill
  (operator runs scripts/backfill_allergens.sql).
- **Loyverse description auto-parsing for allergens** — v2; v1 manual.
- **Live manager transfer** (Twilio Conference) — v2; v1 emits "let me
  transfer" line + SMS alert to staff.
- **Customer dietary preference learning** ("you've previously asked
  about gluten — same restriction?") — v2; merges with Phase 3 CRM
  work using caller-id history.
- **USDA FoodData Central nutritional integration** ("calories?",
  "carbs?") — v2; out-of-scope for v1 since it's allergen-adjacent
  but not allergen-specific.
- **EpiPen-trigger live transfer** — v1 emits closing/transfer line +
  WARNING log; v2 connects via Twilio Conference + staff app push.

---

## 10. Risks / open questions

| Risk | Mitigation |
|---|---|
| Operator hasn't curated allergens for an item | `allergen_unknown` hint → transfer to manager; never silent guess |
| Fuzzy match returns wrong item | cutoff 0.7 + matched_name speakback ("Did you mean Cafe Latte?") — customer catches mismatch |
| Customer asks about allergen we don't track (e.g. "MSG") | Tool returns `allergen_unknown` for unsupported categories; v1 supports FDA top-9 only |
| Gemini freelances despite the rule | system prompt + tool description — but cannot deterministically prevent. Mitigation: monitor cron flags any "free of X" / "contains X" assistant turn that wasn't preceded by an allergen_lookup TOOL RESULT (audit dashboard, future) |
| Allergen data goes stale | Manual backfill v1; Loyverse webhook auto-refresh v2 |
| RLS bypass via fuzzy match | All queries filter on `store_id` parameter (server-side); RLS policy enforces |
| **Severe-allergy customer gets curated answer instead of manager** | Tier 3 keyword detection in dispatcher (BEFORE allergen_lookup fires) + system prompt rule 12 reinforcement. v1 logs warning. v2 live-transfers via Twilio Conference. |
| **California 2026-07-01 chain-restaurant allergen-disclosure law** | JM is non-chain SMB target — direct exposure low. Marketing point: JM helps chain customers comply via menu-item allergen tagging + audit trail. Track CA-specific 20+ chain JM customers and surface compliance feature. |
| **Liability — wrong allergen info → personal injury / wrongful death** | (a) Vendor T&C must include AI-disclaimer + customer-acknowledges-AI clauses (legal review pending). (b) JM customer onboarding: confirm restaurant carries E&O / Product Liability / General Liability insurance covering AI-related claims. (c) Operator responsibility: keep allergen data current — JM provides tooling, restaurant owns truth. |
| **Cross-contamination not modeled in v1** | All curated `allergen_absent` answers carry implicit risk. Tier 3 keyword set explicitly handles cases where this matters most (celiac, anaphylaxis). v2 adds `cross_contam_risk` column. |
| **EpiPen detection false positive** (e.g. "I don't carry an EpiPen") | False positive cost = manager transfer offered when not needed. Acceptable tradeoff given safety asymmetry. False negative cost = liability. Always err toward Tier 3. |

---

## Decisions locked (2026-05-02, customer-confirmed pending)

| # | Decision (proposed) |
|---|---|
| 1 | **FDA top-9 allergens** — dairy, gluten, nuts, soy, shellfish, egg, fish, sesame (peanut subsumed under nuts for v1). |
| 2 | **7 dietary tags** — vegan, vegetarian, gluten_free, dairy_free, nut_free, kosher, halal. |
| 3 | **Operator-curated only** — never LLM inference. `allergen_unknown` is acceptable, hallucination is not. |
| 4 | **One item per query** — multi-item dietary filter deferred to v2. |
| 5 | **No AUTO-FIRE gate** — read-only, fires on first mention. |
| 6 | **Fuzzy match cutoff 0.7** — more permissive than create_order's 0.85 since wrong info is recoverable (customer corrects). |
| 7 | **DB schema**: extend `menu_items` with `allergens jsonb default '[]'` + `dietary_tags jsonb default '[]'`. No new table. |
| 8 | **Tier 3 EpiPen / severe-allergy keyword auto-handoff** — dispatcher gate + system prompt rule 12 reinforcement. Skip allergen_lookup entirely for these. |
| 9 | **Disclaimer wording**: every `allergen_absent` response uses "per our kitchen records" qualifier. Never naked "is X-free". |
| 10 | **Liability disclaimers**: tracked in v1 risk register, vendor T&C update is a parallel legal task — not blocking v1 ship. |

---

## Implementation order

1. ✅ This spec doc (current step — V1 보강 완료 2026-05-02 16:00 PT).
2. DB migration: add `allergens` + `dietary_tags` jsonb columns to `menu_items` (default `[]`).
3. Manual SQL backfill for JM Cafe (12 menu items) — operator data.
4. Write 18 RED tests (10 skill + 8 voice — V6/V7/V8 cover EpiPen handoff).
5. Implement `app.skills.menu.allergen.allergen_lookup` until T1-T10 GREEN.
6. Implement `_has_severe_allergy_signal` helper in voice_websocket.py until V6/V7 GREEN.
7. Implement voice integration (tool registration + Tier 3 intercept + dispatcher branch + script map) until V1-V8 GREEN.
8. System prompt rule 12 update (with Tier 3 keyword list + manager-offer wording).
9. Live-call validation: 1 test call covering 6 hints (per spec §10) + 1 test call exercising EpiPen Tier 3 intercept (e.g. customer says "I'm severely allergic to nuts").
10. PDF archive: `docs/test-scenarios/<date>/allergen_qa_<date>_T<hhmm>.{html,pdf}`.
11. Update `competitive/maple_vs_jm` doc — Allergen category 0 → 8 (Tier 3 + curated invariant + RLS).
12. Legal task (parallel, not blocking v1): vendor T&C AI-disclaimer clauses + onboarding insurance check.

---

## Live validation scenario (turn-by-turn, save to PDF)

| Turn | Speaker | Script | What's validated |
|---|---|---|---|
| 1 | Bot | "Welcome to JM Cafe, how can I help?" | greeting |
| 2 | You | **"Does the cafe latte contain dairy?"** | allergen-specific question |
| 3 | Bot | "Yes, our Cafe Latte contains dairy." | ✅ `allergen_present` (operator data) |
| 4 | You | **"Is the croissant gluten-free?"** | dietary tag question |
| 5 | Bot | "Our Croissant isn't tagged gluten_free — let me have the team double-check. Want me to transfer?" | ✅ `dietary_no_match` (honest unknown) |
| 6 | You | **"What about the cheese pizza — any nuts?"** | allergen absence |
| 7 | Bot | "Our Cheese Pizza is nuts-free per our kitchen records." | ✅ `allergen_absent` |
| 8 | You | **"Is the matcha vegan?"** | item_not_found (matcha sold out per temporary_prompt) |
| 9 | Bot | "I don't see matcha on our menu — could you say it again, or would you like me to read what we have?" | ✅ `item_not_found` |
| 10 | You | **"Tell me about the avocado BLT."** | generic ingredient query |
| 11 | Bot | "Our Avocado BLT contains gluten, dairy. Anything specific you'd like to know?" | ✅ `generic` |
| 12 | You | **"What's in the orion rings?"** | allergen_unknown (no data) |
| 13 | Bot | "I don't have allergen info on hand for the Orion Rings. Want me to transfer you to a manager?" | ✅ `allergen_unknown` (honest) |
| 14 | You | "Bye." | end |

**Validates**: 6 distinct hints in one call + customer safety invariant
+ operator-data sourcing.

---

## Live validation scenario B — Tier 3 EpiPen intercept (separate call)

| Turn | Speaker | Script | What's validated |
|---|---|---|---|
| 1 | Bot | "Welcome to JM Cafe, how can I help?" | greeting |
| 2 | You | **"I'm severely allergic to nuts — does the croissant have any?"** | Tier 3 trigger ("severely allergic") |
| 3 | Bot | "I want to make sure we get this exactly right — let me connect you with our manager who can verify directly with the kitchen. One moment please." | ✅ **Tier 3 intercept fires BEFORE allergen_lookup** — even if curated data says nuts-free, severe case bypasses bot answer |
| 4 | You | (test 2: hang up + new call) **"I have celiac, is the cafe latte gluten-free?"** | Tier 3 trigger ("celiac") |
| 5 | Bot | (same manager-transfer line) | ✅ celiac keyword triggers same path |
| 6 | You | (test 3: edge case) **"My friend has an EpiPen, but I just want a coffee."** | false-positive test |
| 7 | Bot | (manager-transfer line — accepted as conservative bias per Decision #10) | ⚠️ false positive — acceptable per spec; better safe than sorry |

**Validates**: Tier 3 keyword detection + intercept-before-lookup
+ false-positive bias is intentional + monitor logs WARNING for audit.

In v2, turn 3/5 would trigger live Twilio Conference transfer instead of
just speaking the manager-handoff line.
