# 실시간 음성 스택 마이그레이션 분석 — JM Cafe 파일럿
**작성일**: 2026-05-05  |  **작성자**: SMB Voice Agent Researcher  |  **상태**: 전략 의사결정 메모
**분류**: BD / Engineering — 상용화 직전 아키텍처 리뷰
**대상 파일럿**: JM Cafe (Portland, OR) — 단일 매장, 상용화 직전
**현재 스택**: Retell AI (음성 인프라) + Gemini 3.1 Flash Lite (LLM) + FastAPI Bridge + Loyverse POS + Twilio SMS pay link
**의사결정 대상**: 현재 Retell+Gemini 유지 vs OpenAI Realtime 직접 이관 vs Gemini Live 이관 vs LiveKit-Agents 오케스트레이션 스택 도입

---

## 0. 요약 (Executive Summary)

이 파일럿은 흔치 않은 변곡점에 있다: **bridge / 7개 tool / skill은 이미 준비 완료**(393/393 unit tests, allergen Tier-3 handoff, recall_order, reservation lifecycle 모두 라이브 검증). 병목은 *애플리케이션 로직*에서 *음성 I/O 품질과 tool-call 신뢰도*로 옮겨갔다. 현재의 Retell + Gemini 3.1 Flash Lite seam에는 점진 개선으로 사라지지 않는 두 가지 구조적 문제가 있다 — (1) **STT → LLM → TTS** 캐스케이드 구조상 LLM 속도와 무관하게 end-to-end TTFT가 ~800–1300 ms에 박혀 있고, (2) Retell webhook 레이어를 거쳐 비실시간 LLM이 호출하는 함수 호출 정확도는 speech-to-speech 네이티브 모델 대비 구조적 열위에 있다.

OpenAI의 `gpt-realtime`(2025년 8–9월 GA)은 명시적으로 **production voice-agent 모델**로 포지셔닝되었으며, ComplexFuncBench Audio에서 **66.5%**(이전 세대 약 50%)를 기록했고, 가격 20% 인하, turn-taking을 깨지 않는 async function calling, native SIP, image input, MCP tool 지원이 추가됐다. Google의 Gemini 2.5 Flash Live는 기능 폭은 비등하지만(30 HD voices, 24개 언어, native barge-in, Affective Dialog), 2026년 5월 시점 공개 시그널은 여전히 **production 불안정성**을 가리킨다 — 주간 preview rotation 사이의 음성 드리프트, ~1분 이후 audio 품질 저하, first-class control(speech rate, conversation toggle) 부재 등.

2026-05-04 세션 resume의 결정 — **OpenAI Realtime 직진, LiveKit은 post-launch 트랙** — 은 이번 재조사로 그대로 유지된다. 리스크 비대칭성이 *상용 launch 전*에 옮기는 쪽을 강하게 선호한다 (TCR + Quantic + Maverick은 모두 외부 블로커이며, 단일 파일럿 매장에서 롤백할 시간이 있다). launch 후로 미루면 fleet 확장과 함께 회귀 비용이 복리로 증가한다.

**Headline 결론**: 지금(TCR 승인 대기 윈도우) OpenAI Realtime으로 이관. cutover 후 ~30일 동안 Retell을 bridge boundary 뒤에 fallback abstraction으로 유지. Gemini Live는 최소 Q3 2026까지 보류.

(English summary) Migrate to OpenAI Realtime now in the pre-commercial window. Retell + Gemini 3.1 Flash Lite has structural floors on TTFT (cascaded STT-LLM-TTS) and tool-call accuracy that won't improve incrementally. Gemini Live shows production instability in May 2026; revisit Q3 2026. Keep Retell warm in shadow mode for 30 days as rollback. LiveKit deferred to post-launch as the lock-in hedge.

---

## 1. 마이그레이션 타이밍의 정당성

### 1.1 상용화 직전 윈도우는 가장 저렴한 마이그레이션 윈도우

세 개의 외부 의존성이 모두 대기 상태다: **Twilio TCR(10DLC) 승인, Quantic POS 화이트라벨 계약, Maverick 결제 통합 스펙**. 셋 다 실제 go-live를 막는 블로커지만, 어느 것도 코드 작업을 막지 않는다. 이는 종료 시점이 측정 가능한 "공짜" 엔지니어링 윈도우를 만든다 — 정확히 foundational 아키텍처 swap이 가장 저렴한 상황.

"지금 옮긴다 vs 나중에 옮긴다" 의 비대칭성:

| 차원 | 지금 (launch 전) | launch 후 |
|---|---|---|
| cutover 시 영향받는 활성 매장 수 | 1 (JM Cafe) | 1 → N (Phase 1: PDX 5매장) |
| 고객에게 노출되는 라이브 콜 회귀 | 0 (내부 테스트 콜만) | 전체 콜 볼륨에 노출 |
| 한 번의 나쁜 콜로 인한 롤백 압력 | 낮음 (SLA·계약 없음) | 매우 높음 (유료 SMB 사장) |
| 영업 내러티브 비용 | 없음 | "음성 스택 재구축 중" — 영업 진행 중 부정적 |
| go-to-market과 경쟁하는 엔지니어링 capacity | 낮음 (TCR/Quantic/Maverick이 블로커) | 높음 (배포·지원 티켓·교육) |
| 테스트 표면 | 393 unit tests, 통제됨 | 393 + 프로덕션 로그, 부분 커버 |

