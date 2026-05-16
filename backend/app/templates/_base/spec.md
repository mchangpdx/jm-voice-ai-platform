# Vertical Template Framework — 9-Layer Spec
<!-- (수직 템플릿 프레임워크 — 9-layer 표준) -->

**Status:** Phase 1.1 draft · 2026-05-18 · Beauty MVP sprint
**Scope:** `backend/app/templates/<vertical>/`
**Authoritative loader:** `backend/app/services/onboarding/ai_helper.py`

This document defines the 9 layers every vertical template must (eventually)
provide. The framework lets a single codebase serve restaurants, beauty
salons, auto-repair shops, and any future SMB vertical — adding a new
vertical means dropping nine YAML files in the right place, no code change.

Strategy (a) is in effect: **existing 4 filenames are preserved** to avoid
regression in 7+ loader call-sites. The 5 new layers are introduced as
additional files. Conceptual mapping is given in §1.

<!-- (Strategy a — 기존 4 파일명 유지, 신규 5개만 추가. 회귀 위험 zero.) -->

---

## 1. Layer Map at a Glance

| # | Layer | Filename | Status |
|---|---|---|---|
| 1 | Safety rules            | `allergen_rules.yaml`   | existing (kept) |
| 2 | Service catalog         | `menu.yaml`             | existing (kept) |
| 3 | Option groups           | `modifier_groups.yaml`  | existing (kept) |
| 4 | Persona prompt          | `system_prompt_base.txt`| existing (kept) |
| 5 | Intake flow ⭐ new       | `intake_flow.yaml`      | new |
| 6 | Scheduler model ⭐ new   | `scheduler.yaml`        | new |
| 7 | Emergency rules ⭐ new   | `emergency_rules.yaml`  | new |
| 8 | CRM follow-up ⭐ new     | `crm_followup.yaml`     | new |
| 9 | Pricing policy ⭐ new    | `pricing_policy.yaml`   | new |

Layer 1-4 names are historical. Conceptually they generalize:

- *allergen_rules* → safety rules (allergen in food / chemical sensitivity
  in beauty / hazard in home services). The name stays; the schema is
  already general enough — only the vocabulary inside it changes per
  vertical.
- *menu* → service catalog (food menu / hair services / repair line items).
- *modifier_groups* → option groups (extra shot / blow-dry / parts upgrade).

<!-- (Layer 1-3 이름은 음식점 잔재이지만 schema는 일반화 가능. 의미만 vertical마다 다름.) -->

---

## 2. Loading Convention

The loader resolves each layer by path:
```
backend/app/templates/<vertical>/<layer_filename>
```

**Lenient loading.** A missing file does NOT fail. The loader emits a
warning and returns an empty dict / null. Callers must tolerate absence.
This lets a new vertical land incrementally (e.g., ship cafe with the
4 historical files + just `intake_flow.yaml` on day one).

**No duplication.** YAML files are the single source of truth. Never hard-
code menu items, allergen patterns, or PHASE FLOW steps in Python — load
from the matching layer file.

<!-- (Lenient: 파일 누락 → warn + 빈 dict. Incremental 마이그레이션 가능.) -->

---

## 3. Layer Specs

### Layer 1 — `allergen_rules.yaml` (Safety Rules)

**Role.** Pattern-based auto-inference of safety attributes for new items
during onboarding. For food verticals this is FDA-9 allergens; for beauty
it can be chemical sensitivities (PPD allergy, pregnancy contraindications);
for home services it can be hazard classes (electrical, gas, hazmat).

**Schema.**
```yaml
patterns:
  - keywords: [list, of, lowercase, substrings]
    add_allergens: [allergen_ids]        # or add_sensitivities, add_hazards
    confidence: 0.0-1.0                  # threshold for auto-apply
    reason: "Human-readable why"
```

**Required fields:** `keywords` (≥1), `add_allergens` (≥1), `confidence`
(0.0-1.0). Validator emits warning if `confidence` ≥ 0.90 has no `reason`.

**Vertical-specific notes.**
- *Cafe / Pizza / Mexican / KBBQ*: FDA-9 allergens (`gluten`, `dairy`,
  `nuts`, `peanuts`, `eggs`, `soy`, `shellfish`, `fish`, `sesame`).
- *Beauty*: PPD (paraphenylenediamine), thioglycolate, formaldehyde,
  pregnancy_contra, fragrance_sensitivity.
