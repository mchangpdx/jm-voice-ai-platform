# Realtime Voice Stack Migration Analysis — JM Cafe Pilot
**Date**: 2026-05-05  |  **Author**: SMB Voice Agent Researcher  |  **Status**: Strategic Decision Memo
**Classification**: BD / Engineering — Pre-Launch Architecture Review
**Subject Pilot**: JM Cafe (Portland, OR) — single-store, pre-commercial
**Current Stack**: Retell AI (voice infra) + Gemini 3.1 Flash Lite (LLM) + FastAPI Bridge + Loyverse POS + Twilio SMS pay link
**Decision Surface**: Stay on Retell+Gemini  vs. migrate to OpenAI Realtime  vs. migrate to Gemini Live  vs. migrate to LiveKit-Agents-orchestrated stack

---

## 0. Executive Summary

The pilot is at an unusual inflection: the **bridge, tools, and skills are ready** (393/393 unit tests, 7 voice tools, allergen Tier-3 handoff, recall_order, reservation lifecycle) — and the bottleneck has shifted from *application logic* to *speech I/O quality and tool-call reliability*. The Retell + Gemini 3.1 Flash Lite seam shows two structural problems that will not improve incrementally: (1) the cascaded **STT → LLM → TTS** architecture caps end-to-end latency at ~800–1300 ms TTFT regardless of LLM speed, and (2) function-call correctness on a non-realtime LLM driven through Retell's webhook layer is materially weaker than what speech-to-speech native models now deliver.

OpenAI's `gpt-realtime` (GA, Aug-Sep 2025) was specifically positioned as a **production voice-agent model**, scoring **66.5%** on ComplexFuncBench Audio (vs ~50% for the prior generation), with a 20% price cut, async function calling that no longer breaks turn-taking, native SIP, image input, and MCP tool support. Google's Gemini 2.5 Flash Live offers comparable feature breadth (30 HD voices, 24 languages, native barge-in, Affective Dialog) but the public signal in May 2026 still flags **production instability** — voice drift across weekly preview rotations, audio degradation past the ~1-minute mark, and missing first-class controls (speech rate, conversation toggles).

The recommendation embedded in the 2026-05-04 session resume — **OpenAI Realtime direct, LiveKit as a post-launch track** — survives this re-investigation. The asymmetry of risk favors migrating *before* commercial launch (TCR + Quantic + Maverick are all gated externally; we have free engineering cycles and only one pilot store to roll back if needed) rather than after, when fleet expansion makes regression cost compound.

**Headline call**: Migrate to OpenAI Realtime now (pre-TCR-approval window). Keep Retell as a fallback abstraction at the bridge boundary for ~30 days post-cutover. Defer Gemini Live until at least Q3 2026.

(한글 요약) 파일럿 상용화 직전인 지금 OpenAI Realtime으로 옮기는 것이 옳다. 현재 Retell+Gemini 3.1 Flash Lite는 STT→LLM→TTS 캐스케이드 구조상 TTFT가 800–1300ms 이하로 내려가지 않고, 함수 호출 정확도도 native speech-to-speech 모델 대비 구조적 열위. Gemini Live는 기능은 비슷하지만 2026년 5월 시점에서 production 불안정성(음성 드리프트, 1분 이후 품질 저하, 핵심 컨트롤 부재)이 보고되고 있어 Q3 2026까지 대기 권장.

---

## 1. Migration Timing Justification

### 1.1 The Pre-Commercial Window Is the Cheapest Migration Window You Will Ever Have

Three external dependencies are still pending: **Twilio TCR (10DLC) approval, Quantic POS white-label contract, Maverick payment integration spec**. All three block the actual go-live. None of them block code work. This produces a "free" engineering window with a measurable end date — exactly the situation where a foundational architecture swap is cheapest.

The asymmetry of "migrate now" vs "migrate later":

| Dimension | Migrate now (pre-launch) | Migrate after launch |
|---|---|---|
| Active stores affected during cutover | 1 (JM Cafe) | 1 → N (Phase 1: 5 PDX stores) |
| Live-call regressions visible to customers | 0 (only internal test calls) | Full call-volume blast radius |
| Pressure to roll back after a single bad call | Low (no SLA, no contract) | Very high (paying SMB owner) |
| Sales narrative cost | None | "We're rebuilding our voice stack" mid-deal |
| Engineering capacity competing with go-to-market | Low (TCR/Quantic/Maverick are blocking) | High (deployments, support tickets, training) |
| Test surface | 393 unit tests, controlled | 393 + production logs, partial coverage |