### 1.2 현재 Retell + Gemini 3.1 Flash Lite의 실질적 한계

**(a) TTFT 바닥은 구조적, 튜닝으로 안 사라짐.** 현재의 800–1300 ms TTFT는 다음의 합이다: VAD endpointing(~150–250 ms) + Retell STT(~200–300 ms) + Gemini 3.1 Flash Lite first-token(~250–400 ms) + Retell TTS first-byte(~200–300 ms). 단일 컴포넌트가 "고장난" 게 아니라, 캐스케이드 자체가 best-day에도 ~800 ms에서 ceiling을 친다. OpenAI Realtime의 공개 자료는 user 발화 종료 → AI audio 시작까지를 **300–500 ms**, US 클라이언트 TTFB ~500 ms로 문서화한다. SMB 콜러가 "사람 같다"고 느끼는 한계의 *바닥*이지 *천장*이 아니다.

**(b) 캐스케이드 스택의 함수 호출 정확도는 production 기준 미달.** OpenAI 공개 벤치마크 — ComplexFuncBench Audio 49.7%(2024년 12월 모델) → 66.5%(gpt-realtime) — 는 이 시장에서 가장 정직한 데이터 포인트다. 우리 파일럿은 7개 tool, 그 중 다수가 엄격한 schema(`make_reservation`의 party_size + datetime + name disambiguation, `modify_order`의 variant_id resolution, `recall_order`)를 가진다. JSON-arg 단계의 오류는 silent failure로 표면화된다(잘못된 예약 시간, 잘못된 음료 수정자) — 이는 SMB 사장의 day-1 신뢰를 파괴하는 정확한 failure mode다.

**(c) 캐스케이드 스택의 interruption / barge-in은 acceptable, great가 아님.** Retell의 공개 latency(~780 ms response)는 캐스케이드 클래스 안에서는 경쟁력이 있지만, barge-in은 여전히 orchestrator가 in-flight TTS stream을 cancel해야 한다. native speech-to-speech 모델은 모델 안에서 cancel하고 같은 세션 안에서 컨텍스트를 재개한다 — 시끄러운 환경(카페 배경 소리, 주방 소음 — 즉 *정확히* 우리 타깃 환경)에서 이는 질적으로 다르다.

**(d) 다국어 code-switching.** PDX SMB 인구학상 Spanish-EN code-switching이 흔하고, JM Tech One의 wedge thesis에는 한국어가 들어 있다. 캐스케이드 스택은 routing으로 code-switch를 처리한다 — 매번 STT 감지 + TTS voice swap을 round-trip한다. gpt-realtime은 명시적으로 "문장 중간에 매끄럽게 언어 전환"하도록 학습됐다. F&B vertical에서 이는 feature가 아니라 daily occurrence다.

**(e) 비용 추세.** Retell의 실제 loaded cost(voice engine + LLM + telephony)는 **$0.13–$0.31/min**. gpt-realtime audio는 $32 / 1M input + $64 / 1M output tokens — 일반 SMB 콜 mix에서 cached input 절감 후 약 $0.06–$0.10/min, 통신 별도. 30% wide error bar를 인정해도, 분당 비용은 확대가 아니라 압축된다.

### 1.3 지금 옮길 때의 실질 리스크

정직한 failure mode 목록:
1. **Twilio 위 OpenAI Realtime SIP 불안정성.** OpenAI 개발자 포럼에 SIP edge case(발화 중 콜 종료) 오픈 스레드가 있다. 커뮤니티의 mitigation은 WebSocket-bridge 패턴(Twilio Media Streams → custom WebSocket → OpenAI Realtime)이며, 우리는 이미 FastAPI bridge가 있어 그 형태에 부합한다. 결론: failure mode는 알려져 있고 우회는 우리 코드 형태 안에 있다.
2. **특정 어구·억양에서 음성 품질 회귀.** Mitigation: cutover 후 30일 Retell shadow mode 유지 — bridge의 abstraction boundary가 이미 이를 지원한다.
3. **긴 세션의 토큰 비용 surprise.** OpenAI 세션 cap은 60분, 세분화된 컨텍스트 truncation 기능 출시. Mitigation: bridge 레이어에서 conversation truncation 강제.
4. **2인 팀 velocity 손실.** 현실적이지만, TCR/Quantic/Maverick 대기 중에는 경쟁할 배포 작업이 없다는 점이 바로 *이 윈도우가 가장 저렴한 이유*다.

옮기지 *않을* 때의 리스크: TTFT와 함수 호출 ceiling이 알려진 채 production 출시. 후일 유료 SMB 사장이 다수가 되고 롤백 예산이 0이 되었을 때 옮겨야 한다.

