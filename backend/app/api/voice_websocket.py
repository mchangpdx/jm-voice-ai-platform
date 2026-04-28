# Retell Custom LLM WebSocket endpoint — bridges Retell ↔ Gemini
# (Retell Custom LLM WebSocket 엔드포인트 — Retell ↔ Gemini 브리지)
#
# Architecture (ported from jm-saas-platform pattern):
#   1. WS connects  → eager _init_session() fires as asyncio task immediately
#   2. _init_session: REST /v2/get-call → agent_id → Supabase store → greeting → response_id=0
#   3. Any response_required arriving during init is buffered, drained after greeting
#   4. call_details event: fallback for web_call / Retell Simulation flows
#   5. ping → ping_response  |  update_only → ignored  |  reminder_required → nudge
#
# Language: English default — natural switch to Spanish / Korean on customer cue.
# Retell docs: https://docs.retellai.com/api-references/llm-websocket

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF, insert_reservation

log = logging.getLogger(__name__)

# ── Call monitor — dedicated FileHandler bypasses uvicorn log filtering ────────
# (uvicorn 로거 필터 우회 — 전용 파일에 직접 기록)

_monitor_log = logging.getLogger("jm.monitor")
_monitor_log.setLevel(logging.DEBUG)
_monitor_log.propagate = False
_mh = logging.FileHandler("/tmp/jm-monitor.log")
_mh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_monitor_log.addHandler(_mh)
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_monitor_log.addHandler(_sh)


def _mon(msg: str, *args) -> None:
    _monitor_log.info("[MONITOR] " + msg, *args)


def _log_turn(
    call_id: str,
    turn: int,
    response_id: int,
    ttft_ms: float,
    total_ms: float,
    chunks: int,
    chars: int,
    error: bool = False,
) -> None:
    status = "ERROR" if error else "OK"
    _mon("call=%s turn=%d resp_id=%d TTFT=%dms total=%dms chunks=%d chars=%d %s",
         call_id, turn, response_id, ttft_ms, total_ms, chunks, chars, status)

router = APIRouter(tags=["Voice WebSocket"])

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# ── Greeting prompt — mirrors GREETING_PROMPT in jm-saas-platform llmServer.js ─
# Sent as a synthetic turn to Gemini immediately after store context is loaded.
# Uses response_id=0 (no response_required from Retell yet).
# (Retell이 response_required를 보내기 전에 response_id=0으로 선제적 인사말 전송)
_GREETING_PROMPT = (
    "The call just connected. The customer hasn't spoken yet. "
    "Greet warmly in 1 short sentence in ENGLISH (default for the first hello) — "
    "say the store name, briefly introduce yourself as the AI assistant, "
    "and invite the customer to ask anything. "
    "Sound like a friendly real human, not a script. "
    "No markdown, no bullets, no emojis."
)


# ── Pure helper functions (unit-testable, no I/O) ─────────────────────────────

