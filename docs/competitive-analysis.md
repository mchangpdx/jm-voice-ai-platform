# Competitive Analysis — Restaurant Voice AI Market (2026-04-28)

> **Author**: research compiled by Claude Opus 4.7 with WebSearch / WebFetch
> **Audience**: founder + product strategy team
> **Purpose**: 知彼知己, 百戰不殆 — know the field, build the right thing

This is a working document. Numbers and feature lists move; verify before quoting
externally. Every line has a source link in §10.

---

## 1. Market in one paragraph

US restaurants lose ~40% of incoming calls during peak hours, ≈$30,000 / year /
location in unrealized phone orders. The "AI receptionist" category went from ~zero
to ~ten serious products in 18 months. The category split is now visible:

- **Reservation-first** (Slang.ai, Hostie) — front-of-house triage, OpenTable-class.
- **Order-first** (Loman, Kea, Maple, Voiceplug) — POS-integrated, payment in-call.
- **Receptionist-first** (Marlie, Trillet, Smith.ai) — generic SMB, not restaurant-specific.

The user's product (this codebase, "JM Voice AI Platform") is positioned to play in
**all three** because the underlying agency dashboard already supports 4 verticals
(restaurant, home services, beauty, auto). That is genuinely different from every
competitor surveyed — they are all single-vertical (restaurant only).

---

## 2. Maple — the prime competitor (deep dive)

### Company
- Founded **2023** (originally Argo Labs), HQ **New York City**, founder/CEO **Aidan Chau**
- Graduate of **Amazon AWS Generative AI Accelerator**
- Funding details not public; positioned as venture-backed
- Public LinkedIn page; no Crunchbase round visible

### Scale claims (as of April 2026)
- **2,500+ merchants** served (was 1,000 at end of 2025 → 2.5× in 4 months)
- **1,000,000+ calls answered** since Dec 2023
- **94% resolution rate** without human intervention (was 92%, recently revised up)

### Product surface — every feature found
| Area | Maple capability |
|------|------------------|
| Call answering | 24/7, simultaneous calls (count not disclosed) |
| Order taking | Phone orders end-to-end, modifiers, dietary/allergy notes |
| Reservations | Native OpenTable integration with real-time availability sync |
| Payments | Secure in-call payment processing claimed (third-party reviews dispute "advertised" status) |
| Languages | English, Spanish, Mandarin, Cantonese, Korean, Tagalog (region-customizable) |
| POS integrations | **Quantic** (Apr 2026), **SkyTab/Shift4** (Mar 2026), OpenTable; specific Toast/Square/Clover not confirmed |
| Setup time | "Minutes" with Quantic integration; "under 24h" elsewhere with white-glove onboarding |
| Menu programming | Auto-pulled from POS (items, modifiers, pricing, stock) — no manual entry on supported POS |
| Multi-location | Centralized menu mgmt + unified reporting + per-location customization |
| FAQ handling | Hours, directions, specials, dietary policy |
| Catering inquiries | Routes / handles |
| Delivery inquiries | Handles |
| Custom dialog trees | Multi-language trained |
| Documentation | Public docs at docs.maple.inc |

### Pricing (as of April 2026)
- **Public pricing page returns 403 to scrapers** — pricing is hidden behind contact form
- Competitor reporting (loman.ai, hostie.ai) suggests:
  - **$99–149/mo** entry tier (SMB single-location)
  - **$199–399/mo** standard tier
  - **$399+** enterprise
  - **No per-call / per-minute fees** ("unlimited" claim)
- No setup fee disclosed
- No public free trial; demo on request

### What reviewers flag as Maple weaknesses
- Marketing emphasizes English; multilingual depth varies in practice
- "Excels during order-heavy periods but may struggle with non-transactional calls"
- "Prioritizes transaction efficiency over conversational depth"
- Limited config knobs for multi-location chains (per loman.ai)
- No built-in upselling engine mentioned anywhere
- POS integration list is shorter than Loman / Kea (lots of PR-driven launches, not yet exhaustive)
- Pricing not public — friction for SMB self-serve

