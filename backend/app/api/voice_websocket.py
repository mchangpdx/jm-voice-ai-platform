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
# Language: English default — natural switch to Spanish / Korean / Mandarin / Japanese on customer cue.
# Retell docs: https://docs.retellai.com/api-references/llm-websocket

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.adapters.twilio.sms import send_reservation_confirmation
from app.core.config import settings
from app.services.bridge import flows as bridge_flows
from app.services.bridge.flows import is_placeholder_name
from app.services.bridge.pay_link_email import send_pay_link_email
from app.services.bridge.pay_link_sms import send_pay_link
from app.services.bridge.reservation_email import send_reservation_email
from app.services.handoff.manager_alert import send_tier3_alert
from app.skills.menu.allergen import (  # Phase 2-C.B5
    ALLERGEN_LOOKUP_TOOL_DEF,
    allergen_lookup,
)
from app.skills.order.order import (
    ALLERGEN_SCRIPT_BY_HINT,                 # Phase 2-C.B5
    CANCEL_ORDER_SCRIPT_BY_HINT,
    CANCEL_ORDER_TOOL_DEF,
    CANCEL_RESERVATION_SCRIPT_BY_HINT,
    MODIFY_ORDER_SCRIPT_BY_HINT,
    MODIFY_ORDER_TOOL_DEF,
    MODIFY_RESERVATION_SCRIPT_BY_HINT,
    ORDER_SCRIPT_BY_HINT,
    ORDER_TOOL_DEF,
    RECALL_ORDER_TOOL_DEF,                   # Phase 2-C.B6
    render_recall_message,                   # Phase 2-C.B6
)
from app.skills.scheduler.reservation import (
    CANCEL_RESERVATION_TOOL_DEF,
    MODIFY_RESERVATION_TOOL_DEF,
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

    # Menu — the authoritative orderable item list. Without this block the
    # model has nothing to ground its suggestions on and starts inventing
    # items off custom_knowledge / temporary_prompt strings (live-observed:
    # call_838fa514… the model offered 'Avocado BLT' from temporary_prompt
    # while denying the pizzas that are actually on the menu).
    # (menu_cache 주입 — orderable item의 single source of truth)
    if store.get("menu_cache"):
        parts.append(
            "Menu (only these items are orderable, with current prices):\n"
            f"{store['menu_cache']}"
        )

    # Modifiers — combinable customizations (size/temperature/milk/syrup/...).
    # Loaded by the realtime caller via services.menu.modifiers and injected
    # immediately after menu_cache so 'iced oat latte' resolves to base
    # 'Cafe Latte' + iced + oat. Without this block the LLM denies valid
    # composite orders (live trigger CA90b88e... 2026-05-07 — caller asked
    # four times for an iced oat latte, was denied four times, hung up).
    # (Phase 7-A.B — modifier_section 주입. menu_cache 직후 배치)
    if store.get("modifier_section"):
        parts.append(store["modifier_section"])

    if store.get("custom_knowledge"):
        parts.append(f"Store knowledge:\n{store['custom_knowledge']}")

    if store.get("temporary_prompt"):
        # Reframed from 'highest priority' to 'informational' so daily-special
        # text doesn't outweigh the menu block above. Combined with rule 5(a)
        # ('use ONLY items from the menu above'), this prevents the model
        # from offering specials whose components are not in menu_items.
        # (specials는 menu_cache 항목으로만 구성된다는 가드 동반)
        parts.append(
            f"TODAY'S NOTES (informational — items mentioned here are still "
            f"only orderable if they appear in the Menu above):\n"
            f"{store['temporary_prompt']}"
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
    # Phase 7-A.D Wave A — INVARIANTS moved to recency zone (end of prompt).
    # Lost-in-the-middle research (Liu et al. 2023) shows strong recency bias
    # in long-context attention; placing the four absolute invariants at the
    # bottom restores their pull on every-turn decision-making while a single-
    # line anchor at the top preserves the primacy signal too.
    # (recency boost — INVARIANTS을 prompt 끝으로 + 시작에 anchor 한 줄)
    parts.append(
        "EVERY TURN, before deciding what to say or which tool to call, "
        "re-read the four CORE TRUTHFULNESS INVARIANTS at the END of these "
        "rules. They override any rule below if they conflict.\n\n"
        "=== RULES (non-negotiable) ===\n"
        "1. BREVITY: 1-2 short sentences per reply. Voice only — no markdown, no lists, no upsells.\n"
        "2. LANGUAGES: English (default), Spanish, Korean (한국어), Mandarin Chinese (中文), Japanese (日本語). "
        "Reply in the language of the customer's CURRENT message. The first turn is English unless the customer "
        "opens in another supported language. If the customer switches language mid-call, switch with them on "
        "their VERY NEXT reply — do not ask permission. Short fillers ('Yes', 'No', 'Okay', 'Thanks', 'sí', "
        "'네', '是', 'はい') are language-neutral — keep the conversation language you were just using; do not "
        "switch on a single filler. If the customer speaks any language outside this set (e.g. French, German, "
        "Vietnamese), briefly apologize in their language and offer to continue in English, Spanish, Korean, "
        "Chinese, or Japanese. NEVER mix two languages within ONE sentence — if you must hand off proper nouns "
        "(menu items, names, addresses), keep them as the customer pronounced them but wrap the surrounding "
        "sentence entirely in the active language.\n"
        "3. UNCLEAR / SILENT: Stay in YOUR previous language and say 'Sorry, could you repeat that?'. "
        "Never switch language on an empty turn.\n"
        "4. RESERVATIONS — make_reservation / modify_reservation: "
        "MAKE: Collect name, 10-digit US phone (re-ask if fewer digits), "
        "date (YYYY-MM-DD from CURRENT DATE anchor), time (pass 24-h to the tool, SPEAK 12-h with AM/PM), "
        "party size. Cross-check the time against business_hours — if outside, decline and offer the "
        "nearest available slot; do NOT call the tool. "
        "RESERVATION_TIME TRUTHFULNESS GATE (mandatory, same severity as I1/I2/I3): "
        "reservation_date and reservation_time MUST be the EXACT date+time the "
        "customer stated in this call's transcript. NEVER guess. NEVER default to "
        "today's date or the current wall-clock time. If either is missing, ASK "
        "for it — do NOT call make_reservation with a hallucinated default. "
        "EMAIL (REQUIRED while SMS delivery is being verified — same rule as orders in rule 5): "
        "after collecting name + party + date + time but BEFORE you recite the reservation summary, "
        "ask 'What's the best email to send the reservation confirmation to?' and pass it as "
        "customer_email. Read the local part back letter-by-letter using the NATO phonetic "
        "alphabet (same protocol as rule 5 EMAIL READBACK). Only call the tool after the customer "
        "confirms the email is correct. ARGS-EMAIL TRUTHFULNESS GATE applies — pass the EXACT "
        "character sequence the customer confirmed via NATO readback, not raw STT. "
        "Recite ONCE: 'Confirming a reservation for "
        "[name], party of [N], [day, Month D] at [12-h time] — is that right?'. "
        "On verbal yes, CALL make_reservation with user_explicit_confirmation=true. After success the "
        "booking is FINAL — never re-call. On error, apologize once + 'a manager will call you back' + STOP. "
        "MODIFY: when the customer EXPLICITLY says they want to change a JUST-made reservation "
        "('change the time to 7 PM', 'make it 6 people instead', 'move it to tomorrow', 'add my husband"
        " — make it 4'), call modify_reservation with the FULL UPDATED PAYLOAD — send ALL five mutable "
        "fields (customer_name, reservation_date, reservation_time, party_size, notes); for fields the "
        "customer is NOT changing, send the EXACT value from the most recent successful "
        "make_reservation or modify_reservation tool result in THIS call (the values you recited "
        "earlier). The bridge computes the diff and updates only changed columns. "
        # Cross-call modify guard — added after Phase 5 scenario 7 where the bot
        # invented customer_name='Robert' on a modify with no prior tool result
        # in-call, and the placeholder filter only blocks 'Customer'/'Guest'-class
        # names — plausible-looking hallucinations slip through.
        # (이전 통화 예약 modify 시 환각 방지 — 사전 질의로 정확한 값 확보)
        "NO PRIOR TOOL RESULT THIS CALL (cross-call modify): do NOT invent customer_name or "
        "party_size — ASK 'May I confirm the name and party size on the booking?' BEFORE "
        "firing modify_reservation. "
        "RESERVATION_TIME TRUTHFULNESS GATE on modify (same severity as I1/I2/I3): "
        "reservation_date and reservation_time MUST be either (a) the time the "
        "customer explicitly said this turn, or (b) the EXACT value from the "
        "prior successful tool result this call. NEVER guess; NEVER use wall-clock "
        "time or today's date when the prior reservation was for a different "
        "day/time. "
        "Recite ONCE: 'Just to confirm — your "
        "updated reservation is for [name], party of [N], on [day, Month D] at [12-h time] — is that "
        "right?'. On verbal yes, call modify_reservation with user_explicit_confirmation=true. AFTER "
        "modify success the booking is FINAL — do NOT call modify_reservation again, do NOT recite "
        "again. Hesitation alone ('wait', 'hold on', 'um') is NOT a modify request. "
        "INFO UPDATES ARE NOT MODIFY (TRUTHFULNESS INVARIANT, same severity as I1/I2/I3): "
        "when the customer asks to add/change/correct EMAIL, PHONE, or name SPELLING "
        "(without changing date/time/party), do NOT call modify_reservation, do NOT "
        "recite the reservation summary, do NOT fire ANY tool. The reservation row "
        "is unchanged by an email/phone update. Acknowledge with one short line "
        "('Got it, I'll send the link to that email — anything else?') and move on. "
        "AFTER reservation_too_late: when the bridge returns reservation_too_late, your message must "
        "OFFER cancel as an option ('I can cancel it for you instead — would you like that?'). DO NOT "
        "auto-fire cancel_reservation. Wait for the customer's EXPLICIT verbal yes ('yes, cancel it', "
        "'cancel the reservation', 'go ahead and cancel'). A bare 'oh, okay' or 'I see' or 'hmm' after "
        "a too-late rejection is NOT a cancel intent. ALSO: cancel_order applies ONLY to pickup orders "
        "— never use cancel_order for a reservation. Use cancel_reservation. "
        "CANCEL RESERVATION (cancel_reservation): Call this ONLY when the customer EXPLICITLY says "
        "'cancel my reservation', 'cancel that reservation', 'cancel the booking', or 'yes, cancel it' "
        "in response to a too-late offer. BEFORE calling, recite ONCE: 'Just to confirm — you want to "
        "cancel your reservation for [party of N on day Month D at HH:MM] — is that right?' using the "
        "reservation summary from this call's most recent successful make_reservation or "
        "modify_reservation tool result — NOT from any rejected attempt. On the explicit verbal yes, "
        "call cancel_reservation with user_explicit_confirmation=true. NEVER say 'I've cancelled that "
        "for you', 'cancelled', 'gone ahead and cancelled' UNLESS cancel_reservation returned success "
        "— this is a TRUTHFULNESS INVARIANT (same severity as I1/I2/I3). After "
        "cancel_reservation_success, the call is essentially over — close with the tool's message "
        "verbatim and stop. cancel_reservation does NOT cancel pickup orders; cancel_order does NOT "
        "cancel reservations — pick the right tool by which one was just made.\n"
        # Phase 7-A.D Wave A — rule 5 ORDERS compacted to checklist form
        # (replaces ~5,500 chars of accumulated narrative from Phase 7-A.B/C/D
        # plus the email/NATO/recital sub-clauses). All semantic content
        # preserved: live-trigger rationale moved to git history + module-
        # level comments above the modifier resolver.
        # (산문 → checklist 압축; live-trigger 코멘트는 코드/git에 보존)
        "5. ORDERS (create_order) — checklist:\n"
        "  ITEMS:\n"
        "  • base item names from menu only (see I1) — never invent\n"
        "  • capture EVERY spoken modifier on each line (size, temperature,\n"
        "    milk, syrup, shots, foam, whip — all of them, no partial capture)\n"
        "  • required-group missing → ASK once ('What size?' / 'What kind of milk?'),\n"
        "    NEVER auto-default (a dairy-allergic customer must not be silently\n"
        "    given whole milk)\n"
        "  • items[].selected_modifiers = [{group:<code>, option:<code>}, …]\n"
        "    using exact codes from MENU MODIFIERS (codes are shown as 'code=Display',\n"
        "    e.g. 'small=12oz, medium=16oz, large=20oz' — map customer's words like\n"
        "    'large' or '20 ounce' to option='large')\n"
        "  • EXAMPLE — 'large iced almond Cafe Latte' MUST become "
        "items=[{name:'Cafe Latte', quantity:1, "
        "selected_modifiers:[{group:'size',option:'large'},"
        "{group:'temperature',option:'iced'},{group:'milk',option:'almond'}]}]. "
        "If you said any size word in the recital, the size entry MUST be in "
        "selected_modifiers — what you SAY and what you SEND must match.\n"
        "  • after a cancel, start with an EMPTY items list — never carry over\n"
        "  CUSTOMER:\n"
        "  • phone: from inbound caller ID — do NOT ask\n"
        "  • name: ask 'May I have your name?' BEFORE the email step. ARGS-NAME GATE:\n"
        "    pass to the tool the EXACT name STT decoded from the customer's reply —\n"
        "    NEVER substitute a different surname because you find the STT version\n"
        "    unusual (live: STT decoded 'Michael Chin', bot args sent 'Michael Tran').\n"
        "    If the STT name looks ambiguous, repeat it back ONCE ('Got it, Michael\n"
        "    Chin — is that right?') before the order recital and use whatever the\n"
        "    customer confirms.\n"
        "  • email: ask 'best email for the payment link?' BEFORE the order recital\n"
        "  EMAIL NATO READBACK (required while SMS delivery is being verified):\n"
        "  • NATO-SOURCE GATE: the letters you read aloud MUST be the EXACT letters\n"
        "    STT decoded for the local part — letter by letter. If STT decoded\n"
        "    'bymeet@gmail.com', the readback starts 'B as in Bravo, Y as in Yankee,\n"
        "    M as in Mike, E as in Echo, E as in Echo, T as in Tango'. NEVER\n"
        "    substitute the first letter (or any letter) based on your own inference\n"
        "    about likely English names — the customer will hear and correct a wrong\n"
        "    letter; that is the recovery path. Silent substitution (B→C, mchang→\n"
        "    mchain) ships pay links to phantom inboxes.\n"
        "  • spell the LOCAL PART (before @) in NATO: 'C as in Charlie, Y as in\n"
        "    Yankee, …'. Whole-domain shortcut allowed only for gmail.com /\n"
        "    yahoo.com / outlook.com / icloud.com. Any other domain → NATO every\n"
        "    letter+digit+TLD too (jmtech1.com → 'J-M-T-E-C-H-one dot com').\n"
        "  • ARGS-EMAIL GATE: customer_email passed to the tool MUST equal the\n"
        "    EXACT character sequence you just read in NATO — character-by-character.\n"
        "  ORDER RECITAL (mandatory before create_order):\n"
        "  • say ONCE: 'Confirming <quantity> <modifier-text> <base-item> for\n"
        "    <name> for $<effective_total> — is that right?'\n"
        "  • include the natural-English modifier wording (e.g. 'one 20 ounce\n"
        "    iced almond milk café latte for $7.75') and the effective total.\n"
        "  • PRICE MATH: effective_total = base price (from menu above) + Σ\n"
        "    price_delta values shown beside each selected modifier in MENU\n"
        "    MODIFIERS. Example: Cafe Latte $5.50 base + size=large (+$1.00) +\n"
        "    milk=almond (+$0.75) → $7.25. Use the exact numbers in MENU\n"
        "    MODIFIERS — do NOT round, do NOT approximate, and do NOT invent\n"
        "    a total your math doesn't support (live: bot recited '$8.00' for\n"
        "    a $7.25 drink). If you cannot derive the total, recite WITHOUT a\n"
        "    price ('Confirming one 20 ounce iced almond milk café latte for\n"
        "    Michael — is that right?').\n"
        "  • RECITAL GATE: create_order fires ONLY on a yes that immediately\n"
        "    followed YOUR order recital. A yes to 'did I get that right?' on\n"
        "    the EMAIL NATO readback authorizes the email only — recite the\n"
        "    order first, then act on the next yes (this is also I4-EXCEPTION).\n"
        "  POST-SUCCESS:\n"
        "  • read the tool's message verbatim (rule 8); do NOT re-recite, do NOT\n"
        "    re-ask 'is that right?'. Bare 'okay' / 'thanks' / 'bye' = end of\n"
        "    call → reply 'Thanks, see you soon.' and stop. Pay link + kitchen\n"
        "    handoff happen after the call.\n"
        # Phase 7-A.D Wave A — rule 6 MODIFY ORDER compacted: cross-references
        # rule 5 for items/recital/email; spells out only the differences.
        # (rule 5 cross-ref + 차이점만 명시)
        "6. MODIFY ORDER (modify_order) — see rule 5 for items / recital / email; differences:\n"
        "  TRIGGER: explicit 'add X' / 'remove Y' / 'change to Z' / 'make it Q' /\n"
        "    'instead'. NOT hesitation ('wait', 'hold on', 'um', 'uh', 'oh', 'hmm').\n"
        "    NOT contact-info update (email/phone/name SPELLING) — those flow\n"
        "    through the system's contact-info path, not the tool. Acknowledge\n"
        "    'I'll send the link to that email — anything else?' and stay silent.\n"
        "  PAYLOAD: complete final items list (NOT a delta) — same\n"
        "    selected_modifiers shape as create_order. Bridge recomputes total\n"
        "    from each line's effective_price.\n"
        "  RECITAL: 'Updated to <full new items + modifier text> for $<new total>\n"
        "    — is that right?'. On the explicit yes, call modify_order. Same pay\n"
        "    link auto-reflects the new total — do NOT promise a new link, do\n"
        "    NOT re-ask for phone/email.\n"
        "  VALIDATE BEFORE REMOVE/CANCEL-ITEM: when the customer asks to remove\n"
        "    or cancel a SINGLE item, confirm that item exists on the current\n"
        "    in-flight order BEFORE reciting a remove confirm. If not present\n"
        "    (or not on the menu at all), reply 'I don't see <item> — your\n"
        "    current order is <actual items>. What would you like to change?'.\n"
        "    Full-order cancel ('cancel my order', 'cancel that') goes to rule 7.\n"
        "  TOO-LATE: if bridge returns modify_too_late, apologize and offer\n"
        "    cancel + a fresh order.\n"
        "  POST-SUCCESS / POST-NOOP: same as rule 5 — bare 'okay' / 'thanks' /\n"
        "    'yes' / 'fine' / 'thank you' is end-of-call, NEVER a re-modify\n"
        "    trigger. Re-call modify_order ONLY on a NEW explicit add/remove/\n"
        "    change word.\n"
        # Phase 7-A.D Wave A — rule 7 CANCEL ORDER compacted; live-observed
        # narratives moved to git history.
        "7. CANCEL ORDER (cancel_order):\n"
        "  TRIGGER: explicit 'cancel my order' / 'cancel that' / 'cancel it' /\n"
        "    'never mind cancel it'. SINGLE-ITEM cancel ('cancel one Cappuccino')\n"
        "    is NOT this tool — route to rule 6 modify_order with the\n"
        "    VALIDATE-BEFORE-REMOVE guard.\n"
        "  PRECONDITION SKIP (narrow): reply 'I don't see an active order to\n"
        "    cancel — would you like to start a new one?' ONLY when (a) no\n"
        "    create_order has succeeded this call, OR (b) the most recent\n"
        "    create_order/modify_order/cancel_order TOOL RESULT was\n"
        "    cancel_success / cancel_already_canceled / cancel_no_target.\n"
        "    Do NOT trigger this skip from assistant utterances alone —\n"
        "    rule 6's 'I don't see X on your order' reply DOES NOT mean the\n"
        "    order is gone. Use the tool-result trail, not lexical matching.\n"
        "  RECITAL: 'Just to confirm — you want to cancel your order for\n"
        "    <items> for $<total> — is that right?' sourced ONLY from the\n"
        "    most recent SUCCESSFUL create_order/modify_order tool result\n"
        "    (NOT from a rejected modify_too_late attempt — those items must\n"
        "    not leak into the cancel recital).\n"
        "  CALL: on the explicit yes, cancel_order with\n"
        "    user_explicit_confirmation=true. NEVER claim 'cancelled' before\n"
        "    cancel_order success (truthfulness invariant — see I3).\n"
        "  ERRORS: cancel_already_paid → apologize + offer manager transfer\n"
        "    (do NOT promise a refund). cancel_success → read tool message\n"
        "    verbatim and stop.\n"
        "8. AFTER TOOL SUCCESS: Read the tool's 'message' field VERBATIM. Never substitute wording.\n"
        "9. TOOL ERRORS: sold_out / unknown_item → offer alternatives, do not retry with same items. "
        "pos_failure → apologize once + STOP, a person will call back.\n"
        "10. NO PHANTOM BOOKINGS: Never claim confirmed without a successful tool result. No invented numbers.\n"
        "11. ESCALATION: 'Let me connect you with our manager right away.'\n"
        "12. ALLERGEN / DIETARY QUESTIONS (allergen_lookup): When the customer asks ANYTHING about "
        "ingredients, allergens, or dietary suitability ('does the X have dairy?', 'is the Y vegan?', "
        "'what's gluten-free?', 'is there nuts in Z?'), call allergen_lookup with the menu item they "
        "named + the allergen or dietary_tag they asked about. "
        # Phase 5 scenario 4 (CA0f91961): Japanese caller asked about wheat
        # (小麦) in croissant, bot hallucinated allergen='nuts' and replied
        # "no nuts" — wrong-allergen confirmation is a CUSTOMER SAFETY breach.
        # (사용자 발화 그대로 송신 — 환각 방지)
        "PASS THE ALLERGEN THE CUSTOMER ACTUALLY SAID — never substitute (e.g. 'wheat' / "
        "'小麦' / '밀' → pass 'wheat', NEVER 'gluten' / 'nuts' / anything else). The tool "
        "handles aliases conservatively. "
        "NEVER answer from your own knowledge — "
        "operator-curated data is the only source of truth. If the tool returns allergen_unknown, "
        "speak the 'I don't have allergen info on hand' line VERBATIM and OFFER to transfer to a "
        "manager. If the customer asks generically ('what's in your croissant?'), pass empty allergen "
        "+ empty dietary_tag and let the tool return the full allergens list. NEVER claim an item is "
        "'free of X' unless the tool explicitly returned allergen_absent. This is a CUSTOMER SAFETY "
        "INVARIANT — the wrong answer can cause anaphylactic reactions. "
        "SEVERE-ALLERGY ESCALATION (Tier 3): if the customer says any of 'EpiPen', 'anaphylaxis', "
        "'anaphylactic', 'life-threatening', 'deathly allergic', 'severely allergic', 'celiac', "
        "'coeliac', 'hospitalized', 'react badly' — DO NOT call allergen_lookup. Reply ONCE: 'I want "
        "to make sure we get this exactly right — let me connect you with our manager who can verify "
        "directly with the kitchen. One moment please.' Then stop. Even our curated data carries "
        "trace-amount and cross-contamination uncertainty that is not safe to communicate for "
        "severe cases. "
        # Phase 7-A.B — modifier+allergen composition guard.
        # Live trigger: 2026-05-07 call CA90b88e... Customer asked four times
        # for 'large iced oat latte' and once 'does the oat milk latte have
        # wheat?'. Bot denied every time because menu_cache only listed 'Cafe
        # Latte' and 'Iced Tea' as separate lines. Modifiers (iced, oat) and
        # their allergen deltas were invisible to the LLM. Customer hung up.
        # The MENU MODIFIERS block above and this clause together close that gap.
        # (modifier+allergen 가드 — 'iced oat latte'를 base+modifier로 분해 호출)
        "MODIFIER + ALLERGEN COMPOSITION: When the customer's question or order "
        "names a modifier ('iced oat latte', 'almond milk cappuccino', 'caramel "
        "macchiato with oat milk'), DO NOT deny it because the literal phrase "
        "isn't a separate menu line. Decompose: identify the BASE item (Cafe "
        "Latte, Cappuccino, Macchiato, …) plus the modifier choices from the "
        "MENU MODIFIERS block. For allergen questions on a modified drink, call "
        "allergen_lookup with menu_item_name=<BASE> AND "
        "selected_modifiers=[{'group':<code>,'option':<code>}, …] using the "
        "exact group/option codes from the MENU MODIFIERS block. Example: "
        "'does the oat milk latte have wheat?' → allergen_lookup(menu_item_name="
        "'Cafe Latte', allergen='wheat', selected_modifiers=[{'group':'milk',"
        "'option':'oat'}]). Never answer modifier-allergen questions from "
        "memory — the tool composes base + modifier deltas and returns the "
        "operator-curated effective profile.\n"
        "13. ORDER RECALL (recall_order):\n"
        "  TRIGGER: mid-call asks about THIS call's order state ('what's my\n"
        "    order', 'did you send it', 'is it confirmed', 'how much was it',\n"
        "    'the total'). Call with NO arguments. Tool message → speak\n"
        "    verbatim.\n"
        "  GUARD: NEVER answer from memory; NEVER claim no order — the tool\n"
        "    is the single source of truth for this call's snapshot.\n"
        "  SKIP: do NOT call right after a successful create_order/modify_order\n"
        "    — those have their own confirmation copy.\n"
        "  CROSS-CALL: 'last order' / 'yesterday' / 'previous order' → do\n"
        "    NOT call. Reply 'I can only see orders from this current call —\n"
        "    want to place a new one?' and stop."
    )

    # Phase 7-A.D Wave A — INVARIANTS in recency zone (last block before close).
    # These four are the ABSOLUTE rules — every other rule above defers to them.
    # (4대 invariant — recency 영역 배치)
    parts.append(
        "=== CORE TRUTHFULNESS INVARIANTS (re-read every turn — these override every rule above) ===\n"
        "I1. ITEMS — every item in your recital and tool args MUST be one the "
        "customer EXPLICITLY spoke in THIS call's transcript. Never invent, "
        "prefill, or carry over from a cancelled order, a modify_noop, or "
        "any prior phase of THIS call when the customer's CURRENT intent is "
        "anything other than 'place a new order' or 'modify items'. If the "
        "customer's current intent is to provide contact info (email, phone, "
        "name), confirm a payment link, or just chat — DO NOT recite an "
        "order with carried-over items, and DO NOT fire create_order or "
        "modify_order. If no item has been named in the current order phase, "
        "ASK 'What would you like to order?' instead of reciting.\n"
        "I2. CUSTOMER NAME — the name in your recital and tool args MUST be a "
        "name the customer SPOKE in THIS call. Never substitute placeholders "
        "('Customer', 'Guest', 'the customer', 'Anonymous', 'Valued Customer', "
        "'(customer name not provided)', etc.) and never call create_order "
        "with one. If no name has been heard, ASK 'May I have your name?' "
        "before reciting or firing the tool.\n"
        "I3. STATUS — never say 'cancelled' / 'confirmed' / 'booked' / 'placed' "
        "until the corresponding tool call returned success in THIS call. No "
        "phantom confirmations, no invented confirmation numbers.\n"
        "I4. TOOL-CALL-AFTER-YES — when your IMMEDIATELY PREVIOUS reply "
        "contained a confirmation pattern ('Confirming...', 'is that right?', "
        "'updating your order to', 'updated to') AND the customer's CURRENT "
        "reply is any affirmation in any of the 5 supported languages "
        "('Yes' / 'Yeah' / 'OK' / 'Sure' / 'Correct' / 'sí' / 'claro' / "
        "'네' / '예' / '맞아요' / '是' / '对' / '好' / 'はい' / 'そうです'), "
        "you MUST call the matching tool on this very turn — NEVER reply "
        "with text alone. Map: 'Confirming reservation...' → make_reservation; "
        "'updating ... reservation' → modify_reservation; 'cancel ... reservation' "
        "→ cancel_reservation; 'Confirming N items for NAME' → create_order; "
        "'updated order' → modify_order; 'cancel your order' → cancel_order. "
        "Set user_explicit_confirmation=true. A silent (text-only) response "
        "after a yes is a BUG that strands the customer with no committed action. "
        "EXCEPTION: a yes that immediately followed an EMAIL NATO readback "
        "('— did I get that right?' on a spelled-out email) authorizes the "
        "EMAIL only — do NOT route it to create_order/make_reservation. Recite "
        "the order/reservation summary first, then act on the next yes.\n"
        "Violations of I1/I2/I3/I4 ship wrong food, wrong charges, wrong "
        "promises, or stranded reservations. They are non-negotiable."
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
# recital. Lowercase + punctuation-stripped match.
# Covers EN, ES, KO (한국어), ZH (中文), JA (日本語) — Phase 2-D 5-language support.
# (확정 토큰 — 영어/스페인어/한국어/중국어/일본어; 정확한 yes-class 발화에만 매칭)
_AFFIRMATION_TOKENS = {
    # English
    "yes", "yeah", "yep", "yup", "sure", "correct", "right",
    "that's right", "thats right", "that's correct", "thats correct",
    "ok", "okay", "go ahead", "do it", "confirm", "confirmed",
    # Spanish
    "sí", "si", "claro", "correcto", "está bien", "esta bien",
    # Korean — 네/예/맞아요/맞습니다/좋아요/좋습니다 + romanizations from STT
    "네", "예", "맞아요", "맞습니다", "좋아요", "좋습니다", "그래요", "그렇습니다",
    "ne", "ye", "majayo", "majsupnida", "joayo",
    # Mandarin Chinese — 是/对/好/可以 + Pinyin
    "是", "对", "好", "可以", "没问题", "好的",
    "shì", "shi", "duì", "dui", "hǎo", "hao", "kěyǐ", "keyi",
    # Japanese — はい/そうです/大丈夫/お願いします + romaji
    "はい", "そうです", "大丈夫", "お願いします", "了解",
    "hai", "sou desu", "soudesu", "daijoubu", "onegaishimasu", "ryoukai",
}

# Phrases the assistant uses right before a tool call. If the assistant's
# last reply contained one AND the user's current reply is an affirmation,
# we force tool_config=ANY so Gemini commits to the tool instead of looping.
# (직전 assistant 발화에 confirmation 패턴이 있고 사용자가 yes-class면 tool 강제)
_CONFIRMATION_PATTERNS = (
    "is that right",
    "is that correct",
    "confirming",
    "updating your order to",   # modify_order recital phrasing
    "updated to",                # alternate modify recital
    "your updated order is",
)

# Phrases the assistant emits AFTER a successful or no-op modify outcome.
# When one of these is in the recent transcript and the user has not used
# explicit modify intent words, a bare 'yes/okay' is a closing
# acknowledgement, not another modify command — suppress FORCE TOOL.
# (modify 결과 멘트 — 직후 yes는 종료 ack로 해석, FORCE TOOL 차단)
_MODIFY_OUTCOME_PHRASES = (
    "updated — your new total",
    "your order is unchanged",
)

# Words that signal the customer ACTUALLY wants to add/remove/change items.
# A bare yes / okay does NOT count. Only when one of these is present can
# we treat the turn as a real modify intent during the cooldown window.
# (수정 의도 키워드 — bare yes는 modify로 간주하지 않음)
_MODIFY_INTENT_TOKENS = {
    "add", "remove", "drop", "change", "instead", "actually",
    "another", "more", "less", "without", "with",
    "make it", "i changed my mind", "switch", "swap",
    # B2 fix — 'cancel' must clear the modify-cooldown gate so the
    # AUTO-fire recital fallback can fire and Gemini can pick the
    # cancel_order tool. Without this, MODIFY COOLDOWN swallowed the
    # cancel intent and yielded the closing line, leaving cancel_order
    # uncalled even though the customer explicitly asked to cancel
    # (live: call_1df4b018… T11/T12). Token only governs the cooldown
    # gate, not which tool runs — Gemini selects modify vs cancel per
    # system prompt rules 6/7.
    # (cancel — cooldown 통과만, 도구 선택은 system prompt가 분리)
    "cancel",
}


def _in_modify_cooldown(transcript: list[dict]) -> bool:
    """True iff one of the last 6 assistant turns ended a modify cycle
    (success or no-op). Used to suppress reflexive FORCE TOOL on bare
    yes/okay acks that follow a modify outcome.

    Window widened from 4 to 6 assistant turns: AUTO-fire BLOCKED
    recitals are themselves assistant turns, so when Gemini reflexively
    re-fires modify many times the success message gets pushed out of a
    too-narrow window and cooldown silently turns off (live regression
    in call_05bad4f12f… resp_id=13/14 — bare 'oh yeah' bypassed
    cooldown and modify_order ran a no-op against the same items).
    Counting only assistant turns (not all turns) keeps the window
    proportional to actual outcome distance, not user chatter.
    (4 → 6 — 자가 트리거 recital 사이에 success 메시지가 밀려나는 문제 보강)
    """
    agent_turns = [
        (t.get("content") or "").lower()
        for t in transcript
        if t.get("role") != "user"
    ][-6:]
    blob = " ".join(agent_turns)
    return any(p in blob for p in _MODIFY_OUTCOME_PHRASES)


def _has_explicit_modify_intent(user_text: str) -> bool:
    """True iff the user's current turn contains an explicit add/remove/
    change keyword. Bare yes/okay/thanks returns False.
    (사용자 발화에 명시적 수정 키워드가 있는지 — bare yes는 False)
    """
    lc = (user_text or "").lower()
    return any(tok in lc for tok in _MODIFY_INTENT_TOKENS)


# Filler / hesitation tokens. Used together to detect 'utterance carries
# only hesitation, no actual request' so the AUTO-fire gate can skip the
# recital entirely. 'oh wait wait wait' tokenizes to all-hesitation and
# the AI says 'Take your time.' instead of re-firing modify with stale
# items. Live: call_05bad4f12f… resp_id=11 'Oh, wait. Wait. Wait. Wait.'
# (망설임/필러 토큰만으로 구성된 발화 → recital 생략)
_HESITATION_TOKENS = {
    # Pure hesitation / filler — these on their own carry no request.
    "wait", "hold", "on", "um", "uh", "oh", "hmm", "ah", "er",
    "like", "actually", "well",
    "so", "you", "know", "i", "mean",
    "just", "and", "please", "sorry", "thanks", "thank",
    # NOTE: 'yes' / 'yeah' / 'okay' / 'ok' were here originally so
    # AUTO-firing Gemini on a bare ack during cooldown wouldn't recite
    # again. They're removed after call_24aaed77… where the customer's
    # genuine 'Yes' to a fresh recital ('updated order is X — is that
    # right?') was muted with 'Take your time.' because FORCE TOOL
    # detection had race-lost the recital. Affirmations are now handled
    # exclusively by detect_force_tool_use + the cooldown branch in the
    # AUTO-fire gate.
    # (yes/yeah/okay/ok 제거 — 진짜 affirmation 차단 회귀)
}


def _is_hesitation_only(text: str) -> bool:
    """True iff the utterance contains no word outside the hesitation
    set — pure filler. Single-word affirmations ('yes', 'okay') count
    as hesitation here intentionally; FORCE TOOL handles the real
    affirmation path through detect_force_tool_use, so an AUTO-firing
    Gemini on a bare yes during cooldown should NOT yield a recital.
    (필러 only — 진짜 요청이 없으면 recital 생략)
    """
    if not text:
        return True
    words = [w.strip(".,!?'\"-") for w in text.lower().split()]
    words = [w for w in words if w]
    if not words:
        return True
    return all(w in _HESITATION_TOKENS for w in words)


# ── Phase 2-C.B5 — Tier 3 severe-allergy / EpiPen signal detection ───────────
# (Phase 2-C.B5 — Tier 3 중증 알레르기 / EpiPen 신호 감지)
#
# Spec: backend/docs/specs/B5_allergen_qa.md §6d
# Compiled once at import; case-insensitive whole-word match (multi-word
# phrases are checked as substrings on a normalized space-bounded text).
# False-positive bias is intentional (Decision §10, risk-register row).

_SEVERE_ALLERGY_KEYWORDS: tuple[str, ...] = (
    "epipen",
    "epi pen",
    "epi-pen",
    "anaphylaxis",
    "anaphylactic",
    "life-threatening",
    "life threatening",
    "deathly allergic",
    "severely allergic",
    "severe allergy",
    "celiac",
    "coeliac",
    "hospitalized",
    "hospital",
    "react badly",
    "kill me",
)

# Pre-compile a single regex with each keyword wrapped in word boundaries.
# Hyphens are inside \b on most regex flavours but a leading/trailing word
# boundary on 'epi-pen' still matches the start/end of the phrase. For
# multi-word phrases ('react badly') the inner space is literal whitespace.
# (정규식 1회 컴파일 — 모든 키워드 word-boundary 매칭)
_SEVERE_ALLERGY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _SEVERE_ALLERGY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _has_severe_allergy_signal(transcript_user_turn: str) -> bool:
    """True iff the customer's most recent turn contains a Tier 3
    severe-allergy keyword (EpiPen, anaphylaxis, celiac, etc.). The
    voice dispatcher uses this BEFORE allergen_lookup fires to bypass
    even the curated answer and hand off to a manager — trace amounts
    and cross-contamination risk make even our operator data unsafe
    for severe cases. False-positive bias is intentional.
    (Tier 3 키워드 감지 — 양성 우선 보수 편향)
    """
    if not transcript_user_turn:
        return False
    return bool(_SEVERE_ALLERGY_RE.search(transcript_user_turn))


# ── Recital dedup (Wave 1 P0-1) ───────────────────────────────────────────────
# Live: call_9b67f4ec… T15→T16 emitted the same 'Just to confirm — your
# updated order is X — is that right?' twice within 1s because Retell
# issued partial→final transcript pair for the same user utterance
# ('Can you remove one garlic bread?'). The bot recited identically and
# the customer thought it was broken. These two helpers track the most
# recently yielded recital signature on the session and skip a duplicate
# emission inside an 8s window — long enough to absorb Retell echo and
# brief user pauses, short enough that a genuine new attempt later still
# gets a fresh prompt. The window does NOT slide on skip — original ts
# is kept so the deadline is deterministic.
# (recital 재발화 차단 — Retell partial→final echo + 사용자 혼란 흡수)
def _should_skip_recital(
    session: Optional[dict],
    recital_sig: str,
    now_ts: float,
    window_s: float = 8.0,
) -> bool:
    """True when an identical recital was yielded within window_s seconds.
    Mutates session to bump count but keeps original ts (no window slide).
    (같은 sig + 8초 내 → True; ts는 첫 발화 시각 유지)
    """
    if session is None:
        return False
    prev = session.get("last_recital_sig") or ("", 0.0, 0)
    prev_sig = prev[0] if len(prev) > 0 else ""
    prev_ts  = float(prev[1]) if len(prev) > 1 and prev[1] is not None else 0.0
    prev_cnt = int(prev[2])   if len(prev) > 2 and prev[2] is not None else 0
    if prev_sig and prev_sig == recital_sig and (now_ts - prev_ts) < window_s:
        session["last_recital_sig"] = (prev_sig, prev_ts, prev_cnt + 1)
        return True
    return False


def _remember_recital(
    session: Optional[dict],
    recital_sig: str,
    now_ts: float,
) -> None:
    """Record that this recital was just yielded — anchors the dedup window.
    (recital yield 직후 호출 — dedup window의 anchor)
    """
    if session is None:
        return
    session["last_recital_sig"] = (recital_sig, now_ts, 0)


# ── Tool-result yield dedup (Wave 1 P0-3) ─────────────────────────────────────
# Third dedup layer, distinct from last_tool_sig (5s tool-call window) and
# last_recital_sig (8s recital window). Operates on the literal yielded
# string from the bridge tool roundtrip. Live: call_9b67f4ec… T17/T18 (6s
# apart) yielded the same noop / clarification line because the upstream
# tool-call dedup window is 5s and T18 was just past it. Same string back
# to back makes the bot sound stuck even though every gate did its job.
# (msg 문자열 자체에 대한 8s 윈도 dedup — 같은 응답 재발화 차단)
def _should_skip_msg_repeat(
    session: Optional[dict],
    msg: str,
    now_ts: float,
    window_s: float = 8.0,
) -> bool:
    """True when this exact message string was yielded within window_s.
    Empty msg always returns False so the fallback yield path stays live.
    Mutates session to bump count but keeps original ts (no window slide).
    (같은 msg + 8초 내 → True; 빈 msg는 항상 False; ts 첫 발화 시각 유지)
    """
    if session is None or not msg:
        return False
    prev = session.get("last_msg_sig") or ("", 0.0, 0)
    prev_msg = prev[0] if len(prev) > 0 else ""
    prev_ts  = float(prev[1]) if len(prev) > 1 and prev[1] is not None else 0.0
    prev_cnt = int(prev[2])   if len(prev) > 2 and prev[2] is not None else 0
    if prev_msg and prev_msg == msg and (now_ts - prev_ts) < window_s:
        session["last_msg_sig"] = (prev_msg, prev_ts, prev_cnt + 1)
        return True
    return False


def _remember_msg(
    session: Optional[dict],
    msg: str,
    now_ts: float,
) -> None:
    """Record that this msg was just yielded — anchors the dedup window.
    No-op on None session or empty msg.
    (msg yield 직후 호출 — 빈 msg/None session은 no-op)
    """
    if session is None or not msg:
        return
    session["last_msg_sig"] = (msg, now_ts, 0)


# ── Modify clarification line (Wave 1 P0-2) ───────────────────────────────────
# When bridge.modify_order returns ai_script_hint='modify_noop' (items
# unchanged) AND the customer's last turn carried explicit modify intent
# (verbs like 'remove', 'add', 'change'), the standard MODIFY_ORDER_SCRIPT
# line — 'Your order is unchanged — total is still $X' — is misleading:
# the customer did try to change something, just for an item we couldn't
# reconcile (often off-menu, e.g. 'garlic bread' at JM Cafe). Live:
# call_9b67f4ec… T17/T18 said 'remove one garlic bread' twice and the
# bot kept asserting the order was unchanged without ever telling the
# customer the item wasn't on the menu. This helper builds an honest
# clarification that names the current order and asks the customer to
# specify the exact menu item. Only used when intent is True; the
# intent=False path keeps the original noop wording so happy-path acks
# ('okay', 'thanks') don't get nagged.
# (modify intent + noop → 명시 clarification; intent 없음은 기존 closing 유지)
def _build_modify_clarification(
    items: list,
    total_cents: int,
) -> str:
    """Customer-facing clarification when a modify attempt landed on noop.
    (수정 시도가 noop으로 끝났을 때 명확히 안내)
    """
    item_phrases: list[str] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        nm  = (it.get("name") or "").strip()
        if not nm:
            continue
        qty = int(it.get("quantity") or 1)
        plural = "" if qty == 1 else "s"
        item_phrases.append(f"{qty} {nm}{plural}")
    items_str   = ", ".join(item_phrases) if item_phrases else "your order"
    total_human = f"${total_cents / 100:.2f}"
    return (
        f"Hmm, I didn't catch the change. Your order is still {items_str} "
        f"for {total_human}. Could you tell me the exact item from our menu?"
    )


def _build_make_reservation_recital(args: dict) -> str:
    """Build the AUTO-FIRE recital for make_reservation.

    Speaks the FULL reservation summary so the customer can actually
    confirm what they're agreeing to. Earlier the fallback was just
    "Just to confirm a reservation for {name} — is that right?" which
    omitted party/date/time — customer says "yes" without knowing what
    they confirmed (live: call_ebdc036d T2). Issue Σ fix mirrors B3's
    _build_modify_reservation_recital wording.
    (예약 생성 recital — 전체 요약 발화로 무지성 confirm 차단)
    """
    raw_name = (args.get("customer_name") or "").strip()
    name = "you" if is_placeholder_name(raw_name) else raw_name
    date_human = format_date_human(args.get("reservation_date") or "")
    time_human = format_time_12h(args.get("reservation_time") or "")
    try:
        party = int(args.get("party_size") or 0)
    except (TypeError, ValueError):
        party = 0
    return (
        f"Confirming a reservation for {name}, party of {party}, "
        f"on {date_human} at {time_human} — is that right?"
    )


def _build_modify_reservation_recital(args: dict) -> str:
    """Build the AUTO-FIRE recital for modify_reservation.

    Pulls the four mutable fields out of tool_args (full payload) and
    falls back to 'you' on a placeholder customer_name (INVARIANT I2).
    Speaks the time in 12-h with AM/PM and the date in human form.
    (예약 수정 recital — placeholder name이면 'you' 폴백)
    """
    raw_name = (args.get("customer_name") or "").strip()
    name = "you" if is_placeholder_name(raw_name) else raw_name
    date_human = format_date_human(args.get("reservation_date") or "")
    time_human = format_time_12h(args.get("reservation_time") or "")
    try:
        party = int(args.get("party_size") or 0)
    except (TypeError, ValueError):
        party = 0
    return (
        f"Just to confirm — your updated reservation is for {name}, "
        f"party of {party}, on {date_human} at {time_human} "
        f"— is that right?"
    )


def _format_reservation_summary_for_session(
    *,
    party_size:       int,
    reservation_date: str,
    reservation_time: str,
) -> str:
    """Build the human-readable session summary for a successful
    make_reservation / modify_reservation. Used to seed
    session['last_reservation_summary'] which the cancel recital reads.
    (세션 요약 빌더 — make/modify 성공 후 cancel recital용)
    """
    date_human = format_date_human(reservation_date or "")
    time_human = format_time_12h(reservation_time or "")
    try:
        party = int(party_size or 0)
    except (TypeError, ValueError):
        party = 0
    return f"party of {party} on {date_human} at {time_human}"


def _build_pending_reservation_email_payload(
    *,
    args:           dict,
    reservation_id: int,
    store_name:     str,
    prior_payload:  Optional[dict],
) -> Optional[dict]:
    """Build (or refresh) the pending reservation email payload from
    tool_args after a successful make_reservation / modify_reservation.

    The voice handler stashes the result on session['pending_reservation_email']
    and the WS disconnect path fires it. Returning None means there's no
    way to email this customer (no email in args AND no prior payload to
    carry over) — caller skips the snapshot.

    Email carry-over rule: modify_reservation often omits customer_email
    (full payload contract makes it optional and Gemini frequently drops
    optional fields). When that happens, we keep the email captured at
    the original make_reservation so the FINAL state still gets emailed.
    (modify에서 email 없으면 prior에서 carry-over)
    """
    args_email = (args.get("customer_email") or "").strip()
    prior_email = ""
    if prior_payload and isinstance(prior_payload, dict):
        prior_email = (prior_payload.get("to") or "").strip()
    to_addr = args_email or prior_email
    if not to_addr:
        return None

    raw_name = (args.get("customer_name") or "").strip()
    name = "" if is_placeholder_name(raw_name) else raw_name
    date_human = format_date_human(args.get("reservation_date") or "")
    time_human = format_time_12h(args.get("reservation_time") or "")
    try:
        party = int(args.get("party_size") or 0)
    except (TypeError, ValueError):
        party = 0
    notes = (args.get("notes") or "").strip()

    return {
        "to":             to_addr,
        "customer_name":  name,
        "store_name":     store_name or "the restaurant",
        "party_size":     party,
        "date_human":     date_human,
        "time_12h":       time_human,
        "notes":          notes,
        "reservation_id": int(reservation_id) if reservation_id is not None else 0,
    }


def _build_cancel_reservation_recital(session: Optional[dict]) -> str:
    """Build the AUTO-FIRE recital for cancel_reservation.

    Cancel tool args carry NO reservation data (caller-id only), so the
    recital is sourced from session['last_reservation_summary'] which
    was populated by the most recent successful make_reservation /
    modify_reservation. When the session has no summary (cancel
    attempted before any make/modify in this call), fall back to a
    generic 'your reservation' phrase — the bridge will then return
    cancel_reservation_no_target right after the FORCE TOOL fires, but
    the recital still serves as an explicit confirmation gate so a
    misheard 'cancel' never silently triggers a cancel attempt.
    (cancel recital — session summary에서 끌어옴, 없으면 generic 폴백)
    """
    summary = ((session or {}).get("last_reservation_summary") or "").strip()
    if summary:
        return (
            f"Just to confirm — you want to cancel your reservation "
            f"for {summary} — is that right?"
        )
    return (
        "Just to confirm — you want to cancel your reservation "
        "— is that right?"
    )


def _has_recent_explicit_modify_intent(transcript: list[dict], n_user: int = 3) -> bool:
    """True iff ANY of the last N user turns contains explicit modify
    intent. Kept for back-compat / tests; new code should prefer
    _has_explicit_modify_intent_since_outcome which is outcome-anchored.
    (최근 N user turns 중 하나라도 modify 의도 → True; 후방호환용)
    """
    user_turns = [
        (t.get("content") or "")
        for t in transcript
        if t.get("role") == "user"
    ][-n_user:]
    return any(_has_explicit_modify_intent(t) for t in user_turns)


def _has_explicit_modify_intent_since_outcome(transcript: list[dict]) -> bool:
    """True iff a user turn AFTER the most recent modify outcome
    contains explicit modify intent. If no outcome is in the transcript,
    falls back to the last-3-user-turns check.

    Why outcome-anchored: the simpler 'last 3 user turns' check kept
    legacy intent words alive across multiple post-outcome acks, so a
    bare 'yeah' / 'yes' after a successful modify kept re-firing
    modify_order with the same items (live: call_2a3bdd9a…, 5 redundant
    fires). Anchoring on the latest outcome makes the gate read 'has
    the customer expressed a NEW modify intent since the last commit?'
    which is the actual question we care about.
    (직전 outcome 이후 user intent만 검사 — 묵은 intent로 인한 loop 차단)
    """
    last_outcome_idx = -1
    for i, t in enumerate(transcript):
        if t.get("role") == "user":
            continue
        c = (t.get("content") or "").lower()
        if any(p in c for p in _MODIFY_OUTCOME_PHRASES):
            last_outcome_idx = i

    if last_outcome_idx == -1:
        # No outcome yet — there's nothing to "anchor on", so fall back
        # to the recent-window check so the first real modify intent is
        # still picked up correctly.
        return _has_recent_explicit_modify_intent(transcript)

    for t in transcript[last_outcome_idx + 1:]:
        if t.get("role") == "user":
            if _has_explicit_modify_intent(t.get("content") or ""):
                return True
    return False


def detect_force_tool_use(transcript: list[dict]) -> bool:
    """Heuristic: should we force Gemini into tool-call mode this turn?
    True iff the last assistant message recited a confirmation AND the
    user's current message is a clear affirmation. Stops the confirm-loop
    bug where Gemini ignores 'yes' and keeps re-asking.

    Modify cooldown: if a recent assistant turn ended a modify cycle and
    the user's current message has no explicit modify intent, suppress
    FORCE TOOL — the yes is a closing ack, not a new modify command.
    Without this, every post-modify 'okay' triggers another modify and
    the customer hears 'Updated …' / 'Your order is unchanged' on
    repeat (live-observed in call_feede2b9… and call_838fa514…).
    (마지막 assistant 발화 confirmation + 사용자 yes → tool 강제. 단,
     modify 직후 cooldown 중에는 명시 수정 키워드 없으면 차단)
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
    is_affirmation = bool(user_tokens & _AFFIRMATION_TOKENS) or any(
        phrase in last_user for phrase in _AFFIRMATION_TOKENS
    )
    if not is_affirmation:
        return False

    # Cooldown gate — bare yes/okay after a modify outcome is a closing
    # ack, not a new modify command. Allow FORCE TOOL during cooldown
    # only when the customer expressed explicit add/remove/change intent
    # AFTER the most recent modify outcome (not before).
    if (
        _in_modify_cooldown(transcript)
        and not _has_explicit_modify_intent_since_outcome(transcript)
    ):
        return False

    return True


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
                          "business_hours,custom_knowledge,menu_cache,is_active",
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
    in_modify_cooldown: bool = False,
    user_has_modify_intent: bool = False,
    last_user_text: str = "",
    modify_count: int = 0,
    session: Optional[dict] = None,
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
            MODIFY_RESERVATION_TOOL_DEF,
            CANCEL_RESERVATION_TOOL_DEF,
            ORDER_TOOL_DEF,
            MODIFY_ORDER_TOOL_DEF,
            CANCEL_ORDER_TOOL_DEF,
            ALLERGEN_LOOKUP_TOOL_DEF,        # Phase 2-C.B5
            RECALL_ORDER_TOOL_DEF,           # Phase 2-C.B6
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

    # ── Recent-signature dedup (Proposal R, Fix #2 timing) ────────────────
    # Retell's transcript echo lags behind our yields; that lag lets a
    # FORCE TOOL fire on a stale assistant recital trigger the same tool
    # call with the same items 2-4× in a row, even though the bridge
    # has already committed. Dedupe the exact tool+items signature
    # within a 5-second window per session. CRITICAL: the signature is
    # saved ONLY AFTER the bridge actually returns success — saving it
    # earlier (e.g. on AUTO-fire BLOCKED) made the gate fire 'Got it —
    # already on it.' on the very NEXT user turn even though nothing
    # had committed yet (live: call_24aaed77… resp_id 27/28).
    # (sig 저장은 실제 bridge 성공 후 — false dedup 방지)
    sig_str = ""
    if session is not None and tool_name in ("create_order", "modify_order"):
        items_for_sig: list[tuple[str, int]] = []
        try:
            for it in (tool_args.get("items") or []):
                d  = dict(it) if not isinstance(it, dict) else it
                nm = (d.get("name") or "").strip().lower()
                qt = int(d.get("quantity") or 0)
                if nm and qt > 0:
                    items_for_sig.append((nm, qt))
        except Exception:
            pass
        sig_str = "|".join(f"{n}:{q}" for n, q in sorted(items_for_sig))
        prev = session.get("last_tool_sig") or ("", "", 0.0)
        prev_name, prev_sig, prev_ts = (prev[0], prev[1], float(prev[2] or 0.0))
        now_ts = time.time()
        if (
            prev_name == tool_name
            and prev_sig == sig_str
            and sig_str
            and (now_ts - prev_ts) < 5.0
        ):
            elapsed = now_ts - prev_ts
            _mon("TOOL DEDUP tool=%s sig=%s elapsed=%.1fs — within 5s, skipping",
                 tool_name, sig_str[:80], elapsed)
            # Silent skip when the dedup fires within 2s of the prior
            # commit — that's a Gemini double-trigger / transcript-echo
            # artifact, NOT a user re-confirmation. The success line is
            # still mid-flight on the audio path, so adding 'Got it —
            # already on it.' produces back-to-back voice output ~1s
            # apart (live: call_2bd477d1… resp_id 18→19, 18:33:34→35).
            # Beyond 2s the customer has had time to think and re-affirm,
            # so the verbal ack is the right behavior.
            # (1초 간격 더블 발화 차단 — 진짜 재확인은 ≥2s 후 들어옴)
            if elapsed >= 2.0:
                yield "Got it — already on it."
            return
        # NOTE: do NOT save sig_str yet. Save it only after the bridge
        # returns success (in the create_order / modify_order success
        # branches below). That prevents AUTO-fire BLOCKED paths from
        # poisoning the dedup window for the next turn.

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
    if tool_name in ("create_order", "make_reservation", "modify_order", "cancel_order", "modify_reservation", "cancel_reservation") and not force_tool_use:
        # Hesitation-only short-circuit (Proposal E). When the customer's
        # current turn is filler/hesitation only ('oh wait wait wait'),
        # emit a brief 'Take your time' and stay silent — never recite
        # stale items, never re-fire the same modify. Live: call_05bad4f…
        # spent 4 turns on 'wait wait' and Gemini fired modify_order with
        # unchanged items each time.
        # (필러 only → recital 생략, 짧은 안내만)
        if tool_name == "modify_order" and _is_hesitation_only(last_user_text):
            _mon("AUTO-FIRE BLOCKED (hesitation-only) tool=%s user=%r → calm line",
                 tool_name, last_user_text[:40])
            yield "Take your time."
            return

        # Per-call modify cap (Proposal F, threshold 4). Only applies when
        # the customer's current turn has NO explicit modify intent —
        # Proposal P fix after call_aefb581b… turn 28 where 'I changed my
        # mind. I changed my mind.' (real intent) was blocked by the cap.
        # When intent is present we trust the customer; the cap is only
        # for runaway reflexive AUTO re-fires.
        # (intent 있으면 cap 무시 — 합법적 modify는 항상 통과)
        if (
            tool_name == "modify_order"
            and modify_count >= 4
            and not user_has_modify_intent
        ):
            _mon("AUTO-FIRE BLOCKED (modify cap %d) tool=%s → closing line",
                 modify_count, tool_name)
            yield "Got it — your order is set. Tap the payment link whenever you're ready."
            return

        # Modify-cooldown special case: if Gemini is reflexively re-firing
        # modify_order right after a successful (or no-op) modify AND the
        # customer's current turn has no explicit add/remove/change intent
        # (and no recent 3-turn intent either), do NOT yield a recital.
        # Yield a closing line so detect_force_tool_use returns False on
        # the next yes.
        # (cooldown + 명시 수정 의도 부재 → closing)
        if (
            tool_name == "modify_order"
            and in_modify_cooldown
            and not user_has_modify_intent
        ):
            # Proposal I — first cooldown turn after a real outcome
            # gets a warm summary recap; later turns get the short
            # closing line. Customers can hang up on either.
            # (첫 cooldown은 order summary, 이후는 짧은 closing)
            sess_items = (session or {}).get("last_order_items") or []
            sess_total = int((session or {}).get("last_order_total") or 0)
            already_sent = bool((session or {}).get("closing_emitted"))
            if sess_items and sess_total and not already_sent:
                phrase_parts = []
                for it in sess_items:
                    qty = int(it.get("quantity") or 1) if isinstance(it, dict) else 1
                    nm  = (it.get("name") if isinstance(it, dict) else "") or "item"
                    plural = "" if qty == 1 else "s"
                    phrase_parts.append(f"{qty} {nm}{plural}")
                phrase = ", ".join(phrase_parts) if phrase_parts else "your order"
                summary = (
                    f"Your order — {phrase} for ${sess_total / 100:.2f} — will be ready "
                    f"as soon as the payment lands. Thanks for calling JM Cafe, see you soon!"
                )
                if session is not None:
                    session["closing_emitted"] = True
                _mon("AUTO-FIRE BLOCKED (cooldown, no intent) tool=%s → order summary closing",
                     tool_name)
                yield summary
                return
            _mon("AUTO-FIRE BLOCKED (modify cooldown, no intent) tool=%s items=%d → closing line",
                 tool_name, len(tool_args.get("items") or []))
            yield "Got it — your order is set. Tap the payment link whenever you're ready."
            return
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
        # Recital name guard — Gemini sometimes fills customer_name with a
        # placeholder ('Customer', 'Global', 'unknown', 'Unknown Customer').
        # The bridge validate path rejects these on the actual create_order,
        # but the AUTO-FIRE recital fires BEFORE that and would otherwise
        # say "for unknown — is that right?". Fall back to "you" when the
        # raw name is empty or any token matches a placeholder. Live
        # observed: call_6b935ab0 ('Customer'), call_1df4b018 ('Global'),
        # call_f424f5b86 ('unknown').
        # (placeholder 이름이면 "you"로 폴백 — bridge가 다음 단계에서 reject)
        raw_recital_name = (tool_args.get("customer_name") or "").strip()
        recital_name = "you" if is_placeholder_name(raw_recital_name) else raw_recital_name
        if tool_name == "create_order":
            phrase = ", ".join(items_for_recital) or "your order"
            recital = (f"Just to confirm, that's {phrase} for {recital_name} "
                       f"— is that right?")
        elif tool_name == "modify_order":
            phrase = ", ".join(items_for_recital) or "your order"
            recital = (f"Just to confirm — your updated order is {phrase} "
                       f"— is that right?")
        elif tool_name == "cancel_order":
            # Cancel tool args carry no items (caller-id lookup only), so
            # pull the in-flight order summary from the session snapshot
            # populated by the most recent create/modify success. This
            # ensures the recital quotes the actual order the customer is
            # about to lose, not stale or empty data. If no snapshot is
            # available (cancel attempted without a prior order), fall
            # back to a generic recital — bridge will return cancel_no_target
            # right after the FORCE TOOL fires.
            # (cancel은 args에 items 없음 — session snapshot에서 끌어옴)
            sess_items = (session or {}).get("last_order_items") or []
            sess_total = int((session or {}).get("last_order_total") or 0)
            phrase_parts: list[str] = []
            for it in sess_items:
                if not isinstance(it, dict):
                    continue
                qty = int(it.get("quantity") or 1)
                nm  = (it.get("name") or "").strip()
                if not nm:
                    continue
                plural = "" if qty == 1 else "s"
                phrase_parts.append(f"{qty} {nm}{plural}")
            if phrase_parts:
                phrase     = ", ".join(phrase_parts)
                total_str  = f" for ${sess_total / 100:.2f}" if sess_total else ""
                recital = (f"Just to confirm — you want to cancel your order "
                           f"for {phrase}{total_str} — is that right?")
            else:
                recital = ("Just to confirm — you want to cancel your order "
                           "— is that right?")
        elif tool_name == "modify_reservation":
            # B3 — full payload, all 5 mutable fields in tool_args. Helper
            # builds the recital with placeholder-name fallback.
            recital = _build_modify_reservation_recital(tool_args)
        elif tool_name == "cancel_reservation":
            # B4 — caller-id only schema, no payload. Recital sources the
            # reservation summary from session['last_reservation_summary'],
            # populated by the most recent make/modify success. Empty
            # snapshot → generic 'your reservation' fallback (bridge will
            # then return cancel_reservation_no_target after FORCE TOOL).
            recital = _build_cancel_reservation_recital(session)
        elif tool_name == "make_reservation":
            # Issue Σ — full reservation summary so the customer can
            # actually confirm party/date/time. Stub fallback below was
            # only emitted before this branch existed (live regression
            # call_ebdc036d T2: "Just to confirm a reservation for Sofia
            # Chang — is that right?" with no party/date/time).
            recital = _build_make_reservation_recital(tool_args)
        else:
            recital = (f"Just to confirm a reservation for {recital_name} "
                       f"— is that right?")
        # Recital dedup (Wave 1 P0-1) — same recital sig within 8s is a
        # Retell partial→final transcript echo or a confused customer
        # repeating the same out-of-menu request. Repeating the recital
        # makes the bot sound broken; silent skip lets the prior recital
        # stand and Retell's reminder cadence (6s x 2) handles any
        # follow-up nudge. Items_for_recital is the full ordered list,
        # so any legitimate change in items produces a different sig
        # and bypasses the skip.
        # (recital 재발화 차단 — Retell echo + same-utterance 재시도)
        recital_sig = f"{tool_name}|{','.join(items_for_recital)}"
        now_ts = time.time()
        if _should_skip_recital(session, recital_sig, now_ts):
            _mon("RECITAL DEDUP tool=%s sig=%s — within 8s, silent skip",
                 tool_name, recital_sig[:80])
            return
        _mon("AUTO-FIRE BLOCKED tool=%s args_phone=%r args_name=%r args_email=%r "
             "items=%d → recital fallback",
             tool_name,
             tool_args.get("customer_phone") or "",
             tool_args.get("customer_name") or "",
             tool_args.get("customer_email") or "",
             len(tool_args.get("items") or []))
        _remember_recital(session, recital_sig, now_ts)
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

            # Snapshot the reservation summary so a subsequent
            # cancel_reservation recital can quote the actual booking
            # the customer is about to lose. Mirrors last_order_items
            # for orders. (B4 — make_reservation success path)
            # (cancel recital용 summary 스냅샷)
            if session is not None:
                try:
                    session["last_reservation_summary"] = (
                        _format_reservation_summary_for_session(
                            party_size       = int(tool_args.get("party_size") or 0),
                            reservation_date = tool_args.get("reservation_date", ""),
                            reservation_time = tool_args.get("reservation_time", ""),
                        )
                    )
                except Exception as exc:
                    _mon("last_reservation_summary snapshot error (make): %s", exc)

            # Snapshot pending reservation email payload — TCR-fallback
            # delivery channel. Single email per call: this overwrites any
            # earlier draft, modify_reservation will refresh it, and the
            # WS disconnect handler fires the FINAL state exactly once.
            # Cancellation wipes the snapshot so nothing goes out.
            # (B4 — defer-and-fire-on-end semantic; Twilio TCR 펜딩 우회)
            if session is not None:
                try:
                    pending = _build_pending_reservation_email_payload(
                        args            = tool_args,
                        reservation_id  = bridge_result.get("pos_object_id") or 0,
                        store_name      = store_name or "",
                        prior_payload   = session.get("pending_reservation_email"),
                    )
                    session["pending_reservation_email"] = pending
                    _mon("RES EMAIL PENDING set make to=%s party=%s",
                         (pending or {}).get("to") or "",
                         (pending or {}).get("party_size") or "")
                except Exception as exc:
                    _mon("pending_reservation_email snapshot error (make): %s", exc)

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

        # Proposal Q — when bridge rejects with sold_out / unknown_item,
        # name the unavailable item explicitly. The bridge gives us the
        # unavailable list; the AI's recovery line should NAME the item
        # so the customer doesn't get a generic 'something else' nudge
        # and silently re-order the same thing (live in 1st call turn 12).
        # (sold_out / unknown 시 unavailable item 명시)
        if hint == "rejected":
            unavail = bridge_result.get("unavailable") or []
            unavail_names: list[str] = []
            try:
                for u in unavail:
                    nm = (u.get("name") if isinstance(u, dict) else "") or ""
                    if nm and nm not in unavail_names:
                        unavail_names.append(nm)
            except Exception:
                pass
            if unavail_names:
                if len(unavail_names) == 1:
                    naming = unavail_names[0]
                elif len(unavail_names) == 2:
                    naming = f"{unavail_names[0]} and {unavail_names[1]}"
                else:
                    naming = ", ".join(unavail_names[:-1]) + f", and {unavail_names[-1]}"
                reason = bridge_result.get("reason") or "unavailable"
                if reason == "sold_out":
                    lead = f"Sorry, {naming} just sold out today."
                else:
                    lead = f"Sorry, we don't have {naming} on the menu."
                script = (
                    f"{lead} Could I get you something else? — feel free to ask "
                    f"what's available."
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

            # Snapshot items + total to the session for the closing-summary
            # line (Proposal I). Skip on idempotent re-hits — the original
            # entry already wrote the snapshot.
            # (closing line용 items/total 스냅샷)
            if session is not None and not bridge_result.get("idempotent"):
                session["last_order_items"] = bridge_result.get("items") or []
                session["last_order_total"] = int(bridge_result.get("total_cents") or 0)
                session["closing_emitted"]  = False
            # Stamp the dedup sig now that the bridge actually committed
            # (Fix #2). Doing this AFTER the success branch — instead of
            # before the AUTO-fire gate — prevents false-positive dedups.
            # (실제 commit 후에만 sig 저장 — false dedup 방지)
            if session is not None and sig_str:
                session["last_tool_sig"] = (tool_name, sig_str, time.time())

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
            # Issue #2 fix — stamp the dedup sig on DETERMINISTIC failures
            # (sold_out / unknown_item) so the same items don't fire again
            # on the very next confirmation. Same items + same menu +
            # same store = same answer; re-firing wastes a turn and the
            # customer hears the same rejection (live: call_b57c581b…
            # turn 16/17 fired sold_out twice in a row). pos_failure is
            # NOT included — those are transient network blips, the
            # customer should be allowed to retry.
            # (sold_out/unknown_item은 deterministic — sig 저장으로 즉시 dedup)
            if (
                session is not None
                and sig_str
                and bridge_result.get("reason") in ("sold_out", "unknown_item")
            ):
                session["last_tool_sig"] = (tool_name, sig_str, time.time())
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

        # Track modify count on the session so the AUTO-fire gate's
        # per-call cap (Proposal F) can refuse runaway re-fires. We
        # bump on any successful outcome including modify_noop — both
        # exercise the same code path and cost the same audit work.
        # Also snapshot the latest committed items + total so the
        # closing-summary line (Proposal I) can recap the order back to
        # the customer when they end the call.
        # (modify 카운트 + 최신 items/total 스냅샷 — closing line 용)
        if session is not None and bridge_result.get("success"):
            session["modify_count"] = int(session.get("modify_count") or 0) + 1
            session["last_order_items"] = bridge_result.get("items") or session.get("last_order_items") or []
            session["last_order_total"] = int(bridge_result.get("total_cents") or session.get("last_order_total") or 0)
            # A NEW outcome resets the closing flag so a subsequent
            # cooldown period can speak the recap once for the new state.
            session["closing_emitted"] = False
            # Stamp the dedup sig now that the bridge actually committed
            # (Fix #2 — see create_order branch above for the same logic).
            if sig_str:
                session["last_tool_sig"] = (tool_name, sig_str, time.time())

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

        # Wave 1 P0-2 — when bridge returns modify_noop AND the customer's
        # last turn carried explicit modify intent, swap in a clarification
        # line that names the current order and asks for the exact menu
        # item. The standard noop line ('Your order is unchanged') is fine
        # for benign acks ('okay', 'thanks') but actively misleading when
        # the customer just tried to add or remove something the bridge
        # couldn't match — usually an off-menu item like 'garlic bread'
        # (live: call_9b67f4ec… T17/T18). Intent=False path keeps the
        # original wording untouched so the closing line still works.
        # (modify intent + noop → clarification; intent 없음은 그대로)
        if hint == "modify_noop" and user_has_modify_intent:
            script = _build_modify_clarification(
                items       = bridge_result.get("items") or [],
                total_cents = new_total_cents,
            )

        # Issue #1 fix — name the unavailable item on rejected results in
        # the modify path too. Was applied to create_order earlier; the
        # modify branch was getting the generic 'one or more items
        # aren't available right now' message even when the bridge knew
        # exactly which item failed (live: call_b57c581b… turn 16, 2x
        # Americano sold-out).
        # (modify branch에도 unavailable item naming 적용)
        if hint == "rejected":
            unavail = bridge_result.get("unavailable") or []
            unavail_names: list[str] = []
            try:
                for u in unavail:
                    nm = (u.get("name") if isinstance(u, dict) else "") or ""
                    if nm and nm not in unavail_names:
                        unavail_names.append(nm)
            except Exception:
                pass
            if unavail_names:
                if len(unavail_names) == 1:
                    naming = unavail_names[0]
                elif len(unavail_names) == 2:
                    naming = f"{unavail_names[0]} and {unavail_names[1]}"
                else:
                    naming = ", ".join(unavail_names[:-1]) + f", and {unavail_names[-1]}"
                reason = bridge_result.get("reason") or "unavailable"
                if reason == "sold_out":
                    lead = f"Sorry, {naming} just sold out today."
                else:
                    lead = f"Sorry, we don't have {naming} on the menu."
                script = (
                    f"{lead} Would you like something else? — feel free to ask "
                    f"what's available."
                )

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
            # Issue #2 fix — same as create_order branch: stamp the dedup
            # sig on DETERMINISTIC failures so the next bare confirmation
            # against the same items short-circuits.
            # (modify branch에도 sold_out/unknown_item dedup 적용)
            if (
                session is not None
                and sig_str
                and bridge_result.get("reason") in ("sold_out", "unknown_item")
            ):
                session["last_tool_sig"] = (tool_name, sig_str, time.time())
    elif tool_name == "cancel_order":
        # B2 (Phase 2-C.2) — cancel an in-flight order. Bridge owns
        # target lookup (caller-id, in-flight states pending/payment_sent/
        # fired_unpaid), state-machine guard, persistence via advance_state,
        # audit. No POS-side void in V1 (FIRED_UNPAID hint tells the
        # customer to flag staff at the counter). Tool args carry only
        # user_explicit_confirmation — no items, no phone, no name —
        # so we ignore tool_args here and pass caller_phone_e164 only.
        # (B2 — args 최소, caller-id로 식별)
        bridge_result = await bridge_flows.cancel_order(
            store_id          = store_id,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = call_log_id,
        )

        hint = bridge_result.get("ai_script_hint", "")
        # Cancel-specific scripts only — no fallback to ORDER_SCRIPT_BY_HINT
        # because cancel hints (cancel_success / cancel_no_target / etc.)
        # are distinct from create / modify hints. Final fallback is a
        # generic acknowledgment so silence never reaches the caller.
        # (cancel 전용 스크립트 — 폴백은 generic ack)
        script = CANCEL_ORDER_SCRIPT_BY_HINT.get(
            hint,
            "Got it — let me get someone on the line to help.",
        )

        if bridge_result.get("success"):
            result = {
                "success":         True,
                "transaction_id":  bridge_result.get("transaction_id"),
                "lane":            bridge_result.get("lane"),
                "state":           bridge_result.get("state"),
                "prior_state":     bridge_result.get("prior_state"),
                "total_cents":     int(bridge_result.get("total_cents") or 0),
                "items":           bridge_result.get("items"),
                "message":         script,
            }
            # Snapshot reset — the in-flight order is gone. Closing-summary
            # line should not recap a cancelled order on the next ack.
            # (cancel success 후 closing recap 차단)
            if session is not None:
                session["last_order_items"] = []
                session["last_order_total"] = 0
                session["closing_emitted"]  = True
        else:
            result = {
                "success":         False,
                "transaction_id":  bridge_result.get("transaction_id"),
                "state":           bridge_result.get("state"),
                "reason":          bridge_result.get("reason"),
                "message":         script,
                "error":           bridge_result.get("error", ""),
            }
    elif tool_name == "modify_reservation":
        # B3 (Phase 2-C.B3) — update the most-recent confirmed reservation
        # for this caller. Full-payload contract: Gemini sends all 5
        # mutable fields (name/date/time/party/notes); bridge computes the
        # diff and patches only changed columns. caller-id locates the
        # target via _find_modifiable_reservation. v1 stores reservations
        # in the legacy `reservations` table (not bridge_transactions).
        # (B3 — 최근 confirmed 예약 수정, full-payload + diff)
        bridge_result = await bridge_flows.modify_reservation(
            store_id          = store_id,
            args              = tool_args,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = call_log_id,
        )
        hint = bridge_result.get("ai_script_hint", "validation_failed")
        template = MODIFY_RESERVATION_SCRIPT_BY_HINT.get(
            hint,
            "Sorry, I had trouble changing that. Let me connect you with our manager.",
        )
        # Format any {new_summary} placeholder if the bridge produced one.
        try:
            script = template.format(
                new_summary=bridge_result.get("new_summary", "your reservation"),
            )
        except (KeyError, IndexError):
            script = template
        result = {
            "success":        bool(bridge_result.get("success")),
            "reservation_id": bridge_result.get("reservation_id"),
            "diff":           bridge_result.get("diff", {}),
            "reason":         bridge_result.get("reason"),
            "message":        script,
            "error":          bridge_result.get("error", ""),
        }
        # Refresh session reservation summary on a real diff success
        # so a follow-up cancel_reservation recital quotes the NEW
        # values. modify_noop is treated as success but doesn't change
        # the row — leave the prior summary in place. (B4)
        # (modify success → cancel recital용 summary 갱신)
        if (
            session is not None
            and bridge_result.get("success")
            and bridge_result.get("ai_script_hint") == "modify_success"
        ):
            try:
                session["last_reservation_summary"] = (
                    _format_reservation_summary_for_session(
                        party_size       = int(tool_args.get("party_size") or 0),
                        reservation_date = tool_args.get("reservation_date", ""),
                        reservation_time = tool_args.get("reservation_time", ""),
                    )
                )
            except Exception as exc:
                _mon("last_reservation_summary refresh error (modify): %s", exc)
            # Refresh pending email payload — modify_reservation often
            # omits customer_email, so the helper carries it over from
            # the original make_reservation snapshot. (B4 supersede)
            try:
                pending = _build_pending_reservation_email_payload(
                    args            = tool_args,
                    reservation_id  = bridge_result.get("reservation_id") or 0,
                    store_name      = store_name or "",
                    prior_payload   = session.get("pending_reservation_email"),
                )
                session["pending_reservation_email"] = pending
                _mon("RES EMAIL PENDING refresh modify to=%s party=%s",
                     (pending or {}).get("to") or "",
                     (pending or {}).get("party_size") or "")
            except Exception as exc:
                _mon("pending_reservation_email refresh error (modify): %s", exc)
    elif tool_name == "cancel_reservation":
        # B4 (Phase 2-C.B4) — cancel the most-recent confirmed reservation
        # for this caller. Bridge owns target lookup (caller-id, status=
        # 'confirmed' filter), already-cancelled probe, status PATCH,
        # logging. Tool args carry only user_explicit_confirmation — no
        # phone/name/id/date — so we ignore tool_args here and pass
        # caller_phone_e164 only. Option α: no too-late guard (cancel is
        # always allowed once a row exists).
        # (B4 — args 최소, caller-id로 식별, 컷오프 없음)
        bridge_result = await bridge_flows.cancel_reservation(
            store_id          = store_id,
            caller_phone_e164 = caller_phone_e164,
            call_log_id       = call_log_id,
        )
        hint = bridge_result.get("ai_script_hint", "cancel_reservation_failed")
        template = CANCEL_RESERVATION_SCRIPT_BY_HINT.get(
            hint,
            "Sorry, I had trouble cancelling that. Let me connect you with our manager.",
        )
        try:
            script = template.format(
                cancelled_summary=bridge_result.get(
                    "cancelled_summary", "your reservation"
                ),
            )
        except (KeyError, IndexError):
            script = template

        result = {
            "success":        bool(bridge_result.get("success")),
            "reservation_id": bridge_result.get("reservation_id"),
            "prior_status":   bridge_result.get("prior_status"),
            "reason":         bridge_result.get("reason"),
            "message":        script,
            "error":          bridge_result.get("error", ""),
        }
        # Wipe the snapshot on success — the reservation is gone, so a
        # follow-up cancel attempt should hit the no_target / already_
        # canceled path with a generic recital, not re-quote a stale
        # summary the customer no longer has. (mirrors B2 behavior)
        # (cancel success → snapshot clear)
        if session is not None and bridge_result.get("success"):
            session["last_reservation_summary"] = ""
            # Wipe the pending email payload — the cancelled reservation
            # must NOT result in a confirmation email at WS disconnect.
            # (B4 — cancel suppresses the deferred email)
            session["pending_reservation_email"] = None
            _mon("RES EMAIL PENDING cleared cancel")
    elif tool_name == "allergen_lookup":
        # Phase 2-C.B5 — read-only allergen / dietary Q&A.
        # (Phase 2-C.B5 — 읽기 전용 알레르겐/식이 조회)
        #
        # Tier 3 intercept (spec §6d): if the customer's last turn carries
        # a severe-allergy keyword (EpiPen, anaphylaxis, celiac, etc.),
        # SKIP the curated lookup entirely and offer manager handoff —
        # trace amounts + cross-contamination risk make even our data
        # unsafe to communicate for severe cases. False-positive bias is
        # intentional (Decision §10).
        # (Tier 3 — 중증 알레르기 신호 시 lookup 우회 + 매니저 인계)
        if _has_severe_allergy_signal(last_user_text):
            _mon("ALLERGEN TIER3 intercept user=%r — skipping allergen_lookup",
                 (last_user_text or "")[:80])
            # Phase 5 #26 — fire manager alert (V0+, email channel) once per call.
            # The verbal hand-off below tells the caller a manager will follow up;
            # this email is the operator-side leg that was missing pre-Phase-5.
            # (Tier 3 매니저 이메일 fire-and-forget — 통화당 1회만)
            if session is not None and not session.get("tier3_alerted"):
                session["tier3_alerted"] = True
                match      = _SEVERE_ALLERGY_RE.search(last_user_text or "")
                trigger_kw = match.group(0) if match else "severe-allergy"
                try:
                    asyncio.create_task(send_tier3_alert(
                        store_name         = store_name or "the store",
                        caller_phone       = caller_phone_e164 or "",
                        triggered_keyword  = trigger_kw,
                        transcript_excerpt = last_user_text or "",
                        call_sid           = "",  # Retell call_id propagation: V2 follow-up
                    ))
                    _mon("TIER3 alert queued kw=%r caller=%s", trigger_kw, caller_phone_e164)
                except Exception as exc:
                    _mon("TIER3 alert dispatch error: %s", exc)
            result = {
                "success":      True,
                "matched_name": None,
                "allergens":    None,
                "dietary_tags": None,
                "reason":       "severe_allergy_handoff",
                "message": (
                    "I want to make sure we get this exactly right — let "
                    "me connect you with our manager who can verify "
                    "directly with the kitchen. One moment please."
                ),
                "error":        "",
            }
        else:
            skill_result = await allergen_lookup(
                store_id        = store_id,
                menu_item_name  = tool_args.get("menu_item_name", ""),
                allergen        = tool_args.get("allergen", ""),
                dietary_tag     = tool_args.get("dietary_tag", ""),
            )
            hint = skill_result.get("ai_script_hint", "item_not_found")
            template = ALLERGEN_SCRIPT_BY_HINT.get(
                hint,
                "Let me transfer you to a manager.",
            )
            # Render dietary tag as a human-readable string
            # ('gluten_free' → 'gluten-free') for the customer line.
            # (식이 태그 사람-친화 표기 — underscore → hyphen)
            tag_human = (skill_result.get("queried_dietary") or "").replace("_", "-")
            try:
                script = template.format(
                    item        = skill_result.get("matched_name", "that item"),
                    allergen    = skill_result.get("queried_allergen", ""),
                    allergens   = ", ".join(skill_result.get("allergens") or [])
                                  or "no listed allergens",
                    tag         = tag_human,
                )
            except (KeyError, IndexError):
                script = template
            result = {
                "success":      bool(skill_result.get("success")),
                "matched_name": skill_result.get("matched_name"),
                "allergens":    skill_result.get("allergens"),
                "dietary_tags": skill_result.get("dietary_tags"),
                "reason":       hint,
                "message":      script,
                "error":        "",
            }
    elif tool_name == "recall_order":
        # Phase 2-C.B6 — read-only order recap from session snapshot.
        # Live trigger: call_7d7ef130 T25-T26 — without this tool, the
        # bot hallucinated "no active order" even though session held
        # a pending pay_first order. No bridge call, no DB lookup —
        # the snapshot is the source of truth.
        # (B6 — session 스냅샷 그대로 노출. bridge/DB 콜 없음)
        snap_items = (session or {}).get("last_order_items") or []
        snap_total = int((session or {}).get("last_order_total") or 0)
        recap_msg, recap_reason = render_recall_message(
            items       = snap_items,
            total_cents = snap_total,
        )
        _mon("RECALL ORDER reason=%s items=%d total_cents=%d",
             recap_reason, len(snap_items), snap_total)
        result = {
            "success": True,
            "reason":  recap_reason,
            "message": recap_msg,
            "error":   "",
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
        # Wave 1 P0-3 — third dedup layer. Even after the tool-call dedup
        # (last_tool_sig, 5s window) lets a second call through, the bridge
        # may still produce the identical noop / clarification line. Same
        # string within 8s = silent skip so the customer doesn't hear the
        # bot repeat itself. Live: call_9b67f4ec… T17/T18 yielded the same
        # 'modify_noop' line 6s apart (just past the tool-call window).
        # (msg 문자열 8s 윈도 dedup — 같은 응답 재발화 차단)
        msg_now_ts = time.time()
        if _should_skip_msg_repeat(session, msg, msg_now_ts):
            _mon("MSG DEDUP tool=%s msg_len=%d — within 8s, silent skip",
                 tool_name, len(msg))
            return
        _remember_msg(session, msg, msg_now_ts)
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
        "modify_count":       0,      # successful modify_order calls — Proposal F cap
        "last_order_items":   [],     # latest committed items snapshot (Proposal I)
        "last_order_total":   0,      # latest committed total_cents (Proposal I)
        "closing_emitted":    False,  # one-shot flag for the order-summary closing line
        "last_tool_sig":      ("", "", 0.0),  # (tool_name, items_key_str, ts) — Proposal R dedup
        "last_recital_sig":   ("", 0.0, 0),   # (recital_sig, ts, skip_count) — Wave 1 P0-1
        "last_msg_sig":       ("", 0.0, 0),   # (msg, ts, skip_count) — Wave 1 P0-3 yield dedup
        "last_reservation_summary": "",       # B4 — cancel_reservation recital source (party of N on <date> at <time>)
        "pending_reservation_email": None,    # B4 — defer-and-fire-on-end. Set by make/modify success, cleared by cancel success, fired on WS disconnect.
        # Phase 5 #26 — Tier-3 manager alert idempotency latch.
        # The bot's verbal hand-off message can repeat across turns; this flag
        # keeps the operator-side email to ONE per call.
        # (Tier 3 매니저 알림 — 통화당 1회 발송 보장)
        "tier3_alerted":      False,
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

        # Dedupe barge-in echo: same user msg within 1.5s → ack and skip.
        # Issue #3 fix — Retell sends mid-utterance partials as separate
        # response_required messages; the prior exact-match echo dedup
        # missed them when truncations differed by a few characters
        # ('Oh, hold on. Hold on. Actually, can I remove one cheese pizza'
        # vs 'Oh, hold on. Hold on. Actually, can I remove one cheese
        # pizza a' vs '…cheese pizza and…'). Customer ends up hearing
        # the same recital 3-4 times. Match on the first 30 stripped
        # characters within 1.5s instead — same prefix is the same
        # spoken sentence still in flight.
        # (1.5초 + prefix 30자 일치 — 부분 발화 중복 차단)
        now = time.time()
        cur_norm  = last_user.strip().lower()
        prev_norm = (s.get("last_user_msg") or "").strip().lower()
        cur_pre   = cur_norm[:30]
        prev_pre  = prev_norm[:30]
        if (
            cur_norm
            and (now - s.get("last_user_ts", 0)) < 1.5
            and (
                cur_norm == prev_norm
                or (len(cur_pre) >= 10 and cur_pre == prev_pre)
            )
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
        in_cooldown          = _in_modify_cooldown(transcript)
        # Allow modify only when the customer expressed intent AFTER the
        # most recent modify outcome (not the looser last-3 window —
        # that kept stale 'add' keywords alive across multiple post-
        # outcome acks and caused the redundant-modify loop).
        user_intent          = _has_explicit_modify_intent_since_outcome(transcript)
        force_tool_use       = detect_force_tool_use(transcript)
        if force_tool_use:
            _mon("FORCE TOOL call=%s resp_id=%d (post-confirmation yes detected)",
                 cid, response_id)
        if in_cooldown:
            _mon("MODIFY COOLDOWN call=%s resp_id=%d intent=%s — recent modify outcome on transcript",
                 cid, response_id, user_intent)

        try:
            async for chunk in _stream_gemini_response(
                s["system_prompt"], conversation,
                store_id=store_id_for_tools, call_log_id=cid,
                store_name=store_name_for_tools,
                force_tool_use=force_tool_use,
                caller_phone_e164=caller_phone_e164,
                in_modify_cooldown=in_cooldown,
                user_has_modify_intent=user_intent,
                last_user_text=last_user,
                modify_count=int(s.get("modify_count") or 0),
                session=s,
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
    finally:
        # B4 — fire the FINAL pending reservation confirmation email
        # exactly once on call end. make_reservation set the payload,
        # modify_reservation refreshed it, cancel_reservation wiped it.
        # If a payload survives to here, it represents the customer's
        # final intended reservation state.
        # (call 종료 — 최종 1통만 발송, 취소되었으면 None이라 스킵)
        try:
            pending = sess.get("pending_reservation_email")
            if pending and pending.get("to"):
                asyncio.create_task(send_reservation_email(**pending))
                _mon("RES EMAIL queued (fire-and-forget) call=%s to=%s party=%s",
                     call_id, pending.get("to"),
                     pending.get("party_size"))
                sess["pending_reservation_email"] = None
        except Exception as exc:
            _mon("RES EMAIL dispatch error call=%s: %s", call_id, exc)


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
