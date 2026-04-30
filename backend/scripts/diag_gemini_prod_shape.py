"""Reproduce the exact failing production turn against Gemini.
Loads the real system prompt from build_system_prompt() with the live
JM Cafe store row, replays the call_a0ba5ead transcript verbatim, and
dumps every chunk's full shape (parts, finish_reason, prompt_feedback).
(production 실제 페이로드로 재현 — chunks=0 실패 원인 확정용)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google.generativeai as genai
import httpx

from app.api.voice_websocket import build_system_prompt, format_transcript
from app.core.config import settings
from app.skills.order.order import ORDER_TOOL_DEF
from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF

genai.configure(api_key=settings.gemini_api_key)
MODEL = "models/gemini-3.1-flash-lite-preview"


# Verbatim transcript from call_a0ba5ead7d772a9f0be9fca67cf turn 9 (the failing turn).
TRANSCRIPT = [
    {"role": "user",  "content": "Hi. I'd like to place a pickup order."},
    {"role": "agent", "content": "I'd love to help you with that! Could you tell me what you'd like to order, along with your name and phone number?"},
    {"role": "user",  "content": "Uh, you know, My name is Michael Chang. Phone number is five oh three seven oh seven nine five six six."},
    {"role": "agent", "content": "Sure thing, Michael! What items can I get started for you today?"},
    {"role": "user",  "content": "Yeah. Okay. Yeah. Can I get two garfellate?"},
    {"role": "agent", "content": "I apologize, but we don't have garfellate on our menu. Could I interest you in another item instead?"},
    {"role": "user",  "content": "Yeah. Okay. Yeah. Can I get two and one croissant?"},
    {"role": "agent", "content": "I'm sorry, I didn't quite catch the items you'd like. Could you please tell me which items you want to order?"},
    {"role": "user",  "content": "Yeah. Two. Cafe lattes and one croissant."},
    {"role": "agent", "content": "Got it, two cafe lattes and one croissant. May I have your phone number again just to be sure?"},
    {"role": "user",  "content": "Yeah. Two. Cafe lattes and one croissants."},
    {"role": "agent", "content": "Got it, two cafe lattes and one croissant for Michael Chang at 503-707-9566—is that right?"},
    {"role": "user",  "content": "Croissants."},
    {"role": "agent", "content": "Got it, two cafe lattes and one croissant for Michael Chang at 503-707-9566—is that right?"},
    {"role": "user",  "content": ""},
    {"role": "agent", "content": "Sure thing, Michael! Just to confirm, that's two Cafe lattes and one croissant for pickup — is that right?"},
    {"role": "user",  "content": "Yeah."},
]


async def fetch_jm_cafe_store() -> dict:
    headers = {
        "apikey":        settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{settings.supabase_url}/rest/v1/stores",
            headers=headers,
            params={
                "name":   "eq.JM Cafe",
                "select": "id,name,system_prompt,temporary_prompt,business_hours,custom_knowledge,menu_cache",
                "limit":  "1",
            },
        )
    return r.json()[0]


def dump_chunk(label, chunk):
    print(f"\n--- {label} ---")
    try:
        cands = chunk.candidates
        print(f"  candidates: {len(cands)}")
        for ci, cand in enumerate(cands):
            fr = getattr(cand, "finish_reason", "?")
            print(f"  cand[{ci}].finish_reason = {fr}")
            try:
                parts = cand.content.parts
                print(f"  cand[{ci}].parts: {len(parts)}")
                for pi, p in enumerate(parts):
                    fc = getattr(p, "function_call", None)
                    fc_name = getattr(fc, "name", "") if fc else ""
                    txt = getattr(p, "text", "") or ""
                    print(f"    part[{pi}] text={txt!r}  fc.name={fc_name!r}")
            except Exception as exc:
                print(f"  cand[{ci}].content.parts ACCESS ERROR: {exc!r}")
    except Exception as exc:
        print(f"  chunk.candidates ACCESS ERROR: {exc!r}")
    pf = getattr(chunk, "prompt_feedback", None)
    if pf:
        print(f"  prompt_feedback: {pf}")


def run(label, *, store, stream, force_any):
    print(f"\n{'='*80}\n{label}  stream={stream}  force_any={force_any}\n{'='*80}")
    sys_prompt = build_system_prompt(store)
    if store.get("menu_cache"):
        sys_prompt = sys_prompt + f"\n\nMenu:\n{store['menu_cache']}"
    print(f"system_prompt_chars = {len(sys_prompt)}")
    conv = format_transcript(TRANSCRIPT)
    print(f"conversation_chars  = {len(conv)}")
    print(f"transcript_turns_in = {conv.count(chr(10))+1}")

    kwargs = {
        "system_instruction": sys_prompt,
        "tools":              [RESERVATION_TOOL_DEF, ORDER_TOOL_DEF],
    }
    if force_any:
        kwargs["tool_config"] = {"function_calling_config": {"mode": "ANY"}}

    model = genai.GenerativeModel(MODEL, **kwargs)
    chat = model.start_chat()

    if stream:
        resp = chat.send_message(conv, stream=True)
        chunks = list(resp)
        print(f"\nchunk count = {len(chunks)}")
        for ci, chunk in enumerate(chunks):
            dump_chunk(f"chunk[{ci}]", chunk)
    else:
        resp = chat.send_message(conv, stream=False)
        dump_chunk("non-stream", resp)


async def main():
    store = await fetch_jm_cafe_store()
    print(f"loaded store id={store['id']} menu_cache_len={len(store.get('menu_cache') or '')}")
    run("PROD A: stream + AUTO", store=store, stream=True,  force_any=False)
    run("PROD B: stream + ANY",  store=store, stream=True,  force_any=True)
    run("PROD C: non-stream + ANY", store=store, stream=False, force_any=True)


if __name__ == "__main__":
    asyncio.run(main())
