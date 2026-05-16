# Phase 2-B.1.8 — Voice Engine `create_order` tool definition
# (Phase 2-B.1.8 — Voice Engine create_order 도구 정의)
#
# Mirrors RESERVATION_TOOL_DEF in shape — passed to genai.GenerativeModel(tools=[...])
# alongside the reservation tool. The actual order orchestration lives in
# app.services.bridge.flows.create_order; this module only declares the
# Gemini-facing schema + script guidance.

from __future__ import annotations

ORDER_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "create_order",
            "description": (
                "Place a confirmed food/drink order for pickup. "
                "PRECONDITIONS (ALL must be true before calling): "
                "(a) the customer has SPOKEN their actual name to you in this call — "
                "    NEVER invent placeholders like 'Anonymous', 'Customer', 'Guest', or 'N/A'. "
                "    If the customer has not given a name yet, ASK first. "
                "(b) PHONE: the system fills customer_phone automatically from the inbound caller "
                "    ID — DO NOT ask the customer for their phone, and DO NOT invent placeholders. "
                "    Only override (pass a different customer_phone) when the customer explicitly "
                "    asks to send the link to a different number AND has spoken 10+ real digits. "
                "(c) EMAIL: the customer has SPOKEN an email address (something@something.tld) for "
                "    the payment link AND has confirmed it AFTER you read the local part back in "
                "    NATO PHONETIC ALPHABET. Plain letter readback ('c, y, m, e, e, t') sounds "
                "    too close to the customer's original utterance — they say yes to a missing "
                "    letter and the link goes to the wrong inbox. NATO each letter unambiguously: "
                "    'Just to confirm — C as in Charlie, Y as in Yankee, M as in Mike, E as in "
                "    Echo, E as in Echo, T as in Tango at gmail dot com — did I get that right?' "
                "    Wait for explicit yes BEFORE calling this tool. If they correct, capture the "
                "    new spelling and read THAT back in NATO too. While SMS delivery is being "
                "    verified, email is required — only omit customer_email when the customer "
                "    explicitly refuses email AND wants SMS only. "
                "(d) you have recited the full order back with exact menu names and quantities. "
                "(e) the customer has said an explicit verbal 'yes' to your recital. "
                "Only when ALL FIVE are true, set user_explicit_confirmation=true and call this tool. "
                "If any one is missing, DO NOT call — ask the customer for the missing piece. "
                "Do NOT invent menu items — use only items quoted from the menu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set to true ONLY after the customer has verbally said 'yes' "
                            "to your order summary. False or missing = do not call."
                        ),
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Full name of the customer placing the order.",
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": (
                            "Caller phone in E.164 (e.g. +15035551234). The system "
                            "auto-fills this from the inbound caller ID — leave it as the "
                            "default the system provides. Only set a different value when the "
                            "customer EXPLICITLY asks to send the link to another number "
                            "AND speaks 10+ real digits — never invent placeholders."
                        ),
                    },
                    "customer_email": {
                        "type": "string",
                        "description": (
                            "Email address for the payment link. While SMS delivery is being "
                            "verified, ALWAYS ask the customer 'What's the best email to send "
                            "the payment link to?' before reciting the order. Pass the spoken "
                            "address here. Omit only when the customer explicitly refuses email."
                        ),
                    },
                    "items": {
                        "type": "array",
                        "description": (
                            "List of items the customer wants. Each item must have name (exact "
                            "menu name) and quantity (positive integer). When the customer "
                            "spoke modifier choices (size, milk type, syrup, etc.), include "
                            "them in selected_modifiers so the price and POS line carry the "
                            "correct upcharges and customizations."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Exact BASE menu item name (case-insensitive). Strip modifier words like 'iced', 'large', 'oat milk' — those go in selected_modifiers.",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "How many of this item, at least 1.",
                                },
                                "selected_modifiers": {
                                    "type": "array",
                                    "description": (
                                        "Modifier choices for THIS line item. Use the exact "
                                        "group/option codes from the MENU MODIFIERS block in "
                                        "your instructions. Examples: 'large iced oat latte' → "
                                        "[{'group':'size','option':'large'},"
                                        "{'group':'temperature','option':'iced'},"
                                        "{'group':'milk','option':'oat'}]. Pass [] for items "
                                        "the customer ordered without customization."
                                    ),
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "group":  {"type": "string"},
                                            "option": {"type": "string"},
                                        },
                                        "required": ["group", "option"],
                                    },
                                },
                            },
                            "required": ["name", "quantity"],
                        },
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional special requests (allergies, modifications, etc.).",
                    },
                },
                "required": [
                    "user_explicit_confirmation",
                    "customer_name",
                    "customer_phone",
                    "items",
                ],
            },
        }
    ]
}