def build_system_prompt(store: dict) -> str:
    """Compose Gemini system prompt from store persona fields.
    (스토어 페르소나 필드로 Gemini 시스템 프롬프트 조합)
    """
    parts: list[str] = []

    if store.get("system_prompt"):
        parts.append(store["system_prompt"])

    if store.get("business_hours"):
        parts.append(f"Business hours: {store['business_hours']}")

    if store.get("custom_knowledge"):
        parts.append(f"Store knowledge:\n{store['custom_knowledge']}")

    if store.get("temporary_prompt"):
        parts.append(
            f"TODAY'S IMPORTANT NOTES (highest priority):\n{store['temporary_prompt']}"
        )

    # Global rules — voice quality + language + safety guardrails
    # Short prompt = lower TTFT. Every rule pulls its weight.
    parts.append(
        "STRICT RULES (non-negotiable):\n"
        "1. BREVITY: Max 1-2 short sentences per reply. Voice-only — zero markdown, zero lists. "
        "Do NOT tack on extra recommendations or upsells unless the customer asked.\n"
        "2. LANGUAGES SUPPORTED: English, Spanish (Español), Korean (한국어). "
        "All three are fully supported — never claim you can't speak any of them.\n"
        "3. LANGUAGE MATCHING (CRITICAL): Reply in the language of the customer's CURRENT message. "
        "Short English fillers like 'Okay', 'Yes', 'No', 'Hello', 'Thanks', 'Hmm' are ENGLISH — "
        "switch back to English immediately when you hear them, even if the previous turn was Korean. "
        "Each turn is matched independently — never carry inertia from prior turns.\n"
        "4. AMBIGUOUS / INAUDIBLE / SILENT: If the customer's words are unclear, '(inaudible)', "
        "or empty/silent, reply in the SAME LANGUAGE as YOUR OWN previous reply (not a different one) — "
        "with a brief 1-sentence acknowledgment or a polite 'Sorry, could you repeat that?'. "
        "NEVER switch language on an empty/unclear turn. Do NOT pivot to a sales pitch.\n"
        "5. KOREAN STYLE — natural spoken cafe-staff tone (구어체):\n"
        "   - Short and direct. End with '~요' / '~예요' / '~세요'.\n"
        "   - BANNED phrases (do NOT use): '꼭 들러주세요', '꼭 한번 들러보세요', '꼭 놀러 오세요', "
        "'맛보러 오세요', '편하신 시간에 언제든', '편하게 ~ 주세요', '꼭 맛보고 가세요'.\n"
        "   - BANNED behavior: weather small-talk ('날씨가 좋으니'), repeating menu unsolicited, "
        "self-serving 들러주세요 endings.\n"
        "   - Good examples: '네, 가능해요.' / '오늘은 오후 9시까지 해요.' / "
        "'죄송한데 그건 매니저한테 확인해 볼게요.' / '아보카도 BLT 샌드위치는 12달러예요.'\n"
        "   - Bad examples: '아보카도 BLT 샌드위치 세트가 준비되어 있으니 꼭 들러주세요.' (clichéd, pushy)\n"
        "6. OTHER LANGUAGES: For languages outside English/Spanish/Korean, briefly apologize in the "
        "customer's current language and offer one of the three.\n"
        "7. RESERVATIONS — TOOL USAGE: When a customer asks to make a reservation:\n"
        "   (a) Politely collect ALL six fields one at a time, briefly: name, phone, "
        "       date (e.g. 'tomorrow' = compute YYYY-MM-DD), time (24-hour HH:MM), party size.\n"
        "   (b) Recite the full summary back: 'Confirming a reservation for [name], "
        "       party of [N], on [date] at [time] — is that right?'\n"
        "   (c) ONLY after the customer says 'yes' verbally, call make_reservation "
        "       with user_explicit_confirmation=true.\n"
        "   (d) If the tool returns success, tell the customer the reservation is confirmed and read back "
        "       the reservation_id if provided. If it returns an error, apologize and offer to try again.\n"
        "   (e) If the store does NOT take reservations (no business_hours fits or knowledge says walk-ins only), "
        "       tell the customer 'walk-ins are always welcome' and DO NOT call the tool.\n"
        "8. NO PHANTOM BOOKINGS: Never claim a booking/reservation/order is confirmed unless the "
        "make_reservation tool actually returned success. Never invent confirmation numbers.\n"
        "9. UNCERTAINTY: If unsure, say 'I'm not sure — please ask us directly.' Do not fabricate.\n"
        "10. ESCALATION: If the caller is upset or asks for a manager: "
        "'Let me connect you with our manager right away.'"
    )

    return "\n\n".join(parts)


def format_transcript(transcript: list[dict]) -> str:
    """Convert Retell transcript array to conversation string for Gemini.
    (Retell transcript 배열을 Gemini용 대화 문자열로 변환)
    """
    lines = []
    for turn in transcript:
        role = "Customer" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)


# ── Async I/O helpers (mockable in tests) ─────────────────────────────────────

