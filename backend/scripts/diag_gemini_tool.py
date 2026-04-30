"""Direct Gemini tool-call diagnostic. Reproduces the exact call shape
voice_websocket.py uses, then dumps raw response parts for both
streaming and non-streaming, with and without tool_config=ANY.
Goal: prove what Gemini actually returns — no guessing.
(Phase F-2 root cause check — Gemini가 실제로 무엇을 반환하는지 증명)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google.generativeai as genai
from app.core.config import settings
from app.skills.order.order import ORDER_TOOL_DEF
from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF

genai.configure(api_key=settings.gemini_api_key)

MODEL = "models/gemini-3.1-flash-lite-preview"

SYSTEM = (
    "You are Aria, the AI assistant for JM Cafe. "
    "Menu: Cafe Latte $4.99, Croissant $5.99, Americano $3.99. "
    "RULES: 1) Brevity 1-2 sentences. 2) English only here. "
    "3) ORDERS: After the customer says 'yes' to a recited order, CALL "
    "create_order with user_explicit_confirmation=true IMMEDIATELY. "
    "Do NOT recite again. The next yes means CALL THE TOOL."
)

CONVERSATION = (
    "Customer: I'd like to place a pickup order. Two cafe lattes and one croissant. "
    "My name is Michael Chang, phone 503-707-9566.\n"
    "Assistant: Confirming two cafe lattes and one croissant for Michael Chang at "
    "503-707-9566 — is that right?\n"
    "Customer: Yeah, that's correct."
)


def dump_parts(label: str, parts) -> None:
    print(f"\n--- {label} parts={len(parts)} ---")
    for i, p in enumerate(parts):
        fc = getattr(p, "function_call", None)
        fc_name = getattr(fc, "name", "") if fc else ""
        fc_args = dict(getattr(fc, "args", {}) or {}) if fc else {}
        txt = getattr(p, "text", "") or ""
        print(f"  [{i}] text={txt!r}  fc.name={fc_name!r}  fc.args={fc_args}")


def run(label: str, *, stream: bool, force_any: bool) -> None:
    print(f"\n{'='*70}\nCASE: {label}  stream={stream}  force_any={force_any}\n{'='*70}")
    kwargs = {
        "system_instruction": SYSTEM,
        "tools":              [RESERVATION_TOOL_DEF, ORDER_TOOL_DEF],
    }
    if force_any:
        kwargs["tool_config"] = {"function_calling_config": {"mode": "ANY"}}

    model = genai.GenerativeModel(MODEL, **kwargs)
    chat  = model.start_chat()

    if stream:
        resp = chat.send_message(CONVERSATION, stream=True)
        chunks = list(resp)
        print(f"chunk count = {len(chunks)}")
        for ci, chunk in enumerate(chunks):
            try:
                cands = chunk.candidates
                for cand in cands:
                    dump_parts(f"chunk[{ci}].candidate", cand.content.parts)
            except Exception as exc:
                print(f"  chunk[{ci}] parse ERROR: {exc!r}")
        try:
            print(f"\nresp.candidates[0].content.parts (post-iter):")
            dump_parts("post-iter", resp.candidates[0].content.parts)
        except Exception as exc:
            print(f"post-iter access ERROR: {exc!r}")
    else:
        resp = chat.send_message(CONVERSATION, stream=False)
        try:
            dump_parts("non-stream resp.candidates[0]", resp.candidates[0].content.parts)
        except Exception as exc:
            print(f"non-stream parse ERROR: {exc!r}")


if __name__ == "__main__":
    run("A: streaming + AUTO (current default for non-force turns)", stream=True,  force_any=False)
    run("B: streaming + ANY  (current force-tool path)",             stream=True,  force_any=True)
    run("C: non-stream + ANY (proposed fix)",                         stream=False, force_any=True)
    run("D: non-stream + AUTO (sanity check)",                        stream=False, force_any=False)