# Lane-aware customer-facing scripts. The Voice Engine tool handler picks one
# from this map based on bridge_result["ai_script_hint"]. Phrasing is plain
# English because Retell's TTS reads these verbatim.
# (lane별 고객 응답 스크립트 — Voice Engine이 ai_script_hint로 선택)

ORDER_SCRIPT_BY_HINT: dict[str, str] = {
    # Phase 7-A.D Wave A.3 Plan D — POS create_pending now runs in a
    # background task to cut user-perceived latency from ~3s to ~0.5s.
    # The script wording shifted from "in the kitchen now" (POS confirmed)
    # to "placing your order now" (bridge row created, POS in-flight).
    # If the background POS injection fails, manager_alert + daily
    # reconcile picks up the FAILED bridge row — the customer is not
    # falsely told the kitchen has it.
    # (POS는 background — 멘트는 정직하게 "placing")
    "fire_immediate": (
        "Got it — placing your order now and sending a payment link to your phone. "
        "You can pay before pickup or at the counter."
    ),
    "pay_first": (
        "I just sent a payment link to your phone. As soon as you tap it, your order goes "
        "straight to the kitchen — usually about 5 to 10 seconds."
    ),
    "rejected": (
        "I'm sorry — one or more items aren't available right now. Would you like to try "
        "something else?"
    ),
    "pos_failure": (
        "Sorry, our system had a hiccup taking the order. A team member will call you right "
        "back to finalize."
    ),
    "validation_failed": (
        "I'm missing something to place the order — let me ask once more so I get it right. "
        "Could you confirm the items and a phone number for the payment link?"
    ),
}


# B1 — modify_order tool definition (Phase 2-C).
# Customer wants to change items on an order they JUST placed (before
# payment). Tool args deliberately OMIT customer_phone / customer_name
# / customer_email — the bridge looks them up from the in-flight tx
# via caller-id, which kills the phone-hallucination class for modify
# the same way it does for create.
# (B1 — 결제 전 in-flight 주문 items 수정 tool)

MODIFY_ORDER_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "modify_order",
            "description": (
                "Update the items on an in-flight pickup order. Use this WHENEVER "
                "the customer asks to add, remove, or change items on an order "
                "they JUST placed in this same call — EVEN AFTER the payment "
                "link has already been sent. The pay link is informational; the "
                "order is fully modifiable until the customer taps it (state "
                "stays 'pending'). DO NOT tell the customer 'I can't modify it' "
                "or suggest 'cancel and remake' — just call modify_order with "
                "the new item list. The same pay link will reflect the new total. "
                "PRECONDITIONS: "
                "(a) the customer has clearly stated the change, "
                "(b) you have recited the FULL UPDATED order back with the new "
                "    item list and the new total, "
                "(c) the customer has said an explicit verbal yes to the recital. "
                "ALWAYS INCLUDE THE COMPLETE `items` LIST — every call must "
                "carry the full final basket (existing items + any new/changed "
                "ones + leave out the removed ones). NEVER call with `items` "
                "empty or omitted — even when the customer is 'just adding one "
                "thing', re-send every previously confirmed item alongside it. "
                "The 'items' list REPLACES the current order entirely — pass the "
                "COMPLETE final list of items with their final quantities, NOT a "
                "delta. Do NOT pass customer_phone / customer_name / customer_email "
                "— the system looks them up from the existing order via the inbound "
                "caller ID. Do NOT invent menu items or placeholders. If no "
                "in-flight order exists, the bridge will respond accordingly and "
                "you must NOT retry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set to true ONLY after the customer has verbally said "
                            "'yes' to your updated recital. False or missing = do "
                            "not call."
                        ),
                    },
                    "items": {
                        "type": "array",
                        "description": (
                            "Complete final list of items the customer wants on "
                            "the order. Each entry must have name (exact menu name) "
                            "and quantity (positive integer). When the customer "
                            "spoke modifier choices on this update (e.g. switched "
                            "from oat milk to almond milk mid-call), include them "
                            "in selected_modifiers — same shape as create_order so "
                            "the new total reflects the modifier surcharges."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Exact BASE menu item name (case-insensitive). Strip modifier words like 'iced', 'large', 'oat milk' — those go in selected_modifiers.",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "How many of this item, at least 1.",
                                },
                                "selected_modifiers": {
                                    "type": "array",
                                    "description": (
                                        "Modifier choices for THIS line item. Use "
                                        "the exact group/option codes from the MENU "
                                        "MODIFIERS block in your instructions. "
                                        "Example: 'switch the latte to almond milk' "
                                        "→ items[i].selected_modifiers = "
                                        "[{'group':'milk','option':'almond'}]. "
                                        "Pass [] for items the customer left at "
                                        "default."
                                    ),
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "group":  {"type": "string"},
                                            "option": {"type": "string"},
                                        },
                                        "required": ["group", "option"],
                                    },
                                },
                            },
                            "required": ["name", "quantity"],
                        },
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional special requests or modifiers.",
                    },
                },
                "required": ["user_explicit_confirmation", "items"],
            },
        }
    ]
}