### 1.4 2인 팀 + 단일 파일럿 컨텍스트의 ROI

2인 팀에서 가장 중요한 차원은 **결정의 비가역성**. JM Cafe가 라이브 되고 두 번째 매장이 파이프라인에 들어오면 음성 I/O 레이어를 뜯어내는 것은 고객 커뮤니케이션을 동반한 다주(多週) 프로젝트가 된다. 지금 하면 1–2주 프로젝트, 커뮤니케이션 0. 마이그레이션 자체가 우리가 어차피 원하는 abstraction(Retell/OpenAI/Gemini 위의 `VoiceTransport` 인터페이스)을 강제하는 forcing function이 되어, 어떤 provider가 이기든 장기 유연성이 향상된다.

---

## 2. 4-way 비교 매트릭스 (10점 만점 채점)

각 차원 1–10점(10 = 2026년 5월 SMB voice agent 기준 best-in-class). 최종 합계 max 90점.

| # | 차원 | Retell + Gemini 3.1 Flash Lite (현재) | LiveKit Agents + OpenAI Realtime | OpenAI Realtime (직접) | Gemini 2.5 Flash Live |
|---|---|---|---|---|---|
| 1 | 음성 자연스러움, barge-in, EN/KR 다국어 | 6 (TTS 양호, EN 자연·KR 평이; 캐스케이드 barge-in) | 9 (gpt-realtime 음성 + LiveKit 1.5.x adaptive interruption) | 9 (Marin/Cedar; 문장 중 언어전환; native cancel) | 7 (30 HD voice / 24 lang / barge-in 양호 — 단 1분 이후 audio 저하, 주간 voice drift 보고) |
| 2 | Latency (TTFT, 종단 간, S2S vs cascade) | 4 (800–1300 ms cascade; 구조적 floor) | 8 (~200–350 ms S2S; LiveKit orchestration <50 ms) | 9 (300–500 ms 발화종료→AI audio; US TTFB 500 ms) | 7 (S2S 구조이나 preview 불안정) |
| 3 | DX (SDK 성숙도, 문서, 디버깅, 함수호출 안정성) | 6 (Retell DX 강함; 캐스케이드 path의 Gemini 함수호출 부서지기 쉬움) | 8 (LiveKit Agents 1.5.x, MCP native, Python+Node, 성숙한 plugin 생태계) | 8 (Realtime SDK GA; Agents SDK; 폭넓은 커뮤니티; ComplexFuncBench 66.5%) | 5 (Live API는 manual tool-response handling, auto tool loop 없음, 선언이 session 시작 시점에만 가능, "silent" tool exec 불안정) |
| 4 | 분당 원가 (loaded) | 5 ($0.13–$0.31/min loaded incl. telephony) | 7 (~$0.08–$0.12/min audio + LiveKit Cloud or self-host) | 8 ($32/$64 per 1M audio tokens; 20% 인하; cached input $0.40/1M) | 8 ($0.30/$2.50 per 1M Flash; 경쟁력 있으나 audio token 세부 불투명) |
| 5 | POS / SMB 통합 적합성 (함수호출 신뢰도 + interrupt-safe context) | 5 (작동은 함; modify_order의 variant_id resolution 여전히 취약) | 9 (LiveKit의 tool-call orchestration + async tool exec 패턴) | 9 (async function calling으로 session 안 깨짐; MCP tool 지원; 66.5% ComplexFuncBench) | 6 (manual tool-response loop이 bridge 복잡도 추가; session 시작 시점 declaration freeze로 dynamic skill 제약) |
| 6 | 운영 안정성 (uptime, rate limit, 지역) | 7 (Retell mature; Gemini Lite 안정) | 8 (LiveKit infra + OpenAI 둘 다 production-grade) | 8 (GA, SIP edge case는 dev forum에 있음; WebSocket bridge로 mitigate) | 5 (native audio가 여전히 preview/GA-edge; 주간 voice drift 보고) |
| 7 | 데이터 / 프라이버시 (ZDR, HIPAA, 미국 SMB) | 6 (Retell BAA 가능; Gemini Vertex enterprise tier 가능; 혼합) | 8 (LiveKit self-host 옵션 + OpenAI ZDR/BAA) | 8 (ZDR + BAA 승인 후 가능; RBAC + audit logging 필요) | 7 (Vertex AI BAA path; audio-specific 컴플라이언스 문서 미성숙) |
| 8 | Lock-in 위험 | 6 (two-vendor; LLM swap 가능; voice infra는 아님) | 9 (LiveKit이 abstraction 자체 — provider-swappable by design) | 5 (단일 vendor; Realtime session model에 깊이 결합) | 5 (단일 vendor; Vertex 결합) |
| 9 | PDX SMB 다국어 적합도 (EN + ES + KR) | 5 (EN 강함; ES 무난; KR TTS 자연스러움 약함) | 8 (gpt-realtime 다국어 + LiveKit voice provider swap 상속) | 8 (문장 중 code-switching 학습; 학습 98개 언어; KR 발음 합리적) | 7 (24 HD voice 언어 incl. KR; ES 강함; voice drift 주의) |
| **합계** | **/90** | **50** | **74** | **72** | **57** |

