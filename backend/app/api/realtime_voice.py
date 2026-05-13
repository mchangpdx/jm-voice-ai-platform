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
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Form, Request, WebSocket
from fastapi.responses import Response

import httpx
from openai import AsyncOpenAI

from app.adapters.twilio.sms import send_reservation_confirmation
from app.api.voice_websocket import (
    _GREETING_PROMPT,
    _SEVERE_ALLERGY_RE,
    _build_pending_reservation_email_payload,
    _has_severe_allergy_signal,
    build_system_prompt,
)
from app.core.config import settings
from app.services.bridge import flows as bridge_flows
from app.services.bridge.pay_link_email import send_pay_link_email
from app.services.bridge.pay_link_sms import send_pay_link
from app.services.bridge.reservation_email import send_reservation_email
from app.services.bridge.transactions import update_call_metrics
from app.services.crm import customer_lookup, update_recent_customer_email
from app.services.handoff.manager_alert import send_tier3_alert
from app.services.menu.match import build_modifier_index_from_groups
from app.services.menu.modifiers import (
    fetch_modifier_groups,
    format_modifier_block,
)
from app.services.voice.recital import (
    extract_email_from_recital,
    reconcile_email_with_recital,
)
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
from app.skills.transaction.transfer import (
    TRANSFER_TO_MANAGER_TOOL_DEF,
    transfer_to_manager,
)

log = logging.getLogger(__name__)

# ── Supabase REST (mirror of voice_websocket._REST) ──────────────────────────
_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Phase 3a → Pizza pilot (2026-05-11) — Twilio inbound `To` (called_number)
# resolves to a store_id via this map. Unmapped numbers fall back to JM Cafe
# (preserves pre-pilot behavior). To onboard a new store, append one row.
# (called_number → store_id 매핑 — 미등록 번호는 JM Cafe로 fallback)
JM_CAFE_STORE_ID = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
JM_PIZZA_STORE_ID = "7411aaee-8b50-49b0-bc7b-56627932b99a"

PHONE_TO_STORE: dict[str, str] = {
    "+15039941265": JM_CAFE_STORE_ID,   # JM Cafe (PDX) — original pilot
    "+19714447137": JM_PIZZA_STORE_ID,  # JM Pizza (PDX) — 2026-05-11 pilot
}


def _resolve_store_id(called_number: str | None) -> str:
    """Map Twilio `To` (called_number) → store_id. Defaults to JM Cafe."""
    if called_number and called_number in PHONE_TO_STORE:
        return PHONE_TO_STORE[called_number]
    return JM_CAFE_STORE_ID


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


# 9 voice tools — Phase 2-C.B6 set + transfer_to_manager (2026-05-12 fix).
# transfer_to_manager was missing — system_prompt told the LLM to call it on
# severe-allergy events but it wasn't in the registry, so dispatcher returned
# success:False / ms=0 (live trigger: CAaaeedfd1372f9e383087689316038cc0
# turn=18). Adding it as the 9th tool unblocks the severe-allergy hand-off.
# (9개 voice tool — transfer_to_manager 추가 2026-05-12)
_GEMINI_TOOL_DEFS = [
    ORDER_TOOL_DEF,
    MODIFY_ORDER_TOOL_DEF,
    CANCEL_ORDER_TOOL_DEF,
    RESERVATION_TOOL_DEF,
    MODIFY_RESERVATION_TOOL_DEF,
    CANCEL_RESERVATION_TOOL_DEF,
    ALLERGEN_LOOKUP_TOOL_DEF,
    RECALL_ORDER_TOOL_DEF,
    TRANSFER_TO_MANAGER_TOOL_DEF,
]
OPENAI_REALTIME_TOOLS = [_gemini_to_openai_tool(t) for t in _GEMINI_TOOL_DEFS]


# ── call_logs persistence (P2 wire-up, 2026-05-10) ───────────────────────────
# Live trigger: Billy/Jason 2026-05-10 — bridge_transactions.call_log_id stayed
# NULL on every OpenAI Realtime tx because none of the 6 tool dispatch sites
# below passed a call_log_id, AND no call_logs row was inserted at WS start.
# That broke the analytics join the dashboard uses for per-call drill-downs.
#
# Both helpers are fire-and-forget: any failure is logged and swallowed, the
# voice path never blocks on this. INSERT happens once on the Twilio `start`
# event so the row exists before any tool fires; UPDATE happens in the WS
# `finally` block alongside the CRM call_end metrics dispatch.
# (P2 — call_logs INSERT/UPDATE 헬퍼. 실패는 통화 흐름과 격리)

