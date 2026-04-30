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
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.adapters.twilio.sms import send_reservation_confirmation
from app.core.config import settings
from app.services.bridge import flows as bridge_flows
from app.services.bridge.pay_link_email import send_pay_link_email
from app.services.bridge.pay_link_sms import send_pay_link
from app.skills.order.order import (
    MODIFY_ORDER_SCRIPT_BY_HINT,
    MODIFY_ORDER_TOOL_DEF,
    ORDER_SCRIPT_BY_HINT,
    ORDER_TOOL_DEF,
)
from app.skills.scheduler.reservation import (
    RESERVATION_TOOL_DEF,
    format_date_human,
    format_time_12h,
    insert_reservation,
    normalize_phone_us,
)

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
    "The call just connected. The customer has not spoken yet. "
    "Greet in ONE short English sentence: store name + 'how can I help?'. "
    "Maximum 10 words. No name introduction, no markdown, no emojis."
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

    # Inject current date/time so 'tomorrow', 'tonight', 'next Friday' resolve correctly.
    # (현재 날짜/시간 주입 — 'tomorrow', 'tonight', 'next Friday' 등의 정확한 해석)
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        _now = _dt.now(ZoneInfo("America/Los_Angeles"))
        parts.append(
            f"CURRENT DATE/TIME (America/Los_Angeles): "
            f"{_now.strftime('%A, %B %d, %Y at %-I:%M %p')} "
            f"(ISO: {_now.strftime('%Y-%m-%d %H:%M %Z')}). "
            f"Use this as the anchor for relative phrases like 'today', 'tomorrow', 'tonight', "
            f"'next Friday'. Never guess the date — always derive from this anchor."
        )
    except Exception:
        pass

    # Global rules — slim, voice-first, tool-call decisive.
    # Short prompt = lower TTFT and clearer tool-selection signal.
    # (Phase F-2 슬림화: Korean 제거, sub-rules 통합, tool 호출 결단 강화)
    parts.append(
        "RULES (non-negotiable):\n"
        "1. BREVITY: 1-2 short sentences per reply. Voice only — no markdown, no lists, no upsells.\n"
        "2. LANGUAGES: English and Spanish only. Reply in the language of the customer's CURRENT "
        "message. Short fillers ('Yes', 'No', 'Okay', 'Thanks') are ENGLISH — switch back instantly. "
        "If the customer speaks anything else, briefly apologize in their language and offer English or Spanish.\n"
        "3. UNCLEAR / SILENT: Stay in YOUR previous language and say 'Sorry, could you repeat that?'. "
        "Never switch language on an empty turn.\n"
        "4. RESERVATIONS (make_reservation): Collect name, 10-digit US phone (re-ask if fewer digits), "
        "date (YYYY-MM-DD from CURRENT DATE anchor), time (pass 24-h to the tool, SPEAK 12-h with AM/PM), "
        "party size. Cross-check the time against business_hours — if outside, decline and offer the "
        "nearest available slot; do NOT call the tool. Recite ONCE: 'Confirming a reservation for "
        "[name], party of [N], [day, Month D] at [12-h time] — is that right?'. "
        "On verbal yes, CALL make_reservation with user_explicit_confirmation=true. After success the "
        "booking is FINAL — never re-call. On error, apologize once + 'a manager will call you back' + STOP.\n"
        "5. ORDERS (create_order): Use ONLY items from the menu above. Collect name + items+quantity. "
        "PHONE: do NOT ask the customer for their phone number — the system already has it from the "
        "inbound call. Only ask if they explicitly want the link sent to a different number. "
        "EMAIL (REQUIRED while SMS delivery is being verified): after items are agreed but BEFORE you "
        "recite the order, ask 'What's the best email to send the payment link to?' and pass it as "
        "customer_email. If the customer truly insists on SMS only, omit customer_email — but always "
        "ask once. "
        "Recite ONCE: 'Confirming [N] [item], [N] [item] "
        "for [name] — is that right?'. On the FIRST verbal yes (yes / yeah / sure / correct / that's right / sí), "
        "CALL create_order with user_explicit_confirmation=true IMMEDIATELY — do NOT recite again, do NOT "
        "apologize, do NOT ask the same question twice. If you have already confirmed the items once, the "
        "next yes means CALL THE TOOL. AFTER the tool returns success and you read its message, the order "
        "is FINAL: do NOT call create_order again, do NOT ask 'is that right?' again. If the customer says "
        "'okay' or 'thanks' or 'bye', reply with one short closing sentence ('Thanks, see you soon.') and "
        "stop. The pay link / kitchen handoff happens after the call ends.\n"
        "6. MODIFY ORDER (modify_order): If the customer asks to change an order they "
        "JUST placed in this same call (add an item, remove one, change a quantity) AND it "
        "has not yet been paid for, recite the FULL UPDATED order with the NEW total "
        "('Updated to two cafe lattes and one croissant for $15.97 — is that right?'). On "
        "the explicit verbal yes, call modify_order with the COMPLETE new items list (NOT "
        "a delta). The same payment link automatically reflects the new total — do NOT "
        "promise a new link, do NOT ask for the phone or email again. If the bridge "
        "returns modify_too_late, apologize and offer to cancel + place a fresh order.\n"
        "7. AFTER TOOL SUCCESS: Read the tool's 'message' field VERBATIM. Never substitute wording.\n"
        "8. TOOL ERRORS: sold_out / unknown_item → offer alternatives, do not retry with same items. "
        "pos_failure → apologize once + STOP, a person will call back.\n"
        "9. NO PHANTOM BOOKINGS: Never claim confirmed without a successful tool result. No invented numbers.\n"
        "10. ESCALATION: 'Let me connect you with our manager right away.'"
    )

    return "\n\n".join(parts)


