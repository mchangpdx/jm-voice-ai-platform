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
                "(c) you have recited the full order back with exact menu names and quantities. "
                "(d) the customer has said an explicit verbal 'yes' to your recital. "
                "Only when ALL FOUR are true, set user_explicit_confirmation=true and call this tool. "
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
