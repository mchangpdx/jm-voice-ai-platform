"""Phase 1.0 — OpenAI Realtime WebSocket text-mode protocol smoke test.
(Phase 2-D 마이그레이션 — Realtime 세션 라이프사이클 검증, 오디오 없이)

Validates: connect → session.update → conversation.item.create → response.create
            → response.text.delta stream → done. No audio plumbing.
Expected runtime: <5s. Cost: ~$0.001 (text-only on gpt-realtime-mini).
"""

import asyncio
import os
import time
from pathlib import Path

# Load .env for OPENAI_API_KEY (project root or backend/.env)
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(ENV_PATH)
assert os.environ.get("OPENAI_API_KEY"), f"OPENAI_API_KEY missing — checked {ENV_PATH}"

from openai import AsyncOpenAI

MODEL = os.environ.get("OPENAI_REALTIME_MODEL_POC", "gpt-realtime-mini")


async def main() -> None:
    client = AsyncOpenAI()
    print(f"[POC] Connecting to Realtime API model={MODEL!r} ...")
    t_connect_start = time.monotonic()

    async with client.beta.realtime.connect(model=MODEL) as conn:
        t_connected = time.monotonic()
        print(f"[POC] Connected in {(t_connected - t_connect_start)*1000:.0f}ms")

        # 1) session.update — text-only modality, no audio
        await conn.session.update(
            session={
                "modalities": ["text"],
                "instructions": (
                    "You are Aria, the voice agent for JM Cafe. "
                    "Reply in ONE short sentence."
                ),
            }
        )
        print("[POC] session.update sent (modalities=text)")

        # 2) conversation.item.create — user message
        await conn.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Say hello and confirm you can hear me.",
                    }
                ],
            }
        )
        print("[POC] user message queued")

        # 3) response.create — kick off generation
        t_request = time.monotonic()
        await conn.response.create()
        print("[POC] response.create sent — awaiting deltas...")

        # 4) Stream events
        first_delta_ts: float | None = None
        text_buf: list[str] = []
        async for event in conn:
            etype = event.type
            if etype == "response.text.delta":
                if first_delta_ts is None:
                    first_delta_ts = time.monotonic()
                    print(f"[POC] TTFT (first text delta): "
                          f"{(first_delta_ts - t_request)*1000:.0f}ms")
                text_buf.append(event.delta)
            elif etype == "response.text.done":
                print(f"[POC] response.text.done — full text: "
                      f"{''.join(text_buf)!r}")
            elif etype == "response.done":
                t_done = time.monotonic()
                print(f"[POC] response.done — total {(t_done - t_request)*1000:.0f}ms")
                # Surface usage for cost accounting
                resp = getattr(event, "response", None)
                if resp is not None:
                    usage = getattr(resp, "usage", None)
                    if usage is not None:
                        print(f"[POC] usage: {usage}")
                break
            elif etype == "error":
                print(f"[POC] ERROR: {event}")
                break

    print("[POC] connection closed")
    print("[POC] ✓ Phase 1.0 smoke test PASSED")


if __name__ == "__main__":
    asyncio.run(main())