# Cap transcript length sent to Gemini. Past ~12 turns the model starts
# self-loop hallucinating ("I'm sorry, I missed the items in the system…")
# from seeing its own repeated confirmations in history. Voice flows are
# short by nature — last 12 turns is plenty of context.
# (12턴 초과 시 자가증식 사과 루프 차단)
_TRANSCRIPT_TAIL_TURNS = 12


def format_transcript(transcript: list[dict]) -> str:
    """Convert Retell transcript array to conversation string for Gemini.
    (Retell transcript 배열을 Gemini용 대화 문자열로 변환 — 최근 N턴만)
    """
    tail = transcript[-_TRANSCRIPT_TAIL_TURNS:] if len(transcript) > _TRANSCRIPT_TAIL_TURNS else transcript
    lines = []
    for turn in tail:
        role = "Customer" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)


# Affirmation tokens that trigger forced tool-call mode after a "Confirming…"
# recital. Lowercase + punctuation-stripped match. Covers EN + ES.
# (확정 토큰 — 영어 + 스페인어; 정확한 yes-class 발화에만 매칭)
_AFFIRMATION_TOKENS = {
    "yes", "yeah", "yep", "yup", "sure", "correct", "right",
    "that's right", "thats right", "that's correct", "thats correct",
    "ok", "okay", "go ahead", "do it", "confirm", "confirmed",
    "sí", "si", "claro", "correcto", "está bien", "esta bien",
}

# Phrases the assistant uses right before a tool call. If the assistant's
# last reply contained one AND the user's current reply is an affirmation,
# we force tool_config=ANY so Gemini commits to the tool instead of looping.
# (직전 assistant 발화에 confirmation 패턴이 있고 사용자가 yes-class면 tool 강제)
_CONFIRMATION_PATTERNS = ("is that right", "is that correct", "confirming")


def detect_force_tool_use(transcript: list[dict]) -> bool:
    """Heuristic: should we force Gemini into tool-call mode this turn?
    True iff the last assistant message recited a confirmation AND the
    user's current message is a clear affirmation. Stops the confirm-loop
    bug where Gemini ignores 'yes' and keeps re-asking.
    (마지막 assistant 발화가 'is that right?' + 사용자 yes → tool_config=ANY 강제)
    """
    last_user = ""
    last_assistant = ""
    for turn in reversed(transcript):
        c = (turn.get("content") or "").lower().strip().strip(".!?,")
        if not last_user and turn.get("role") == "user":
            last_user = c
        elif not last_assistant and turn.get("role") != "user":
            last_assistant = c
        if last_user and last_assistant:
            break

    if not last_user or not last_assistant:
        return False

    if not any(p in last_assistant for p in _CONFIRMATION_PATTERNS):
        return False

    # Match affirmation as standalone word or short fragment within the user
    # turn ("yes that's correct" / "yeah, sure" / "sí claro").
    user_tokens = {tok.strip() for tok in last_user.replace(",", " ").split()}
    if user_tokens & _AFFIRMATION_TOKENS:
        return True
    return any(phrase in last_user for phrase in _AFFIRMATION_TOKENS)


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