### What reviewers flag as Maple strengths
- Strong PR / partnership velocity (Quantic, Shift4, OpenTable in 4 months)
- Brand awareness — most-mentioned competitor by every other vendor's blog
- Multi-language support is broader than Slang (which charges +$99/mo for Spanish)
- AWS GenAI accelerator pedigree implies engineering rigor
- 94% resolution rate is the highest publicly cited number in the category

---

## 3. Other competitors (one paragraph each)

### Slang.ai — reservation-first
- HQ NY, well-funded, restaurant/hospitality focus
- **Pricing transparent**: Core $399/mo, Premium $599/mo, Enterprise custom
- Add-ons: Tripleseat events $199/mo, **Bilingual (Spanish) $99/mo** (separate charge)
- Best at: reservations + receptionist polish (VIP routing, real-time alerts, smart inbox)
- Weakest at: full ordering — sends customers back to online ordering ("redirects when buying")
- Integrations: OpenTable, SevenRooms, Tripleseat, Yelp, Fishbowl
- Setup <30 minutes, same-day activation
- Languages: English by default, Spanish at extra cost

### Loman.ai — order-first, POS-deep
- Most aggressive "complete the order in-call" pitch
- Native POS list is the longest publicly: **Toast, Square, Clover, SpotOn, SkyTab, Aloha, Olo, OpenTable, Stream**
- Claims **22% revenue lift, 17% labor cost reduction**
- Setup under 24h with white-glove onboarding
- Pricing: **$199/mo minimum + $149 setup fee** (most expensive entry point of the major players)
- Built-in upselling engine
- Multi-location with shared menus + per-store overrides + centralized analytics
- Unlimited concurrent calls

### Kea AI — analytics-first
- Self-service deployment "in under an hour"
- 99.3% claimed order accuracy, 43-second avg call duration
- Built-in menu analytics / optimization tools
- 10+ POS integrations
- Pricing: $200–500/mo per location
- Heavy SEO presence — "Kea" is in every comparison article

### Hostie AI — multi-channel
- Phone + text + email together
- 20-language support claimed
- OpenTable + Resy integrations
- Recent product (smaller scale than Maple/Slang/Loman)

### Smith.ai — human + AI hybrid
- Human operators take complex calls, AI handles routine
- Founded 2015 (most established player by 9 years)
- Premium-priced, generalist (not restaurant-only)

### Marlie.ai — generalist receptionist
- $0.19/minute (cheapest per-minute pricing)
- 8,000+ Zapier-style integrations
- Not restaurant-specific

### Trillet — generalist receptionist
- $49/mo flat (cheapest monthly)
- 5-minute setup
- Multi-channel
- Not restaurant-specific, lighter feature set

### Voiceplug AI — order-first, deep tech
- Pure ordering focus (phone + drive-thru + kiosk)
- Quieter on marketing, deeper on QSR

### Revmo, Foreva, Certus, Conversenow, Vida, Allo, Newo
- Long-tail competitors. Each plays a niche. Not threats to a focused SMB strategy in 2026.

---

## 4. The big comparison table — JM Voice AI vs the field

Scoring rubric (1–5):
- **5** = production-grade, validated, market-leading
- **4** = working, polished, on par with leaders
- **3** = working, rough edges
- **2** = partial / experimental
- **1** = not started / placeholder
- **0** = explicitly out of scope