# Customer-facing lines for modify_order outcomes. The voice handler
# substitutes {total} on success before yielding, so the customer hears
# the new total verbatim instead of a templated placeholder.
# (modify_order 결과별 멘트 — handler가 {total}을 실제 금액으로 치환)

MODIFY_ORDER_SCRIPT_BY_HINT: dict[str, str] = {
    "modify_success": (
        "Updated — your new total is {total}. The same payment link still works."
    ),
    "modify_noop": (
        "Your order is unchanged — the total is still {total}. "
        "Tap the payment link whenever you're ready."
    ),
    "modify_no_target": (
        "I don't see an active order to modify. Would you like to start a new one?"
    ),
    "modify_too_late": (
        "The kitchen has already started that order, so I can't change it now. "
        "I can cancel it and place a fresh one if you'd like."
    ),
    # rejected / validation_failed share lines with create_order so the
    # customer hears consistent phrasing. The handler can fall back to
    # ORDER_SCRIPT_BY_HINT when one of those hints comes back.
}


# B2 — cancel_order tool definition (Phase 2-C.2).
# Customer wants to cancel an in-flight order placed THIS SAME call.
# Tool args carry only user_explicit_confirmation — the bridge looks the
# order up via caller-id and items/phone are not needed (cancel operates
# on the transaction as a whole). This kills phone-hallucination AND
# prevents Gemini from inventing a fake order to cancel. Live:
# call_faba29762 — without this tool the bot hallucinated 'I've gone
# ahead and cancelled that for you' on a still-live FIRED_UNPAID order.
# (B2 — in-flight 주문 취소 tool. caller-id로 식별, args 최소)

CANCEL_ORDER_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "cancel_order",
            "description": (
                "Cancel an in-flight pickup order placed IN THIS SAME CALL "
                "before it's paid. Use ONLY when the customer EXPLICITLY "
                "says 'cancel my order', 'cancel that', 'never mind, cancel "
                "it' AFTER you have already placed an order for them in "
                "THIS call via create_order. "
                "PRECONDITIONS: "
                "(a) create_order has succeeded earlier in THIS call (you "
                "    have an in-call order snapshot — last_order_items + "
                "    last_order_total are non-empty), "
                "(b) the customer has clearly stated cancel intent, "
                "(c) you have recited 'Just to confirm — you want to cancel "
                "    your order for [items] for $[total] — is that right?' "
                "    using the items and total from this call's order, "
                "(d) the customer has said an explicit verbal yes to that "
                "    recital. "
                "If NO order has been placed in THIS call yet (no in-call "
                "snapshot) and the customer asks to cancel, call "
                "recent_orders FIRST — that tool covers cross-call cancels. "
                "Do NOT pass customer_phone, customer_name, customer_email, "
                "or items — the system identifies the order via the inbound "
                "caller ID. NEVER say 'I've cancelled that for you' without "
                "actually calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set to true ONLY after the customer has verbally "
                            "said 'yes' to your cancel recital. False or "
                            "missing = do not call."
                        ),
                    },
                },
                "required": ["user_explicit_confirmation"],
            },
        }
    ]
}


# Customer-facing lines for cancel_order outcomes. The voice handler
# yields these verbatim — no {total} substitution (cancel scripts don't
# quote the total; the recital does that BEFORE the tool call).
# (cancel_order 결과별 멘트 — handler가 verbatim yield)

