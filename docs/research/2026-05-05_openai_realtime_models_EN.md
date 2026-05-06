# OpenAI Realtime Models — Comprehensive Research for JM Tech One Migration

**Date:** 2026-05-05  |  **Analyst:** smb-voice-agent-researcher  |  **Audience:** JM Tech One founders (2-person team, Portland HQ)  |  **Decision context:** Retell + Gemini 3.1 Flash Lite → OpenAI Realtime direct migration

---

## Executive Summary

As of 2026-05-05, OpenAI's Realtime API has converged on a clean three-model lineup: **`gpt-realtime-1.5`** (flagship, released 2026-02-23), **`gpt-realtime`** (GA Aug 2025, snapshot `2025-08-28`), and **`gpt-realtime-mini`** (cost-tier, two snapshots `2025-10-06` and `2025-12-15`). The legacy `gpt-4o-realtime-preview*` family was deprecation-noticed in September 2025 and exits the API in March 2026 (already past — i.e., effectively retired by today's date). Pricing has stabilized at **$32/$64 per 1M audio in/out** for the full models and **~$10/$20 per 1M audio in/out** for mini (a ~3× cost reduction). For JM Tech One's pilot — a single-store F&B operation in Portland with 8 voice tools, idempotent guards, and an explicit Asian-SMB expansion path — the right choice is **`gpt-realtime-1.5`** for production with **`gpt-realtime-mini`** as the canary/regression and rate-limit-fallback tier. Avoid `gpt-4o-realtime-preview*` outright (deprecated), and avoid pinning to dated `gpt-realtime-2025-08-28` for new development given that 1.5 ships measurable wins on tool-calling reliability (+7% instruction following), Korean/Japanese/Chinese language switching mid-utterance, and alphanumeric transcription (+10.23%) — all four of which map directly to JM's pain surface (tool-call reliability dominates restaurant correctness; alphanumeric matters for phone numbers and order codes; multilingual switching is the entire Asian-SMB wedge).

---

## 1. Model Lineup — Exhaustive Inventory (2026-05-05)

| Model | Snapshot(s) | Released | Status | Modalities | Context | Max Output | Max Session |
|---|---|---|---|---|---|---|---|
| **`gpt-realtime-1.5`** | `gpt-realtime-1.5` (alias), Azure version `2026-02-23` | 2026-02-23 | GA, current flagship | audio in/out, text, image in | 32K (~28,672 input cap) | 4,096 | 60 min (OpenAI) / 30 min (Azure EU) |
| **`gpt-realtime`** | `gpt-realtime-2025-08-28` (dated), `gpt-realtime` (alias floats forward) | 2025-08-28 GA | GA, prior flagship; alias may now point to 1.5 | audio in/out, text, image in | 32K | 4,096 | 60 min |
| **`gpt-realtime-mini`** | `gpt-realtime-mini-2025-12-15` (newer), `gpt-realtime-mini-2025-10-06` (older) | 2025-10-06 / 2025-12-15 | GA, cost-tier | audio in/out, text | 128K (per model card) / 32K effective in Realtime sessions | 4,096 | 60 min |
| **`gpt-4o-realtime-preview-*`** | `2024-10-01`, `2024-12-17`, `2025-06-03` | 2024-10 → 2025-06 | **Deprecated** (sunset 6 months from Sep 2025 notice → ~March 2026) | audio in/out, text | 128K | 4,096 | 30 min historically |
| **`gpt-4o-mini-realtime-preview-*`** | `2024-12-17` | 2024-12 | **Deprecated** with parent family | audio in/out, text | 128K | 4,096 | 30 min |

**Voices available on the Realtime API (gpt-realtime / 1.5):** `marin`, `cedar` (introduced with the Aug-2025 GA, exclusive to Realtime), plus legacy voices `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`. Marin and Cedar are reported by OpenAI as the most natural-sounding voices in the portfolio.