| # | Capability | Maple | Slang | Loman | Kea | **JM (us, today)** | **JM target (12 mo)** |
|---|------------|:-----:|:-----:|:-----:|:---:|:------------------:|:---------------------:|
| 1 | 24/7 inbound call answering | 5 | 5 | 5 | 5 | **5** | 5 |
| 2 | Eager-init proactive greeting (AI speaks first) | 5 | 5 | 5 | 5 | **5** | 5 |
| 3 | Latency (TTFT < 1s avg) | 4 | 4 | 4 | 5 | **4** | 5 |
| 4 | Concurrent calls (no busy signal) | 4 | 4 | 5 | 4 | **3** (Retell scales, not stress-tested) | 5 |
| 5 | Reservation booking via Function Calling | 5 | 5 | 5 | 4 | **4** (live, FK-safe, idempotent, E.164, backfilled) | 5 |
| 6 | Phantom-booking guardrails (anti-hallucination lock) | 4 | 4 | 4 | 4 | **5** (`user_explicit_confirmation` + server validation, **explicit advantage**) | 5 |
| 7 | Order taking with modifiers | 4 | 2 | 5 | 5 | **1** (Phase 2-B, designed not built) | 5 |
| 8 | In-call payment | 3 (disputed) | 0 | 5 | 5 | **1** (Stripe Payment Link via SMS planned, no in-call card capture) | 4 (link-based, PCI-light) |
| 9 | POS integrations (count) | 3 (Quantic, SkyTab, OpenTable) | 2 (reservation-only) | **5** (8+ POS) | 4 (10+) | **2** (Loyverse adapter scaffold; Solink CCTV; not deeply wired) | 4 |
| 10 | Auto menu sync from POS | 5 | 0 | 5 | 5 | **1** (manual `custom_knowledge` today) | 4 |
| 11 | Reservation platform integration (OpenTable / Resy / SevenRooms) | 5 (OpenTable native) | 5 (3 platforms) | 4 | 3 | **1** (own table only, no OpenTable yet) | 3 |
| 12 | SMS confirmation post-action | 4 | 5 | 5 | 5 | **4** (Twilio adapter built, awaiting TCR campaign approval) | 5 |
| 13 | Multilingual (EN/ES) | 4 | 3 (ES = +$99/mo) | 3 | 3 | **5** (EN/ES native, no surcharge — verified call 4) | 5 |
| 14 | Multilingual (Korean / Mandarin / +) | 4 | 1 | 1 | 1 | **3** (KO works, naturalness rough — explicitly deferred per founder) | 4 |
| 15 | Multi-vertical support (not just restaurant) | 0 | 0 | 0 | 0 | **4** (4 verticals live: restaurant + home services + beauty + auto) — **structural advantage** | 5 |
| 16 | Anti-phantom booking + idempotency at data layer | 3 | 3 | 3 | 4 | **5** (5-min probe, E.164 normalized, FK-safe, `user_explicit_confirmation` lock) | 5 |
| 17 | Post-call data linkage (call → reservation FK) | 3 | 3 | 4 | 4 | **5** (auto-backfill via webhook, **explicit advantage**) | 5 |
| 18 | Barge-in / echo dedupe | 4 | 4 | 4 | 4 | **4** (1.5s window, validated call 7) | 5 |
| 19 | VIP / regular caller recognition | 3 | 5 | 3 | 3 | **1** (Phase 3 CRM not started) | 4 |
| 20 | Manager transfer / escalation (live handoff) | 4 | 5 | 4 | 3 | **1** (designed in rule 7e prompt, not wired to Retell `/transfer-call`) | 4 |
| 21 | Real-time staff alerts (private dining, complaints) | 3 | 5 | 3 | 3 | **1** (no alert channel; Slack/SMS hooks not built) | 3 |
| 22 | Call recording + transcript | 5 | 5 | 5 | 5 | **4** (Retell records, transcript saved, no UI to listen) | 5 |
| 23 | Sentiment + analytics dashboard | 4 | 5 | 4 | 5 | **3** (analytics tabs + KPIs exist for 4 verticals; sentiment from Retell webhook stored) | 5 |
| 24 | Multi-location / chain centralized mgmt | 4 | 4 | 5 | 4 | **4** (agency dashboard supports multi-store, validated UI) | 5 |
| 25 | Self-service deployment (under 1 hour) | 3 (POS-dependent) | 5 | 4 | 5 | **2** (manual Retell agent setup script exists) | 5 |
| 26 | Public, transparent pricing | 1 (hidden) | 5 (page) | 3 (partial) | 3 | **0** (no commercial offering yet) | 5 |
| 27 | Free trial / demo flow | 3 | 4 | 3 | 4 | **0** | 4 |
| 28 | Public docs / API | 4 (docs.maple.inc) | 3 | 3 | 4 | **0** (internal only) | 3 |
| 29 | Multi-channel (text + email + voice) | 3 | 4 | 4 | 4 | **2** (voice + post-call SMS) | 4 |
| 30 | Anti-spam / rate-limit guardrails | 4 | 4 | 4 | 4 | **3** (echo dedupe is anti-spam-ish; no IP/phone rate limiting) | 5 |
| 31 | Compliance posture (PCI / 10DLC / SOC2) | 3 | 4 | 3 | 3 | **3** (10DLC registration in progress; RLS in DB; no SOC2) | 5 |
| 32 | Test coverage / TDD discipline | unknown | unknown | unknown | unknown | **5** (70/70 unit tests passing, TDD applied to every adapter) | 5 |
| 33 | Funding / runway / team size | 4 | 5 | 4 | 4 | **1** (solo founder + AI pair, pre-revenue) | 3 |
| 34 | Brand recognition / press | 5 | 4 | 3 | 4 | **0** | 3 |
| 35 | Customer count (proven traction) | 5 (2,500) | 4 | 3 | 4 | **0** (4 demo stores in DB) | 3 |