### 1.2 What's Actually Wrong With Retell + Gemini 3.1 Flash Lite for Production

**(a) TTFT floor is structural, not tunable.** The current 800–1300 ms TTFT is the sum of: VAD endpointing (~150–250 ms) + Retell STT (~200–300 ms) + Gemini 3.1 Flash Lite first-token (~250–400 ms) + Retell TTS first-byte (~200–300 ms). No single component is "broken" — but the cascade itself ceilings at ~800 ms even on a perfect day. OpenAI Realtime documents typical end-of-user-speech to start-of-AI-audio of **300–500 ms**, with TTFB of ~500 ms from US clients. That is the *floor*, not the *ceiling*, of what an SMB caller perceives as "human."

**(b) Function call accuracy on cascaded stacks is not where it needs to be.** OpenAI's published benchmark — ComplexFuncBench Audio jumping from 49.7% (Dec 2024 model) to 66.5% (gpt-realtime) — is the most honest data point in this market. Our pilot has 7 tools, several with strict schemas (`make_reservation` with party_size + datetime + name disambiguation, `modify_order` with variant_id resolution, `recall_order`). Errors at the JSON-arg level surface as silent failures (wrong reservation time, wrong drink modifier) — exactly the failure mode that destroys SMB owner trust on day 1.

**(c) Interruption / barge-in on cascaded stacks is acceptable, not great.** Retell's published latency (~780 ms response) is competitive in the cascaded-stack class but barge-in still requires the orchestrator to cancel a TTS stream that's already in flight. Native speech-to-speech models cancel in-model and resume context inside the same session, which is qualitatively different in messy environments (cafe background, kitchen noise — i.e. the literal target environment).

**(d) Multilingual code-switching.** PDX SMB demographics make Spanish-EN code-switching common, and JM Tech One's wedge thesis includes Korean. Cascaded stacks code-switch by routing — every switch round-trips through STT detection and TTS voice swap. gpt-realtime explicitly trained for "switching seamlessly between languages mid-sentence." For F&B verticals this is not a feature, it is a daily occurrence.

**(e) Cost trajectory.** Retell's true loaded cost (voice engine + LLM + telephony) is **$0.13–$0.31/min**. gpt-realtime audio is $32 / 1M input + $64 / 1M output tokens — roughly $0.06–$0.10/min for typical SMB call mixes after cached input savings, *before* telephony. Even granting a 30% wide error bar, the cost-per-minute compresses, not expands.

### 1.3 What's the Actual Risk of Migrating Now?

Honest list of failure modes:
1. **OpenAI Realtime SIP unreliability over Twilio.** OpenAI dev forum has open threads on SIP edge cases (calls ending unexpectedly mid-utterance). The community mitigation is the WebSocket-bridge pattern (Twilio Media Streams → custom WebSocket → OpenAI Realtime), which we already have the FastAPI bridge for. Net: the failure mode is known and the workaround is in our codebase shape.
2. **Voice quality regression on a specific phrase or accent.** Mitigation: keep Retell warm in shadow mode for 30 days post-cutover; the abstraction boundary at our FastAPI bridge already supports this.
3. **Token-cost surprise on long sessions.** OpenAI session cap is 60 min and now ships fine-grained context truncation. Mitigation: enforce conversation truncation at bridge layer.
4. **2-person team velocity loss.** Realistic — but the absence of competing deployment work during the TCR/Quantic/Maverick wait is the literal reason this is the cheapest window.

The risk of *not* migrating: shipping production with a TTFT and function-call ceiling we know we'll have to break later, after we have multiple paying SMB owners and zero rollback budget.

### 1.4 ROI in 2-Person + 1-Pilot Context

For a 2-person team, the dimension that matters most is **decision irreversibility**. Once JM Cafe is live and a second store is in pipeline, ripping out the speech I/O layer becomes a multi-week project with customer comms. Doing it now is a 1–2 week project with no comms. The migration itself is a forcing function for the abstraction we want anyway (a `VoiceTransport` interface above Retell/OpenAI/Gemini), which improves long-term flexibility regardless of which provider wins.

---