CANCEL_ORDER_SCRIPT_BY_HINT: dict[str, str] = {
    "cancel_success": (
        "Got it — your order has been cancelled. No charge will go through. "
        "Sorry for the trouble!"
    ),
    "cancel_success_fired": (
        # FIRED_UNPAID branch — kitchen has the receipt; staff need a
        # heads-up since V1 doesn't auto-void Loyverse.
        "Got it — your order has been cancelled on our side. The kitchen "
        "had already started, so when you're nearby please let our team "
        "at the counter know so they can clear it. No charge will go through."
    ),
    "cancel_no_target": (
        "I don't see an active order to cancel. Is there something else I "
        "can help with?"
    ),
    "cancel_already_canceled": (
        "That order has already been cancelled. Is there anything else I "
        "can help with?"
    ),
    "cancel_already_paid": (
        "That order has already been paid for. Let me connect you with our "
        "manager so they can help with a refund."
    ),
    "cancel_failed": (
        "Sorry, I had trouble cancelling that. Let me connect you with our "
        "manager to sort it out."
    ),
}


# ── B3 modify_reservation: customer-facing scripts ────────────────────────────
# Per spec backend/docs/specs/B3_modify_reservation.md section 7.
# Hints from flows.modify_reservation are looked up in this map by the
# voice handler. Templates with {new_summary} / {original_summary} are
# .format()'d in the dispatcher using bridge_result fields.
# (modify_reservation 결과별 멘트 — handler가 format 후 yield)

MODIFY_RESERVATION_SCRIPT_BY_HINT: dict[str, str] = {
    "modify_success": (
        "Got it — your reservation is updated to {new_summary}. We'll see "
        "you then."
    ),
    "reservation_no_target": (
        "I don't see an active reservation under your number — would you "
        "like to make one?"
    ),
    "reservation_too_late": (
        "That reservation starts in less than 30 minutes — I can't change "
        "it now. I can cancel it and we can rebook?"
    ),
    "reservation_noop": (
        "Your reservation is unchanged. What would you like to change?"
    ),
    "outside_business_hours": (
        "Sorry, that time is outside our hours. Want to try another time?"
    ),
    "party_too_large": (
        "We don't seat parties over 20 by phone — let me connect you with "
        "our manager."
    ),
    "validation_failed": (
        "I'm missing something — could you tell me the new date, time, "
        "and party size?"
    ),
}


# ── B4 cancel_reservation: customer-facing scripts ────────────────────────────
# Per spec backend/docs/specs/B4_cancel_reservation.md section 7.
# Hints from flows.cancel_reservation are looked up in this map by the voice
# handler. The success template carries a {cancelled_summary} placeholder that
# the dispatcher .format()'s with the bridge result.
# (cancel_reservation 결과별 멘트 — handler가 format 후 yield)

CANCEL_RESERVATION_SCRIPT_BY_HINT: dict[str, str] = {
    "cancel_reservation_success": (
        "Got it — your reservation for {cancelled_summary} has been "
        "cancelled. Hope to see you another time!"
    ),
    "cancel_reservation_no_target": (
        "I don't see an active reservation under your number. Is there "
        "something else I can help with?"
    ),
    "cancel_reservation_already_canceled": (
        "That reservation has already been cancelled. Anything else I "
        "can help with?"
    ),
    "cancel_reservation_failed": (
        "Sorry, I had trouble cancelling that. Let me connect you with "
        "our manager to sort it out."
    ),
}


# ── Phase 2-C.B5 — allergen / dietary Q&A scripts ────────────────────────────
# (Phase 2-C.B5 — 알레르겐/식이 질문 응답 스크립트)
#
# Spec: backend/docs/specs/B5_allergen_qa.md §7
# Operator-curated only (CUSTOMER SAFETY INVARIANT) — wording is intentionally
# conservative ("per our kitchen records" qualifier on every absent claim,
# manager-transfer offer on every unknown).

ALLERGEN_SCRIPT_BY_HINT: dict[str, str] = {
    "item_not_found": (
        "I don't see {item} on our menu — could you say it again, or "
        "would you like me to read what we have?"
    ),
    "allergen_unknown": (
        "I don't have allergen info on hand for the {item}. Want me to "
        "transfer you to a manager?"
    ),
    "allergen_present": (
        "Yes, our {item} contains {allergen}."
    ),
    "allergen_absent": (
        "Our {item} is {allergen}-free per our kitchen records."
    ),
    "dietary_match": (
        "Yes, our {item} is {tag}."
    ),
    "dietary_no_match": (
        "Our {item} isn't tagged {tag} — let me have the team "
        "double-check. Want me to transfer?"
    ),
    "generic": (
        "Our {item} contains {allergens}. Anything specific you'd "
        "like to know?"
    ),
}