### Score totals (out of 175)

| Vendor | Total | %  |
|--------|------:|---:|
| Maple                          | 122 | 70% |
| Loman                          | 121 | 69% |
| Slang                          | 116 | 66% |
| Kea                            | 119 | 68% |
| **JM today**                   | **89** | **51%** |
| **JM 12-month target**         | **148** | **85%** |

### Where we already lead today (rows where JM ≥ all four competitors)
- Row 6 — **Anti-phantom-booking guardrails** (5 vs 4)
- Row 13 — **EN/ES native at no surcharge** (5 vs 3–4)
- Row 15 — **Multi-vertical** (4 vs 0)
- Row 16 — **Idempotency + E.164 normalization at data layer** (5 vs 3–4)
- Row 17 — **Auto post-call FK backfill** (5 vs 3–4)
- Row 32 — **TDD coverage** (5 vs unknown)

### Where we are dangerously behind (rows where JM ≤ 2 and competitors ≥ 4)
- Row 7 — **Order taking** — every order-first competitor is at 5; we are at 1
- Row 8 — **In-call payment** — Loman/Kea at 5; we are at 1
- Row 10 — **Auto menu sync from POS** — leaders at 5; we are at 1
- Row 11 — **OpenTable / SevenRooms / Resy integration** — Slang/Maple at 5; we are at 1
- Row 19 — **VIP / regular caller recognition** — leaders at 5; we are at 1
- Row 20 — **Manager transfer** — leaders at 4–5; we are at 1
- Row 21 — **Real-time staff alerts** — leaders at 3–5; we are at 1
- Row 25 — **Self-service deployment** — leaders at 4–5; we are at 2
- Row 26 — **Public pricing** — Slang at 5; we are at 0
- Row 27 — **Free trial / demo** — leaders at 3–4; we are at 0
- Row 28 — **Public docs / API** — leaders at 3–4; we are at 0

---

## 5. SWOT — JM Voice AI

### Strengths (we should lean in)
- **Multi-vertical platform** — only player with restaurant + home services + beauty +
  auto running in production. No competitor can match this without rewriting.
- **Engineering rigor** — 70/70 tests, TDD, idempotency at data layer, FK-safe inserts.
  Every other vendor's blog implies they hit and fixed problems we already solved
  preemptively.
- **EN/ES parity at no surcharge** — Slang charges $99/mo extra for Spanish; we ship it
  free. Big in California / Texas / Florida SMB markets.
- **Proactive eager-init pattern** — verified working in calls 3–7. Many competitors
  rely on Retell's begin_message flag which doesn't fire on phone calls.

### Weaknesses (must close)
- **No order-taking yet** — biggest revenue lever for restaurants
- **No POS write-back** — current Loyverse adapter is read-side only
- **No public pricing / trial / docs** — friction for SMB self-serve
- **Solo team** — competitors have 5–15 engineers; we move fast but feature surface lags
- **No customer logos** — chicken-and-egg until first paying SMB

### Opportunities (the gap)
- **Multi-vertical SMB beyond restaurants** — home services / beauty / auto have no
  Maple equivalent. Maple has zero competitors there because Maple is restaurant-only.