**No undisclosed beta / `gpt-realtime-2.0` / `gpt-realtime-pro`** is currently surfaced in Azure model registries, OpenAI changelog, or developer community posts as of 2026-05-05. If such a model exists, it is non-public.

---

## 2. Pricing — Authoritative as of 2026-05-05

All prices in USD per 1M tokens. Audio token math: **user audio = 1 token / 100 ms** (600 tokens/min); **assistant audio = 1 token / 50 ms** (1,200 tokens/min).

| Model | Audio in | Audio out | Audio cached in | Text in | Text out | Text cached in |
|---|---|---|---|---|---|---|
| `gpt-realtime-1.5` | $32.00 | $64.00 | $0.40 | $4.00 | $16.00 | $0.40 |
| `gpt-realtime` (2025-08-28) | $32.00 | $64.00 | $0.40 | $4.00 | $16.00 | $0.40 |
| `gpt-realtime-mini` | $10.00 | $20.00 | $0.30 | $0.60 | $2.40 | $0.06 |
| `gpt-4o-realtime-preview-2025-06-03` (deprecated) | $40.00 | $80.00 | $2.50 | $5.00 | $20.00 | $2.50 |
| `gpt-4o-mini-realtime-preview` (deprecated) | $10.00 | $20.00 | $0.30 | $0.60 | $2.40 | $0.30 |

**Per-minute estimate for an 80/20 listen-vs-speak ratio (5-minute call, customer talks 4 min, agent talks 1 min):**

- Audio in: 4 min × 600 tok/min = 2,400 tokens
- Audio out: 1 min × 1,200 tok/min = 1,200 tokens
- gpt-realtime-1.5 cost per 5-min call: (2,400 × $32 + 1,200 × $64) / 1,000,000 = **$0.1536** ≈ **$0.031/min**
- gpt-realtime-mini cost per 5-min call: (2,400 × $10 + 1,200 × $20) / 1,000,000 = **$0.048** ≈ **$0.0096/min**
- gpt-4o-realtime-preview legacy: ~$0.192 per 5-min call ≈ $0.038/min (deprecated)

**Note on cached input:** With aggressive system-prompt and tool-schema caching, 1.5 / GA reduce effective input cost ~80× ($32 → $0.40). For JM's restaurant prompt + 8 tool schemas (~5K tokens system + tools), cached repeat hits drop the static cost to negligible per call.

---

## 3. Capability Differences (1.5 vs GA vs mini)

| Capability | gpt-realtime-1.5 | gpt-realtime (08-28) | gpt-realtime-mini |
|---|---|---|---|
| Function calling — ComplexFuncBench Audio | not separately disclosed; +7% instruction-following over GA | 66.5% (vs 49.7% for prior) | not disclosed; reported as adequate, not flagship |
| Async function calling | yes (preserves session flow) | yes | yes |
| Parallel tool calls | yes | yes | yes |
| Image input (multimodal context) | yes | yes | no (text + audio only) |
| MCP server connection | yes | yes | yes |
| Semantic VAD (with eagerness param) | yes | yes | yes |
| Server VAD (legacy) | yes | yes (note: known bug interaction with tool use in some snapshots) | yes |
| SIP support | yes (dedicated SIP IPs added 2026) | yes | yes |
| WebRTC / WebSocket | both | both | both |
| Voices | Marin, Cedar + 8 legacy | same | subset (legacy voices; Marin/Cedar availability inconsistent in mini) |
| Multilingual switching mid-utterance | improved over GA; explicit feature | yes; weaker than 1.5 | yes; weakest of the three |
| Big Bench Audio reasoning | +5% over GA | baseline | below GA |
| Alphanumeric transcription | +10.23% over GA (phone numbers, order codes) | baseline (already strong vs gpt-4o) | weaker — risk for order numbers / phone capture |
| EU data residency | yes (also `gpt-4o-realtime-preview-2025-06-03`) | yes (`2025-08-28` snapshot only) | partial |
| HIPAA via OpenAI BAA | not formally listed for audio in/out as of 2026 (per Azure clarification thread) — **flag for legal review** | same caveat | same caveat |
| Zero Data Retention (ZDR) | available via Trust Center request; compatible with `store=false` and WebSocket | same | same |

