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
                            "menu name) and quantity (positive integer)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Exact menu item name (case-insensitive).",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "How many of this item, at least 1.",
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
    "fire_immediate": (
        "Got it — your order is in the kitchen now. I just sent a payment link to your phone. "
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
                "Update the items on an in-flight pickup order, before payment. "
                "Use ONLY when the customer explicitly asks to add, remove, or "
                "change items on an order they JUST placed in this same call. "
                "PRECONDITIONS: "
                "(a) the customer has clearly stated the change, "
                "(b) you have recited the FULL UPDATED order back with the new "
                "    item list and the new total, "
                "(c) the customer has said an explicit verbal yes to the recital. "
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
                            "and quantity (positive integer)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Exact menu item name (case-insensitive).",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "How many of this item, at least 1.",
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
                "Cancel an in-flight pickup order before it's paid. "
                "Use ONLY when the customer EXPLICITLY says 'cancel my "
                "order', 'cancel that', 'never mind, cancel it'. "
                "PRECONDITIONS: "
                "(a) the customer has clearly stated cancel intent, "
                "(b) you have recited 'Just to confirm — you want to cancel "
                "    your order for [items] for $[total] — is that right?' "
                "    using the items and total from this call's order, "
                "(c) the customer has said an explicit verbal yes to that "
                "    recital. "
                "Do NOT pass customer_phone, customer_name, customer_email, "
                "or items — the system identifies the order via the inbound "
                "caller ID. NEVER say 'I've cancelled that for you' without "
                "actually calling this tool. If no in-flight order exists, "
                "the bridge will respond accordingly and you must NOT retry."
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