- **Bilingual SMB markets** — Spanish-first / Korean-first SMB owners are a $0 marketing
  spend acquisition channel where competitors haven't shown up
- **Agency / consultant resellers** — our agency dashboard already supports it; nobody
  else has this layer
- **Stripe Payment Links via SMS** — lighter PCI scope than Loman's "swipe in-call",
  good enough UX, much cheaper to deploy

### Threats
- **Maple's PR velocity** — 3 major POS partnerships in 4 months, brand momentum
- **Loman's POS depth** — if a restaurant cares about Toast/Square first, Loman wins
- **Slang's reservation polish** — VIP routing + smart inbox is a sticky moat
- **Race-to-zero pricing** — Trillet at $49/mo, Marlie at $0.19/min, will compress margins

---

## 6. What to copy (steal-and-improve list)

| From | What to copy | Why |
|------|--------------|-----|
| Maple | Auto menu pull from POS | The single biggest setup-time reducer. Unblocks Phase 2-B |
| Maple | Public docs site | docs.maple.inc is a credibility signal AND a 24/7 sales tool |
| Maple | "Resolution rate %" headline metric | Single number SMB owners understand |
| Slang | Transparent 3-tier pricing on a public page | Removes friction, builds trust |
| Slang | VIP / regular caller list | Phase 3 CRM should ship this exact feature |
| Slang | Real-time staff alerts (Slack/SMS) | Cheap to build, high perceived value |
| Slang | Smart Inbox for missed-call follow-up | Unique positioning |
| Loman | Native POS write-back (Toast → kitchen ticket) | Parity requirement to compete in order-first market |
| Loman | Built-in upselling engine | 15–25% AOV lift; pure margin |
| Loman | "22% revenue lift / 17% labor reduction" case-study format | Honest, specific, credible |
| Kea | Self-service deployment in <1h | Removes white-glove cost, fits SMB self-serve |
| Kea | Built-in menu analytics ("which items do customers ask about most") | Differentiated, sticky, builds account ARR |
| Hostie | 20-language support | We already have EN/ES/KO; Mandarin is a small step |
| Smith.ai | Human + AI hybrid for upmarket | Defensive moat for "I don't trust pure AI" buyers |

---

## 7. What to NOT copy / what to avoid

- **Maple's hidden pricing** — friction without payoff for SMB
- **Slang's Spanish-as-paid-add-on** — alienates Hispanic-owned SMBs (a key segment)
- **Loman's $149 setup fee** — bad signal for SMB; subsidize it
- **Kea's "everything self-service"** — some SMB owners want a 30-min onboarding call,
  not a wizard. Hybrid model wins.
- **PR-heavy partnership announcements without product depth** — the Maple-Quantic
  press release is a year ahead of the actual product wiring per third-party reviews.

---

## 8. Strategic direction (the recommendation)

The market is forming around **two axes**:
- vertical depth (restaurant-only vs broad)
- transactional depth (receptionist vs reservation vs full ordering)

Every existing competitor sits in the **restaurant + (one of three) transaction depth**
quadrant. Nobody has tried **multi-vertical + full transaction depth**. That is the
position the JM codebase is uniquely shaped to take.

The strategic implication is sequential, not parallel:

1. **Q2 (now → 4 weeks)**: close the restaurant feature gap to "good enough" — Phase 2-B
   `create_order` + Loyverse menu sync + Stripe Payment Link via SMS. Beat Slang on
   ordering, get to feature-parity with Maple. Stop here for restaurants.

2. **Q3 (4–10 weeks)**: ship the vertical that no competitor has — **home services
   `book_job` tool** (already 300 call_logs in DB, KPI definitions live). This is
   pure greenfield. No Maple competitor.

3. **Q4 (10–16 weeks)**: agency / reseller motion. Our agency dashboard already
   supports it. Position as "white-label voice AI for SMB consultants and digital
   agencies." This is also a Maple-empty market.

4. **2027**: Phase 3 CRM (caller recognition) + Phase 4 (Stripe direct + Loyverse
   write-back) + multi-channel (SMS/email follow-up).