async def _insert_call_log_row(
    *,
    call_id:        str,
    store_id:       str,
    customer_phone: Optional[str],
    start_iso:      str,
) -> bool:
    """INSERT one call_logs row at WS start. Idempotent on call_id duplicate.
    (start 이벤트 직후 1회 호출 — 중복 call_id는 ON CONFLICT로 skip)
    """
    if not call_id or not store_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"{_REST}/call_logs",
                headers={
                    **_SUPABASE_HEADERS,
                    # Idempotent on PK collision (e.g. Twilio reconnect mid-call).
                    # PostgREST: Prefer header for ON CONFLICT do nothing semantics.
                    "Prefer": "return=minimal,resolution=ignore-duplicates",
                },
                json={
                    "call_id":        call_id,
                    "store_id":       store_id,
                    "start_time":     start_iso,
                    "customer_phone": customer_phone or None,
                    "call_status":    "in_progress",
                },
            )
            if resp.status_code in (200, 201, 204):
                return True
            log.warning(
                "[call_log] insert non-2xx call_id=%s status=%d body=%s",
                call_id, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as exc:
        log.warning("[call_log] insert error call_id=%s err=%s",
                    call_id, type(exc).__name__)
        return False


async def _update_call_log_row(
    *,
    call_id:    str,
    duration_s: int,
    status:     str = "Successful",
    transcript: str | None = None,
) -> bool:
    """UPDATE duration + final status on the call_logs row at call_end.
    Optionally persists the full turn-by-turn transcript JSON string.
    (call_end 시점 1회 — 통화 길이와 status, 그리고 transcript JSON 저장)
    """
    if not call_id:
        return False
    payload: dict[str, Any] = {
        "duration":    duration_s,
        "call_status": status,
    }
    if transcript is not None:
        payload["transcript"] = transcript
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.patch(
                f"{_REST}/call_logs",
                headers=_SUPABASE_HEADERS,
                params={"call_id": f"eq.{call_id}"},
                json=payload,
            )
            if resp.status_code in (200, 204):
                return True
            log.warning(
                "[call_log] update non-2xx call_id=%s status=%d body=%s",
                call_id, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as exc:
        log.warning("[call_log] update error call_id=%s err=%s",
                    call_id, type(exc).__name__)
        return False


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

    # Wave A.3 Plan E — server-side authoritative email reconciliation.
    # The bot's NATO recital ('C as in Charlie...') is what the customer
    # heard and confirmed with 'yes', so it is more trustworthy than the
    # LLM's separately-generated args.customer_email (which collapses
    # doubles, drops/reorders letters in 90%+ of live calls 2026-05-08).
    # Apply to every tool that takes customer_email so the persisted email
    # and the queued pay-link delivery both go to the verified address.
    # No-op when no NATO recital was made or when args already match.
    # (NATO recital이 args보다 권위 — 모든 email-bearing tool에 적용)
    if tool_name in ("create_order", "modify_order", "make_reservation",
                     "modify_reservation"):
        # Prefer the latched NATO-bearing agent text over last_assistant_text.
        # last_assistant_text gets overwritten on every turn — including the
        # order/reservation confirmation that typically follows the email
        # NATO recital — so reconcile would lose the NATO source by tool-fire
        # time. last_email_recital_text only updates when the agent text
        # actually contains a parseable NATO email, so it survives across
        # intervening turns. Live trigger 2026-05-08 CA47b6683b... — args
        # 'cym eet@gmail.com' (whitespace inserted by LLM) sailed past
        # reconcile because last_assistant_text was the order confirmation,
        # not the NATO recital that had already been spoken correctly.
        # (NATO recital이 후속 confirmation에 덮이지 않도록 별도 latch 우선)
        recital_text = (
            session_state.get("last_email_recital_text")
            or session_state.get("last_assistant_text")
        )
        reconciled = reconcile_email_with_recital(
            args_email          = tool_args.get("customer_email"),
            last_assistant_text = recital_text,
        )
        if reconciled and reconciled != tool_args.get("customer_email"):
            _dbg(f"[tool] EMAIL RECONCILED args={tool_args.get('customer_email')!r} "
                 f"-> recital={reconciled!r}")
            tool_args["customer_email"] = reconciled

    if tool_name == "create_order":
        result = await bridge_flows.create_order(
            store_id       = store_id,
            args           = tool_args,
            call_log_id    = session_state.get("call_log_id") or None,
            modifier_index = session_state.get("modifier_index"),
        )
        # Snapshot for recall_order
        if result.get("success"):
            session_state["last_order_items"] = result.get("items") or []
            session_state["last_order_total"] = int(result.get("total_cents") or 0)
            # CRM Wave 1 — latch the most recent successful tx so the call_end
            # UPDATE (in the WS finally block) writes call_duration_ms +
            # crm_* flags to the right row. Last-write-wins if there are
            # multiple create_orders in one call (rare but legal).
            # (CRM Wave 1 — call_end UPDATE 대상 tx_id 래치)
            #
            # FIX-C (2026-05-09): skip the latch when this branch is an
            # idempotent re-hit — the tx already belongs to a PRIOR call
            # within the 5-min dedup window (flows.py:_find_recent_duplicate).
            # Latching here would let call_end overwrite the prior call's
            # AHT + CRM flags. Live regression caught 2026-05-09 with two
            # tx_id pairs reused across redials (f4394c1c, 44cca8e7). The
            # in-call snapshots above (last_order_items / last_order_total)
            # are still required for recall_order / modify_order follow-ups
            # in THIS call so they stay outside the guard.
            # (Idempotent hit는 prior call의 tx — call_end UPDATE 대상에서 제외)
            tx_id_latched = str(result.get("transaction_id") or "")
            if tx_id_latched and not result.get("idempotent"):
                session_state["active_tx_id"] = tx_id_latched
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
            call_log_id       = session_state.get("call_log_id") or None,
            modifier_index    = session_state.get("modifier_index"),
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
            call_log_id       = session_state.get("call_log_id") or None,
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
            call_log_id   = session_state.get("call_log_id") or None,
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
            call_log_id       = session_state.get("call_log_id") or None,
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
            call_log_id       = session_state.get("call_log_id") or None,
        )
        hint = result.get("ai_script_hint") or "cancel_reservation_no_target"
        result["message"] = CANCEL_RESERVATION_SCRIPT_BY_HINT.get(hint, result.get("message", ""))
        # B4 — wipe pending email so nothing fires on call end
        if result.get("success"):
            session_state["pending_reservation_email"] = None
            _dbg("[tool] RES EMAIL pending cleared (cancel)")
        return result

    if tool_name == "allergen_lookup":
        # Phase 7-A.B — pass selected_modifiers through so allergen profile is
        # composed from base + modifier deltas (oat milk → +gluten +wheat -dairy).
        # The LLM is instructed to send [] when no modifiers were spoken.
        # (modifier 인자 통과 — base allergens 단독 lookup이 아니라 dynamic 계산)
        sm = tool_args.get("selected_modifiers") or []
        if not isinstance(sm, list):
            sm = []
        skill_result = await allergen_lookup(
            store_id           = store_id,
            menu_item_name     = tool_args.get("menu_item_name", ""),
            allergen           = tool_args.get("allergen", ""),
            dietary_tag        = tool_args.get("dietary_tag", ""),
            selected_modifiers = sm,
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

    if tool_name == "transfer_to_manager":
        # Pull manager phone from the store row's custom_knowledge / system_prompt
        # if present; fall back to the founder line we ship with every pilot
        # store. (operator can override per-store later via a `manager_phone`
        # column if/when we add one.)
        # (매장별 manager phone — 기본값 +1-503-707-9566)
        store_row = session_state.get("store_row") or {}
        manager_phone = (
            store_row.get("manager_phone")
            or "+15037079566"
        )
        result = await transfer_to_manager(
            store_id      = store_id,
            args          = tool_args,
            manager_phone = manager_phone,
        )
        # The result.message is the script the LLM should read; we keep the
        # default ai_script_hint='manager_handoff' so the dispatcher does not
        # rewrite the message via ORDER_SCRIPT_BY_HINT.
        # (manager_handoff hint — dispatcher 메시지 덮어쓰기 회피)
        return result

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

# CRM Wave 1 — heuristic detector for "the usual" offer in agent transcript.
# Multilingual coverage (en/ko/ja/zh/es) so usual_offered DB column stays
# accurate when the agent matches the caller's language. English pattern
# remains word-bounded so substrings ("usually", "ritual") don't false-
# positive. CJK/Spanish patterns rely on lexical specificity (these phrases
# are stable order-flow expressions, not common filler words).
# Live regression caught 2026-05-09 KO call (visits=29) where agent said
# "평소 드시던 20온스 뜨거운 오트밀크 카페라떼로 하실까요" but DB column
# stayed False because regex was English-only.
# (CRM Wave 1 — 5개 언어 "the usual" 감지. 영어는 word boundary, 그 외는 어휘 특이성)
_THE_USUAL_RE = re.compile(
    r"\bthe\s+usual\b"                       # English
    r"|평소(?:처럼|\s*드시던|\s*같이)?"        # Korean: 평소 / 평소처럼 / 평소 드시던 / 평소 같이
    r"|이전과\s*같이|똑같이"                  # Korean variants
    r"|いつもの|前回と同じ"                   # Japanese
    r"|老样子|和上次一样"                     # Chinese (Mandarin)
    r"|lo\s+de\s+siempre|lo\s+usual",        # Spanish
    re.IGNORECASE
)


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
    "PUBLIC_BASE_URL", "https://jmtechone.ngrok.app"
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

    # P2 fix (2026-05-10) — INSERT call_logs row at WS start so every
    # bridge_transactions.call_log_id can join back to the call. Fire-and-
    # forget — INSERT failure must NEVER block the voice path; we just
    # leave call_log_id empty and the tx rows continue as call_log_id=None
    # (existing behavior, pre-fix). Idempotent on call_id (Twilio reconnect).
    # (call_logs INSERT — 통화 시작 직후 1회, 실패 시 None 유지)
    # Resolve store_id from Twilio inbound number (PHONE_TO_STORE map).
    # (called_number 기반 매장 라우팅 — 미등록 시 JM Cafe로 fallback)
    resolved_store_id = _resolve_store_id(called_number)
    _dbg(f"[realtime] called_number={called_number} → store_id={resolved_store_id}")

    if call_sid:
        try:
            _start_iso = datetime.now(timezone.utc).isoformat()
            asyncio.create_task(_insert_call_log_row(
                call_id        = call_sid,
                store_id       = resolved_store_id,
                customer_phone = caller_phone or None,
                start_iso      = _start_iso,
            ))
            _dbg(f"[call_log] insert dispatched call_id={call_sid}")
        except Exception as exc:
            _dbg(f"[call_log] insert dispatch error: {exc}")

    # 2) Load store + build system prompt (Phase 3a)
    # (Phase 3a — 매장 row 조회 + 시스템 프롬프트 빌드)
    store = await _load_store_by_id(resolved_store_id)
    if not store:
        _dbg(f"[realtime] ❌ store not found id={resolved_store_id}")
        await ws.close()
        return
    store_id = store["id"]
    store_name = store.get("name") or "the restaurant"

    # Phase 7-A.B — load modifier groups + options for this store and pass them
    # into build_system_prompt as `modifier_section`. Without this block the LLM
    # sees only menu_cache (base items) and denies composite orders like "iced
    # oat latte" — see live trigger CA90b88e... 2026-05-07.
    # (Phase 7-A.B — modifier 사전 로드 + 시스템 프롬프트 주입)
    mod_group_count = 0
    # Wave A.3 — build the (group_code, option_code) → option index once at
    # session start so create_order / modify_order can skip their per-call
    # modifier_groups + modifier_options REST round-trip (~400-500ms saved).
    # session_state["modifier_index"] is the source of truth for the call;
    # legacy callers that pass None still get the lazy fetch path.
    # (세션 시작 시 modifier index 1회 빌드 → 매 tool 호출의 REST 우회)
    session_modifier_index: dict[tuple[str, str], dict[str, Any]] | None = None
    try:
        mod_groups = await fetch_modifier_groups(store_id)
        mod_group_count = len(mod_groups)
        store["modifier_section"] = format_modifier_block(mod_groups)
        session_modifier_index = build_modifier_index_from_groups(mod_groups)
    except Exception as exc:
        # Modifier load is best-effort. A failure must not abort the call —
        # fall back to base-menu-only behavior (pre-Phase 7-A.B).
        # (modifier 로드 실패는 통화 중단 사유 아님 — base menu only로 fallback)
        _dbg(f"[realtime] ⚠ modifier load failed: {type(exc).__name__}: {exc}")
        store["modifier_section"] = ""
        session_modifier_index = None

    # CRM Wave 1 — phone-keyed lookup before prompt build. The lookup helper
    # has a hard 500ms internal timeout and full graceful-degrade (anonymous /
    # 5xx / 4xx / exception → None), so this await never blocks the call for
    # more than half a second and never raises out. CRM_LOOKUP_ENABLED=false
    # is the kill switch for emergency rollback (NULLABLE columns means the
    # only side effect is that returning callers stop being recognized).
    # (CRM Wave 1 — 전화번호 lookup 1회 후 프롬프트에 주입. 환경변수로 비상 차단)
    customer_ctx = None
    if os.getenv("CRM_LOOKUP_ENABLED", "true").lower() != "false":
        try:
            customer_ctx = await customer_lookup(store_id, caller_phone or None)
        except Exception as exc:
            # Defensive — customer_lookup already swallows everything, this is
            # an extra ring against unforeseen import-time / settings issues.
            _dbg(f"[crm] lookup_unexpected_top_level err={type(exc).__name__}: {exc}")
            customer_ctx = None

    instructions = build_system_prompt(store, customer_context=customer_ctx)
    _dbg(f"[realtime] store loaded id={store_id} name={store_name!r} "
         f"prompt_len={len(instructions)} modifier_groups={mod_group_count} "
         f"crm_returning={customer_ctx is not None and customer_ctx.visit_count > 0} "
         f"crm_visits={customer_ctx.visit_count if customer_ctx else 0}")

    # 3) Open OpenAI Realtime session
    # (OpenAI Realtime 세션 오픈 — g711_ulaw 양방향 + server VAD)
    if not settings.openai_api_key:
        _dbg("[realtime] ❌ OPENAI_API_KEY missing — cannot open session")
        await ws.close()
        return
    _dbg(f"[realtime] opening OpenAI session model={MODEL} voice={VOICE}")
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        async with client.realtime.connect(model=MODEL) as oai:
            _dbg(f"[realtime] OpenAI WS connected, sending session.update")
            # GA Realtime API shape (2026-05-12 migration from beta):
            #   - session.type="realtime" required
            #   - audio nested: audio.input.format / audio.output.format / .voice
            #   - turn_detection moved under audio.input
            #   - input_audio_transcription → audio.input.transcription
            #   - modalities removed → output_modalities at root
            #   - g711_ulaw → {"type": "audio/pcmu"}
            _input_transcription = (
                {
                    "model":    "gpt-4o-mini-transcribe",
                    "language": "en",
                    "prompt":   (
                        "JM Pizza phone order taking. The customer "
                        "speaks English or Spanish. Common items: "
                        "pepperoni, mozzarella, ricotta, gluten-free, "
                        "cheese pizza, slice, large, small, thin "
                        "crust. Reply 'Yes'/'No'/'OK' are common."
                    ),
                }
                if (store.get("industry") or "").lower() == "pizza"
                else {"model": "gpt-4o-mini-transcribe"}
            )
            await oai.session.update(
                session={
                    "type": "realtime",
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},
                            "turn_detection": {
                                "type":                 "server_vad",
                                "threshold":            0.5,
                                "prefix_padding_ms":    300,
                                "silence_duration_ms":  1200,
                                "create_response":      True,
                                "interrupt_response":   True,
                            },
                            "transcription": _input_transcription,
                        },
                        "output": {
                            "format": {"type": "audio/pcmu"},
                            "voice":  VOICE,
                        },
                    },
                    "instructions": instructions,
                    "tools": OPENAI_REALTIME_TOOLS,
                    "tool_choice": "auto",
                }
            )
            _dbg(f"[realtime] ✓ session.update sent (audio/pcmu GA shape, "
                 f"system_prompt={len(instructions)}B, "
                 f"tools={len(OPENAI_REALTIME_TOOLS)}, "
                 f"vad=server_vad/silence=1200ms + whisper transcription)")

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
                    "output_modalities": ["audio"],
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
                # Phase 7-A.D quality fix — track whether bot is mid-utterance
                # so barge-in clears only fire on TRUE interrupts (not on
                # caller utterances that begin while the bot is idle, e.g. a
                # 'Hello?' after the bot finished).
                # Set True on response.audio.delta (first audio frame leaving
                # OpenAI) and reset on response.done.
                # (bot 발화 중 추적 — 진짜 끼어들기일 때만 clear)
                "bot_speaking": False,
            }

            # Per-call state for tool snapshots (recall_order / cancel recital
            # / B4 deferred reservation email).
            # (통화 중 스냅샷 — recall_order, cancel recital, 예약 이메일 deferred)
            session_state: dict[str, Any] = {
                "last_order_items": [],
                "last_order_total": 0,
                "pending_reservation_email": None,
                # P2 fix (2026-05-10) — call_logs row PK for tool-dispatch
                # wire-up. Set once at WS start (above), consumed by every
                # bridge_flows.* call below as call_log_id so the resulting
                # bridge_transactions row joins back to the call.
                # (call_logs row PK — tool dispatch가 bridge_transactions에 join)
                "call_log_id":      call_sid or "",
                # Phase 5 #26 — Tier-3 manager alert state.
                # last_user_text feeds the keyword detector; tier3_alerted
                # is an idempotency latch so repeated keyword utterances
                # in the same call don't fan out duplicate emails.
                # (Tier 3 매니저 알림 상태 — 통화당 1회만 발송)
                "last_user_text":   "",
                "tier3_alerted":    False,
                # Latched copy of the most recent agent text containing a
                # parseable NATO+at-domain email recital. Separate from
                # last_assistant_text so a later non-NATO turn (order
                # confirmation, allergen response, etc.) cannot wipe it
                # before reconcile_email_with_recital reads it.
                # (NATO email recital을 별도 latch — 덮어쓰기 방지)
                "last_email_recital_text": "",
                # Auto-retry budget for response.create after a
                # rate_limit_exceeded. Capped at 3 total per call to
                # bound runaway recovery loops while still covering the
                # 1-2 expected throttles in a long Tier-1 call.
                # (rate_limit retry 회로 차단기)
                "_rate_limit_retries": 0,
                # Wave A.3 — modifier index reused across every create_order /
                # modify_order in the call (built once at session.update above).
                # (modifier index — 통화 단위 캐시, tool 호출마다 REST 우회)
                "modifier_index":   session_modifier_index,
                # CRM Wave 1 — analytics state. call_started_at_ms is the wall-
                # clock anchor for AHT (matches t_accept's monotonic clock for
                # duration but uses time.time so the persisted ms is comparable
                # across processes). active_tx_id latches the LAST successful
                # create_order so the call_end UPDATE writes its analytics flags
                # to the row that actually represents the order. usual_offered
                # is regex-detected from agent transcripts; usual_accepted is
                # left None for Pilot (Wave 2 will infer from accepted vs
                # recent[0] item match).
                # (CRM Wave 1 — 분석용 상태. call_end에서 사용)
                "call_started_at_ms": int(time.time() * 1000),
                "customer_context":   customer_ctx,
                "active_tx_id":       None,
                "usual_offered":      False,
                "usual_accepted":     None,
                # Debug-2026-05-12 — full turn log persisted to
                # call_logs.transcript on session end. Each entry is
                # {role, text, ts_ms}. Lets us diagnose tool-not-firing
                # cases (JM Pizza pilot Day 1: 5 calls completed Successful
                # but 0 bridge_transactions — root cause unknown without
                # transcripts). Fire-and-forget UPDATE on disconnect.
                # (전체 turn log를 call_logs.transcript에 저장 — tool 미발사 디버깅용)
                "transcript_turns":   [],
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
                            # Caller speech detected. Two paths:
                            #   bot_speaking=True  → real barge-in: clear Twilio's
                            #     outbound buffer so customer doesn't hear bot
                            #     finish a sentence over them.
                            #   bot_speaking=False → bot is idle (greeting / last
                            #     response.done already fired). Sending a clear
                            #     here is a no-op but historically created the
                            #     fragmented-turn pattern observed across 4 calls
                            #     2026-05-07 (CA9c22bb95 / CA55035ea4 / CA941741f6
                            #     / CAf6e2e1ee — barge-in clears 1.0/turn). Skip
                            #     the clear so post-bot caller utterances ('Hello?',
                            #     'Did you get that?') don't generate empty
                            #     response.done turn=N events.
                            # (bot 발화 중일 때만 clear — false-positive 끼어들기 차단)
                            stats["user_turns"] += 1
                            stats["speech_stop_ts"] = None
                            stats["first_response_ttft_ms"] = None
                            if stats.get("bot_speaking"):
                                try:
                                    await ws.send_text(json.dumps({
                                        "event": "clear",
                                        "streamSid": stream_sid,
                                    }))
                                except Exception:
                                    pass
                                _dbg("[oai→twilio] caller speech_started — sent clear (bot was speaking)")
                            else:
                                _dbg("[oai→twilio] caller speech_started — bot idle, skipping clear")

                        elif etype == "input_audio_buffer.speech_stopped":
                            stats["speech_stop_ts"] = time.monotonic()
                            _dbg("[oai→twilio] caller speech_stopped")

                        elif etype == "response.output_audio.delta":
                            # First-byte TTFT measurement
                            if (
                                stats["speech_stop_ts"] is not None
                                and stats["first_response_ttft_ms"] is None
                            ):
                                ttft = (time.monotonic() - stats["speech_stop_ts"]) * 1000
                                stats["first_response_ttft_ms"] = ttft
                                _dbg(f"[oai→twilio] turn={stats['user_turns']} TTFT={ttft:.0f}ms")
                            # Bot is now mid-utterance — barge-in clear is valid
                            # if a caller speech_started follows.
                            stats["bot_speaking"] = True
                            # Forward audio delta as Twilio media frame
                            await ws.send_text(json.dumps({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": event.delta},
                            }))
                            stats["openai_audio_out"] += 1

                        elif etype == "response.output_audio_transcript.done":
                            agent_text = getattr(event, 'transcript', '') or ""
                            _dbg(f"[oai→twilio] turn={stats['user_turns']} agent: "
                                 f"{agent_text!r}")
                            # Debug-2026-05-12 — accumulate for DB persistence
                            session_state["transcript_turns"].append({
                                "role": "agent",
                                "text": agent_text,
                                "turn": stats["user_turns"],
                                "ts_ms": int(time.time() * 1000),
                            })
                            # Wave A.3 Plan E — keep the bot's last response
                            # so the tool dispatcher can reconcile NATO email
                            # readback against args.customer_email before
                            # firing create_order. Live ops 2026-05-08:
                            # 10/11 emails landed at wrong addresses because
                            # the LLM's args dropped/added letters relative
                            # to its own correct spoken NATO recital.
                            # (마지막 bot 발화 보관 → NATO 추출용)
                            session_state["last_assistant_text"] = agent_text

                            # Latch only NATO-email-bearing agent texts in a
                            # separate slot. last_assistant_text is overwritten
                            # every turn so by the time create_order fires the
                            # NATO recital is usually 1-2 turns stale and gone.
                            # This slot survives across intervening turns and
                            # becomes the source-of-truth for email reconcile.
                            # (NATO 추출 가능한 agent text만 별도 latch — 후속 turn 덮어쓰기 방지)
                            if extract_email_from_recital(agent_text):
                                session_state["last_email_recital_text"] = agent_text

                            # CRM Wave 1 — latch usual_offered the first time
                            # the agent emits "the usual" anywhere in a turn.
                            # Once-true-stays-true so a follow-up turn that
                            # doesn't mention it still keeps the analytics
                            # flag set for the call_end UPDATE.
                            # (CRM Wave 1 — "the usual" 발화 감지 시 latch)
                            if (not session_state.get("usual_offered")
                                    and _THE_USUAL_RE.search(agent_text or "")):
                                session_state["usual_offered"] = True
                                _dbg(f"[crm] usual_offered=true detected in agent_text")

                        elif etype == "conversation.item.input_audio_transcription.completed":
                            user_text = getattr(event, 'transcript', '') or ""
                            _dbg(f"[oai→twilio] turn={stats['user_turns']} caller: "
                                 f"{user_text!r}")
                            # Debug-2026-05-12 — accumulate for DB persistence
                            session_state["transcript_turns"].append({
                                "role": "caller",
                                "text": user_text,
                                "turn": stats["user_turns"],
                                "ts_ms": int(time.time() * 1000),
                            })
                            # Track for tier-3 detection + (future) audit context.
                            session_state["last_user_text"] = user_text
                            # Phase 5 #26 — Tier-3 manager alert (V0+).
                            # Fire-and-forget email when a severe-allergy keyword
                            # appears. Idempotent per call (latch in session_state).
                            # The bot's verbal hand-off is driven separately by the
                            # system prompt rule 12; this is the operator-side
                            # follow-up channel that was missing pre-Phase-5.
                            # (Tier 3 키워드 감지 → 매니저 이메일 fire-and-forget,
                            #  통화당 1회만)
                            if (not session_state["tier3_alerted"]
                                    and _has_severe_allergy_signal(user_text)):
                                session_state["tier3_alerted"] = True
                                match = _SEVERE_ALLERGY_RE.search(user_text)
                                trigger_kw = match.group(0) if match else "severe-allergy"
                                _dbg(f"[tier3] keyword={trigger_kw!r} — dispatching "
                                     f"manager alert (caller={caller_phone} "
                                     f"call_sid={call_sid})")
                                try:
                                    asyncio.create_task(send_tier3_alert(
                                        store_name         = store_name or "the store",
                                        caller_phone       = caller_phone or "",
                                        triggered_keyword  = trigger_kw,
                                        transcript_excerpt = user_text,
                                        call_sid           = call_sid or "",
                                    ))
                                except Exception as exc:
                                    _dbg(f"[tier3] alert dispatch error: {exc}")

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
                            # Debug-2026-05-12 — persist tool call attempt
                            session_state["transcript_turns"].append({
                                "role": "tool_call",
                                "tool": tool_name,
                                "args": tool_args,
                                "turn": stats["user_turns"],
                                "ts_ms": int(time.time() * 1000),
                            })
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
                            # Debug-2026-05-12 — persist tool result (slim copy)
                            session_state["transcript_turns"].append({
                                "role": "tool_result",
                                "tool": tool_name,
                                "ok": bool(tool_result.get("success")),
                                "reason": tool_result.get("reason"),
                                "hint": tool_result.get("ai_script_hint"),
                                "unavailable": tool_result.get("unavailable"),
                                "ms": int(tool_ms),
                                "turn": stats["user_turns"],
                                "ts_ms": int(time.time() * 1000),
                            })
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
                            # Bot finished its turn — caller utterances after
                            # this point are NOT barge-ins, so the clear should
                            # be skipped (see speech_started handler).
                            # (bot 발화 종료 — 이후 caller 발화는 barge-in 아님)
                            stats["bot_speaking"] = False

                            # Diagnostic — capture id / status / output shape so
                            # the silent-after-tool failure mode (Wave A.3 fire_immediate
                            # branch, observed 2026-05-08 callSid CA59d6f3f31...) is
                            # debuggable from the log alone. We record:
                            #  - response_id: which response (multiple emit per turn
                            #    when a tool fires — first carries the function_call,
                            #    second is meant to carry the post-tool audio reply)
                            #  - status / status_details: completed / cancelled /
                            #    failed / incomplete, with reason when present
                            #  - output_types: ['function_call'] vs ['message'] vs
                            #    ['function_call','message'] tells us which response
                            #    actually produced speech vs only a tool
                            #  - has_audio + transcript: first 80 chars of any audio
                            #    transcript, or '' when the response was empty
                            # This is logging-only — no behavior change. Decisions
                            # about whether to retry, fallback, or alarm on empty
                            # post-tool responses come in a follow-up commit once
                            # we have data on which pattern actually fires.
                            # (Wave A.3 후 fire_immediate 무음 진단용 — 행동 무변경)
                            response = getattr(event, "response", None)
                            r_id     = getattr(response, "id", "?") or "?"
                            r_status = getattr(response, "status", "?") or "?"
                            r_status_details = getattr(response, "status_details", None)
                            output_items = getattr(response, "output", None) or []
                            output_types: list[str] = []
                            has_audio  = False
                            transcript = ""
                            for item in output_items:
                                it_type = getattr(item, "type", "") or ""
                                output_types.append(it_type)
                                if it_type != "message":
                                    continue
                                for c in (getattr(item, "content", None) or []):
                                    c_type = getattr(c, "type", "") or ""
                                    if c_type in ("output_audio", "audio"):
                                        has_audio = True
                                        if not transcript:
                                            transcript = (getattr(c, "transcript", "") or "")[:80]
                                    elif c_type in ("output_text", "text") and not transcript:
                                        transcript = (getattr(c, "text", "") or "")[:80]
                            _dbg(
                                f"[oai→twilio] response.done turn={stats['user_turns']} "
                                f"id={r_id} status={r_status} "
                                f"output_types={output_types} has_audio={has_audio} "
                                f"transcript={transcript!r}"
                            )
                            if r_status_details:
                                _dbg(f"[oai→twilio] response.status_details={r_status_details!r}")

                            # Auto-retry on rate_limit_exceeded — turns the
                            # silent-agent failure mode into a 1-2s pause
                            # instead of waiting for the caller to break the
                            # silence themselves. Live trigger 2026-05-08
                            # callSid CA6eb23bf4... at turn=8: post-tool
                            # response failed with rate_limit_exceeded; the
                            # error message includes "try again in N.NNNs"
                            # — we honor that hint with a small safety
                            # margin and re-fire response.create exactly
                            # once per failed response. Capped at 3 total
                            # retries per call so a wedge doesn't spin
                            # forever; capped at 5s per wait so a runaway
                            # number doesn't hold the WS open. interrupt
                            # handling (caller starts speaking during the
                            # wait) is preserved by OpenAI's own VAD layer.
                            # (rate_limit_exceeded 자동 재시도 — silent agent
                            #  6-10s → 1-2s, 회로 차단기로 무한 retry 방지)
                            if r_status == "failed" and r_status_details is not None:
                                err_obj = getattr(r_status_details, "error", None)
                                err_code = getattr(err_obj, "code", "") if err_obj else ""
                                if err_code == "rate_limit_exceeded":
                                    retry_count = session_state.get("_rate_limit_retries", 0)
                                    if retry_count >= 3:
                                        _dbg(f"[oai→twilio] rate_limit_retry_budget_exhausted "
                                             f"count={retry_count} response_id={r_id}")
                                    else:
                                        err_msg = getattr(err_obj, "message", "") or ""
                                        m = re.search(r"try again in ([\d.]+)s", err_msg)
                                        wait_s = min(
                                            (float(m.group(1)) if m else 2.0) + 0.2,
                                            5.0,
                                        )
                                        session_state["_rate_limit_retries"] = retry_count + 1
                                        _dbg(
                                            f"[oai→twilio] rate_limit_retry "
                                            f"attempt={retry_count + 1}/3 wait={wait_s:.2f}s "
                                            f"response_id={r_id}"
                                        )

                                        async def _delayed_retry(client=oai, delay=wait_s, rid=r_id):
                                            try:
                                                await asyncio.sleep(delay)
                                                await client.response.create()
                                                _dbg(f"[oai→twilio] rate_limit_retry_sent "
                                                     f"after_response_id={rid}")
                                            except Exception as ex:
                                                _dbg(f"[oai→twilio] rate_limit_retry_failed "
                                                     f"after_response_id={rid} "
                                                     f"err={type(ex).__name__}: {ex}")

                                        asyncio.create_task(_delayed_retry())

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

            # FIX-A (2026-05-09) — Twilio Media Streams keepalive.
            # Live regression: 5x WebSocket Abnormal Closure (1006) on
            # 2026-05-09 between 11:26 and 12:09, all clustered in idle
            # windows (20-30s of caller silence after a turn). 1006 means
            # the TCP connection was severed without a WS close frame —
            # typical of carrier-level RTP idle timeouts or NAT eviction.
            # Twilio Media Streams does NOT support standard WS ping
            # frames, but it DOES support 'mark' events (application
            # layer). Sending a mark every 15s keeps bidirectional
            # traffic flowing (Twilio echoes the mark back), which
            # prevents intermediate hops from declaring the connection
            # idle. Failure of the keepalive task itself MUST NOT
            # terminate the call — it runs as a fire-and-forget side
            # task and is explicitly cancelled in the cleanup block.
            # (Twilio mark 15s 주기 발송 — 1006 abnormal closure 방지)
            async def twilio_mark_keepalive() -> None:
                interval_s = 15.0
                seq = 0
                try:
                    while True:
                        await asyncio.sleep(interval_s)
                        if not stream_sid:
                            continue  # start event not yet processed
                        seq += 1
                        try:
                            await ws.send_text(json.dumps({
                                "event":     "mark",
                                "streamSid": stream_sid,
                                "mark":      {"name": f"ka-{seq}"},
                            }))
                        except Exception as exc:
                            _dbg(f"[keepalive] send failed seq={seq} "
                                 f"{type(exc).__name__}: {exc}")
                            return  # WS likely dead — exit task quietly
                except asyncio.CancelledError:
                    return

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
                # FIX-A keepalive runs alongside but is NOT part of the
                # FIRST_COMPLETED set — its termination should never
                # trigger pump cancellation cascade.
                t_keepalive = asyncio.create_task(
                    twilio_mark_keepalive(), name="keepalive")
                done, pending = await asyncio.wait(
                    {t_twilio, t_openai},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                first_done_names = sorted(t.get_name() for t in done)
                _dbg(f"[realtime] first pump exit: {first_done_names} — cancelling rest")
                for task in pending:
                    task.cancel()
                # Cancel keepalive too (separate from FIRST_COMPLETED set)
                t_keepalive.cancel()
                # Give cancellations a moment to propagate cleanly
                await asyncio.gather(*pending, t_keepalive, return_exceptions=True)
            finally:
                duration = time.monotonic() - t_accept
                duration_ms = int(duration * 1000)
                _dbg(
                    f"[realtime] call done — duration={duration:.1f}s "
                    f"callSid={call_sid} twilio_in={stats['twilio_media_in']} "
                    f"openai_out={stats['openai_audio_out']} turns={stats['user_turns']}"
                )

                # CRM Wave 1 — call_end analytics. Single grep-friendly log
                # line + fire-and-forget UPDATE on bridge_transactions when
                # we have a tx_id binding (mid-call hangup → no_tx_skip path
                # logged inside update_call_metrics). Both paths are safe
                # against any failure — we are exiting the WS handler and
                # the caller has already disconnected.
                # (CRM Wave 1 — 통화 종료 분석 영속화 + grep용 단일 로그 라인)
                _crm_ctx       = session_state.get("customer_context")
                _crm_visits    = _crm_ctx.visit_count if _crm_ctx else 0
                _crm_returning = _crm_ctx is not None and _crm_visits > 0
                _crm_tx        = session_state.get("active_tx_id") or ""
                _crm_offered   = bool(session_state.get("usual_offered"))
                _crm_accepted  = session_state.get("usual_accepted")

                _dbg(
                    f"[perf] call_end tx={_crm_tx or '-'} aht_ms={duration_ms} "
                    f"returning={_crm_returning} visits={_crm_visits} "
                    f"usual_offered={_crm_offered} usual_accepted={_crm_accepted}"
                )

                if _crm_tx:
                    try:
                        asyncio.create_task(update_call_metrics(
                            transaction_id     = _crm_tx,
                            call_duration_ms   = duration_ms,
                            crm_returning      = _crm_returning,
                            crm_visit_count    = _crm_visits,
                            crm_usual_offered  = _crm_offered,
                            crm_usual_accepted = _crm_accepted,
                        ))
                    except Exception as exc:
                        _dbg(f"[perf] call_end_persist_dispatch_error: {exc}")
                else:
                    _dbg(f"[perf] call_end no_tx_skip_update aht_ms={duration_ms}")

                # P2 fix (2026-05-10) — UPDATE call_logs duration + status so
                # the dashboard's per-call drill-down shows actual length and
                # final state. status='Successful' when we reached call_end
                # without an exception path; failure paths go through the
                # outer `except` and never reach here. Fire-and-forget.
                # (call_logs UPDATE — 통화 종료 시점 duration + status)
                if call_sid:
                    # Debug-2026-05-12 — serialize accumulated transcript turns.
                    # Compact JSON keeps the DB column small; consumed by
                    # diagnostic scripts only. Capped at 100KB to avoid runaway
                    # entries from very long calls / event storms.
                    # (transcript JSON — 통화당 100KB cap)
                    try:
                        _transcript_json = json.dumps(
                            session_state.get("transcript_turns") or [],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        if len(_transcript_json) > 100_000:
                            _transcript_json = _transcript_json[:100_000]
                    except Exception:
                        _transcript_json = None

                    try:
                        asyncio.create_task(_update_call_log_row(
                            call_id    = call_sid,
                            duration_s = max(1, duration_ms // 1000),
                            status     = "Successful",
                            transcript = _transcript_json,
                        ))
                    except Exception as exc:
                        _dbg(f"[call_log] update dispatch error: {exc}")

                # G6 fix (2026-05-10) — persist mid-call email update so the
                # next customer_lookup for this phone picks up the corrected
                # address. Live trigger CA7748f354... Jason called after Billy
                # (same phone), did a NATO recital of a corrected email AFTER
                # his only create_order had fired, then hung up — the new
                # email never landed in any tx and a 3rd call would still
                # match the stale row. We reuse last_email_recital_text (the
                # same source reconcile_email_with_recital trusts for tool
                # args) so the persisted email matches whatever the agent
                # spelled back and the caller verified. Fire-and-forget; the
                # helper internally short-circuits on anonymous / no-match /
                # already-current. (G6 — mid-call email update DB 영속화)
                try:
                    _latched_recital = session_state.get("last_email_recital_text") or ""
                    if _latched_recital and caller_phone:
                        _verified_email = extract_email_from_recital(_latched_recital)
                        if _verified_email:
                            asyncio.create_task(update_recent_customer_email(
                                store_id          = store_id,
                                caller_phone_e164 = caller_phone,
                                new_email         = _verified_email,
                            ))
                            _dbg(f"[crm] email_update dispatched email=***@{_verified_email.split('@')[-1] if '@' in _verified_email else '?'}")
                except Exception as exc:
                    _dbg(f"[crm] email_update dispatch error: {exc}")

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