# B6 — recall_order tool definition (Phase 2-C.B6).
# Read-only recap of the in-flight order placed THIS SAME call. Bridge
# session keeps last_order_items + last_order_total snapshot whenever
# create_order / modify_order succeeds; this tool surfaces that snapshot
# back to the customer so the bot doesn't hallucinate "no active order"
# mid-call. Live trigger: call_7d7ef130ad839e9a2c3c68816a7 T25-T26.
# (B6 — 통화 중 주문 재요약. session 스냅샷 그대로 노출)

RECALL_ORDER_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "recall_order",
            "description": (
                "Recap the customer's current in-flight order placed in "
                "THIS SAME call. Use when the customer asks anything like "
                "'what's my order', 'did you send it', 'order info', "
                "'is it confirmed', 'how much was it', 'the total'. "
                "Read-only — does NOT modify, place, or cancel anything. "
                "Do NOT call reflexively right after a successful "
                "create_order / modify_order — those have their own "
                "confirmation copy. Pass NO arguments — the system reads "
                "the order from the in-call snapshot."
            ),
            "parameters": {
                "type":       "object",
                "properties": {},
                "required":   [],
            },
        }
    ]
}


# Render the customer-facing recap line from the session snapshot. Pure
# function — voice_websocket dispatcher passes session["last_order_items"]
# and session["last_order_total"] in directly. Returns (message, reason).
# Plural rule mirrors the existing closing-summary line (Proposal I).
# (snapshot → recap 문구. closing-summary와 동일한 plural 규칙)

# N1 — recent_orders tool definition (2026-05-17).
# Cross-call cancel/modify entry point. recall_order is in-call snapshot
# only (Phase 5 #25 invariant). When the caller references a PRIOR call
# ('my last order', 'I ordered 10 minutes ago'), the LLM calls this tool
# instead — bridge looks up actionable (pending / payment_sent /
# fired_unpaid) tx within 30 min by caller phone. Result drives a verbal
# recap, then a follow-up cancel_order/modify_order acts on the most
# recent match (the existing tools fetch by caller-id, so single-match
# wires straight through).
# (cross-call 진입 tool — 30분 내 actionable tx, caller-id로 단일 매칭)

RECENT_ORDERS_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "recent_orders",
            "description": (
                "List the caller's recent (last 30 minutes) actionable "
                "orders at THIS store. Use ONLY when the customer "
                "references a PRIOR call ('my last order', 'I called "
                "earlier', 'the burrito I ordered before') and you "
                "have NO in-call order yourself. Pass NO arguments — "
                "the system fills caller_phone from carrier ID. After "
                "the result comes back, speak the message verbatim. If "
                "the customer then confirms cancel/modify intent, "
                "proceed through cancel_order / modify_order's normal "
                "confirmation flow. Do NOT use for THIS call's order "
                "(use recall_order). Do NOT invent past orders if the "
                "tool returns recent_none."
            ),
            "parameters": {
                "type":       "object",
                "properties": {},
                "required":   [],
            },
        }
    ]
}


# Customer-facing lines for recent_orders outcomes. The voice handler
# yields these verbatim — totals and item summaries are interpolated by
# the renderer below before yielding, so the dispatcher doesn't need to
# .format() these. (recent_orders 결과별 멘트 — renderer가 interpolate)

RECENT_ORDERS_SCRIPT_BY_HINT: dict[str, str] = {
    "recent_none": (
        "I don't see any recent orders under your number. Want to place a "
        "new one?"
    ),
    # `recent_single` and `recent_multi` are rendered with concrete content
    # by `render_recent_orders_message` — these entries are kept here so
    # the hint vocabulary lives in one place even though no string lookup
    # happens for them at dispatch time.
    # (single/multi는 renderer가 직접 문자열 생성, hint 키만 등록)
    "recent_single": "",
    "recent_multi":  "",
}