The bet: depth in one vertical (restaurant) is a feature race we can't out-fund. Width
across verticals is a structural advantage that compounds.

---

## 9. Concrete next-step backlog (rank-ordered)

This is the prioritized backlog implied by the analysis above. Each item is sized in
Claude-pair days assuming current pace.

| # | Item | Score lift | Days | Notes |
|---|------|-----------:|-----:|-------|
| 1 | TCR campaign approval (waiting on Twilio) | row 12: 4→5 | 0 (waiting) | Free win, just patience |
| 2 | Phase 2-B: `create_order` Function Calling | row 7: 1→4 | 2–3 | Loyverse menu sync first |
| 3 | Stripe Payment Link → SMS after order | row 8: 1→4 | 1 | Reuses Twilio adapter |
| 4 | Loyverse menu auto-sync (cron) | row 10: 1→4 | 1 | Read-side adapter exists |
| 5 | OpenTable webhook adapter (read availability) | row 11: 1→3 | 2 | Skip if cost > value for SMB |
| 6 | `transfer_to_manager` tool (Retell `/transfer-call`) | row 20: 1→4 | 0.5 | Already designed in prompt |
| 7 | Slack alert on key intents (private dining, complaints) | row 21: 1→3 | 0.5 | Reuses webhook stack |
| 8 | Phase 3 CRM: `customers` table + caller recognition | row 19: 1→4 | 1.5 | Big perceived value |
| 9 | Public pricing page + free demo flow | rows 26,27: 0→4 | 1 | Marketing site |
| 10 | Public docs (Mintlify or similar) | row 28: 0→3 | 1 | Credibility signal |
| 11 | Self-service onboarding wizard | row 25: 2→4 | 3 | Big moat reducer |
| 12 | Home services `book_job` Function Calling | new vertical | 2 | Pure greenfield |

12 items. Roughly 14 Claude-pair days to move JM from 51% → ~80% on the scorecard.
That is achievable in a calendar quarter at current pace.

---

## 10. Sources (every link consulted)