- *Auto repair / Home services*: gas_line, electrical_high_voltage,
  asbestos, lead_paint, refrigerant.

The list name (`add_allergens` vs `add_sensitivities`) is allowed to differ;
the loader normalizes via `vertical_kinds.yaml` mapping.

---

### Layer 2 — `menu.yaml` (Service Catalog)

**Role.** Master list of items / services the vertical offers, with
category grouping, base price, base safety attributes, and duration
(for service-kind verticals).

**Schema.**
```yaml
categories:
  - id: <category_code>
    en: <English label>
    items:
      - id: <item_code>
        en: <English label>
        ko: <Korean label>           # optional, per vertical multilingual policy
        price: <number, USD>
        base_allergens: [...]        # food
        duration_min: <int>          # service (haircut=45, color=120)
        applies_modifiers: [...]     # modifier group ids
```

**Required fields:** per item — `id`, `en`, `price`. For service-kind
verticals — also `duration_min`.

**Multilingual.** Per [[feedback_multilingual_policy]]: cafe ships 5
languages (en/es/ko/ja/zh); other food verticals ship en + 1 native; beauty
ships en + ko + es (LA/NY/PDX market).

---

### Layer 3 — `modifier_groups.yaml` (Option Groups)

**Role.** Reusable groups of options that attach to items (size, milk
choice, blow-dry add-on, parts upgrade).

**Schema** (already established in cafe template — kept verbatim):
```yaml
groups:
  - id: <group_code>
    en: <English label>
    required: true|false
    min: <int>
    max: <int>
    options:
      - id: <option_code>
        en: <English label>
        price_delta: <number>
        allergen_add: [...]    # dynamics: ∪ on customer selection
        allergen_remove: [...] # dynamics: − on customer selection
    applies_to: [item_codes_or_categories]
```

**Allergen dynamics.** Effective allergen set =
`base_allergens ∪ ∪(option.allergen_add) − ∪(option.allergen_remove)`.
The `allergen_lookup` tool must use the effective set.

---

### Layer 4 — `system_prompt_base.txt` (Persona Prompt)

**Role.** Vertical-specific persona, language policy, behavioral rules.
Jinja2-style placeholders are resolved at session start.

**Required placeholders** (resolved by `voice_websocket.build_system_prompt`):
- `{{store_name}}`
- `{{business_hours}}`
- `{{address}}`
- `{{menu_listing}}` (service-kind: rendered service catalog)
- `{{modifier_listing}}`

**Recommended sections** (each as `=== HEADER ===` block):
- `LANGUAGE POLICY` (which languages supported; default; no mid-response
  switching).
- `TODAY'S MENU` or `TODAY'S SERVICES`.
- `AVAILABLE MODIFIERS` or `ADD-ONS`.
- `ABSOLUTE RULES` (greeting must include store name + persona; PHASE
  FLOW gate; etc.).

**Persona name extraction.** First line `You are <Name>, ...` is parsed
by `_extract_persona_name()`. Keep this format stable.

---

### Layer 5 — `intake_flow.yaml` ⭐ NEW

**Role.** Declarative PHASE FLOW gate. Currently hard-coded in
`voice_websocket.py:build_system_prompt` (PHASE FLOW gate rule 5). Lift
to yaml so each vertical can declare its own intake sequence.

**Schema.**
```yaml
phases:
  - id: <phase_code>           # e.g. CART, TOTAL, NAME, EMAIL, RECITAL
    label: <human readable>
    description: <what happens here>
    requires: [field_ids]      # fields that must be collected before exit
    optional_skip:
      - condition: <e.g. "customer_returning">
        skip_to: <phase_code>
    backtrack_allowed: true|false
    guardrails:
      - rule: <e.g. "MUST_HAVE_ITEMS_IN_CART">
        message: <what to say when violated>
completion_signals:
  - language: en
    pattern: <regex or keyword list>
    response: "<say this on detection>"
  - language: ko
    pattern: ...
    response: ...
```

**Vertical examples.**
- *Cafe / Pizza / Mexican / KBBQ* (order kind): CART → TOTAL → NAME → EMAIL → RECITAL
- *Beauty* (service kind): INTAKE → SERVICE_SELECT → STYLIST → TIME_SLOT → CONFIRM
- *Auto repair* (service_with_dispatch): SYMPTOM_INTAKE → DIAGNOSTIC_QUOTE → APPT_SCHEDULE → CONFIRM

