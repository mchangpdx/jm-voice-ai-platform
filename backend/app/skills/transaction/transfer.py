# Manager hand-off skill — used for severe allergy, repeat clarification
# failures, and explicit "let me speak to a person" requests.
# (매니저 hand-off skill — 심각 알러지, 반복 clarification 실패, 사람 요청)
#
# Implementation choice (V0, 2026-05-12): VERBAL hand-off only.
#
# We considered three transfer modes:
#   A. Verbal hand-off — agent reads the manager's number, caller calls back
#      → simplest, no Twilio TwiML mutation, no manager-side answer dependency
#   B. Twilio REST <Dial> mutation — PUT /Calls/{CallSid} mid-call
#      → harder UX (manager may not answer; call drops if they don't),
#        requires extra Twilio plumbing
#   C. Email/SMS alert only — manager gets a "call now" alert
#      → fine as a complement, useless as the primary path (caller has nothing)
#
# We ship A + C: read the number aloud AND fire a manager alert email so the
# operator-side follow-up runs in parallel. The Tier-3 alert plumbing already
# exists in realtime_voice.py for severe-allergy keywords (Phase 5 #26) — this
# skill explicitly invokes the same alert channel via the response message so
# the caller sees a single decisive hand-off instead of two scripts colliding.

from __future__ import annotations

from typing import Any


TRANSFER_TO_MANAGER_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "transfer_to_manager",
            "description": (
                "Hand the caller off to the store manager. Use this for: "
                "(1) a SEVERE-ALLERGY situation where the caller said "
                "'EpiPen', 'anaphylaxis', 'celiac', 'life-threatening', or "
                "'severely allergic' — do NOT call allergen_lookup, transfer "
                "IMMEDIATELY. "
                "(2) the caller has explicitly asked for 'a manager', "
                "'a person', 'a human', or 'someone to help me'. "
                "(3) you have failed two consecutive clarification attempts "
                "on the same point. "
                "When this tool returns, READ THE manager_phone_spoken VALUE "
                "to the caller exactly as written (e.g. 'five oh three, seven "
                "oh seven, nine five six six'). Do NOT improvise an alternate "
                "phrasing. Then end the call gracefully — do not keep taking "
                "their order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Short one-line reason for the hand-off. Pick "
                            "ONE of: 'severe_allergy', 'customer_requested', "
                            "'repeated_clarification_failure', 'other'."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Optional one-sentence summary of what the "
                            "caller said that triggered the hand-off. Helps "
                            "the operator-side manager call back ready."
                        ),
                    },
                },
                "required": ["reason"],
            },
        }
    ]
}


def _spoken_phone(e164: str) -> str:
    """Convert '+15037079566' → 'five oh three, seven oh seven, nine five six six'.
    Phone-spelling rule mirrors the cafe agent's NATO email recital cadence so
    elderly / hard-of-hearing callers can write it down on a single hearing.
    (전화번호 음성 spelling — 어르신/저잡음 환경용)
    """
    digits = "".join(c for c in (e164 or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return e164  # fallback to raw

    word_map = {
        "0": "oh", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    }
    groups = [digits[0:3], digits[3:6], digits[6:10]]
    return ", ".join(" ".join(word_map[d] for d in g) for g in groups)


async def transfer_to_manager(
    *,
    store_id:          str,
    args:              dict[str, Any],
    manager_phone:     str = "+15037079566",
) -> dict[str, Any]:
    """Build the verbal hand-off payload. Returns a result dict the voice
    handler injects back into the OpenAI session — `message` is the script
    the model reads, `manager_phone_spoken` is the precise digit cadence.
    (verbal hand-off payload 생성)
    """
    reason = (args.get("reason") or "other").strip()
    spoken = _spoken_phone(manager_phone)
    e164_pretty = manager_phone.replace("+1", "")
    if len(e164_pretty) == 10:
        e164_pretty = f"{e164_pretty[:3]}-{e164_pretty[3:6]}-{e164_pretty[6:]}"

    message = (
        f"Our manager can help you with this directly. Please call them at "
        f"{spoken} — that's {e164_pretty}. Have a good day."
    )

    return {
        "success":              True,
        "reason":               reason,
        "manager_phone":        manager_phone,
        "manager_phone_spoken": spoken,
        "manager_phone_pretty": e164_pretty,
        "message":              message,
        "ai_script_hint":       "manager_handoff",
    }
