"""Phase 2-D — Twilio Media Streams ↔ OpenAI Realtime bridge (Phase 2 of migration plan).
(Phase 2-D — Twilio Media Streams ↔ OpenAI Realtime 브릿지 — 마이그레이션 Phase 2)

This module sits IN PARALLEL with app/api/voice_websocket.py (the Retell+Gemini
handler). Both stay live during dual-track migration; Twilio routes traffic per
phone number. NO existing code path is modified.
(기존 voice_websocket.py와 병행 운영 — 듀얼 트랙 마이그레이션 핵심)

Flow:
    PSTN → Twilio Voice (number config) → HTTP POST /twilio/voice/inbound
                                          ↓ TwiML <Connect><Stream wss://.../ws/realtime>
                                          ↓
    Twilio Media Streams ↔ ws://localhost:8000/ws/realtime ↔ OpenAI Realtime API

Phase 2 scope: ECHO MODE only — system prompt is a simple repeat-back instruction.
Phase 3 will replace `INSTRUCTIONS` and add the 8 voice tools (create_order etc.).

Audio format: g711_ulaw 8 kHz mono — Twilio native, OpenAI native. Zero
transcoding both directions. (양방향 변환 없음 — 통과 패스스루)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Form, Request, WebSocket
from fastapi.responses import Response

import httpx
from openai import AsyncOpenAI

from app.adapters.twilio.sms import send_reservation_confirmation
from app.api.voice_websocket import (
    _GREETING_PROMPT,
    _build_pending_reservation_email_payload,
    build_system_prompt,
)
from app.core.config import settings
from app.services.bridge import flows as bridge_flows
from app.services.bridge.pay_link_email import send_pay_link_email
from app.services.bridge.pay_link_sms import send_pay_link
from app.services.bridge.reservation_email import send_reservation_email
from app.skills.menu.allergen import (
    ALLERGEN_LOOKUP_TOOL_DEF,
    allergen_lookup,
)
from app.skills.order.order import (
    ALLERGEN_SCRIPT_BY_HINT,
    CANCEL_ORDER_SCRIPT_BY_HINT,
    CANCEL_ORDER_TOOL_DEF,
    CANCEL_RESERVATION_SCRIPT_BY_HINT,
    MODIFY_ORDER_SCRIPT_BY_HINT,
    MODIFY_ORDER_TOOL_DEF,
    MODIFY_RESERVATION_SCRIPT_BY_HINT,
    ORDER_SCRIPT_BY_HINT,
    ORDER_TOOL_DEF,
    RECALL_ORDER_TOOL_DEF,
    render_recall_message,
)
from app.skills.scheduler.reservation import (
    CANCEL_RESERVATION_TOOL_DEF,
    MODIFY_RESERVATION_TOOL_DEF,
    RESERVATION_TOOL_DEF,
    format_date_human,
    format_time_12h,
    normalize_phone_us,
)

log = logging.getLogger(__name__)

# ── Supabase REST (mirror of voice_websocket._REST) ──────────────────────────
_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Phase 3a — single-store pilot: JM Cafe (PDX). Phase 7 multi-store rollout
# will replace this with a phone_number → store_id mapping.
# (Phase 3a — JM Cafe 단일 매장 하드코드. Phase 7에서 매핑 테이블로 교체)
JM_CAFE_STORE_ID = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"


# ── Tool schema conversion (Gemini function_declarations → OpenAI tools) ────
# Both formats are JSON-Schema-shaped — only the wrapper differs.
# (Gemini wrapper {"function_declarations": [...]} → OpenAI flat tool dict)

def _gemini_to_openai_tool(gemini_def: dict) -> dict:
    """Convert one Gemini-style tool_def into one OpenAI Realtime `tool` dict."""
    decl = gemini_def["function_declarations"][0]
    return {
        "type": "function",
        "name": decl["name"],
        "description": decl["description"],
        "parameters": decl.get("parameters", {"type": "object", "properties": {}}),
    }


# 8 voice tools — Phase 2-C.B6 set (mirrors voice_websocket.py tool registry).
# (8개 voice tool — 기존 Retell 핸들러와 동일 목록)
_GEMINI_TOOL_DEFS = [
    ORDER_TOOL_DEF,
    MODIFY_ORDER_TOOL_DEF,
    CANCEL_ORDER_TOOL_DEF,
    RESERVATION_TOOL_DEF,
    MODIFY_RESERVATION_TOOL_DEF,
    CANCEL_RESERVATION_TOOL_DEF,
    ALLERGEN_LOOKUP_TOOL_DEF,
    RECALL_ORDER_TOOL_DEF,
]
OPENAI_REALTIME_TOOLS = [_gemini_to_openai_tool(t) for t in _GEMINI_TOOL_DEFS]


# ── Tool dispatcher (OpenAI function_call → bridge_flows) ────────────────────
# Mirrors the dispatcher branches in voice_websocket.py:1410-2102 but stripped
# to the essentials: parse args, call the right bridge_flows function, return
# a string output that OpenAI feeds back into the conversation.
# (voice_websocket의 거대한 dispatcher를 본질만 추려 — args parse + 호출 + 결과 string 리턴)

async def _dispatch_tool_call(
    *,
    tool_name:         str,
    tool_args:         dict,
    store_id:          str,
    store_name:        str,
    caller_phone_e164: str,
    session_state:     dict,
) -> dict:
    """Execute one tool call and return a result dict suitable for serialization
    back to OpenAI as the `output` of a function_call_output item.

    Mirrors the routing logic in voice_websocket.py without the AUTO-FIRE
    gate, recital dedup, and modify-cooldown layers — those are Retell-specific
    timing workarounds. Realtime's native VAD + barge-in handle that pathway.
    (Retell 전용 timing 가드는 생략 — Realtime VAD가 동등 기능 제공)
    """
    # caller_phone_e164 is the carrier-authenticated server source of truth.
    # Override any LLM-provided customer_phone for create_order / make_reservation.
    # (voice_websocket.py:1484 mirror)
    if tool_name in ("create_order", "make_reservation") and caller_phone_e164:
        tool_args["customer_phone"] = caller_phone_e164

    if tool_name == "create_order":
        result = await bridge_flows.create_order(
            store_id    = store_id,
            args        = tool_args,
            call_log_id = None,
        )
        # Snapshot for recall_order
        if result.get("success"):
            session_state["last_order_items"] = result.get("items") or []
            session_state["last_order_total"] = int(result.get("total_cents") or 0)
        # Pick lane-aware customer-facing line
        hint = result.get("ai_script_hint") or ("rejected" if not result.get("success") else "pay_first")
        result["message"] = ORDER_SCRIPT_BY_HINT.get(hint, result.get("message", ""))

        # Phase 4 — fire-and-forget pay link SMS + email (mirror voice_websocket:1672-1716)
        # (멱등 재시도/실패 시 둘 다 skip — voice_websocket 패턴 그대로)
        if result.get("success") and not result.get("idempotent"):
            tx_id       = str(result.get("transaction_id") or "")
            lane_str    = str(result.get("lane") or "pay_first")
            total_cents = int(result.get("total_cents") or 0)
            items_for_email = result.get("items") or []
            try:
                asyncio.create_task(send_pay_link(
                    to             = tool_args.get("customer_phone", "") or caller_phone_e164,
                    store_name     = store_name or "the restaurant",
                    total_cents    = total_cents,
                    transaction_id = tx_id,
                    lane           = lane_str,
                ))
                _dbg(f"[tool] PAY LINK SMS queued tx={tx_id} lane={lane_str}")
            except Exception as exc:
                _dbg(f"[tool] PAY LINK SMS dispatch error: {exc}")
            customer_email = (tool_args.get("customer_email") or "").strip()
            if customer_email:
                try:
                    asyncio.create_task(send_pay_link_email(
                        to              = customer_email,
                        customer_name   = tool_args.get("customer_name", ""),
                        store_name      = store_name or "the restaurant",
                        total_cents     = total_cents,
                        items           = items_for_email,
                        transaction_id  = tx_id,
                        lane            = lane_str,
                    ))
                    _dbg(f"[tool] PAY LINK EMAIL queued tx={tx_id} to={customer_email}")
                except Exception as exc:
                    _dbg(f"[tool] PAY LINK EMAIL dispatch error: {exc}")
            else:
                _dbg(f"[tool] PAY LINK EMAIL skipped tx={tx_id} — no customer_email in tool_args")
        return result

    if tool_name == "modify_order":
        result = await bridge_flows.modify_order(
            store_id          = store_id,
            args              = tool_args,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = None,
        )
        if result.get("success"):
            session_state["last_order_items"] = result.get("items") or session_state.get("last_order_items") or []
            session_state["last_order_total"] = int(result.get("total_cents") or session_state.get("last_order_total") or 0)
        hint = result.get("ai_script_hint") or "modify_noop"
        result["message"] = MODIFY_ORDER_SCRIPT_BY_HINT.get(hint, result.get("message", ""))
        return result

    if tool_name == "cancel_order":
        result = await bridge_flows.cancel_order(
            store_id          = store_id,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = None,
        )
        if result.get("success"):
            session_state["last_order_items"] = []
            session_state["last_order_total"] = 0
        hint = result.get("ai_script_hint") or "cancel_no_target"
        result["message"] = CANCEL_ORDER_SCRIPT_BY_HINT.get(hint, result.get("message", ""))
        return result

    if tool_name == "make_reservation":
        result = await bridge_flows.create_reservation(
            store_id      = store_id,
            args          = tool_args,
            call_log_id   = None,
            deposit_cents = 0,
        )
        if result.get("success"):
            # Phase 4 — fire-and-forget SMS confirmation (mirror voice_websocket:1571-1584)
            try:
                phone_e164 = normalize_phone_us(tool_args.get("customer_phone", "") or caller_phone_e164)
                asyncio.create_task(send_reservation_confirmation(
                    to            = phone_e164,
                    store_name    = store_name or "the restaurant",
                    customer_name = tool_args.get("customer_name", ""),
                    date_human    = format_date_human(tool_args.get("reservation_date", "")),
                    time_12h      = format_time_12h(tool_args.get("reservation_time", "")),
                    party_size    = int(tool_args.get("party_size", 0) or 0),
                ))
                _dbg(f"[tool] RES SMS queued to={phone_e164}")
            except Exception as exc:
                _dbg(f"[tool] RES SMS dispatch error: {exc}")
            # B4 — defer email to call-end (set pending payload).
            # (예약 이메일 deferred — 통화 종료 시 발송)
            try:
                pending = _build_pending_reservation_email_payload(
                    args            = tool_args,
                    reservation_id  = int(result.get("pos_object_id") or 0),
                    store_name      = store_name or "",
                    prior_payload   = session_state.get("pending_reservation_email"),
                )
                session_state["pending_reservation_email"] = pending
                _dbg(f"[tool] RES EMAIL pending set "
                     f"to={(pending or {}).get('to') or '(none)'}")
            except Exception as exc:
                _dbg(f"[tool] RES EMAIL pending error: {exc}")
        return result

    if tool_name == "modify_reservation":
        result = await bridge_flows.modify_reservation(
            store_id          = store_id,
            args              = tool_args,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = None,
        )
        hint = result.get("ai_script_hint") or "modify_reservation_noop"
        result["message"] = MODIFY_RESERVATION_SCRIPT_BY_HINT.get(hint, result.get("message", ""))
        # B4 — refresh pending email payload (carry-over rule for missing email)
        if result.get("success"):
            try:
                pending = _build_pending_reservation_email_payload(
                    args            = tool_args,
                    reservation_id  = int(result.get("pos_object_id") or 0),
                    store_name      = store_name or "",
                    prior_payload   = session_state.get("pending_reservation_email"),
                )
                session_state["pending_reservation_email"] = pending
                _dbg(f"[tool] RES EMAIL pending refreshed (modify) "
                     f"to={(pending or {}).get('to') or '(none)'}")
            except Exception as exc:
                _dbg(f"[tool] RES EMAIL pending error (modify): {exc}")
        return result

    if tool_name == "cancel_reservation":
        result = await bridge_flows.cancel_reservation(
            store_id          = store_id,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = None,
        )
        hint = result.get("ai_script_hint") or "cancel_reservation_no_target"
        result["message"] = CANCEL_RESERVATION_SCRIPT_BY_HINT.get(hint, result.get("message", ""))
        # B4 — wipe pending email so nothing fires on call end
        if result.get("success"):
            session_state["pending_reservation_email"] = None
            _dbg("[tool] RES EMAIL pending cleared (cancel)")
        return result

    if tool_name == "allergen_lookup":
        skill_result = await allergen_lookup(
            store_id        = store_id,
            menu_item_name  = tool_args.get("menu_item_name", ""),
            allergen        = tool_args.get("allergen", ""),
            dietary_tag     = tool_args.get("dietary_tag", ""),
        )
        hint = skill_result.get("ai_script_hint", "item_not_found")
        template = ALLERGEN_SCRIPT_BY_HINT.get(hint, "Let me transfer you to a manager.")
        tag_human = (skill_result.get("queried_dietary") or "").replace("_", "-")
        try:
            script = template.format(
                item       = skill_result.get("matched_name", "that item"),
                allergen   = skill_result.get("queried_allergen", ""),
                allergens  = ", ".join(skill_result.get("allergens") or []) or "no listed allergens",
                tag        = tag_human,
            )
        except (KeyError, IndexError):
            script = template
        return {
            "success":      bool(skill_result.get("success")),
            "matched_name": skill_result.get("matched_name"),
            "allergens":    skill_result.get("allergens"),
            "dietary_tags": skill_result.get("dietary_tags"),
            "reason":       hint,
            "message":      script,
        }

    if tool_name == "recall_order":
        msg, reason = render_recall_message(
            items       = session_state.get("last_order_items") or [],
            total_cents = int(session_state.get("last_order_total") or 0),
        )
        return {
            "success": True,
            "reason":  reason,
            "message": msg,
        }

    return {
        "success": False,
        "error":   f"unsupported tool: {tool_name}",
    }


async def _load_store_by_id(store_id: str) -> dict | None:
    """Fetch store row from Supabase by primary key.
    (Supabase에서 id로 매장 조회 — voice_websocket._load_store_by_agent와 동등 패턴)
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "id": f"eq.{store_id}",
                "select": "id,name,retell_agent_id,system_prompt,temporary_prompt,"
                          "business_hours,custom_knowledge,menu_cache,is_active",
                "limit": "1",
            },
        )
    if resp.status_code != 200:
        return None
    rows = resp.json()
    return rows[0] if rows else None

