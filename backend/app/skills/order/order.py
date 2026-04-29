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
                "BEFORE calling this tool you MUST: "
                "(a) confirm the customer's name and the phone number we should send the payment link to "
                "    (use the caller's phone unless they ask to use a different one), "
                "(b) recite the full order back to the customer with item names and quantities, "
                "(c) receive an explicit verbal 'yes' from the customer. "
                "Only then set user_explicit_confirmation=true. "
                "Never call this tool without verbal confirmation. "
                "Do NOT invent menu items — only call with items that were quoted from the menu."
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
                            "Phone number to receive the SMS payment link (digits and + only, "
                            "E.164 preferred — e.g. +15035551234)."
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
}