def _summarize_items(items: list, max_items: int = 3) -> str:
    """Compress an items_json list into a short spoken phrase.

    Mirrors `render_recall_message`'s plural rule. Used for both single
    and multi-match scripts. Caps at `max_items` then appends 'and
    more' so 5-line orders stay one breath long.
    (items_json → 짧은 spoken phrase, plural + max_items cap)
    """
    parts: list[str] = []
    overflow = 0
    for idx, it in enumerate(items or []):
        if not isinstance(it, dict):
            continue
        try:
            qty = int(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        nm = (it.get("name") or "").strip()
        if not nm:
            continue
        if idx >= max_items:
            overflow += 1
            continue
        plural = "" if qty == 1 else "s"
        parts.append(f"{qty} {nm}{plural}")
    if overflow:
        parts.append("and more")
    return ", ".join(parts) if parts else ""


def _minutes_ago(created_at_iso: str | None) -> int:
    """Whole minutes between created_at and now (UTC). 0 if unparseable.

    Used to phrase the recap ("placed 8 minutes ago"). We snap to 1 when
    the diff rounds to 0 so a brand-new tx still reads naturally instead
    of "0 minutes ago".
    (created_at → minutes ago, 0 → 1 snap, parse 실패 시 0)
    """
    if not created_at_iso:
        return 0
    try:
        # Supabase returns ISO with timezone, e.g. 2026-05-17T01:23:45.123+00:00
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(str(created_at_iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - ts
        m = int(diff.total_seconds() // 60)
        return max(m, 1)
    except (ValueError, TypeError):
        return 0


def render_recent_orders_message(
    rows: list[dict],
) -> tuple[str, str, list[dict]]:
    """Build the customer-facing recap line + reason + candidate list.

    Returns (message, reason, candidates) where reason is one of
    'recent_none' / 'recent_single' / 'recent_multi'. `candidates` is
    a compact dict list the dispatcher caches on session state so a
    follow-up cancel_order can identify the chosen row when the caller
    later disambiguates verbally — current scope acts on the
    caller-id's single most recent tx, so the list is informational.
    (renderer — message + reason + cache용 candidates 반환)
    """
    if not rows:
        return (RECENT_ORDERS_SCRIPT_BY_HINT["recent_none"], "recent_none", [])

    candidates: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        candidates.append({
            "id":          r.get("id"),
            "state":       r.get("state"),
            "total_cents": int(r.get("total_cents") or 0),
            "items":       r.get("items_json") or [],
            "created_at":  r.get("created_at"),
        })

    if len(candidates) == 1:
        c = candidates[0]
        phrase = _summarize_items(c["items"]) or "your order"
        total  = f"${c['total_cents'] / 100:.2f}"
        mins   = _minutes_ago(c["created_at"])
        ago    = (
            f"placed {mins} minute{'' if mins == 1 else 's'} ago"
            if mins else "from a moment ago"
        )
        message = (
            f"I found your order — {phrase} for {total}, {ago}. "
            f"Want me to cancel it or change something?"
        )
        return (message, "recent_single", candidates)

    # Multi-match — speak up to 3 lines (LLM disambiguates verbally).
    lines: list[str] = []
    for c in candidates[:3]:
        phrase = _summarize_items(c["items"], max_items=2) or "an order"
        total  = f"${c['total_cents'] / 100:.2f}"
        mins   = _minutes_ago(c["created_at"])
        suffix = f"{mins} min ago" if mins else "recent"
        lines.append(f"{phrase} for {total} ({suffix})")
    summary = "; ".join(lines)
    message = (
        f"I see {len(candidates)} recent orders under your number: "
        f"{summary}. Which one — the most recent, or tell me the items?"
    )
    return (message, "recent_multi", candidates)


def render_recall_message(
    *,
    items:       list,
    total_cents: int,
) -> tuple[str, str]:
    """Build the customer-facing recap line + reason hint.

    Returns:
        (message, reason) where reason is 'recall_present' if items+total
        are non-empty, else 'recall_empty'.
    (스냅샷에 주문이 있으면 recall_present, 없으면 recall_empty)
    """
    if not items or not isinstance(items, list) or int(total_cents or 0) <= 0:
        return (
            "I don't have an order placed for you yet. Would you like to start one?",
            "recall_empty",
        )

    parts: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            qty = int(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        nm = (it.get("name") or "").strip()
        if not nm:
            continue
        plural = "" if qty == 1 else "s"
        parts.append(f"{qty} {nm}{plural}")

    if not parts:
        return (
            "I don't have an order placed for you yet. Would you like to start one?",
            "recall_empty",
        )

    phrase = ", ".join(parts)
    return (
        f"You have {phrase} for ${total_cents / 100:.2f}. The payment "
        f"link is on its way — tap it and your order goes straight to "
        f"the kitchen.",
        "recall_present",
    )