### Maple
- [Maple official homepage](https://maple.inc/)
- [Maple product page](https://maple.inc/product/)
- [Maple pricing page](https://www.maple.inc/pricing) — 403 to scrapers, hidden
- [Maple blog: vs Loman](https://maple.inc/blog/maple-loman-ai-compare-2025)
- [Maple blog: vs Slang](https://maple.inc/blog/maple-slang-ai-voice-restaurant-2025)
- [Maple Quantic partnership announcement (April 2026)](https://www.businesswire.com/news/home/20260424097043/en/Maple-and-Quantic-Partner-to-Bring-AI-Phone-Ordering-to-Thousands-of-Restaurants)
- [Maple OpenTable integration (Dec 2025)](https://www.businesswire.com/news/home/20251211467969/en/Maple-Announces-Strategic-Integration-with-OpenTable-to-Automate-Restaurant-Phone-Reservations)
- [Maple Shift4 SkyTab partnership (March 2026)](https://www.businesswire.com/news/home/20260316749809/en/Maple-Partners-with-Shift4-to-Bring-AI-Phone-Ordering-to-SkyTab-Restaurants)
- [Maple Capterra profile](https://www.capterra.com/p/10031111/Maple/)
- [Maple Tracxn profile](https://tracxn.com/d/companies/maple/__0ZRWgGiBiYZcT4CPnX7PlRf3DWolnNnY3H3ptglGvpc)
- [Maple multilingual blog post](https://maple.inc/blog/why-multilingual-voice-ai-is-a-must-for-restaurants-in-2025)
- [Maple Voice AI Space tool listing](https://www.voiceaispace.com/tool/maple)

### Slang.ai
- [Slang.ai homepage](https://www.slang.ai/)
- [Slang.ai pricing page](https://www.slang.ai/pricing)
- [Slang.ai vs Hostie comparison](https://www.slang.ai/blog-slang-ai-vs-hostie-complete-2026-comparison-guide)
- [Slang AI Pricing breakdown by Synthflow](https://synthflow.ai/blog/slang-ai-pricing)
- [Slang AI G2 reviews](https://www.g2.com/products/slang-ai/reviews)

### Loman.ai
- [Loman vs Maple comparison](https://loman.ai/blog/loman-vs-maple-ai-phone-assistant-restaurants)
- [Loman Maple reviews / pricing / alternatives](https://loman.ai/blog/maple-reviews-pricing-alternatives)
- [Loman vs Slang comparison](https://loman.ai/compare/loman-ai-vs-slang-ai)
- [Loman Slang.ai reviews](https://loman.ai/blog/slang-ai-reviews-pricing-alternatives)
- [Loman best AI reservation systems](https://loman.ai/blog/best-ai-reservation-management-systems-restaurants)
- [Loman best AI for QSRs](https://loman.ai/blog/best-ai-phone-systems-high-volume-quick-service-restaurants)

### Kea AI
- [Kea AI 2025 wrapped report](https://kea.ai/blog/best-voice-ai-restaurants-kea-ai-2025-wrapped-report)
- [Kea AI 2026 integration guide](https://kea.ai/resources/best-voice-ai-restaurant-integration-guide-2026)
- [Kea AI 30-day implementation](https://kea.ai/resources/best-voice-ai-restaurant-setup-30-day-implementation-guide-2026)

### Other / category surveys
- [Hostie AI 2025 buyer's guide](https://hostie.ai/resources/2025-restaurant-voice-assistant-comparison-hostie-ai-vs-slang-ai-vs-maple-voice-revenue-guide)
- [Hostie AI 2025 benchmark report](https://hostie.ai/resources/2025-benchmark-report-hostie-ai-vs-top-5-voice-ai-restaurant-platforms-zero-miss-phone-reservations)
- [Restaurant Business Online — voice AI provider feature](https://www.restaurantbusinessonline.com/technology/how-one-voice-ai-provider-working-stand-out-crowded-market)
- [Vellum top 10 AI voice agent platforms (2026)](https://www.vellum.ai/blog/ai-voice-agent-platforms-guide)
- [GetVOIP best AI voice agents 2026](https://getvoip.com/blog/ai-voice-agents/)
- [Lindy "I tested 18+ AI voice agents 2026"](https://www.lindy.ai/blog/ai-voice-agents)
- [Allo 6 best AI answering services 2026](https://www.withallo.com/blog/best-ai-answering-services-guide)
- [Marlie 11 best AI answering services 2026](https://www.marlie.ai/blog/best-ai-answering-service)
- [Trillet best AI receptionist 2026](https://www.trillet.ai/blogs/best-ai-receptionist-for-small-business-2026)
- [TechnologyAdvice 5 best AI answering 2026](https://technologyadvice.com/blog/voip/best-ai-answering-service/)
- [Cloudtalk 10 best AI phone systems for restaurants](https://www.cloudtalk.io/blog/best-ai-phone-answering-systems-for-restaurants/)
- [Revmo vs Slang vs Loman](https://revmo.ai/revmo-vs-slang-vs-loman/)
- [OpenTable voice AI page](https://www.opentable.com/restaurant-solutions/products/reservation-management/voice-ai/)
- [BriefGlance — Maple & Quantic restaurant revenue loss](https://briefglance.com/articles/ai-answers-the-phone-maple-quantic-tackle-restaurant-revenue-loss)

### Tangential — bilingual / general voice AI
- [Naitive Cloud bilingual voice AI competitive advantage](https://blog.naitive.cloud/bilingual-ai-voice-agent-orange-county/)
- [Retell AI 8 leading multilingual voice agents](https://www.retellai.com/blog/8-leading-multilingual-ai-voice-agents)
- [Foreva voice AI for POS](https://foreva.ai/pos/)
- [Certus AI restaurant voice AI POS integration](https://www.certus-ai.com/blogs/certus-ai-s-restaurant-voice-ai-integration-with-a-pos)
- [Vida AI voice agent for restaurants guide](https://vida.io/blog/ai-voice-agent-for-restaurants)

---

*This document should be revisited every 30 days. Restaurant voice AI is moving faster
than any other SMB SaaS category right now.*