# Dedicated debug file — bypasses any uvicorn logger config issues.
# (uvicorn 로거 설정 우회 — 직접 파일에 기록)
import sys

_DEBUG_FILE = "/tmp/realtime_debug.log"

def _dbg(msg: str) -> None:
    """Print to stderr (unbuffered) AND append to debug file."""
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        with open(_DEBUG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


router = APIRouter()

# ── Config (read from settings — pydantic-settings handles .env loading) ─────
# Phase 2 default mini (cost). Phase 5+ flips to gpt-realtime-1.5 via .env.
# (Phase 2는 비용 최소화 위해 mini, Phase 5+에서 1.5로 .env 변경)
MODEL = settings.openai_realtime_model
VOICE = settings.openai_realtime_voice

# Phase 2 echo instructions — replaced in Phase 3 with build_system_prompt(store)
INSTRUCTIONS_PHASE2_ECHO = (
    "You are testing a phone-call audio bridge. When the caller speaks, "
    "briefly repeat back what they said in ONE short sentence starting with "
    "'You said:'. Keep it under 12 words. If they say goodbye, wish them a "
    "great day."
)

# Public WebSocket URL — must match the ngrok / prod domain Twilio reaches.
# (Twilio가 도달할 수 있는 공개 URL — ngrok 또는 prod 도메인)
PUBLIC_BASE = os.environ.get(
    "PUBLIC_BASE_URL", "https://bipectinate-cheerily-akilah.ngrok-free.dev"
)
# Convert https://... → wss://...
WS_BASE = PUBLIC_BASE.replace("https://", "wss://", 1).replace("http://", "ws://", 1)


# ── 1) TwiML inbound endpoint ────────────────────────────────────────────────
# Twilio hits this on every incoming call. Returns TwiML that opens a Media
# Streams WebSocket back to our backend for full-duplex audio.
# (Twilio가 인바운드 콜마다 호출 — Media Streams WebSocket 양방향 audio)

@router.post("/twilio/voice/inbound")
async def twilio_voice_inbound(
    request: Request,
    From: str = Form(""),
    To: str = Form(""),
    CallSid: str = Form(""),
) -> Response:
    """Return TwiML <Connect><Stream> pointing to our /ws/realtime WebSocket.

    Twilio submits caller info as form fields (From, To, CallSid). We pass
    these as <Parameter> so the WebSocket handler can identify the caller
    without an extra REST round-trip.
    (Twilio가 form으로 caller 정보 전달 — Parameter로 WebSocket에 forward)
    """
    log.info("[realtime] inbound call CallSid=%s From=%s To=%s", CallSid, From, To)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{WS_BASE}/ws/realtime">
      <Parameter name="caller_phone" value="{From}"/>
      <Parameter name="called_number" value="{To}"/>
      <Parameter name="call_sid" value="{CallSid}"/>
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# ── 2) WebSocket bridge ──────────────────────────────────────────────────────
# Twilio Media Streams protocol:
#   inbound frames: { "event": "connected"|"start"|"media"|"stop"|"mark", ... }
#   outbound frames (we send): { "event": "media"|"clear"|"mark", "streamSid": ..., "media": {"payload": <base64>} }
# (Twilio Media Streams 프로토콜 — JSON frame, base64 g711_ulaw payload)

@router.websocket("/ws/realtime")
async def realtime_bridge(ws: WebSocket) -> None:
    """Bidirectional bridge: Twilio Media Streams ↔ OpenAI Realtime."""
    _dbg(f"[realtime] HANDLER ENTERED — client={ws.client}")
    try:
        await ws.accept()
    except Exception as exc:
        _dbg(f"[realtime] ws.accept() FAILED: {type(exc).__name__}: {exc}")
        return
    t_accept = time.monotonic()
    _dbg(f"[realtime] WS accepted from {ws.client.host if ws.client else '?'}")

    stream_sid: str = ""
    call_sid: str = ""
    caller_phone: str = ""
    called_number: str = ""

    # 1) Wait for Twilio "start" event with stream metadata
    try:
        while True:
            raw = await ws.receive_text()
            _dbg(f"[realtime] RX frame ({len(raw)} bytes)")
            data = json.loads(raw)
            event = data.get("event")
            _dbg(f"[realtime] RX event={event}")
            if event == "connected":
                _dbg(f"[realtime] connected protocol={data.get('protocol')}")
                continue
            if event == "start":
                start = data.get("start", {})
                stream_sid = start.get("streamSid", "")
                call_sid = start.get("callSid", "")
                params = start.get("customParameters", {}) or {}
                caller_phone = params.get("caller_phone", "")
                called_number = params.get("called_number", "")
                _dbg(f"[realtime] start streamSid={stream_sid} callSid={call_sid} "
                     f"from={caller_phone} to={called_number}")
                break
            _dbg(f"[realtime] unexpected pre-start event: {event}")
    except Exception as exc:
        _dbg(f"[realtime] receive failed: {type(exc).__name__}: {exc}")
        try:
            await ws.close()
        except Exception:
            pass
        return

    # 2) Load store + build system prompt (Phase 3a)
    # (Phase 3a — 매장 row 조회 + 시스템 프롬프트 빌드)
    store = await _load_store_by_id(JM_CAFE_STORE_ID)
    if not store:
        _dbg(f"[realtime] ❌ store not found id={JM_CAFE_STORE_ID}")
        await ws.close()
        return
    store_id = store["id"]
    store_name = store.get("name") or "the restaurant"
    instructions = build_system_prompt(store)
    _dbg(f"[realtime] store loaded id={store_id} name={store_name!r} "
         f"prompt_len={len(instructions)}")

    # 3) Open OpenAI Realtime session
    # (OpenAI Realtime 세션 오픈 — g711_ulaw 양방향 + server VAD)
    if not settings.openai_api_key:
        _dbg("[realtime] ❌ OPENAI_API_KEY missing — cannot open session")
        await ws.close()
        return
    _dbg(f"[realtime] opening OpenAI session model={MODEL} voice={VOICE}")
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        async with client.beta.realtime.connect(model=MODEL) as oai:
            _dbg(f"[realtime] OpenAI WS connected, sending session.update")
            await oai.session.update(
                session={
                    "modalities": ["audio", "text"],
                    "voice": VOICE,
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "instructions": instructions,
                    "tools": OPENAI_REALTIME_TOOLS,
                    "tool_choice": "auto",
                    # Semantic VAD with low eagerness — the model decides when
                    # the caller is truly done speaking (semantic boundary), not
                    # a fixed silence timer. Drops false-positive triggers from
                    # mid-utterance pauses + background noise. Fixes 75% silent
                    # response.done rate observed across CA82876bb / CAe0f29142.
                    # (Phase 4 — semantic_vad eagerness=low: 자연스러운 대화 pause
                    #  허용, 백그라운드 노이즈로 인한 false trigger 감소)
                    "turn_detection": {
                        "type": "semantic_vad",
                        "eagerness": "low",
                        "create_response":    True,   # auto-fire response.create on speech_stopped
                        "interrupt_response": True,   # cancel ongoing audio on barge-in
                    },
                    # Enable user audio transcription so debug log shows what
                    # the model heard. Critical for diagnosing tool-not-firing
                    # cases (e.g. CA79c80b2a turn-7 'yes' that didn't trigger
                    # make_reservation) and language-detection issues.
                    # (사용자 발화 transcript을 log에 기록 — tool 미발사 디버깅)
                    "input_audio_transcription": {
                        "model": "gpt-4o-mini-transcribe",
                    },
                }
            )
            _dbg(f"[realtime] ✓ session.update sent (g711_ulaw, "
                 f"system_prompt={len(instructions)}B, "
                 f"tools={len(OPENAI_REALTIME_TOOLS)}, "
                 f"vad=semantic_vad/low + whisper transcription)")

            # Phase 4 — trigger initial agent greeting BEFORE caller speaks.
            # OpenAI Realtime with server VAD waits for input by default; we
            # must explicitly request the first response with greeting
            # instructions. response.create's `instructions` field OVERRIDES
            # session-level instructions for that turn — so the greeting
            # prompt must embed the actual store_name (otherwise the model
            # has no JM Cafe context and hallucinates a generic café name,
            # observed live in call CA00e5f988 turn=0 → "Sunrise Café").
            # (response.create의 instructions는 session prompt를 override —
            #  store_name을 직접 주입해야 환각 방지)
            store_name_safe = (store_name or "").strip() or "the restaurant"
            greeting_instruction = (
                f"The call just connected. The customer has not spoken yet. "
                f"You are Aria for {store_name_safe}. Greet in ONE short "
                f"English sentence: say \"{store_name_safe}, how can I help?\" "
                f"or a near-equivalent. Maximum 10 words. No name introduction, "
                f"no markdown, no emojis."
            )
            _dbg(f"[realtime] greeting prompt: {greeting_instruction!r}")
            try:
                await oai.response.create(response={
                    "modalities":   ["audio", "text"],
                    "instructions": greeting_instruction,
                })
                _dbg("[realtime] ✓ initial greeting response.create sent")
            except Exception as exc:
                _dbg(f"[realtime] greeting response.create failed: {exc}")

            # Stats counters
            stats: dict[str, Any] = {
                "twilio_media_in": 0,
                "openai_audio_out": 0,
                "user_turns": 0,
                "first_response_ttft_ms": None,
                "speech_stop_ts": None,
            }

            # Per-call state for tool snapshots (recall_order / cancel recital
            # / B4 deferred reservation email).
            # (통화 중 스냅샷 — recall_order, cancel recital, 예약 이메일 deferred)
            session_state: dict[str, Any] = {
                "last_order_items": [],
                "last_order_total": 0,
                "pending_reservation_email": None,
            }

            async def twilio_to_openai() -> None:
                """Receive Twilio media frames → forward to OpenAI input buffer."""
                _dbg("[twilio→oai] pump started")
                last_count_log = 0
                try:
                    while True:
                        raw = await ws.receive_text()
                        data = json.loads(raw)
                        event = data.get("event")
                        if event == "media":
                            payload = data.get("media", {}).get("payload", "")
                            if payload:
                                # μ-law 8 kHz base64 — pass through unchanged
                                await oai.input_audio_buffer.append(audio=payload)
                                stats["twilio_media_in"] += 1
                                # First frame + every 100 frames
                                cnt = stats["twilio_media_in"]
                                if cnt == 1 or cnt - last_count_log >= 100:
                                    _dbg(f"[twilio→oai] forwarded {cnt} media frames "
                                         f"(payload {len(payload)}B)")
                                    last_count_log = cnt
                        elif event == "stop":
                            _dbg("[twilio→oai] Twilio stop event — caller hung up")
                            return
                        elif event == "mark":
                            _dbg(f"[twilio→oai] mark echo: {data.get('mark', {})}")
                        else:
                            _dbg(f"[twilio→oai] unknown event: {event}")
                except Exception as exc:
                    import traceback
                    _dbg(f"[twilio→oai] EXIT: {type(exc).__name__}: {exc}")
                    _dbg(f"[twilio→oai] traceback:\n{traceback.format_exc()}")

            async def openai_to_twilio() -> None:
                """Receive OpenAI events → forward audio to Twilio media frames."""
                _dbg("[oai→twilio] pump started")
                event_count = 0
                event_types_seen: dict[str, int] = {}
                try:
                    async for event in oai:
                        etype = event.type
                        event_count += 1
                        event_types_seen[etype] = event_types_seen.get(etype, 0) + 1
                        # First 5 events explicit log
                        if event_count <= 5:
                            _dbg(f"[oai→twilio] event #{event_count} type={etype}")

                        if etype == "input_audio_buffer.speech_started":
                            # Caller barge-in: clear Twilio's outbound buffer to
                            # stop currently-playing assistant audio. Without
                            # this, customer hears tail of agent voice for
                            # ~200-500ms after they start speaking.
                            # (사용자 끼어들기 — Twilio 출력 버퍼 즉시 비움)
                            stats["user_turns"] += 1
                            stats["speech_stop_ts"] = None
                            stats["first_response_ttft_ms"] = None
                            try:
                                await ws.send_text(json.dumps({
                                    "event": "clear",
                                    "streamSid": stream_sid,
                                }))
                            except Exception:
                                pass
                            _dbg("[oai→twilio] caller speech_started — sent clear")

                        elif etype == "input_audio_buffer.speech_stopped":
                            stats["speech_stop_ts"] = time.monotonic()
                            _dbg("[oai→twilio] caller speech_stopped")

                        elif etype == "response.audio.delta":
                            # First-byte TTFT measurement
                            if (
                                stats["speech_stop_ts"] is not None
                                and stats["first_response_ttft_ms"] is None
                            ):
                                ttft = (time.monotonic() - stats["speech_stop_ts"]) * 1000
                                stats["first_response_ttft_ms"] = ttft
                                _dbg(f"[oai→twilio] turn={stats['user_turns']} TTFT={ttft:.0f}ms")
                            # Forward audio delta as Twilio media frame
                            await ws.send_text(json.dumps({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": event.delta},
                            }))
                            stats["openai_audio_out"] += 1

                        elif etype == "response.audio_transcript.done":
                            _dbg(f"[oai→twilio] turn={stats['user_turns']} agent: "
                                 f"{getattr(event, 'transcript', '')!r}")

                        elif etype == "conversation.item.input_audio_transcription.completed":
                            _dbg(f"[oai→twilio] turn={stats['user_turns']} caller: "
                                 f"{getattr(event, 'transcript', '')!r}")

                        elif etype == "response.function_call_arguments.done":
                            # Tool dispatch — model has finished emitting args.
                            # event has: name, call_id, arguments (JSON str).
                            # (모델이 tool 인자 전송 완료 — dispatch 시작)
                            tool_name = getattr(event, "name", "")
                            call_id = getattr(event, "call_id", "")
                            args_str = getattr(event, "arguments", "") or "{}"
                            try:
                                tool_args = json.loads(args_str)
                            except Exception as exc:
                                _dbg(f"[tool] ❌ args parse fail name={tool_name} "
                                     f"args={args_str!r} err={exc}")
                                tool_args = {}
                            _dbg(f"[tool] CALL name={tool_name} call_id={call_id} "
                                 f"args_keys={list(tool_args.keys())}")
                            t_tool_start = time.monotonic()
                            try:
                                tool_result = await _dispatch_tool_call(
                                    tool_name         = tool_name,
                                    tool_args         = tool_args,
                                    store_id          = store_id,
                                    store_name        = store_name,
                                    caller_phone_e164 = caller_phone,
                                    session_state     = session_state,
                                )
                            except Exception as exc:
                                import traceback
                                _dbg(f"[tool] ❌ dispatch threw: {type(exc).__name__}: {exc}")
                                _dbg(traceback.format_exc())
                                tool_result = {
                                    "success": False,
                                    "error":   f"internal: {type(exc).__name__}",
                                    "message": "Sorry, something went wrong on our end.",
                                }
                            tool_ms = (time.monotonic() - t_tool_start) * 1000
                            _dbg(f"[tool] DONE name={tool_name} ok={tool_result.get('success')} "
                                 f"reason={tool_result.get('reason')} ms={tool_ms:.0f}")
                            # Send result back to OpenAI as function_call_output.
                            # Output must be a string — we serialize the dict.
                            # (결과를 string으로 직렬화 — OpenAI Realtime 사양)
                            try:
                                await oai.conversation.item.create(item={
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(tool_result),
                                })
                                # Trigger model to consume the output and reply
                                await oai.response.create()
                            except Exception as exc:
                                _dbg(f"[tool] ❌ failed to return result: "
                                     f"{type(exc).__name__}: {exc}")

                        elif etype == "response.done":
                            _dbg(f"[oai→twilio] response.done turn={stats['user_turns']}")

                        elif etype == "error":
                            err = getattr(event, "error", None)
                            _dbg(f"[oai→twilio] ❌ OpenAI ERROR: "
                                 f"type={getattr(err, 'type', '?')} "
                                 f"code={getattr(err, 'code', '?')} "
                                 f"msg={getattr(err, 'message', '?')}")
                except Exception as exc:
                    import traceback
                    _dbg(f"[oai→twilio] EXIT: {type(exc).__name__}: {exc}")
                    _dbg(f"[oai→twilio] events seen: {event_types_seen}")
                    _dbg(f"[oai→twilio] traceback:\n{traceback.format_exc()}")

            _dbg("[realtime] starting bidirectional pumps")
            try:
                # FIRST_COMPLETED + cancel pending — when Twilio stop event
                # makes twilio_to_openai return, we must cancel the OpenAI
                # event loop (which would otherwise wait indefinitely for
                # next event). Without this, asyncio.gather hangs and the
                # finally block never fires the deferred reservation email.
                # (한쪽 종료 시 다른 쪽 즉시 cancel — finally 블록 보장)
                t_twilio = asyncio.create_task(twilio_to_openai(), name="twilio_pump")
                t_openai = asyncio.create_task(openai_to_twilio(), name="openai_pump")
                done, pending = await asyncio.wait(
                    {t_twilio, t_openai},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                first_done_names = sorted(t.get_name() for t in done)
                _dbg(f"[realtime] first pump exit: {first_done_names} — cancelling rest")
                for task in pending:
                    task.cancel()
                # Give cancellations a moment to propagate cleanly
                await asyncio.gather(*pending, return_exceptions=True)
            finally:
                duration = time.monotonic() - t_accept
                _dbg(
                    f"[realtime] call done — duration={duration:.1f}s "
                    f"callSid={call_sid} twilio_in={stats['twilio_media_in']} "
                    f"openai_out={stats['openai_audio_out']} turns={stats['user_turns']}"
                )
                # B4 — fire deferred reservation email if payload pending
                # (예약 이메일 deferred-fire — make/modify로 set, cancel로 clear)
                pending = session_state.get("pending_reservation_email")
                if pending and isinstance(pending, dict) and pending.get("to"):
                    try:
                        # Synchronous fire — handler is exiting, no audio race
                        await send_reservation_email(**pending)
                        _dbg(f"[realtime] RES EMAIL fired to={pending['to']}")
                    except Exception as exc:
                        _dbg(f"[realtime] RES EMAIL fire error: {exc}")
    except Exception as exc:
        import traceback
        _dbg(f"[realtime] ❌ OpenAI session error: {type(exc).__name__}: {exc}")
        _dbg(f"[realtime] traceback:\n{traceback.format_exc()}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass
        _dbg("[realtime] handler returning")