### 해석
- **LiveKit + OpenAI** 가 표면상 최고점(74). lock-in 보호와 DX가 견인. 그러나 framework dependency 추가가 launch 전 윈도우에서 2인 팀의 attention을 두고 경쟁 — 음성 swap이 "지금" 저렴한 바로 그 윈도우에서. 2026-05-04 결정인 **LiveKit은 post-launch로 지연** 이 유효.
- **OpenAI Realtime 직접**(72)은 lock-in 단 한 차원에서만 LiveKit 대비 -2. 그 외 모두 동등 또는 우위 — 마이그레이션 도중 추가 abstraction overhead가 없기 때문.
- **현재 Retell + Gemini 3.1 Flash Lite**(50)는 어느 OpenAI 경로 대비 ~22점 낮음 — gap의 주요 driver는 latency(4 vs 9), tool-call 적합도(5 vs 9), 음성 자연스러움(6 vs 9).
- **Gemini Live**(57)는 현 시점 Q3-2026 재평가 candidate이지 May-2026 마이그레이션 target이 아님. production 불안정성 + 함수 호출 ergonomic이 disqualifier.

---

## 3. OpenAI Realtime vs Gemini Live — 항목별 비교

### 3.1 모델 라인업 (2026년 5월)
| | OpenAI | Gemini |
|---|---|---|
| 플래그십 | `gpt-realtime` (GA 2025-08/09; 갱신 `gpt-realtime-mini-2025-12-15`) | `gemini-2.5-flash-live-api`; `gemini-2.5-flash-preview-native-audio-dialog` |
| Mini | `gpt-realtime-mini` (저렴, 약간 낮은 instruction follow) | (Live tier가 2.5 Flash로 흡수) |
| Image input | 가능 (gpt-realtime) | 가능 (multimodal native) |

### 3.2 가격 (2026년 5월)
| | OpenAI gpt-realtime | Gemini 2.5 Flash Live |
|---|---|---|
| Audio input | $32 / 1M tokens | 2.5 Flash 가격에 번들 — audio-only 토큰 단가는 공개 문서 부정확 |
| Audio output | $64 / 1M tokens | 동일 caveat |
| Cached input | $0.40 / 1M | ~20% 할인 tier |
| Text in/out 참조 | $0.30 / $2.50 per 1M (Flash baseline) | $0.30 / $2.50 per 1M Flash |
| 비고 | 이전 세대 대비 20% 인하; audio token 라인 아이템 명시 | 2026-05 시점 audio token 경제학이 공개 문서상 덜 투명 — 정확한 production cost modeling은 Vertex pricing portal 접근 필요 |

### 3.3 Latency 벤치마크
| | OpenAI gpt-realtime | Gemini 2.5 Flash Live |
|---|---|---|
| 발화 종료 → AI audio 시작 | 300–500 ms 일반 | S2S 구간 비등(preview); production 안정성 입증 미흡 |
| TTFB (US 클라이언트) | ~500 ms | 비등 |
| 아키텍처 | 단일 multimodal 모델 native S2S | native audio output, preview-tier voice drift |

### 3.4 Function calling
| | OpenAI gpt-realtime | Gemini 2.5 Flash Live |
|---|---|---|
| 메커니즘 | side channel function-calling 이벤트; turn 깨지 않는 async exec | manual tool-response handling 필요 (auto loop 없음) |
| 벤치마크 | ComplexFuncBench Audio: 66.5% (이전 49.7%) | 동등한 voice tool-call 공개 벤치마크 없음 |
| Dynamic tool registration | session별 tool, 업데이트 가능 | 모든 tool은 session 시작 시 declare — mid-session add 불가 |
| Async tool execution | Native; long-running tool이 conversation 안 깨뜨림 | async 가능하나 "silent" execution 불안정; 모델이 tool exec 내레이션할 수 있음 |
| MCP 지원 | Native MCP server tool calling | plugin 경유 가능, Live에서는 first-class 정도 약함 |

우리의 7-tool 표면(create/modify/cancel order, make/modify/cancel reservation, allergen_lookup, recall_order)에 대해 **OpenAI의 session model이 더 잘 맞는다**. 특히 cancel/recall/modify 트리오는 async exec의 혜택이 크다 — 이들은 가끔 2–5초 걸리는 Loyverse 호출을 wrap한다.

### 3.5 Interruption / barge-in / VAD
| | OpenAI | Gemini |
|---|---|---|
| Barge-in | 사용자 발화 시 native cancel (server-side VAD) | Native, "improved barge-in" 광고 |
| Interruption sensitivity 컨트롤 | VAD threshold 설정 가능; 커뮤니티는 tunable이지만 문서화 안 된 edge들이 있다고 보고 | 일부 컨트롤; speech-rate가 Live에서 first-class 아님 |