## 2. Four-Way Comparison Matrix (10-point scoring)

Each dimension scored 1–10 (10 = best in class for SMB voice agent, May 2026). Final row sums to a maximum of 90.

| # | Dimension | Retell + Gemini 3.1 Flash Lite (current) | LiveKit Agents + OpenAI Realtime | OpenAI Realtime (direct) | Gemini 2.5 Flash Live |
|---|---|---|---|---|---|
| 1 | Speech naturalness, barge-in, multilingual EN/KR | 6 (TTS competent, EN-only natural; KR mediocre; barge-in cascaded) | 9 (gpt-realtime speech + LiveKit's adaptive interruption 1.5.x) | 9 (gpt-realtime Cedar/Marin voices; mid-sentence language switching; native cancel) | 7 (30 HD voices / 24 langs / barge-in good — but 1-min audio degradation, voice drift across previews reported) |
| 2 | Latency (TTFT, end-to-end, S2S vs cascade) | 4 (800–1300 ms cascade; structural floor) | 8 (~200–350 ms via S2S; LiveKit adds <50 ms orchestration) | 9 (300–500 ms end-of-speech to AI-audio; 500 ms TTFB US) | 7 (S2S architecture, but preview instability) |
| 3 | DX (SDK maturity, docs, debugging, function-call stability) | 6 (Retell DX strong; Gemini function-calling on cascaded path is brittle) | 8 (LiveKit Agents 1.5.x, MCP native, Python+Node, mature plugin ecosystem) | 8 (Realtime SDK GA; Agents SDK; broad community; ComplexFuncBench 66.5%) | 5 (Live API requires manual tool-response handling, no auto tool loop, declarations only at session start, "silent" tool execution unreliable) |
| 4 | Cost per minute (loaded) | 5 ($0.13–$0.31/min loaded incl. telephony) | 7 (~$0.08–$0.12/min audio + LiveKit Cloud or self-host) | 8 ($32/$64 per 1M audio tokens; 20% price cut; cached input $0.40/1M) | 8 ($0.30/$2.50 per 1M Flash; competitive but audio-token specifics opaque) |
| 5 | POS / SMB integration fit (function-call reliability + interrupt-safe context) | 5 (works; modify_order variant_id resolution still fragile) | 9 (LiveKit's tool-call orchestration + async tool exec patterns) | 9 (async function calling no longer breaks session; MCP tool support; 66.5% ComplexFuncBench) | 6 (manual tool-response loop adds bridge complexity; declarations frozen at session start limits dynamic skills) |
| 6 | Operational stability (uptime, rate limit, regional) | 7 (Retell mature; Gemini Lite reliable) | 8 (LiveKit infra + OpenAI both production-grade) | 8 (GA, but SIP edge cases noted in dev forum; WebSocket bridge mitigates) | 5 (still in preview/GA-edge for native audio; community reports voice drift week-over-week) |
| 7 | Data / privacy (ZDR, HIPAA, US SMB) | 6 (Retell BAA available; Gemini Vertex enterprise tier yes; mixed surface) | 8 (LiveKit self-host option + OpenAI ZDR/BAA) | 8 (ZDR + BAA available on approval; need RBAC + audit logging) | 7 (Vertex AI BAA path; audio-specific compliance docs less mature) |
| 8 | Lock-in risk | 6 (two-vendor; LLM swappable; voice infra not) | 9 (LiveKit is the abstraction — provider-swappable by design) | 5 (single vendor; deep coupling to Realtime session model) | 5 (single vendor; Vertex coupling) |
| 9 | Multilingual fit for PDX SMB (EN + ES + KR) | 5 (EN strong; ES okay; KR weak on TTS naturalness) | 8 (inherits gpt-realtime multilingual + LiveKit voice-provider swap) | 8 (mid-sentence code-switching trained; 98 langs in training; KR pronunciation reasonable) | 7 (24 HD voice langs incl. KR; ES strong; voice quality drift caveat) |
| **Total** | **/90** | **50** | **74** | **72** | **57** |

### Interpretation
- **LiveKit + OpenAI** scores highest on paper (74), driven by lock-in protection and DX. But it adds a framework dependency that the 2-person team must absorb during pre-launch — the same window that makes "now" cheap for the speech swap is the window where adding a new framework competes for attention. The 2026-05-04 decision to **defer LiveKit to post-launch track** stands.
- **OpenAI Realtime direct** (72) is 2 points behind LiveKit only on lock-in. Everything else is parity or stronger because there's no extra abstraction overhead during the migration.
- **Current Retell + Gemini 3.1 Flash Lite** (50) is below either OpenAI path by ~22 points — the gap is real, dominated by latency (4 vs 9), tool-call fit (5 vs 9), and speech naturalness (6 vs 9).
- **Gemini Live** (57) is currently a Q3-2026-revisit candidate, not a May-2026 migration target. Production instability + function-call ergonomics are the disqualifiers.

---

## 3. OpenAI Realtime vs Gemini Live — Item-by-Item

### 3.1 Model lineup (May 2026)
| | OpenAI | Gemini |
|---|---|---|
| Flagship | `gpt-realtime` (GA Aug-Sep 2025; refresh `gpt-realtime-mini-2025-12-15`) | `gemini-2.5-flash-live-api`; `gemini-2.5-flash-preview-native-audio-dialog` |
| Mini variant | `gpt-realtime-mini` (cheaper, slightly lower instruction follow) | (Live tier rolls into 2.5 Flash) |
| Image input | Yes (gpt-realtime) | Yes (multimodal native) |

### 3.2 Pricing (May 2026)
| | OpenAI gpt-realtime | Gemini 2.5 Flash Live |
|---|---|---|
| Audio input | $32 / 1M tokens | Bundled in 2.5 Flash pricing — public docs imprecise on audio-only token rate |
| Audio output | $64 / 1M tokens | Same caveat |
| Cached input | $0.40 / 1M | Discount tier ~20% available |
| Text in/out reference | $0.30 / $2.50 per 1M (Flash baseline) | $0.30 / $2.50 per 1M Flash |
| Note | 20% price cut vs prior gen; explicit audio-token line item | Audio token economics still less transparent in public docs as of 2026-05; production cost modeling requires Vertex pricing portal access |

### 3.3 Latency benchmarks
| | OpenAI gpt-realtime | Gemini 2.5 Flash Live |
|---|---|---|
| End-of-speech → AI audio start | 300–500 ms typical | Comparable S2S range (preview); production stability less proven |
| TTFB (US client) | ~500 ms | Comparable |
| Architecture | Native speech-to-speech, single multimodal model | Native audio output, but preview-tier voice drift reported |

### 3.4 Function calling
| | OpenAI gpt-realtime | Gemini 2.5 Flash Live |
|---|---|---|
| Mechanism | Function-calling events on side channel; async exec without breaking turn | Manual tool-response handling required (no auto loop) |
| Benchmark | ComplexFuncBench Audio: 66.5% (vs 49.7% prior) | No equivalent published voice tool-call benchmark |
| Dynamic tool registration | Tools per session, updateable | All tools must be declared at session start — no mid-session add |
| Async tool execution | Native; long-running tools don't disrupt conversation | Async supported but "silent" execution unreliable; model may narrate tool exec |
| MCP support | Native MCP server tool calling | MCP available via plugins, less first-class in Live |

For our 7-tool surface (create/modify/cancel order, make/modify/cancel reservation, allergen_lookup, recall_order), **OpenAI's session model is a closer fit**. The cancel/recall/modify trio especially benefits from async exec — these wrap Loyverse calls that occasionally take 2–5 s.

### 3.5 Interruption / barge-in / VAD
| | OpenAI | Gemini |
|---|---|---|
| Barge-in | Native cancel on user speech (server-side VAD) | Native, "improved barge-in" advertised |
| Interruption sensitivity controls | Configurable VAD threshold; community reports it's tunable but undocumented edges | Some controls; speech-rate not first-class in Live |

### 3.6 Transport
| | OpenAI | Gemini |
|---|---|---|
| WebRTC | Yes (best perceived latency for browser/mobile) | Yes |
| WebSocket | Yes | Yes (default) |
| SIP | Yes (native SIP connector w/ Twilio Elastic SIP Trunking; some edge cases reported) | Via WebSocket bridge |
| Recommended for Twilio voice call | Twilio Media Streams → WebSocket bridge → OpenAI Realtime | Twilio Media Streams → WebSocket bridge → Gemini Live |

### 3.7 SDK / DX
| | OpenAI | Gemini |
|---|---|---|
| Python SDK | Mature; Realtime + Agents SDK | google-genai; less voice-specific affordance |
| Node SDK | Mature | Available |
| Browser | WebRTC sample apps in OpenAI cookbook | Examples repo on GitHub |
| Debugging | Side-channel events visible; community + cookbook substantial | Live API troubleshooting docs exist; community signal smaller |

### 3.8 Voice options
| | OpenAI | Gemini |
|---|---|---|
| Voice count | 10 (alloy, ash, ballad, coral, echo, sage, shimmer, verse, **marin**, **cedar**) | 30 HD voices |
| Recommended for production | Marin or Cedar (gpt-realtime tuned) | Voice quality drift reported on previews; testing needed per voice |
| Voice cloning | No | No (HD voice library only) |

### 3.9 Context / session
| | OpenAI | Gemini |
|---|---|---|
| Context window | 32k (gpt-realtime) — 128k on some configs; instructions+tools cap 16,384 tokens | Larger Flash context (1M text equivalent), but Live session token limits less explicit |
| Max session | 60 min (OpenAI direct); 30 min (Azure OpenAI) | Session caps less documented; reconnects common |
| Truncation | Auto at ~28,672 tokens; configurable | Manual context management more often required |

### 3.10 Languages
| | OpenAI | Gemini |
|---|---|---|
| Trained languages | 98 (TTS + STT) | 70 supported; 24 HD voice langs |
| Korean | Supported; mid-sentence switching trained | Supported; HD voice available |
| Spanish (PDX SMB priority) | Strong | Strong |
| Code-switching | Trained | Multilingual session support |

### 3.11 Known constraints / drawbacks
**OpenAI Realtime:**
- SIP path has known edge cases over Twilio; WebSocket bridge is the safer production pattern.
- Voice cannot be changed mid-session once first audio response has been emitted.
- Cedar/Marin voices have a community-reported issue where they occasionally ignore agent system instructions (GitHub issue openai/openai-agents-python#1746).
- Vendor lock-in is real — abstraction boundary must be designed deliberately.

**Gemini Live:**
- Voice drift across weekly preview rotations (Capella voice cited as broken).
- Audio quality degradation on TTS responses past ~1 minute.
- Speech rate not first-class; conversation behavior toggles missing.
- Function calling requires manual response handling; declarations frozen at session start.
- "Silent" tool execution unreliable — model may narrate execution unless guarded.
- Less production-tested in independent SMB voice deployments; preview/GA-edge.

### 3.12 Net call
For our pilot in May 2026, **OpenAI Realtime is the better match**. The deciding factors are: function-call benchmark transparency, async tool exec for Loyverse-bound tools, mature SDK + cookbook + community, and the absence of preview-tier instability reports. Gemini Live becomes a real second-source candidate **once native-audio preview stabilizes** (likely Q3 2026 by current cadence).

---

## 4. Migration Procedure — Step-by-Step

### 4.1 Migration to OpenAI Realtime

#### Phase 0: Prerequisites (0.5 day)
- Provision OpenAI org with Realtime API access; request ZDR + BAA via Trust Center if any vertical (clinic, beauty) requires it.
- Confirm rate limits adequate for pilot (typically default tier covers single-store traffic).
- Network: outbound WSS to api.openai.com:443 from FastAPI bridge.
- Set env keys: `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL=gpt-realtime`.
- **Checklist**: API key live, BAA filed (if applicable), rate-limit dashboard visible.
- **Rollback**: revert env vars; bridge falls back to Retell path.

#### Phase 1: POC — Single-Call Echo (0.5 day)
- Standalone script: Twilio Media Streams → WebSocket bridge → OpenAI Realtime → echo reply.
- Verify: end-of-speech detection, audio out, end-to-end latency on real PSTN.
- **Risk**: codec mismatch (μ-law from Twilio vs PCM16 expected by OpenAI). Resample at bridge.
- **Time**: 4–8 hours.
- **Rollback**: discard branch.

#### Phase 2: Bridge integration — 7 tools (2–3 days)
- Map current 7 tools to Realtime function definitions:
  - `create_order`, `modify_order`, `cancel_order`
  - `make_reservation`, `modify_reservation`, `cancel_reservation`
  - `allergen_lookup` (Tier-3 EpiPen handoff path preserved)
  - `recall_order`
- Wire async tool executor (asyncio task, returns `function_call_output` event when done).
- Preserve our Bridge's existing `tenant_id` / RLS context propagation.
- **Risk**: schema strictness — Realtime is stricter than Gemini on JSON. Add JSON-schema validation at tool boundary.
- **Test**: invoke each tool 10× via voice; record JSON-arg correctness rate.
- **Rollback**: feature flag `VOICE_PROVIDER=retell|openai`; flip back at any time.

#### Phase 3: System prompt port (1 day)
- Port rule 1–13 + INVARIANTS from current Gemini system prompt.
- Re-tune for gpt-realtime instruction-following style (it follows literal style instructions like "speak empathetically" — exploit this).
- Encode allergen Tier-3 mandatory handoff as a hard rule (no probabilistic phrasing).
- Validate Korean greeting prompt naturalness with Marin and Cedar voices.
- **Risk**: instruction-follow regression on edge cases.
- **Test**: 30 scripted scenarios from existing test bank.

#### Phase 4: Pay link integration (0.5 day)
- Current: Retell post-call hook fires Twilio SMS pay link.
- Realtime equivalent: bridge listens for `response.done` + tool-call boundary, then triggers pay link.
- Preserve idempotency keys.
- **Risk**: hook timing — fire after tool completion, not after response.
- **Rollback**: keep Retell hook handler dormant.

#### Phase 5: Regression test (1 day)
- Run full 393/393 unit suite (no change expected — bridge tests are provider-abstracted).
- Add Realtime-specific tests: (1) tool-call schema, (2) async tool exec, (3) interruption mid-tool, (4) language switch mid-session.
- Live-call shadow: call JM Cafe pilot number 20× across morning/lunch/evening, score each call on 5 axes (latency, tool accuracy, speech naturalness, interruption handling, language).
- Target: ≥18/20 calls score "as good or better" than current stack.

#### Phase 6: Canary cutover (1 day live + 30 days monitoring)
- Day 0: 10% traffic to Realtime via feature flag (rollout key on caller hash).
- Day 1: 50%.
- Day 3: 100%.
- Retell warm in shadow mode (calls also routed for comparison logging, not to caller) for 30 days.
- **Rollback trigger**: if 2+ calls/day score below baseline on tool accuracy → flip flag back, RCA before retry.

#### Phase 7: Retell removal (1 day, day-30+)
- Remove Retell SDK from `requirements.txt`.
- Archive Retell webhook handlers under `app/adapters/_archive/`.
- Update `docs/architecture/ARCHITECTURE.md`.
- Keep `VoiceTransport` interface — this is the LiveKit-future-readiness investment.

**Total estimated effort**: 6–8 engineering days + 30 days monitoring.

### 4.2 Migration to Gemini Live (alternative path)
*(Not recommended for May 2026; documented for completeness.)*

#### Phase 0: Prerequisites (0.5 day)
- Vertex AI project with Gemini 2.5 Flash Live API access; or Google AI Studio API key (for non-enterprise).
- BAA via GCP if vertical requires.
- Set env: `GOOGLE_API_KEY` or service-account creds; `GEMINI_LIVE_MODEL=gemini-2.5-flash-live-api`.

#### Phase 1: POC echo (0.5–1 day)
- Same Twilio Media Streams → WebSocket bridge pattern.
- Audio chunk size: 20–40 ms (Gemini Live constraint).
- **Risk**: chunk-size discipline — wrong chunking visibly increases latency.

#### Phase 2: Tool integration (3–5 days)
- All 7 tools declared at session start (Live API limitation — no mid-session add).
- **Manual tool-response handling**: write our own loop that listens for `tool_call`, executes, and posts `tool_response`. No auto-orchestration like OpenAI provides.
- Add explicit "silent execution" guardrails in system prompt to suppress narration of tool exec — and/or use fire-and-forget pattern (don't post FunctionResponse) for async-style tools.
- **Risk**: silent execution leakage where model verbally narrates a tool call (documented Live API behavior).

#### Phase 3: System prompt port (1–2 days)
- Re-tune for Gemini Live native-audio behavior; voice drift means production validation per HD voice.
- Affective Dialog tuning available — use for empathetic allergen Tier-3 handoff.

#### Phase 4: Pay link integration (0.5 day)
- Bridge-driven, same pattern as OpenAI path.

#### Phase 5: Regression test (1.5 days — heavier than OpenAI due to manual tool loop validation)
- Same 393/393 unit suite.
- Additional: voice-quality regression test across HD voices we use (drift risk).
- 1-minute-plus TTS quality check (known degradation point).

#### Phase 6: Canary cutover (1 day + 30 day monitoring)
- Same canary pattern. Higher rollback probability given preview-tier instability.

#### Phase 7: Retell removal (1 day)
- Same as OpenAI path.

**Total estimated effort**: 8–11 engineering days + 30 days monitoring (plus higher monitoring intensity due to preview-tier risk).

### 4.3 Side-by-side migration cost comparison

| Phase | OpenAI Realtime | Gemini 2.5 Flash Live |
|---|---|---|
| Prereqs | 0.5 d | 0.5 d |
| POC echo | 0.5 d | 0.5–1 d |
| Tool integration | 2–3 d | 3–5 d (manual tool loop overhead) |
| Prompt port | 1 d | 1–2 d (per-voice tuning) |
| Pay link | 0.5 d | 0.5 d |
| Regression | 1 d | 1.5 d |
| Canary | 1 d + 30 d watch | 1 d + 30 d watch (higher intensity) |
| Retell removal | 1 d | 1 d |
| **Total dev** | **6–8 days** | **8–11 days** |

---

## 5. Risk Register and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| OpenAI Realtime SIP edge cases over Twilio | Medium | Medium | Use WebSocket-bridge pattern (already in our codebase shape), not native SIP connector |
| Voice quality regression on a corner-case phrase or accent | Medium | Low-Medium | 30-day Retell shadow mode; per-call scoring rubric |
| Tool-call JSON schema strictness vs current looser handling | Low-Medium | Medium | Add JSON-schema validator at tool boundary; expand schema test fixtures |
| Token-cost surprise on long sessions | Low | Low | Enforce conversation truncation in bridge; cap session at 30 min for single-call use case |
| Cedar/Marin voice ignoring system instructions (open issue) | Low | Low | Use `verse` or `coral` as fallback voice; pin voice version once chosen |
| Two-person team velocity hit during pre-launch | Medium | Medium | Migration is sequential with TCR/Quantic/Maverick blockers — net cost of work is near zero |
| Vendor lock-in on OpenAI | Medium | High (it is real) | Maintain `VoiceTransport` interface; LiveKit becomes the post-launch hedge |

---

## 6. Recommendation Summary

1. **Migrate to OpenAI Realtime now**, during the TCR/Quantic/Maverick external-blocker window.
2. **Estimated cost**: 6–8 engineering days + 30-day shadow-mode monitoring.
3. **Keep Retell warm for 30 days post-cutover** as a hard rollback path.
4. **Defer Gemini Live to Q3 2026 re-evaluation** when native-audio preview is expected to stabilize.
5. **Defer LiveKit Agents to post-launch** as the lock-in hedge — but design the `VoiceTransport` interface now so LiveKit insertion is a 1–2 day swap later, not a rebuild.
6. **Voice choice**: start with `marin` for general F&B, validate `cedar` for premium-tone vertical (clinic/beauty), keep `verse` as fallback.
7. **Function calling**: implement async-tool-exec pattern from day 1 — Loyverse calls regularly take 2–5 s and we must not block turn-taking.

(한글 요약) 즉시 OpenAI Realtime 마이그레이션 권장. 6–8 엔지니어링 일 + 30일 shadow 모니터링. Retell은 30일 fallback로 유지. Gemini Live는 Q3 2026 재평가. LiveKit은 launch 이후 lock-in hedge로 추가. 음성은 marin 시작, 비상시 verse fallback. 7개 툴 모두 async tool exec 패턴 적용.

---

## Sources

1. [Introducing gpt-realtime — OpenAI](https://openai.com/index/introducing-gpt-realtime/) — 2025-08/09; ComplexFuncBench 66.5%, Cedar/Marin voices, 20% price cut, async function calling, MCP support, image input.
2. [OpenAI API Pricing](https://openai.com/api/pricing/) — May 2026; gpt-realtime audio $32/$64 per 1M tokens, $0.40/1M cached input.
3. [Realtime API with WebRTC — OpenAI](https://platform.openai.com/docs/guides/realtime-webrtc) — WebRTC vs WebSocket guidance.
4. [Realtime API with SIP — OpenAI](https://developers.openai.com/api/docs/guides/realtime-sip) — Native SIP support.
5. [Realtime API unreliable over SIP — community thread](https://community.openai.com/t/realtime-api-unreliable-over-sip/1366350) — SIP edge cases.
6. [Connect OpenAI Realtime SIP Connector with Twilio Elastic SIP Trunking — Twilio](https://www.twilio.com/en-us/blog/developers/tutorials/product/openai-realtime-api-elastic-sip-trunking) — Production SIP integration guide.
7. [Updates for developers building with voice — OpenAI Developers](https://developers.openai.com/blog/updates-audio-models) — gpt-realtime-mini-2025-12-15: 22% instruction-follow, 13% function-calling improvement.
8. [GPT Realtime maximum session length — Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5741275/gpt-realtime-maximum-session-length-30-minutes) — 60-min OpenAI / 30-min Azure cap.
9. [Context Summarization with Realtime API — OpenAI Cookbook](https://developers.openai.com/cookbook/examples/context_summarization_with_realtime_api) — Token truncation patterns.
10. [Cedar and Marin ignore agent instructions — openai-agents-python#1746](https://github.com/openai/openai-agents-python/issues/1746) — Known voice instruction-follow issue.
11. [OpenAI Enterprise Privacy](https://openai.com/enterprise-privacy/) — ZDR, BAA path.
12. [Tool use with Live API — Google AI for Developers](https://ai.google.dev/gemini-api/docs/live-api/tools) — Manual tool-response handling, declarations at session start.
13. [Gemini Live API overview — Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api) — 30 HD voices, 24 langs, Affective Dialog.
14. [Gemini 2.5 Native Audio upgrade — Google blog](https://blog.google/products-and-platforms/products/gemini/gemini-audio-model-updates/) — Native audio model line.
15. [Gemini Live's voices don't sound like they should — 9to5Google, 2026-03-30](https://9to5google.com/2026/03/30/gemini-lives-voices-dont-sound-like-they-should/) — Voice drift across previews.
16. [Gemini 3.1 Flash Live audio quality degradation — Google AI Developer Forum](https://discuss.ai.google.dev/t/gemini-31-flash-live-voice-slowly-changing-massive-audio-quality-volume-dropping-on-tts-requests-longer-than-1-minute/142499) — 1-minute TTS degradation.
17. [Gemini Developer API Pricing](https://ai.google.dev/gemini-api/docs/pricing) — 2.5 Flash baseline pricing.
18. [Gemini API Pricing 2026 — MetaCTO](https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration) — Cost guide.
19. [LiveKit Agents framework — GitHub](https://github.com/livekit/agents) — 1.5.x adaptive interruption, MCP native.
20. [OpenAI and LiveKit partnership — LiveKit blog](https://blog.livekit.io/openai-livekit-partnership-advanced-voice-realtime-api/) — Multimodal Agent API wrapping Realtime.
21. [Build and Deploy LiveKit AI Voice Agents — Forasoft 2026](https://www.forasoft.com/blog/article/livekit-ai-agents-guide) — 200–350 ms S2S latency.
22. [Retell AI vs Synthflow vs Twilio — Retell AI](https://www.retellai.com/resources/sub-second-latency-voice-assistants-benchmarks) — 780 ms response time.
23. [Retell AI Pricing 2026 — Dialora](https://www.dialora.ai/blog/retell-ai-pricing) — $0.13–$0.31/min loaded cost.
24. [Real-Time Voice AI: The State of Conversational AI in 2026 — Learnia](https://learn-prompting.fr/blog/real-time-voice-ai-2026) — Industry baseline.
25. [Integrating OpenAI Realtime API with WebRTC, SIP, WebSockets — Forasoft 2026](https://www.forasoft.com/blog/article/openai-realtime-api-webrtc-sip-websockets-integration) — Production build patterns.
26. [Function calling with the Gemini API](https://ai.google.dev/gemini-api/docs/function-calling) — Function-calling baseline.
27. [Long function calls and Realtime API — community thread](https://community.openai.com/t/long-function-calls-and-realtime-api/1119021) — Async tool exec patterns.
28. [Is OpenAI HIPAA Compliant — Arkenea](https://arkenea.com/blog/is-openai-hipaa-compliant-2025-guide/) — BAA + ZDR scope.

---

*End of report.*