---

## 4. Latency, Rate Limits, Operational Limits

- **TTFT / first-audio-chunk:** OpenAI Realtime family historically benchmarks at ~250–300 ms TTFT on audio-out (GA `gpt-realtime`). 1.5 is incremental — no public TTFT regression reported; community feedback (Sendbird, Genspark) emphasizes "exceptional improvements in handling interruptions" and "phone call errors cut in half" with 66% connection-rate doubling at Genspark.
- **Rate limits (Tier 1, default for new accounts):** ~200 RPM, ~40K TPM — but Realtime sessions are accounted differently (concurrent session counts dominate). Tier 5 reaches ~20K RPM, 15M TPM.
- **Concurrent Realtime sessions:** Officially soft-capped around 100 per API key (community-reported), but several developers have observed >500 sessions opening successfully without 429s. **Plan for ~100 hard, validate via stress test before assuming more.**
- **Max session length:** 60 min on direct OpenAI; 30 min on Azure EU. JM Cafe restaurant calls are typically <5 min — non-binding.
- **Context window:** 32K tokens with ~28,672 input cap. Long calls require client-side summarization/truncation; Realtime API does not auto-compact.
- **Known issues to plan around:**
  - Server VAD in some snapshots breaks tool use (community-reported in Q1 2026); semantic VAD recommended.
  - Transcript leakage bug filed against `gpt-realtime-2025-08-28` (other users' data appearing in transcripts) — yet another reason to use the floating alias `gpt-realtime` or move to 1.5.
  - Multilingual: French and accented English are weaker than core English; Korean/Japanese/Chinese accuracy is good but not flawless — language can spontaneously switch mid-conversation if prompt isn't anchored.

---

## 5. Multilingual Reality Check

OpenAI publishes 57+ supported languages but only asserts those with <50% WER as "supported." For JM's planned Asian-SMB expansion, the practical picture:

| Language | gpt-realtime-1.5 | gpt-realtime GA | mini | Notes |
|---|---|---|---|---|
| English | excellent | excellent | excellent | Native quality |
| Spanish | very good (improved alphanumeric) | very good | good | Hispanic-heavy PDX markets viable |
| Korean | good — improved switching in 1.5 | usable | weakest | Anchor prompt to Korean explicitly to prevent mid-call drift |
| Japanese | good | usable | weakest | Same anchor advice |
| Mandarin Chinese | good | usable | weakest | Tone reliability acceptable; idiom less natural |
| French | weakest among majors | weakest | weakest | Avoid for now |

**Mid-call language switching** ("English ↔ Korean ↔ English") is a marquee 1.5 feature and substantially better than GA. mini is meaningfully worse — do not deploy mini to multilingual markets without prompt-level guardrails.

---

## 6. Scoring Matrix — JM-Specific Decision Factors

All scores out of 10. Weights reflect JM's stated priority: cost is real but not dominant at single-store scale; tool reliability is existential; multilingual is the wedge for Asian-SMB.

**Weights:** Cost 20%, Latency (TTFT/barge-in) 20%, Multilingual switching 25%, Tool/feature compatibility 35%.

| Model | Cost (20%) | Latency (20%) | Multilingual (25%) | Tool/feature compat (35%) | Weighted total |
|---|---|---|---|---|---|
| **`gpt-realtime-1.5`** | 7 / 10 (mid) | 9 / 10 (best interruption handling) | 9 / 10 (mid-call switching, +10% alphanumeric) | 10 / 10 (best ComplexFuncBench, async tools, image, MCP) | **(7×0.20)+(9×0.20)+(9×0.25)+(10×0.35) = 1.4+1.8+2.25+3.5 = 8.95** |
| **`gpt-realtime` (08-28 dated)** | 7 / 10 | 8 / 10 | 7 / 10 | 9 / 10 (66.5% ComplexFuncBench) | **(7×0.20)+(8×0.20)+(7×0.25)+(9×0.35) = 1.4+1.6+1.75+3.15 = 7.90** |
| **`gpt-realtime-mini`** | 10 / 10 (3× cheaper) | 8 / 10 | 5 / 10 (weakest) | 7 / 10 (no image; tool-call accuracy below flagship) | **(10×0.20)+(8×0.20)+(5×0.25)+(7×0.35) = 2.0+1.6+1.25+2.45 = 7.30** |
| **`gpt-4o-realtime-preview-2025-06-03`** | 4 / 10 (most expensive, deprecated) | 7 / 10 | 6 / 10 | 6 / 10 (49.7% ComplexFuncBench) | **(4×0.20)+(7×0.20)+(6×0.25)+(6×0.35) = 0.8+1.4+1.5+2.1 = 5.80** |
| **`gpt-4o-mini-realtime-preview`** | 9 / 10 (cheap, deprecated) | 7 / 10 | 4 / 10 | 5 / 10 (older tool stack) | **(9×0.20)+(7×0.20)+(4×0.25)+(5×0.35) = 1.8+1.4+1.0+1.75 = 5.95** |

**Winner by aggregate: `gpt-realtime-1.5` at 8.95/10.** Mini is the strongest fallback at 7.30. Both gpt-4o legacy variants are dominated and deprecated — exclude.

---

## 7. Scenario-Based Recommendations

**Monthly call volume baseline: 5 stores × 50 calls/day × 5 min × 30 days = 37,500 minutes/month.**

### Scenario A — Single-store English-mostly pilot (JM Cafe, today)
- **Recommended: `gpt-realtime-1.5`** (alias `gpt-realtime` at minimum if 1.5 not yet available on selected billing region).
- Monthly cost at 1 store (7,500 min): ~$0.031/min × 7,500 = **~$232/mo** (before caching). With cached system+tools, plausibly $180–$200.
- Why: tool-call reliability is the existential risk for restaurant ordering. The cost gap to mini ($72/mo savings) is not worth the function-calling regression at 1-store scale.

### Scenario B — PDX 5-store expansion, Hispanic customer share elevated
- **Recommended: `gpt-realtime-1.5`** for all 5 stores. Spanish quality on 1.5 is "very good" with strong alphanumeric — important for capturing phone numbers in Spanish.
- Monthly cost: ~$232 × 5 = **~$1,160/mo** raw; **~$700–$900/mo** with caching.
- Hybrid not recommended at this stage — operational complexity exceeds savings.

### Scenario C — Asian-SMB expansion (Korean / Japanese / Chinese restaurants)
- **Recommended: `gpt-realtime-1.5`, no compromise.** Mini's multilingual quality is the weakest tier and would directly damage the Korean wedge.
- Anchor the system prompt explicitly to the store's primary language with `respond_in_language` directive; instruct switching only on user-initiated request.
- Monthly cost projection identical to B until volume scales.

### Scenario D — 100 calls/hour scale (single mega-store or aggregate)
- **Recommended: `gpt-realtime-1.5` primary + `gpt-realtime-mini` overflow router.** Pre-classify intent on call setup (caller-ID + first-utterance intent classifier on text-only Gemini 3.1 Flash Lite or `gpt-realtime-mini`); route simple FAQ/hours/menu reads to mini; route reservation/order/payment intents to 1.5.
- Hybrid ROI: if 40% of calls route to mini, blended cost drops from $0.031/min → ~$0.022/min (~30% savings). At 100 calls/hour × 8 hrs × 5 min = 4,000 min/day = 120K min/month, savings = ~$1,080/mo.
- Operational caveat: hybrid routing adds 2 fail-modes (router error, mini-to-flagship handoff). Build only after 1.5-only is stable at 5-store scale.

### Hybrid mini ↔ flagship routing — when to enable
- Volume threshold: >50K min/month (above 5-store organic).
- Routing signal: intent classifier on first 2 seconds of audio + caller-history features.
- Fallback: if mini emits a function-call confidence below threshold, hot-swap mid-session to 1.5 (Realtime API supports session model swap via `session.update` in current API).

---

## 8. Migration Decision Tree

```
POC (Week 0–2): gpt-realtime-mini
  → Why: cheapest to fail-fast on plumbing (WebRTC/SIP, Twilio TCR, audio
    pass-through, idempotent guards). Tool-call quality differences won't
    yet be the bottleneck while you fix transport bugs.

Regression Test (Week 2–4): gpt-realtime-1.5
  → Why: replay the existing Retell+Gemini call corpus. 1.5 is the
    production target; you want regression diffs against the actual model
    you'll ship, not against mini.

Canary (Week 4–6): gpt-realtime-1.5 (5–10% of live traffic)
  → Why: identical to production model so canary signal is not muddied.
  → Pin to dated snapshot only if a behavior surprise emerges that requires
    rollback isolation (otherwise use floating alias `gpt-realtime-1.5`).

Full Production (Week 6+): gpt-realtime-1.5 (floating alias)
  → Why: floating alias auto-receives improvements (e.g., a future
    `gpt-realtime-1.6` or `2.0`). Acceptable risk given OpenAI's stable
    deprecation cadence (6-month notice).
  → Maintain a smoke-test suite that runs daily against the alias to
    detect drift.

Rate-limit / 429 Fallback: gpt-realtime-mini
  → Why: 3× cheaper, identical Realtime session protocol, drop-in compatible.
    Quality degradation is visible but call still completes.
  → Implement as Realtime client-side retry with model swap; do not silently
    serve mini without logging.

Dev/Test Cost Optimization: gpt-realtime-mini
  → Why: ~70% cheaper for non-customer-facing test runs. Production tests
    still must hit 1.5.
```

---

## 9. Implementation Hooks for the JM Stack

- **Tool-schema caching:** All 8 voice tools (`create_order`, `modify_order`, `cancel_order`, `make_reservation`, `modify_reservation`, `cancel_reservation`, `allergen_lookup`, `recall_order`) should be defined once at session start with stable IDs. With cached input at $0.40/M, the cost of re-injecting tools per call is negligible.
- **Idempotent guards:** No change required for OpenAI Realtime — function calls preserve `call_id` semantics. Continue current idempotency layer (RLS-tenanted `tenant_id` + dedup key on tool args hash).
- **RLS isolation:** Pass `tenant_id` as a session-scoped variable; do not expose to model. Server-side enforce on every tool call (existing pattern).
- **Semantic VAD with `eagerness=low`:** Reduces premature interruptions during reservation read-backs (longer agent turns).
- **Twilio TCR + SIP:** OpenAI added dedicated SIP IP ranges in 2026 (`sip.api.openai.com` with GeoIP routing); use direct SIP rather than WebRTC bridging where feasible to minimize PSTN latency.
- **Voice choice:** `marin` for English-default stores (warmer); `cedar` for higher-energy/younger demos. Test Korean naturalness on both — community reports vary.
- **Allergen tool (Tier 3 EpiPen handoff):** Confirm 1.5's improved instruction-following preserves the Tier 3 handoff hard-stop. Add to canary acceptance gate.

---

## 10. Risks & Watchlist

1. **HIPAA gap:** OpenAI Realtime audio in/out is not yet on the standard BAA scope per Azure's Q1 2026 clarification. JM's restaurant scope likely doesn't trigger PHI handling, but if any health-adjacent vertical (pharmacy, clinic-attached) enters, re-evaluate.
2. **Transcript leakage bug** in `gpt-realtime-2025-08-28` snapshot — avoid pinning to that exact snapshot. Use floating `gpt-realtime` or move directly to `gpt-realtime-1.5`.
3. **Server VAD ↔ tool use conflict** in some snapshots — default to semantic VAD for the JM tool surface.
4. **Concurrent session ceiling** ambiguity — load-test to confirm before committing 5-store rollout SLA.
5. **Floating alias drift** — a future model bump (e.g., 1.6) may regress on JM's tool patterns. Daily smoke-test mitigates; quarterly snapshot-pinning review.
6. **Mini quality on Korean/Japanese** — explicitly do not route Asian-SMB calls to mini, even under load; prefer 429 retry on flagship.

---

## 11. Sources

1. [OpenAI — Introducing gpt-realtime](https://openai.com/index/introducing-gpt-realtime/) — GA announcement, 2025-08-28; pricing, ComplexFuncBench 66.5%, voices Marin/Cedar.
2. [OpenAI Platform — gpt-realtime model card](https://platform.openai.com/docs/models/gpt-realtime) — snapshots, modalities.
3. [OpenAI Platform — gpt-realtime-mini model card](https://platform.openai.com/docs/models/gpt-realtime-mini) — context, modalities, cost tier.
4. [OpenAI Developers — gpt-realtime-1.5 model card](https://developers.openai.com/api/docs/models/gpt-realtime-1.5) — 1.5 specs.
5. [Perplexity — OpenAI releases gpt-realtime-1.5 for voice AI developers](https://www.perplexity.ai/page/openai-releases-gpt-realtime-1-uvxkVAujTJKQFr1N8we4Tg) — 2026-02-23 release confirmation; +7% instruction-following, +10.23% alphanumeric, +5% Big Bench Audio.
6. [OpenAI API Pricing](https://openai.com/api/pricing/) — authoritative pricing.
7. [Azure OpenAI Foundry — model availability](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio) — confirms versions 2025-08-28, 2025-10-06, 2025-12-15, 2026-02-23.
8. [OpenAI Developers — Deprecations](https://developers.openai.com/api/docs/deprecations) — gpt-4o-realtime-preview deprecation.
9. [OpenAI Realtime VAD guide](https://platform.openai.com/docs/guides/realtime-vad) — semantic VAD eagerness param.
10. [OpenAI Developer Community — gpt-realtime-2025-08-28 transcript leakage bug](https://community.openai.com/t/bug-realtime-api-transcript-returns-other-users-data-and-internal-tokens-gpt-realtime-2025-08-28/1369978) — known issue.
11. [OpenAI Developer Community — Realtime languages](https://community.openai.com/t/languages-in-realtime-api/980149) — 57+ language list, accuracy notes.
12. [OpenAI Developer Community — multilingual challenges](https://community.openai.com/t/challenges-in-multilingual-understanding-with-realtime-apis/991453) — French weakness, language-drift behavior.
13. [Sprinklr — Benchmarking gpt-realtime](https://www.sprinklr.com/blog/voice-bot-gpt-realtime/) — independent voice-agent benchmark.
14. [InfoQ — gpt-realtime production-ready](https://www.infoq.com/news/2025/09/openai-gpt-realtime/) — feature analysis.
15. [Microsoft Q&A — HIPAA eligibility of Realtime audio](https://learn.microsoft.com/en-us/answers/questions/5616040/clarification-request-hipaa-eligibility-of-azure-o) — HIPAA gap as of 2026.
16. [Microsoft Q&A — Realtime 30-min session](https://learn.microsoft.com/en-us/answers/questions/5741275/gpt-realtime-maximum-session-length-30-minutes) — Azure-EU session ceiling.
17. [GitHub — openai/openai-realtime-agents issue #119](https://github.com/openai/openai-realtime-agents/issues/119) — session-length management patterns.
18. [Forasoft — Realtime API WebRTC/SIP/WebSocket integration](https://www.forasoft.com/blog/article/openai-realtime-api-webrtc-sip-websockets-integration) — transport matrix.
19. [eesel — gpt-realtime-mini pricing](https://www.eesel.ai/blog/gpt-realtime-mini-pricing) — independent per-minute analysis.
20. [Hacker News — GPT-Realtime-1.5 Released](https://news.ycombinator.com/item?id=47129942) — community signal on 1.5 reliability.