async def _load_store_by_agent(agent_id: str) -> Optional[dict]:
    """Fetch store row from Supabase by retell_agent_id.
    (Supabase에서 retell_agent_id로 스토어 행 조회)
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "retell_agent_id": f"eq.{agent_id}",
                "select": "id,name,retell_agent_id,system_prompt,temporary_prompt,"
                          "business_hours,custom_knowledge,is_active",
                "limit": "1",
            },
        )
    rows = resp.json()
    return rows[0] if rows else None


async def _get_agent_id_from_call(call_id: str) -> Optional[str]:
    """Fetch agent_id from Retell REST API using call_id.
    (Retell REST API에서 call_id로 agent_id 조회)
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{settings.retell_api_url}/v2/get-call/{call_id}",
                headers={
                    "Authorization": f"Bearer {settings.retell_api_key}",
                    "Content-Type":  "application/json",
                },
            )
        if resp.status_code == 200:
            return resp.json().get("agent_id")
    except Exception as exc:
        log.warning("_get_agent_id_from_call failed: %s", exc)
    return None


async def _generate_greeting(system_prompt: str) -> str:
    """Generate a short proactive greeting from Gemini (non-streaming, fast).
    (Gemini로 짧은 선제적 인사말 생성 — 논스트리밍, 빠른 단일 응답)
    """
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        "models/gemini-3.1-flash-lite-preview",
        system_instruction=system_prompt,
    )
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: model.generate_content(_GREETING_PROMPT),
    )
    return response.text.strip()