### 3.6 Transport
| | OpenAI | Gemini |
|---|---|---|
| WebRTC | 가능 (브라우저/모바일 음성 UX의 best perceived latency) | 가능 |
| WebSocket | 가능 | 가능 (default) |
| SIP | 가능 (Twilio Elastic SIP Trunking과 native SIP connector; 일부 edge case 보고) | WebSocket bridge 경유 |
| Twilio voice 콜 권장 | Twilio Media Streams → WebSocket bridge → OpenAI Realtime | Twilio Media Streams → WebSocket bridge → Gemini Live |

### 3.7 SDK / DX
| | OpenAI | Gemini |
|---|---|---|
| Python SDK | 성숙; Realtime + Agents SDK | google-genai; voice-specific affordance 약함 |
| Node SDK | 성숙 | 가능 |
| Browser | OpenAI cookbook의 WebRTC 샘플 | GitHub examples 저장소 |
| 디버깅 | Side-channel 이벤트 가시; cookbook + 커뮤니티 풍부 | Live API troubleshooting 문서 존재; 커뮤니티 시그널 작음 |

### 3.8 음성 옵션
| | OpenAI | Gemini |
|---|---|---|
| 음성 수 | 10 (alloy, ash, ballad, coral, echo, sage, shimmer, verse, **marin**, **cedar**) | 30 HD voices |
| Production 권장 | Marin 또는 Cedar (gpt-realtime tuned) | preview voice drift 보고; voice별 검증 필요 |
| Voice cloning | 없음 | 없음 (HD voice 라이브러리만) |

### 3.9 Context / session
| | OpenAI | Gemini |
|---|---|---|
| Context window | 32k (gpt-realtime) — 일부 구성에서 128k; instructions+tools cap 16,384 토큰 | Flash context 대형(텍스트 1M 등가)이나 Live session 토큰 한도는 덜 명시 |
| 최대 session | 60분 (OpenAI 직접); 30분 (Azure OpenAI) | session cap 문서화 약함; 재연결 흔함 |
| Truncation | ~28,672 토큰에서 auto; 설정 가능 | manual context management 자주 필요 |

### 3.10 언어
| | OpenAI | Gemini |
|---|---|---|
| 학습 언어 | 98 (TTS + STT) | 70 지원; HD voice는 24개 언어 |
| 한국어 | 지원; 문장 중 전환 학습 | 지원; HD voice 가능 |
| 스페인어 (PDX SMB 우선순위) | 강함 | 강함 |
| Code-switching | 학습 | 다국어 session 지원 |