**Backward compat.** If `intake_flow.yaml` is missing, the loader returns
null and `build_system_prompt` falls back to the existing hard-coded
PHASE FLOW gate block.

<!-- (현재 voice_websocket.py에 hard-coded된 PHASE FLOW gate를 yaml화. 누락 시 기존 흐름 유지.) -->

---

### Layer 6 — `scheduler.yaml` ⭐ NEW

**Role.** Slot model for the vertical. Food verticals use this for
pickup/reservation time slots (table seats × duration); beauty uses
stylist-bound slots; auto-repair uses bay × technician × duration.

**Schema.**
```yaml
slot_kind: table | stylist | technician | bay | none
default_duration_min: <int>
duration_buckets: [<min>, <min>, ...]   # e.g. [30, 45, 60, 90, 120] for beauty
opening_block_min: <int>                # smallest scheduling increment
resources:
  - id: <resource_id>                   # stylist_name or table_no
    en: <display label>
    specialties: [<service_ids>]        # optional
    capacity: <int>                     # 1 for stylist, N seats for table
buffer_min: <int>                       # gap between bookings
advance_booking_limit_days: <int>       # max days into future bookable
```

**Vertical examples.**
- *Cafe / Pizza*: `slot_kind: none` (pickup-only, no scheduling).
- *KBBQ / Sushi* (reservation-capable): `slot_kind: table`, capacity by
  seats.
- *Beauty*: `slot_kind: stylist`, duration_buckets `[30, 45, 60, 90, 120]`,
  resources lists each stylist with their specialties.

---

### Layer 7 — `emergency_rules.yaml` ⭐ NEW

**Role.** Time-sensitive policies and escalations that trigger handoff
to a human or follow strict protocols.

**Schema.**
```yaml
rules:
  - id: <rule_id>
    trigger:
      type: keyword | time_window | severity_match
      patterns: [<lowercase keywords>]
      time_before_appt_hours: <int>      # for late-cancel rules
      severity: [<critical_levels>]      # for allergy escalation
    action:
      type: handoff_human | apology_policy | offer_alternatives
      message: "<en/ko/es text>"
      log_severity: warn | critical
```

**Vertical examples.**
- *Beauty*: 24-hour-cancel policy → if `time_before_appt_hours < 24`,
  apologize + transfer to manager (no automatic cancel).