async def _get_call_metadata(call_id: str) -> dict:
    """Fetch agent_id + from_number (caller phone) from Retell REST API.
    Returns {} on failure so callers can branch cleanly.
    (Retell REST API에서 call_id로 agent_id + from_number 동시 조회)

    from_number is the carrier-authenticated caller ID. Using it as the
    server-side source of truth for customer_phone removes the entire
    class of STT/Gemini phone-hallucination bugs (verified 2026-04-29
    against legacy jm-saas-platform pattern in src/websocket/llmServer.js).
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
            body = resp.json()
            return {
                "agent_id":    body.get("agent_id") or "",
                "from_number": body.get("from_number") or "",
            }
    except Exception as exc:
        log.warning("_get_call_metadata failed: %s", exc)
    return {}


# Back-compat shim — keep the old call site working until everything is
# migrated to _get_call_metadata().
# (구 호출부 호환 — _get_call_metadata로 점진 이행)
async def _get_agent_id_from_call(call_id: str) -> Optional[str]:
    meta = await _get_call_metadata(call_id)
    return meta.get("agent_id") or None


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
    store_name: Optional[str] = None,
    force_tool_use: bool = False,
    caller_phone_e164: str = "",
) -> AsyncGenerator[str, None]:
    """Stream Gemini text chunks. Handles tool calls transparently.
    (Gemini 텍스트 스트리밍 + tool 호출 처리)

    Function-calling flow:
      1. Send conversation with tools enabled
      2. If chunk contains function_call → execute server-side, send result back
      3. Stream the follow-up text response after tool result

    force_tool_use=True sets tool_config to ANY mode — Gemini MUST emit a
    function call this turn instead of free text. Used after the user
    explicitly confirms a recited order/reservation, to break the
    "I'm sorry, I missed the items" self-loop in flash-lite.
    (force_tool_use=True → 사과 루프 차단용 강제 tool 호출 모드)

    store_id and call_log_id are server-resolved — never trusted from Gemini args.
    """
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)

    # Enable function calling only when we have a store context (real calls).
    # Synthetic test calls (no store_id) keep the legacy text-only path for stability.
    # (스토어 컨텍스트가 있을 때만 도구 활성화 — 합성 테스트 호출은 기존 텍스트 전용 경로 유지)
    kwargs: dict = {"system_instruction": system_prompt}
    tools_enabled = bool(store_id)
    if tools_enabled:
        # Both reservation and order tools are exposed to Gemini. The model
        # picks one (or none) per turn based on the customer's ask. Mixing
        # reservation + order in the same call is not allowed by prompt rules.
        # (예약 + 주문 도구를 모두 Gemini에 노출 — 프롬프트가 한 번에 하나만 선택)
        kwargs["tools"] = [
            RESERVATION_TOOL_DEF,
            ORDER_TOOL_DEF,
            MODIFY_ORDER_TOOL_DEF,
        ]
        if force_tool_use:
            kwargs["tool_config"] = {
                "function_calling_config": {"mode": "ANY"},
            }
            log.info("Gemini tool_config=ANY forced (post-confirmation)")

    model = genai.GenerativeModel("models/gemini-3.1-flash-lite-preview", **kwargs)
    chat = model.start_chat()

    loop = asyncio.get_event_loop()

    response = await loop.run_in_executor(
        None,
        lambda: chat.send_message(conversation, stream=True),
    )

    function_call = None
    chunk_idx = 0
    for chunk in response:
        chunk_idx += 1
        try:
            cand_count = len(chunk.candidates)
            for ci, cand in enumerate(chunk.candidates):
                fr = getattr(cand, "finish_reason", "?")
                part_count = len(cand.content.parts)
                for pi, part in enumerate(cand.content.parts):
                    fc = getattr(part, "function_call", None)
                    fc_name = getattr(fc, "name", "") if fc else ""
                    txt_dbg = getattr(part, "text", "") or ""
                    if force_tool_use:
                        _mon(
                            "STREAM DBG chunk=%d cand=%d/%d part=%d/%d "
                            "finish=%s text=%r fc.name=%r",
                            chunk_idx, ci, cand_count, pi, part_count,
                            fr, txt_dbg[:40], fc_name,
                        )
                    if fc and fc_name:
                        function_call = fc
                        continue
                    if txt_dbg:
                        yield txt_dbg
        except Exception as exc:
            # Fallback: SDK shape variation across versions (SDK 버전 호환 폴백)
            if force_tool_use:
                _mon("STREAM DBG chunk=%d EXCEPTION: %r", chunk_idx, exc)
            txt = getattr(chunk, "text", "") or ""
            if txt:
                yield txt
    if force_tool_use:
        _mon("STREAM DBG done: total_chunks=%d function_call_set=%s",
             chunk_idx, bool(function_call))

    if not function_call or not tools_enabled:
        return

    # ── Tool roundtrip ────────────────────────────────────────────────────
    tool_name = function_call.name
    tool_args = dict(function_call.args) if function_call.args else {}

    # ── AUTO-FIRE GATE (server-side hardening) ────────────────────────────
    # Reject any create_order / make_reservation that arrives WITHOUT the
    # FORCE TOOL signal. force_tool_use=True means we detected the explicit
    # confirmation pattern (assistant recital + user yes-class word) just
    # before this turn — that's the only path we trust to actually book or
    # charge a customer. Anything else is Gemini AUTO-deciding it has
    # 'enough info' and self-firing, which is exactly how 'Guest' /
    # 'Anonymous' / mid-sentence STT garbage have been slipping through.
    #
    # When we block, we coerce Gemini back into a clean confirm cycle by
    # synthesizing a recital from whatever args it provided. The customer
    # hears 'Just to confirm, that's X for Y — is that right?', says yes,
    # detect_force_tool_use fires next turn, and we run the real tool.
    # (AUTO-fire 차단 — recite-and-yes 사이클로 강제 환원)
    if tool_name in ("create_order", "make_reservation", "modify_order") and not force_tool_use:
        items_for_recital: list[str] = []
        try:
            for it in (tool_args.get("items") or []):
                d = dict(it) if not isinstance(it, dict) else it
                qty  = int(d.get("quantity") or 1)
                nm   = (d.get("name") or "").strip() or "item"
                plural = "" if qty == 1 else "s"
                items_for_recital.append(f"{qty} {nm}{plural}")
        except Exception:
            pass
        recital_name = (tool_args.get("customer_name") or "").strip() or "you"
        if tool_name == "create_order":
            phrase = ", ".join(items_for_recital) or "your order"
            recital = (f"Just to confirm, that's {phrase} for {recital_name} "
                       f"— is that right?")
        else:
            recital = (f"Just to confirm a reservation for {recital_name} "
                       f"— is that right?")
        _mon("AUTO-FIRE BLOCKED tool=%s args_phone=%r args_name=%r args_email=%r "
             "items=%d → recital fallback",
             tool_name,
             tool_args.get("customer_phone") or "",
             tool_args.get("customer_name") or "",
             tool_args.get("customer_email") or "",
             len(tool_args.get("items") or []))
        yield recital
        return

    # Server-side caller_phone override — single source of truth.
    # Retell hands us the carrier-authenticated caller phone (from_number)
    # at WebSocket connect; we ALWAYS use that over anything Gemini puts
    # in customer_phone. Gemini's transcribed/hallucinated value is
    # discarded unconditionally when we have a caller_phone_e164.
    #
    # The earlier "alternate-number bypass" tried to honour 'send to a
    # different number' requests but in practice Gemini's hallucinated
    # 555-fictional numbers always tripped the bypass and we ended up
    # with multiple Loyverse receipts under fake phones (verified in
    # call_c350ebdcc5...: 3 distinct fake phones → 3 receipts in 30s).
    # Alternate-number routing, when needed, will land as an explicit
    # store-config feature — not as a heuristic on Gemini args.
    # (caller_phone_e164은 항상 server source-of-truth — bypass 제거)
    if tool_name in ("create_order", "make_reservation") and caller_phone_e164:
        tool_args["customer_phone"] = caller_phone_e164

    # Use _mon for visibility — log.info from this module is silenced by
    # uvicorn's default logger config and never reaches /tmp/backend.log.
    # Pull out the item names explicitly so reject-loops are diagnosable
    # without parsing proto MapComposite repr() (which hides actual names).
    # (item 이름을 명시 추출 — proto repr이 가려서 디버그 불가했음)
    item_summary: list[str] = []
    try:
        for it in (tool_args.get("items") or []):
            d = dict(it) if not isinstance(it, dict) else it
            item_summary.append(f"{d.get('quantity', '?')}x {d.get('name', '?')!r}")
    except Exception:
        pass
    _mon("TOOL CALL name=%s phone=%r name=%r email=%r force=%s items=[%s]",
         tool_name,
         tool_args.get("customer_phone"),
         tool_args.get("customer_name"),
         tool_args.get("customer_email") or "",
         force_tool_use,
         ", ".join(item_summary))

    if tool_name == "make_reservation":
        # Phase 2-B: route through Bridge Server. Bridge owns:
        # - bridge_transactions row + audit trail (bridge_events)
        # - state machine (pending → payment_sent → paid → fulfilled)
        # - POS adapter (Supabase today, Quantic later)
        # - payment adapter (NoOp today, Maverick later)
        # POS write to reservations table happens inside the bridge via SupabasePOSAdapter.
        # (Bridge Server 통과 — 트랜잭션/감사/상태기계/어댑터 모두 Bridge가 관리)
        bridge_result = await bridge_flows.create_reservation(
            store_id    = store_id,
            args        = tool_args,
            call_log_id = call_log_id,
            deposit_cents = 0,        # free reservation today; deposits later via Maverick
        )

        # Adapt bridge result to the existing tool_response shape Gemini expects
        # (Gemini가 기대하는 기존 tool_response 형식으로 변환)
        if bridge_result.get("success"):
            result = {
                "success":        True,
                "reservation_id": bridge_result.get("pos_object_id"),
                "transaction_id": bridge_result.get("transaction_id"),
                "message":        bridge_result.get("message", ""),
                "idempotent":     False,
            }

            # Fire-and-forget SMS confirmation
            try:
                phone_e164 = normalize_phone_us(tool_args.get("customer_phone", ""))
                asyncio.create_task(send_reservation_confirmation(
                    to            = phone_e164,
                    store_name    = store_name or "the restaurant",
                    customer_name = tool_args.get("customer_name", ""),
                    date_human    = format_date_human(tool_args["reservation_date"]),
                    time_12h      = format_time_12h(tool_args["reservation_time"]),
                    party_size    = int(tool_args.get("party_size", 0)),
                ))
                _mon("SMS confirmation queued (fire-and-forget) to=%s", phone_e164)
            except Exception as exc:
                _mon("SMS dispatch error (ignored): %s", exc)
        else:
            result = {
                "success": False,
                "error":   bridge_result.get("error", "reservation failed"),
            }
    elif tool_name == "create_order":
        # Phase 2-B.1.8 — order flow with lane-aware response.
        # Bridge owns: bridge_transactions row, audit trail, state machine,
        # menu match (variant_id resolution), policy lane decision,
        # POS adapter selection, payment lane bookkeeping.
        # SMS pay link wiring lands in Phase 2-B.1.10.
        # (Bridge가 모두 관리 — SMS pay link는 Phase 2-B.1.10)
        bridge_result = await bridge_flows.create_order(
            store_id    = store_id,
            args        = tool_args,
            call_log_id = call_log_id,
        )

        # Pick the customer-facing line based on lane. Falling back to a
        # neutral confirmation keeps the call from going silent if a new
        # ai_script_hint is added without a matching script.
        # (lane별 멘트 선택 — 누락된 hint는 안전한 기본 멘트로 폴백)
        hint   = bridge_result.get("ai_script_hint", "")
        script = ORDER_SCRIPT_BY_HINT.get(
            hint,
            "Thanks — I've got that. A team member will follow up shortly.",
        )

        if bridge_result.get("success"):
            result = {
                "success":         True,
                "lane":            bridge_result.get("lane"),
                "transaction_id":  bridge_result.get("transaction_id"),
                "pos_object_id":   bridge_result.get("pos_object_id", ""),
                "total_cents":     bridge_result.get("total_cents", 0),
                "message":         script,
                "idempotent":      bool(bridge_result.get("idempotent")),
            }

            # Fire-and-forget pay link delivery. Skip on idempotent re-hits —
            # the link was already sent on the first call. Two channels run
            # in parallel: SMS (primary, blocked by Twilio TCR for now) and
            # email (TCR-fallback, requires customer_email from the tool args).
            # Either channel reaching the customer is enough to close the loop.
            # Failures of either are swallowed — audio path must never block.
            # (멱등 재요청은 양쪽 모두 스킵 / 한쪽만 도달해도 OK)
            if not bridge_result.get("idempotent"):
                tx_id        = str(bridge_result.get("transaction_id") or "")
                lane_str     = str(bridge_result.get("lane") or "pay_first")
                total_cents  = int(bridge_result.get("total_cents") or 0)
                items_for_em = bridge_result.get("items") or []

                try:
                    asyncio.create_task(send_pay_link(
                        to             = tool_args.get("customer_phone", ""),
                        store_name     = store_name or "the restaurant",
                        total_cents    = total_cents,
                        transaction_id = tx_id,
                        lane           = lane_str,
                    ))
                    _mon("PAY LINK SMS queued tx=%s to=%s lane=%s",
                         tx_id, tool_args.get("customer_phone", "")[:14], lane_str)
                except Exception as exc:
                    _mon("PAY LINK SMS dispatch error tx=%s: %s", tx_id, exc)

                # Email fallback — only fires when the customer gave an
                # email address. Useful while Twilio TCR approval is pending
                # (carriers silently filter A2P SMS during that window).
                # (TCR 승인 전 이메일 fallback — 수신처가 있을 때만 발송)
                customer_email = (tool_args.get("customer_email") or "").strip()
                if customer_email:
                    try:
                        asyncio.create_task(send_pay_link_email(
                            to              = customer_email,
                            customer_name   = tool_args.get("customer_name", ""),
                            store_name      = store_name or "the restaurant",
                            total_cents     = total_cents,
                            items           = items_for_em,
                            transaction_id  = tx_id,
                            lane            = lane_str,
                        ))
                        _mon("PAY LINK EMAIL queued tx=%s to=%s lane=%s",
                             tx_id, customer_email, lane_str)
                    except Exception as exc:
                        _mon("PAY LINK EMAIL dispatch error tx=%s: %s", tx_id, exc)
                else:
                    _mon("PAY LINK EMAIL skipped tx=%s — no customer_email in tool args",
                         tx_id)
        else:
            # Refusal (sold_out / unknown_item / pos_failure) — use the
            # script for that hint so the agent says something useful.
            result = {
                "success":     False,
                "lane":        bridge_result.get("lane"),
                "reason":      bridge_result.get("reason"),
                "unavailable": bridge_result.get("unavailable", []),
                "message":     script,
                "error":       bridge_result.get("error", ""),
            }
    elif tool_name == "modify_order":
        # Phase 2-C.B1 — replace items on an in-flight order. Bridge owns
        # target lookup (caller-id), state-guarding (PENDING / PAYMENT_SENT
        # only), menu resolution, total recompute, persistence, audit.
        # No new pay link is dispatched — /pay/{tx_id} reads total_cents at
        # click time, so the existing link auto-reflects the new total.
        # (B1 — 결제 전 items 교체. pay link 재발송 X)
        bridge_result = await bridge_flows.modify_order(
            store_id          = store_id,
            args              = tool_args,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = call_log_id,
        )

        hint = bridge_result.get("ai_script_hint", "")
        # Modify-specific scripts first; fall back to ORDER_SCRIPT_BY_HINT
        # for the shared 'rejected' / 'validation_failed' lines.
        # (modify 전용 스크립트 우선, 공용은 ORDER_SCRIPT_BY_HINT 폴백)
        script_template = (
            MODIFY_ORDER_SCRIPT_BY_HINT.get(hint)
            or ORDER_SCRIPT_BY_HINT.get(
                hint,
                "Thanks — I've got that.",
            )
        )

        # Substitute {total} for the success line. Other lines have no
        # placeholder, so .format() leaves them unchanged.
        # (성공 시 새 total을 멘트에 치환)
        new_total_cents = int(bridge_result.get("total_cents") or 0)
        total_human     = f"${new_total_cents / 100:.2f}"
        try:
            script = script_template.format(total=total_human)
        except (KeyError, IndexError):
            script = script_template

        if bridge_result.get("success"):
            result = {
                "success":         True,
                "transaction_id":  bridge_result.get("transaction_id"),
                "lane":            bridge_result.get("lane"),
                "state":           bridge_result.get("state"),
                "total_cents":     new_total_cents,
                "items":           bridge_result.get("items"),
                "message":         script,
            }
        else:
            result = {
                "success":     False,
                "reason":      bridge_result.get("reason"),
                "unavailable": bridge_result.get("unavailable", []),
                "message":     script,
                "error":       bridge_result.get("error", ""),
            }
    else:
        result = {"success": False, "error": f"unsupported tool: {tool_name}"}

    # Surface the actual rejection reason and rejected items so a failed
    # call is diagnosable without diffing the bridge code path.
    # (거부 이유 + 거부된 item 명시 — 디버그 추적 가능)
    unavail_summary = ""
    unavail_list = result.get("unavailable") or []
    if unavail_list:
        try:
            unavail_summary = ", ".join(
                f"{u.get('quantity','?')}x {u.get('name','?')}" for u in unavail_list
            )
        except Exception:
            unavail_summary = repr(unavail_list)
    _mon("TOOL RESULT name=%s success=%s lane=%s reason=%s unavailable=[%s] err=%r message_len=%d",
         tool_name,
         result.get("success"),
         result.get("lane"),
         result.get("reason"),
         unavail_summary,
         result.get("error"),
         len(result.get("message") or ""))

    # Yield the bridge-supplied script verbatim. We deliberately do NOT round-
    # trip the function_response through Gemini for a paraphrase: with
    # tool_config=ANY (force_tool_use path) the chat session keeps emitting
    # another function_call instead of text, producing chunks=0. Even in AUTO
    # mode our system prompt rule 6 mandates VERBATIM reading of the message.
    # So we are authoritative here — Gemini does not edit the customer line.
    # (Gemini paraphrase 차단 — tool_config=ANY가 followup도 function_call로 강제,
    #  rule 6에서 VERBATIM 명시 — bridge message를 그대로 Retell로 전달)
    msg = result.get("message") or ""
    if msg:
        yield msg
    else:
        # Last-resort safety: a tool result with no message would leave the
        # caller in silence. Emit a generic acknowledgment so the call moves on.
        yield "Got it. A team member will follow up shortly."


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

    # Session state — mutated by _init_session task and WS message loop.
    # caller_phone_e164 is the carrier-authenticated caller ID, captured
    # from Retell's /v2/get-call REST response on connect. The order tool
    # roundtrip overrides whatever Gemini puts in customer_phone with this
    # value when present, removing the entire phone-hallucination class
    # (verified in jm-saas-platform legacy pattern).
    # (caller_phone_e164 — Retell carrier-authenticated phone, server source of truth)
    sess = {
        "store":              None,   # dict once loaded
        "system_prompt":      "",
        "initialized":        False,  # True after greeting sent
        "greeting_sent":      False,
        "pending":            [],     # response_required messages buffered during init
        "last_user_msg":      "",     # dedupe key for barge-in echo
        "last_user_ts":       0.0,    # timestamp of last processed turn
        "caller_phone_e164":  "",     # Retell from_number, set by _init_session
    }
    init_done = asyncio.Event()

    # ── Inner: proactive init (fires immediately on connect) ──────────────────
    async def _init_session():
        """Load store via REST, generate greeting, mark initialized."""
        try:
            meta     = await _get_call_metadata(call_id)
            agent_id = meta.get("agent_id") or ""
            from_num = meta.get("from_number") or ""
            if not agent_id:
                _mon("INIT: no agent_id from REST for call=%s (web/test call)", call_id)
                return  # will fall back to call_details event

            store = await _load_store_by_agent(agent_id)
            if not store:
                _mon("INIT: no store for agent_id=%s call=%s", agent_id, call_id)
                return

            sess["store"]         = store
            sess["system_prompt"] = build_system_prompt(store)
            # Stash carrier-authenticated caller phone so the order tool
            # roundtrip can override Gemini's customer_phone with it.
            # (caller_phone_e164는 Gemini args를 server-side override)
            if from_num:
                sess["caller_phone_e164"] = from_num
                _mon("INIT OK call=%s store=%s caller=%s",
                     call_id, store["name"], from_num)
            else:
                _mon("INIT OK call=%s store=%s caller=<unknown>", call_id, store["name"])

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

        # Lifecycle-safe send. Retell hangs up mid-stream when the caller drops
        # the line; firing send_json on a closed socket raises 'Cannot call
        # send once close'. Check client_state before every write so a hangup
        # doesn't poison the rest of the turn loop.
        # (통화 끊김 후 send 시도 보호 — Retell side close에 대비)
        async def _safe_send(payload: dict) -> bool:
            try:
                if ws.client_state.value != 1:   # 1 = CONNECTED
                    return False
                await ws.send_json(payload)
                return True
            except Exception as exc:             # send race lost — log and drop
                _mon("WS SEND DROPPED call=%s resp_id=%s: %s",
                     cid, payload.get("response_id"), exc)
                return False

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
            await _safe_send({
                "response_id":      response_id,
                "content":          "",
                "content_complete": True,
            })
            return

        s["last_user_msg"] = last_user
        s["last_user_ts"]  = now
        turn_count        += 1
        _mon("TURN %d resp_id=%d user=%r", turn_count, response_id, last_user[:60])

        # Turn-1 silent-input guard: the eager greeting (response_id=0) has
        # already played, but Retell often fires response_required before the
        # caller has actually said anything. last_user lands as 'Hi', 'I',
        # 'Hello' or empty, and Gemini replies with a second greeting that
        # collides audibly with the first. Suppress it: emit empty content
        # with content_complete=true and let the caller speak.
        # (Turn 1 빈 발화시 두 번째 인사 차단 — eager greeting과 겹침 방지)
        if turn_count == 1 and len(last_user.strip()) <= 5:
            _mon("TURN1 SHORT SKIP call=%s user=%r", cid, last_user[:30])
            await _safe_send({
                "response_id":      response_id,
                "content":          "",
                "content_complete": True,
            })
            return

        t_start  = time.time()
        ttft_ms  = 0.0
        chunk_n  = 0
        full_txt = ""
        error    = False

        store_id_for_tools   = s["store"]["id"]   if s.get("store") else None
        store_name_for_tools = s["store"]["name"] if s.get("store") else None
        caller_phone_e164    = s.get("caller_phone_e164") or ""
        force_tool_use       = detect_force_tool_use(transcript)
        if force_tool_use:
            _mon("FORCE TOOL call=%s resp_id=%d (post-confirmation yes detected)",
                 cid, response_id)

        try:
            async for chunk in _stream_gemini_response(
                s["system_prompt"], conversation,
                store_id=store_id_for_tools, call_log_id=cid,
                store_name=store_name_for_tools,
                force_tool_use=force_tool_use,
                caller_phone_e164=caller_phone_e164,
            ):
                if chunk_n == 0:
                    ttft_ms = (time.time() - t_start) * 1000
                chunk_n  += 1
                full_txt += chunk
                if not await _safe_send({
                    "response_id":      response_id,
                    "content":          chunk,
                    "content_complete": False,
                }):
                    # Caller hung up mid-stream — abort the rest of the turn.
                    # (통화 끊김 — 남은 청크 발송 중단)
                    break
            await _safe_send({
                "response_id":      response_id,
                "content":          "",
                "content_complete": True,
            })
        except Exception as exc:
            error = True
            _mon("GEMINI ERROR call=%s turn=%d: %s", cid, turn_count, exc)
            await _safe_send({
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
                    from_num  = call_info.get("from_number", "") or "unknown"
                    store = await _load_store_by_agent(agent_id)
                    if not store:
                        _mon("NO STORE agent_id=%s — closing", agent_id)
                        await websocket.send_json({"error": f"No store found for agent {agent_id}"})
                        await websocket.close(code=1008)
                        return
                    sess["store"]         = store
                    sess["system_prompt"] = build_system_prompt(store)
                    if from_num and from_num != "unknown" and not sess.get("caller_phone_e164"):
                        sess["caller_phone_e164"] = from_num
                    _mon("CALL START (call_details) call=%s store=%s agent=%s from=%s",
                         call_id, store["name"], agent_id[:24], from_num)
                else:
                    # Eager init already loaded — just log from_number, capture if missing
                    from_num = raw.get("call", {}).get("from_number", "") or "unknown"
                    if from_num and from_num != "unknown" and not sess.get("caller_phone_e164"):
                        sess["caller_phone_e164"] = from_num
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

    # ── Backfill: link reservations created during this call to call_log_id ─────
    # (백필: 이 통화 중 생성된 예약을 call_log_id로 연결)
    # FK to call_logs(call_id) is now satisfied. Match by store_id + customer_phone +
    # NULL call_log_id within the call's time window.
    backfill_count = await _backfill_reservation_call_log_id(
        store_id, call_id, call.get("from_number", ""), start_iso,
    )
    if backfill_count:
        log.info("Backfilled call_log_id on %d reservations for call=%s", backfill_count, call_id)

    return {"status": "ok", "backfilled_reservations": backfill_count}


async def _backfill_reservation_call_log_id(
    store_id: str,
    call_id: str,
    from_number: str,
    start_iso: Optional[str],
) -> int:
    """After call ends, link reservations created during the call to call_log_id.
    (통화 종료 후, 통화 중 생성된 예약을 call_log_id로 연결)

    Strategy: store_id + customer_phone + NULL call_log_id + created_at within 1 hour
    of call start. Returns count of rows updated.
    """
    from app.skills.scheduler.reservation import normalize_phone_us

    if not from_number or not start_iso:
        return 0

    phone_e164 = normalize_phone_us(from_number)
    # Backfill window: 1 hour before call start to allow for clock skew / long calls
    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        window_start = (start_dt - timedelta(hours=1)).isoformat()
    except Exception:
        return 0

    async with httpx.AsyncClient(timeout=10) as client:
        # Find candidates
        probe = await client.get(
            f"{_REST}/reservations",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":       f"eq.{store_id}",
                "customer_phone": f"eq.{phone_e164}",
                "call_log_id":    "is.null",
                "created_at":     f"gte.{window_start}",
                "select":         "id",
            },
        )
        if probe.status_code != 200 or not probe.json():
            return 0

        ids = [str(r["id"]) for r in probe.json()]
        # PATCH each (PostgREST allows id=in.(...) filter)
        patch_resp = await client.patch(
            f"{_REST}/reservations",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"in.({','.join(ids)})"},
            json={"call_log_id": call_id},
        )
        if patch_resp.status_code in (200, 204):
            return len(ids)
        log.warning("Backfill PATCH failed %s: %s", patch_resp.status_code, patch_resp.text[:120])
        return 0
