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
                "    the payment link AND has confirmed it AFTER you read it back LETTER BY LETTER. "
                "    Speech-to-text routinely garbles letters in spoken email; phonetic readback "
                "    sounds identical to the customer's own speech and they will NOT catch a single-"
                "    letter error like 'cymee' vs 'cymeet'. You MUST spell the local part one letter "
                "    at a time with commas: 'Just to confirm — c, y, m, e, e, t at gmail dot com — "
                "    did I get that right?' and wait for an explicit yes BEFORE calling this tool. "
                "    If they correct, capture the new spelling and read THAT back the same way. "
                "    While SMS delivery is being verified, email is required — only omit "
                "    customer_email when the customer explicitly refuses email AND wants SMS only. "
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