- *Food*: severe allergy declaration → escalate to staff before
  confirming order (don't promise allergen-free).
- *Auto repair / Home services*: emergency keywords ("gas leak",
  "no heat in winter") → immediate dispatch handoff.

---

### Layer 8 — `crm_followup.yaml` ⭐ NEW

**Role.** Trigger conditions for outbound CRM messages (post-call SMS,
re-engagement reminders).

**Schema.**
```yaml
triggers:
  - id: <trigger_id>
    when:
      type: post_call | post_appointment | inactivity
      delay_days: <int>                  # e.g. 42 for 6-week haircut refresh
      filter:
        last_service_in: [<service_ids>]
        customer_status: returning | new | lapsed
    channel: sms | email | both
    template_id: <crm_template_code>     # references jm_crm.templates
    enabled: true|false
```

**Vertical examples.**
- *Beauty*: 6-week haircut refresh (`delay_days: 42`, returning customer).
- *Cafe*: 7-day usual-order check-in (returning customer, ≥3 prior orders).
- *Auto repair*: oil-change reminder (`delay_days: 90`, last_service=oil_change).

---

### Layer 9 — `pricing_policy.yaml` ⭐ NEW

**Role.** Pricing rules beyond per-item price — surcharges, gratuity,
membership discounts, late-cancel fees.

**Schema.**
```yaml
model: per_item | flat_rate | hourly_plus_fee | membership
gratuity:
  enabled: true|false
  default_pct: <number, e.g. 18>
  required_for: [<service_categories>]    # mandatory tip on color services?
surcharges:
  - id: <surcharge_id>
    label: <human label>
    type: percent | flat
    amount: <number>
    applies_when: <condition_expression>
late_cancel_fee:
  enabled: true|false
  pct_of_service: <0.0-1.0>
  free_window_hours: <int>                # 24 for beauty
tax_rate: <0.0-1.0>                       # e.g. 0.0 for OR, 0.0825 for CA
```

**Vertical examples.**
- *Cafe / Pizza / Mexican*: per-item, optional tip, no late-cancel fee.
- *Beauty*: per_item + mandatory gratuity 18% on color, late_cancel_fee
  50% with 24h free window.
- *Auto repair*: hourly_plus_fee (labor hourly + parts).

---

## 4. Validator (`validator.py`)

**Behavior.** Lenient. Missing files → warning + return None. Missing
required field within a present file → warning, return parsed structure
with that field set to a documented default.

**API.**
```python
from app.templates._base.validator import load_template, validate_layer

template = load_template(vertical)         # returns TypedDict with all 9 layers
issues   = validate_layer(template, layer="intake_flow")
```

`load_template` returns a `VerticalTemplate` TypedDict:
```python
class VerticalTemplate(TypedDict):
    vertical: str
    kind: Literal["order", "service", "service_with_dispatch"]
    safety_rules:    dict | None
    catalog:         dict | None
    option_groups:   dict | None
    persona_prompt:  str  | None
    intake_flow:     dict | None
    scheduler:       dict | None
    emergency_rules: dict | None
    crm_followup:    dict | None
    pricing_policy:  dict | None
    issues: list[ValidationIssue]
```

**Required-field errors** are emitted as `ValidationIssue` records with
`severity` (warn/error) and `path` (e.g. `intake_flow.phases[2].requires`).
Phase 1.3 implements this.

---

## 5. Adding a New Vertical (Future)

Once Phase 1.6 lands, adding a new vertical requires:

1. Pick a `vertical_kind` from `_base/vertical_kinds.yaml`.
2. Create `backend/app/templates/<new_vertical>/`.
3. Drop 9 yaml files (or fewer if accepting fallbacks).
4. Add `DEFAULT_PERSONAS[<vertical>] = "<PersonaName>"` to
   `db_seeder.py` (already vertical-aware after [[vertical_default_persona_2026-05-16]]).
5. Optionally add a vertical-specific KPI module in
   `backend/app/knowledge/<vertical>.py` if the metrics differ from the
   base (food/beauty already provided).

Expected time: **2-3 days** per new vertical once the framework is locked.

<!-- (새 vertical 추가 = yaml 9개 + persona 1줄. ~2-3일.) -->

---

## 6. Backward Compatibility Promise

This Phase 1 work MUST NOT change behavior for existing live stores
(JM Cafe / JM Pizza / JM Taco / JM Korean BBQ / JM Home Services / JM
Auto Repair). Concretely:

- The 4 historical files (`allergen_rules.yaml`, `menu.yaml`,
  `modifier_groups.yaml`, `system_prompt_base.txt`) keep their filenames
  and existing schema.
- All 7+ call-sites that reference these filenames remain valid (no
  rename).
- New layers (5/6/7/8/9) are optional. If absent, `build_system_prompt`
  and the dispatcher behave exactly as today.
- A `vertical_kind` column on `stores` will be added in Phase 2 with a
  default of `"order"` for every existing row.
- Feature flag idea: in Phase 2 we can wrap service-kind dispatch behind
  `if store.vertical_kind == "service":`, leaving food paths untouched.

---

## 7. Open Questions (resolved during Phase 1)

- **Q1:** Should layers 1-3 be renamed to `safety_rules.yaml` /
  `service_catalog.yaml` / `option_groups.yaml`?
  **A1:** No — Strategy (a) confirmed. Keep historical filenames.

- **Q2:** Strict vs lenient validator?
  **A2:** Lenient. Missing fields → warning, default applied. Strict mode
  may be a future flag for CI.

- **Q3:** Do all five new layers ship in Phase 1?
  **A3:** Phase 1 ships the spec (this file) + validator + vertical_kinds.
  Actual yaml content for each existing vertical is filled in Phase 1.4/1.5.
  Beauty's nine layers are written in Phase 4.

---

## 8. Cross-references

- Plan: `docs/plans/2026-05-17_beauty-salon-mvp-plan/plan.pdf` (§Phase 1)
- Loader: `backend/app/services/onboarding/ai_helper.py:33`
- Existing PHASE FLOW gate (target of Layer 5): `backend/app/api/voice_websocket.py`
- Persona dict: see [[vertical_default_persona_2026-05-16]]
- Multilingual policy: see [[feedback_multilingual_policy]]
- Live-call caveat: see [[feedback_no_edits_during_live_call]]