async def _stream_gemini_response(
    system_prompt: str,
    conversation: str,
    store_id: Optional[str] = None,
    call_log_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream Gemini text chunks. Handles make_reservation tool calls transparently.
    (Gemini 텍스트 스트리밍 + make_reservation 도구 호출 처리)

    Function-calling flow:
      1. Send conversation with tools enabled
      2. If chunk contains function_call → execute server-side, send result back
      3. Stream the follow-up text response after tool result

    store_id and call_log_id are server-resolved — never trusted from Gemini args.
    """
    import google.generativeai as genai
    from google.generativeai import protos

    genai.configure(api_key=settings.gemini_api_key)

    # Enable function calling only when we have a store context (real calls).
    # Synthetic test calls (no store_id) keep the legacy text-only path for stability.
    # (스토어 컨텍스트가 있을 때만 도구 활성화 — 합성 테스트 호출은 기존 텍스트 전용 경로 유지)
    kwargs: dict = {"system_instruction": system_prompt}
    tools_enabled = bool(store_id)
    if tools_enabled:
        kwargs["tools"] = [RESERVATION_TOOL_DEF]

    model = genai.GenerativeModel("models/gemini-3.1-flash-lite-preview", **kwargs)
    chat = model.start_chat()

    loop = asyncio.get_event_loop()

    response = await loop.run_in_executor(
        None,
        lambda: chat.send_message(conversation, stream=True),
    )

    function_call = None
    for chunk in response:
        try:
            for cand in chunk.candidates:
                for part in cand.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and getattr(fc, "name", ""):
                        function_call = fc
                        continue
                    txt = getattr(part, "text", "")
                    if txt:
                        yield txt
        except Exception:
            # Fallback: SDK shape variation across versions (SDK 버전 호환 폴백)
            txt = getattr(chunk, "text", "") or ""
            if txt:
                yield txt

    if not function_call or not tools_enabled:
        return

    # ── Tool roundtrip ────────────────────────────────────────────────────
    tool_name = function_call.name
    tool_args = dict(function_call.args) if function_call.args else {}
    log.info("Gemini tool call: %s args=%s", tool_name, tool_args)

    if tool_name == "make_reservation":
        result = await insert_reservation(tool_args, store_id, call_log_id)
    else:
        result = {"success": False, "error": f"unsupported tool: {tool_name}"}

    log.info("Tool %s result: %s", tool_name, result)

    followup = await loop.run_in_executor(
        None,
        lambda: chat.send_message(
            protos.Content(parts=[
                protos.Part(function_response=protos.FunctionResponse(
                    name=tool_name,
                    response={"result": result},
                ))
            ]),
            stream=True,
        ),
    )

    for chunk in followup:
        try:
            for cand in chunk.candidates:
                for part in cand.content.parts:
                    txt = getattr(part, "text", "")
                    if txt:
                        yield txt
        except Exception:
            txt = getattr(chunk, "text", "") or ""
            if txt:
                yield txt


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/llm-websocket/{call_id}")
async def websocket_llm(websocket: WebSocket, call_id: str):
    """Retell Custom LLM WebSocket — eager init pattern from jm-saas-platform.
    (jm-saas-platform의 즉시 초기화 패턴 — Retell call_details 이벤트 의존성 제거)

    Init sequence (mirrors llmServer.js _initSession):
      1. Accept WS → immediately start _init_session() as asyncio task
      2. _init_session: REST → agent_id → Supabase store → greeting (response_id=0)
      3. response_required arriving during init is queued → drained after greeting
      4. call_details arrival → fallback/override if store not yet loaded
    """
    await websocket.accept()
    call_started  = time.time()
    turn_count    = 0
    _mon("CONNECTED call=%s", call_id)

    # Session state — mutated by _init_session task and WS message loop
    sess = {
        "store":          None,   # dict once loaded
        "system_prompt":  "",
        "initialized":    False,  # True after greeting sent
        "greeting_sent":  False,
        "pending":        [],     # response_required messages buffered during init
        "last_user_msg":  "",     # dedupe key for barge-in echo
        "last_user_ts":   0.0,    # timestamp of last processed turn
    }
    init_done = asyncio.Event()

    # ── Inner: proactive init (fires immediately on connect) ──────────────────
    async def _init_session():
        """Load store via REST, generate greeting, mark initialized."""
        try:
            agent_id = await _get_agent_id_from_call(call_id)
            if not agent_id:
                _mon("INIT: no agent_id from REST for call=%s (web/test call)", call_id)
                return  # will fall back to call_details event

            store = await _load_store_by_agent(agent_id)
            if not store:
                _mon("INIT: no store for agent_id=%s call=%s", agent_id, call_id)
                return

            sess["store"]         = store
            sess["system_prompt"] = build_system_prompt(store)
            _mon("INIT OK call=%s store=%s", call_id, store["name"])

            # Generate and send proactive greeting (response_id=0, no prior request)
            try:
                greeting = await _generate_greeting(sess["system_prompt"])
                if websocket.client_state.value == 1:  # CONNECTED
                    await websocket.send_json({
                        "response_id":      0,
                        "content":          greeting,
                        "content_complete": True,
                    })
                    sess["greeting_sent"] = True
                    _mon("GREETING call=%s: %r", call_id, greeting[:80])
            except Exception as exc:
                _mon("GREETING ERROR call=%s: %s", call_id, exc)
                # Send static fallback so TTS pipeline is not left hanging
                if websocket.client_state.value == 1:
                    await websocket.send_json({
                        "response_id":      0,
                        "content":          "Hello! Thanks for calling. How can I help you today?",
                        "content_complete": True,
                    })
                    sess["greeting_sent"] = True

        except Exception as exc:
            _mon("INIT ERROR call=%s: %s", call_id, exc)
        finally:
            sess["initialized"] = True
            init_done.set()

            # Drain any response_required messages that arrived during init
            for queued in sess["pending"]:
                await _handle_response_required(websocket, call_id, queued, sess)
            sess["pending"].clear()

    # ── Inner: streaming response handler ────────────────────────────────────
    async def _handle_response_required(ws, cid, raw, s):
        nonlocal turn_count
        response_id  = raw["response_id"]
        transcript   = raw.get("transcript", [])
        conversation = format_transcript(transcript)

        last_user = next(
            (t["content"] for t in reversed(transcript) if t["role"] == "user"), ""
        )

        # Dedupe barge-in echo: same user msg within 1.5s → ack and skip
        # (바지인 에코 차단: 1.5초 내 동일 사용자 발화 → 짧게 종료)
        now = time.time()
        if (
            last_user.strip()
            and last_user.strip() == s.get("last_user_msg", "").strip()
            and (now - s.get("last_user_ts", 0)) < 1.5
        ):
            _mon("ECHO SKIP call=%s resp_id=%d user=%r", cid, response_id, last_user[:60])
            await ws.send_json({
                "response_id":      response_id,
                "content":          "",
                "content_complete": True,
            })
            return

        s["last_user_msg"] = last_user
        s["last_user_ts"]  = now
        turn_count        += 1
        _mon("TURN %d resp_id=%d user=%r", turn_count, response_id, last_user[:60])

        t_start  = time.time()
        ttft_ms  = 0.0
        chunk_n  = 0
        full_txt = ""
        error    = False

        store_id_for_tools = s["store"]["id"] if s.get("store") else None

        try:
            async for chunk in _stream_gemini_response(
                s["system_prompt"], conversation,
                store_id=store_id_for_tools, call_log_id=cid,
            ):
                if chunk_n == 0:
                    ttft_ms = (time.time() - t_start) * 1000
                chunk_n  += 1
                full_txt += chunk
                await ws.send_json({
                    "response_id":      response_id,
                    "content":          chunk,
                    "content_complete": False,
                })
            await ws.send_json({
                "response_id":      response_id,
                "content":          "",
                "content_complete": True,
            })
        except Exception as exc:
            error = True
            _mon("GEMINI ERROR call=%s turn=%d: %s", cid, turn_count, exc)
            await ws.send_json({
                "response_id":      response_id,
                "content":          "I'm sorry, I had a connection issue. Could you repeat that?",
                "content_complete": True,
            })

        total_ms = (time.time() - t_start) * 1000
        _log_turn(cid, turn_count, response_id, ttft_ms, total_ms, chunk_n, len(full_txt), error)
        _mon("  response=%r", full_txt[:100])

    # ── Launch eager init immediately ─────────────────────────────────────────
    asyncio.create_task(_init_session())

    try:
        async for raw in websocket.iter_json():
            interaction = raw.get("interaction_type")
            _mon("MSG call=%s type=%r", call_id, interaction)

            # ── call_details: fallback / web_call / Retell Simulation ─────────
            if interaction == "call_details":
                if not sess["store"]:
                    # Eager init hasn't loaded store yet (or failed) — load now
                    call_info = raw.get("call", {})
                    agent_id  = call_info.get("agent_id", "")
                    from_num  = call_info.get("from_number", "unknown")
                    store = await _load_store_by_agent(agent_id)
                    if not store:
                        _mon("NO STORE agent_id=%s — closing", agent_id)
                        await websocket.send_json({"error": f"No store found for agent {agent_id}"})
                        await websocket.close(code=1008)
                        return
                    sess["store"]         = store
                    sess["system_prompt"] = build_system_prompt(store)
                    _mon("CALL START (call_details) call=%s store=%s agent=%s from=%s",
                         call_id, store["name"], agent_id[:24], from_num)
                else:
                    # Eager init already loaded — just log from_number
                    from_num = raw.get("call", {}).get("from_number", "unknown")
                    _mon("CALL START (already init) call=%s store=%s from=%s",
                         call_id, sess["store"]["name"], from_num)

            # ── ping: keepalive ───────────────────────────────────────────────
            elif interaction == "ping":
                await websocket.send_json({"interaction_type": "ping_response"})

            # ── response_required: buffer during init, process after ───────────
            elif interaction == "response_required":
                if not sess["store"]:
                    # Still waiting for init — buffer this message
                    _mon("BUFFERING resp_id=%d (init in progress)", raw.get("response_id"))
                    sess["pending"].append(raw)
                    # Wait for init to complete (with safety timeout)
                    try:
                        await asyncio.wait_for(init_done.wait(), timeout=4.0)
                    except asyncio.TimeoutError:
                        _mon("INIT TIMEOUT call=%s — sending hold message", call_id)
                        await websocket.send_json({
                            "response_id":      raw["response_id"],
                            "content":          "Thank you for calling! One moment please.",
                            "content_complete": True,
                        })
                    # Remove from pending (already drained by _init_session or we gave a hold)
                    if raw in sess["pending"]:
                        sess["pending"].remove(raw)
                else:
                    await _handle_response_required(websocket, call_id, raw, sess)

            # ── update_only: transcript push, no reply needed ─────────────────
            elif interaction == "update_only":
                pass

            # ── reminder_required: customer went silent — send nudge ───────────
            elif interaction == "reminder_required":
                response_id = raw.get("response_id", 0)
                _mon("REMINDER call=%s resp_id=%d", call_id, response_id)
                await websocket.send_json({
                    "response_id":      response_id,
                    "content":          "I'm still here — is there anything else I can help you with?",
                    "content_complete": True,
                })

    except WebSocketDisconnect:
        elapsed = time.time() - call_started
        store_name = sess["store"]["name"] if sess["store"] else "unknown"
        _mon("CALL END call=%s turns=%d duration=%.1fs store=%s",
             call_id, turn_count, elapsed, store_name)
    except Exception as exc:
        _mon("ERROR call=%s: %s", call_id, exc)


# ── Retell Webhook — POST /api/retell/webhook ─────────────────────────────────
# Retell calls this after each call ends (call_ended / call_analyzed events).
# (Retell이 통화 종료 후 call_ended / call_analyzed 이벤트로 호출)

@router.post("/api/retell/webhook")
async def retell_webhook(request: Request):
    """Receive Retell post-call event and upsert to call_logs.
    (Retell 통화 후 이벤트 수신 → call_logs 업서트)
    """
    body = await request.json()
    event = body.get("event", "")
    call  = body.get("call",  {})

    if event not in ("call_ended", "call_analyzed"):
        return {"status": "ignored", "event": event}

    call_id       = call.get("call_id")
    agent_id      = call.get("agent_id", "")
    start_time    = call.get("start_timestamp")
    end_time      = call.get("end_timestamp")
    duration_ms   = (end_time - start_time) if (start_time and end_time) else None
    duration_sec  = round(duration_ms / 1000) if duration_ms else None

    disconnect    = call.get("disconnection_reason", "")
    call_status   = "Successful" if disconnect in ("user_hangup", "agent_hangup") else "Unsuccessful"

    analysis      = call.get("call_analysis", {})
    summary       = analysis.get("call_summary", "")
    sentiment     = analysis.get("user_sentiment", "")
    recording_url = call.get("recording_url", "")
    transcript    = call.get("transcript", "")

    store = await _load_store_by_agent(agent_id)
    store_id = store["id"] if store else None

    if not store_id:
        log.warning("Webhook: no store for agent_id=%s call=%s", agent_id, call_id)
        return {"status": "ok", "warning": "store not found"}

    # Retell sends timestamps as ms-epoch ints — Postgres timestamp column needs ISO 8601
    # (Retell의 ms 단위 epoch 정수 → Postgres timestamp 컬럼은 ISO 8601 필요)
    start_iso = (
        datetime.fromtimestamp(start_time / 1000, tz=timezone.utc).isoformat()
        if start_time else None
    )

    row = {
        "call_id":        call_id,
        "store_id":       store_id,
        "agent_id":       agent_id,
        "start_time":     start_iso,
        "customer_phone": call.get("from_number", ""),
        "duration":       duration_sec,
        "sentiment":      sentiment,
        "call_status":    call_status,
        "recording_url":  recording_url,
        "summary":        summary,
        "transcript":     transcript,
    }
    row = {k: v for k, v in row.items() if v is not None and v != ""}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_REST}/call_logs",
            headers={**_SUPABASE_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=row,
        )

    if resp.status_code not in (200, 201):
        log.error("Webhook upsert failed: %s %s", resp.status_code, resp.text[:200])
        return {"status": "error", "detail": resp.text[:200]}

    log.info("Webhook saved: call=%s store=%s status=%s", call_id, store_id, call_status)
    return {"status": "ok"}