### 3.11 알려진 제약 / 단점
**OpenAI Realtime:**
- Twilio 위 SIP path는 알려진 edge case가 있음; WebSocket bridge가 더 안전한 production 패턴.
- 첫 audio 응답 emit 후 session 도중 voice 변경 불가.
- Cedar/Marin이 system instruction을 이따금 무시하는 커뮤니티 보고 (GitHub openai/openai-agents-python#1746).
- Vendor lock-in이 실재 — abstraction boundary를 의도적으로 설계해야 함.

**Gemini Live:**
- 주간 preview rotation 사이의 voice drift (Capella voice 깨짐 사례 인용).
- ~1분 이후 TTS audio 품질 저하.
- speech rate가 first-class 아님; conversation behavior toggle 부재.
- function calling은 manual response handling 필요; declaration이 session 시작 시점에 freeze.
- "silent" tool execution 불안정 — guardrail 없으면 모델이 narrate 가능.
- 독립적인 SMB voice 배포에서 production 검증 사례 적음; preview/GA-edge.

### 3.12 결론
2026년 5월 우리 파일럿에 대해, **OpenAI Realtime이 더 좋은 매치**. 결정 요인: 함수 호출 벤치마크 투명성, Loyverse-bound tool에 대한 async tool exec, 성숙한 SDK + cookbook + 커뮤니티, preview-tier 불안정성 보고 부재. Gemini Live는 native-audio preview가 안정화될 때(현 cadence상 Q3 2026 예상) 진정한 second-source 후보가 됨.

---

## 4. 마이그레이션 절차 — 단계별

### 4.1 OpenAI Realtime 마이그레이션

#### Phase 0: 사전 준비 (0.5일)
- OpenAI org에 Realtime API 액세스 프로비저닝; vertical(clinic, beauty)이 요구하면 Trust Center로 ZDR + BAA 신청.
- rate limit이 파일럿 트래픽에 충분한지 확인 (보통 default tier는 단일 매장 트래픽 커버).
- 네트워크: FastAPI bridge에서 api.openai.com:443으로 outbound WSS 허용.
- 환경 변수: `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL=gpt-realtime`.
- **체크리스트**: API 키 라이브, BAA 제출(필요 시), rate-limit 대시보드 가시.
- **롤백**: 환경 변수 revert; bridge가 Retell path로 fallback.

#### Phase 1: POC — 단일 콜 echo (0.5일)
- 단독 스크립트: Twilio Media Streams → WebSocket bridge → OpenAI Realtime → echo 응답.
- 검증: 발화 종료 감지, audio out, 실제 PSTN end-to-end latency.
- **리스크**: 코덱 불일치 (Twilio μ-law vs OpenAI 기대 PCM16). bridge에서 resample.
- **시간**: 4–8시간.
- **롤백**: 브랜치 폐기.

#### Phase 2: Bridge 통합 — 7개 tool (2–3일)
- 현재 7개 tool을 Realtime function definition으로 매핑:
  - `create_order`, `modify_order`, `cancel_order`
  - `make_reservation`, `modify_reservation`, `cancel_reservation`
  - `allergen_lookup` (Tier-3 EpiPen handoff path 보존)
  - `recall_order`
- async tool executor 와이어링 (asyncio task, 완료 시 `function_call_output` 이벤트 반환).
- bridge의 `tenant_id` / RLS 컨텍스트 propagation 보존.
- **리스크**: schema 엄격성 — Realtime이 Gemini보다 JSON에 엄격. tool boundary에 JSON-schema validation 추가.
- **테스트**: 각 tool을 voice로 10회 호출; JSON-arg 정확도 기록.
- **롤백**: feature flag `VOICE_PROVIDER=retell|openai`; 언제든 flip.

#### Phase 3: 시스템 프롬프트 포팅 (1일)
- 현재 Gemini system prompt의 rule 1–13 + INVARIANTS 포팅.
- gpt-realtime의 instruction-following style에 맞춰 재튜닝 (이 모델은 "speak empathetically" 같은 literal style instruction을 따름 — 활용).
- allergen Tier-3 mandatory handoff를 hard rule로 인코드 (확률적 표현 금지).
- Marin과 Cedar voice로 한국어 인사 prompt 자연스러움 검증.
- **리스크**: edge case에서 instruction-follow 회귀.
- **테스트**: 기존 test bank에서 30개 scripted scenario.

#### Phase 4: Pay link 통합 (0.5일)
- 현재: Retell post-call hook이 Twilio SMS pay link 발사.
- Realtime 등가물: bridge가 `response.done` + tool-call 경계를 감지 후 pay link 트리거.
- idempotency key 보존.
- **리스크**: hook 타이밍 — response 종료 후가 아니라 tool 완료 후에 fire.
- **롤백**: Retell hook handler를 dormant 상태로 유지.

#### Phase 5: 회귀 테스트 (1일)
- 393/393 unit suite 전체 실행 (변경 없음 예상 — bridge test는 provider-abstracted).
- Realtime-specific 테스트 추가: (1) tool-call schema, (2) async tool exec, (3) tool 실행 중 interruption, (4) session 도중 언어 전환.
- 라이브 콜 shadow: 아침/점심/저녁 JM Cafe 파일럿 번호로 20회 콜, 각 콜을 5축으로 채점 (latency, tool 정확도, 음성 자연스러움, interruption 처리, 언어).
- 목표: 20회 중 ≥18회가 현재 스택과 "동등 또는 더 좋음" 점수.

#### Phase 6: Canary 절환 (1일 라이브 + 30일 모니터링)
- Day 0: feature flag로 Realtime에 10% 트래픽 (caller hash로 rollout key).
- Day 1: 50%.
- Day 3: 100%.
- 30일간 Retell warm shadow mode (콜이 비교 로깅용으로도 라우팅, 사용자에는 미전달).
- **롤백 트리거**: tool 정확도가 하루 2콜 이상 baseline 미달 → flag 되돌리고 재시도 전 RCA.

#### Phase 7: Retell 의존성 제거 (1일, day-30 이후)
- `requirements.txt`에서 Retell SDK 제거.
- Retell webhook handler를 `app/adapters/_archive/`로 이관.
- `docs/architecture/ARCHITECTURE.md` 업데이트.
- `VoiceTransport` 인터페이스 유지 — 이것이 LiveKit-future-readiness 투자.

**총 예상 노력**: 엔지니어링 6–8일 + 모니터링 30일.

### 4.2 Gemini Live 마이그레이션 (대안 경로)
*(2026년 5월 기준 권장 안 함; 완전성을 위해 문서화.)*

#### Phase 0: 사전 준비 (0.5일)
- Vertex AI 프로젝트 with Gemini 2.5 Flash Live API 액세스; 또는 Google AI Studio API key (비-엔터프라이즈).
- vertical 요구 시 GCP를 통한 BAA.
- 환경 변수: `GOOGLE_API_KEY` 또는 service-account credentials; `GEMINI_LIVE_MODEL=gemini-2.5-flash-live-api`.

#### Phase 1: POC echo (0.5–1일)
- 동일한 Twilio Media Streams → WebSocket bridge 패턴.
- audio chunk size: 20–40 ms (Gemini Live 제약).
- **리스크**: chunking discipline — 잘못된 chunking은 latency를 가시적으로 증가.

#### Phase 2: Tool 통합 (3–5일)
- 7개 tool 모두 session 시작 시 declare (Live API 제약 — mid-session add 불가).
- **Manual tool-response handling**: `tool_call` 수신 → 실행 → `tool_response` 게시하는 자체 loop 작성. OpenAI가 제공하는 auto-orchestration 없음.
- system prompt에 tool exec narration을 억제하는 명시적 "silent execution" guardrail 추가 — 그리고/또는 async-style tool에는 fire-and-forget 패턴 사용 (FunctionResponse 미게시).
- **리스크**: 모델이 verbal하게 tool 호출을 narrate하는 silent execution leakage (문서화된 Live API 거동).

#### Phase 3: 시스템 프롬프트 포팅 (1–2일)
- Gemini Live native-audio 거동에 맞춰 재튜닝; voice drift는 사용 HD voice별 production 검증을 의미.
- Affective Dialog 튜닝 가능 — empathetic allergen Tier-3 handoff에 활용.

#### Phase 4: Pay link 통합 (0.5일)
- bridge-driven, OpenAI 경로와 동일 패턴.

#### Phase 5: 회귀 테스트 (1.5일 — manual tool loop 검증으로 OpenAI 대비 무거움)
- 동일한 393/393 unit suite.
- 추가: 사용 HD voice 전반 voice-quality 회귀 테스트 (drift 위험).
- 1분 초과 TTS 품질 체크 (알려진 저하 지점).

#### Phase 6: Canary 절환 (1일 + 30일 모니터링)
- 동일 canary 패턴. preview-tier 불안정성 고려 시 롤백 확률 더 높음.

#### Phase 7: Retell 제거 (1일)
- OpenAI 경로와 동일.

**총 예상 노력**: 엔지니어링 8–11일 + 모니터링 30일 (preview-tier 위험으로 모니터링 강도 더 높음).

### 4.3 마이그레이션 비용 side-by-side

| Phase | OpenAI Realtime | Gemini 2.5 Flash Live |
|---|---|---|
| 사전 준비 | 0.5일 | 0.5일 |
| POC echo | 0.5일 | 0.5–1일 |
| Tool 통합 | 2–3일 | 3–5일 (manual tool loop 오버헤드) |
| 프롬프트 포팅 | 1일 | 1–2일 (per-voice 튜닝) |
| Pay link | 0.5일 | 0.5일 |
| 회귀 | 1일 | 1.5일 |
| Canary | 1일 + 30일 watch | 1일 + 30일 watch (강도 더 높음) |
| Retell 제거 | 1일 | 1일 |
| **총 dev** | **6–8일** | **8–11일** |

---

## 5. 리스크 레지스터와 mitigation

| 리스크 | 심각도 | 발생 가능성 | Mitigation |
|---|---|---|---|
| Twilio 위 OpenAI Realtime SIP edge case | Medium | Medium | native SIP connector 대신 WebSocket-bridge 패턴(이미 우리 코드 형태) |
| 코너 케이스 어구·억양에서 음성 품질 회귀 | Medium | Low-Medium | 30일 Retell shadow mode; per-call 채점 rubric |
| 현재의 느슨한 처리 vs Tool-call JSON schema 엄격성 | Low-Medium | Medium | tool boundary에 JSON-schema validator; schema test fixture 확장 |
| 긴 세션 토큰 비용 surprise | Low | Low | bridge에서 conversation truncation 강제; 단일 콜 use case에 30분 cap |
| Cedar/Marin이 system instruction 무시 (open issue) | Low | Low | `verse` 또는 `coral`을 fallback voice로; voice version 핀 |
| launch 전 2인 팀 velocity hit | Medium | Medium | 마이그레이션은 TCR/Quantic/Maverick 블로커와 순차 — net 작업 비용은 0 근처 |
| OpenAI vendor lock-in | Medium | High (실재) | `VoiceTransport` 인터페이스 유지; LiveKit이 post-launch hedge |

---

## 6. 권고 요약

1. TCR/Quantic/Maverick 외부 블로커 윈도우 동안 **지금 OpenAI Realtime으로 마이그레이션**.
2. **예상 비용**: 엔지니어링 6–8일 + shadow-mode 모니터링 30일.
3. 하드 롤백 경로로 **cutover 후 30일 동안 Retell warm 유지**.
4. native-audio preview가 안정화될 것으로 예상되는 **Q3 2026 재평가까지 Gemini Live 보류**.
5. lock-in hedge로 **LiveKit Agents는 post-launch로 미루되**, `VoiceTransport` 인터페이스를 지금 설계해 향후 LiveKit 삽입이 1–2일 swap이 되도록 (rebuild가 아니라).
6. **음성 선택**: 일반 F&B는 `marin`으로 시작, premium-tone vertical(clinic/beauty)은 `cedar` 검증, `verse`를 fallback으로 유지.
7. **Function calling**: day 1부터 async-tool-exec 패턴 적용 — Loyverse 호출이 정기적으로 2–5초 걸리므로 turn-taking을 block하면 안 됨.

(English summary) Migrate to OpenAI Realtime now. 6–8 engineering days + 30-day shadow monitoring. Keep Retell as 30-day fallback. Defer Gemini Live to Q3 2026. Defer LiveKit to post-launch as lock-in hedge but design VoiceTransport interface now. Voice: marin primary, verse fallback, cedar for premium verticals. Apply async tool exec pattern to all 7 tools from day 1.

---

## Sources

1. [Introducing gpt-realtime — OpenAI](https://openai.com/index/introducing-gpt-realtime/) — 2025-08/09; ComplexFuncBench 66.5%, Cedar/Marin voices, 20% 가격 인하, async function calling, MCP support, image input.
2. [OpenAI API Pricing](https://openai.com/api/pricing/) — May 2026; gpt-realtime audio $32/$64 per 1M tokens, $0.40/1M cached input.
3. [Realtime API with WebRTC — OpenAI](https://platform.openai.com/docs/guides/realtime-webrtc) — WebRTC vs WebSocket 가이던스.
4. [Realtime API with SIP — OpenAI](https://developers.openai.com/api/docs/guides/realtime-sip) — Native SIP 지원.
5. [Realtime API unreliable over SIP — community](https://community.openai.com/t/realtime-api-unreliable-over-sip/1366350) — SIP edge case.
6. [Connect OpenAI Realtime SIP Connector with Twilio Elastic SIP Trunking — Twilio](https://www.twilio.com/en-us/blog/developers/tutorials/product/openai-realtime-api-elastic-sip-trunking) — Production SIP 가이드.
7. [Updates for developers building with voice — OpenAI Developers](https://developers.openai.com/blog/updates-audio-models) — gpt-realtime-mini-2025-12-15: instruction-follow 22% / function-calling 13% 향상.
8. [GPT Realtime maximum session length — Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5741275/gpt-realtime-maximum-session-length-30-minutes) — 60분 OpenAI / 30분 Azure cap.
9. [Context Summarization with Realtime API — OpenAI Cookbook](https://developers.openai.com/cookbook/examples/context_summarization_with_realtime_api) — 토큰 truncation 패턴.
10. [Cedar and Marin ignore agent instructions — openai-agents-python#1746](https://github.com/openai/openai-agents-python/issues/1746) — voice instruction-follow 이슈.
11. [OpenAI Enterprise Privacy](https://openai.com/enterprise-privacy/) — ZDR, BAA path.
12. [Tool use with Live API — Google AI for Developers](https://ai.google.dev/gemini-api/docs/live-api/tools) — manual tool-response handling, session 시작 시점 declaration.
13. [Gemini Live API overview — Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api) — 30 HD voice, 24 lang, Affective Dialog.
14. [Gemini 2.5 Native Audio upgrade — Google blog](https://blog.google/products-and-platforms/products/gemini/gemini-audio-model-updates/) — native audio model 라인.
15. [Gemini Live's voices don't sound like they should — 9to5Google, 2026-03-30](https://9to5google.com/2026/03/30/gemini-lives-voices-dont-sound-like-they-should/) — preview voice drift.
16. [Gemini 3.1 Flash Live audio degradation — Google AI Developer Forum](https://discuss.ai.google.dev/t/gemini-31-flash-live-voice-slowly-changing-massive-audio-quality-volume-dropping-on-tts-requests-longer-than-1-minute/142499) — 1분 TTS 저하.
17. [Gemini Developer API Pricing](https://ai.google.dev/gemini-api/docs/pricing) — 2.5 Flash baseline 가격.
18. [Gemini API Pricing 2026 — MetaCTO](https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration) — 비용 가이드.
19. [LiveKit Agents framework — GitHub](https://github.com/livekit/agents) — 1.5.x adaptive interruption, MCP native.
20. [OpenAI and LiveKit partnership — LiveKit blog](https://blog.livekit.io/openai-livekit-partnership-advanced-voice-realtime-api/) — Multimodal Agent API wrapping Realtime.
21. [Build and Deploy LiveKit AI Voice Agents — Forasoft 2026](https://www.forasoft.com/blog/article/livekit-ai-agents-guide) — 200–350 ms S2S latency.
22. [Retell AI vs Synthflow vs Twilio — Retell AI](https://www.retellai.com/resources/sub-second-latency-voice-assistants-benchmarks) — 780 ms response time.
23. [Retell AI Pricing 2026 — Dialora](https://www.dialora.ai/blog/retell-ai-pricing) — $0.13–$0.31/min loaded cost.
24. [Real-Time Voice AI: The State of Conversational AI in 2026 — Learnia](https://learn-prompting.fr/blog/real-time-voice-ai-2026) — 산업 baseline.
25. [Integrating OpenAI Realtime API with WebRTC, SIP, WebSockets — Forasoft 2026](https://www.forasoft.com/blog/article/openai-realtime-api-webrtc-sip-websockets-integration) — production build 패턴.
26. [Function calling with the Gemini API](https://ai.google.dev/gemini-api/docs/function-calling) — function-calling baseline.
27. [Long function calls and Realtime API — community](https://community.openai.com/t/long-function-calls-and-realtime-api/1119021) — async tool exec 패턴.
28. [Is OpenAI HIPAA Compliant — Arkenea](https://arkenea.com/blog/is-openai-hipaa-compliant-2025-guide/) — BAA + ZDR scope.

---

*보고서 끝.*
