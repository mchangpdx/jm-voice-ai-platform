"""Phase 1.2 — OpenAI Realtime live mic echo POC + TTFT measurement.
(Phase 2-D 마이그레이션 — 라이브 마이크 → Realtime → 스피커 양방향 echo)

Goal: validate end-to-end audio plumbing (mic capture → Realtime API →
speaker playback) and measure first-audio-byte latency (TTFT).

Usage:
    cd backend && .venv/bin/python ../scripts/poc_realtime_audio.py

How it works:
1. Captures mic at 24 kHz mono PCM16 (OpenAI Realtime native format)
2. Streams chunks to Realtime via input_audio_buffer.append
3. Server VAD detects end-of-speech, fires response.create automatically
4. Plays response.audio.delta chunks to speakers as they arrive
5. Reports TTFT (response.create commit → first audio byte played)

Press Ctrl+C to stop. Each turn measured separately.
First run will trigger macOS mic permission prompt — grant to Terminal/iTerm.
"""

from __future__ import annotations

import asyncio
import base64
import os
import queue
import sys
import time
from pathlib import Path

# Force unbuffered stdout so prints appear immediately
# (출력 버퍼링 비활성화 — 즉시 화면 출력)
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

print("[BOOT] poc_realtime_audio.py starting…", flush=True)

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(ENV_PATH)
print(f"[BOOT] .env loaded from {ENV_PATH}", flush=True)
assert os.environ.get("OPENAI_API_KEY"), f"OPENAI_API_KEY missing — checked {ENV_PATH}"
print(f"[BOOT] OPENAI_API_KEY present (len={len(os.environ['OPENAI_API_KEY'])})", flush=True)

import numpy as np
import sounddevice as sd
from openai import AsyncOpenAI

print(f"[BOOT] imports OK — sounddevice={sd.__version__} numpy={np.__version__}", flush=True)
print(f"[BOOT] default input device: {sd.query_devices(sd.default.device[0])['name']}", flush=True)
print(f"[BOOT] default output device: {sd.query_devices(sd.default.device[1])['name']}", flush=True)

# ── Audio config — OpenAI Realtime native: PCM16 mono 24 kHz ─────────────────
SAMPLE_RATE = 24_000
CHANNELS = 1
DTYPE = "int16"
CHUNK_MS = 40                    # mic chunk size — 40ms ≈ 960 samples @24kHz
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000

# ── Model + voice ────────────────────────────────────────────────────────────
MODEL = os.environ.get("OPENAI_REALTIME_MODEL_POC", "gpt-realtime-mini")
VOICE = "marin"

INSTRUCTIONS = (
    "You are a friendly assistant testing audio. "
    "When the user speaks, briefly repeat back what they said in one sentence, "
    "starting with 'You said:'. Keep it under 15 words."
)


class TurnTimer:
    """Track per-turn TTFT — first user-audio-stop → first agent-audio-byte.
    (턴별 TTFT 측정 — 사용자 발화 종료 → 에이전트 첫 오디오 byte)
    """

    def __init__(self) -> None:
        self.user_speech_stop: float | None = None
        self.first_audio_byte: float | None = None
        self.turn_count = 0

    def mark_speech_stop(self) -> None:
        self.user_speech_stop = time.monotonic()
        self.first_audio_byte = None
        self.turn_count += 1

    def mark_first_audio(self) -> float | None:
        if self.user_speech_stop is None or self.first_audio_byte is not None:
            return None
        self.first_audio_byte = time.monotonic()
        ttft_ms = (self.first_audio_byte - self.user_speech_stop) * 1000
        return ttft_ms


async def main() -> None:
    timer = TurnTimer()
    client = AsyncOpenAI()
    print(f"[POC] Connecting to Realtime API model={MODEL!r} voice={VOICE!r} ...")
    print(f"[POC] Speak into mic. Press Ctrl+C to stop.\n")

    # Speaker output queue — events thread pushes PCM frames, audio thread plays
    speaker_q: queue.Queue[bytes | None] = queue.Queue()

    def speaker_callback(outdata, frames, time_info, status):
        try:
            data = speaker_q.get_nowait()
        except queue.Empty:
            outdata.fill(0)
            return
        if data is None:
            outdata.fill(0)
            return
        # Convert raw PCM16 bytes → numpy int16 → fill outdata
        arr = np.frombuffer(data, dtype=np.int16)
        n = min(len(arr), len(outdata))
        outdata[:n, 0] = arr[:n]
        if n < len(outdata):
            outdata[n:].fill(0)

    async with client.beta.realtime.connect(model=MODEL) as conn:
        # 1) Configure session — server VAD + audio modality
        await conn.session.update(
            session={
                "modalities": ["audio", "text"],
                "voice": VOICE,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "instructions": INSTRUCTIONS,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
            }
        )
        print("[POC] session.update sent (server VAD + 24kHz PCM16)")

        # 2) Mic capture in background thread, push to async queue
        mic_loop = asyncio.get_running_loop()
        mic_q: asyncio.Queue[bytes] = asyncio.Queue()

        def mic_callback(indata, frames, time_info, status):
            if status:
                print(f"[mic] status: {status}", file=sys.stderr)
            # indata is int16 ndarray (frames, channels=1) → bytes
            pcm = indata.tobytes()
            mic_loop.call_soon_threadsafe(mic_q.put_nowait, pcm)

        # 3) Speaker output stream
        spk_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_SAMPLES,
            callback=speaker_callback,
        )

        # 4) Mic input stream
        mic_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_SAMPLES,
            callback=mic_callback,
        )

        spk_stream.start()
        mic_stream.start()
        print("[POC] mic + speaker streams started — start speaking!\n")

        async def pump_mic() -> None:
            """Forward mic chunks to Realtime API + emit RMS heartbeat.
            (마이크 chunk 전송 + 1초마다 RMS 평균 출력)
            """
            chunks_sent = 0
            rms_window: list[float] = []
            last_heartbeat = time.monotonic()
            try:
                while True:
                    pcm = await mic_q.get()
                    # Compute RMS for this chunk (diagnostic)
                    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
                    if arr.size > 0:
                        rms_window.append(float(np.sqrt(np.mean(arr ** 2))))
                    b64 = base64.b64encode(pcm).decode("ascii")
                    await conn.input_audio_buffer.append(audio=b64)
                    chunks_sent += 1

                    # Heartbeat every 1s — confirms mic + send pipeline alive
                    now = time.monotonic()
                    if now - last_heartbeat >= 1.0:
                        avg_rms = (
                            sum(rms_window) / len(rms_window) if rms_window else 0.0
                        )
                        peak_rms = max(rms_window) if rms_window else 0.0
                        print(
                            f"[mic→api] chunks={chunks_sent} "
                            f"avg_rms={avg_rms:.0f} peak={peak_rms:.0f}",
                            flush=True,
                        )
                        rms_window.clear()
                        last_heartbeat = now
            except asyncio.CancelledError:
                return

        async def pump_events() -> None:
            """Receive Realtime events, play audio, report TTFT.
            All event types logged for diagnostics.
            (모든 이벤트 type을 로그 — 어디서 막히는지 파악)
            """
            event_counter: dict[str, int] = {}
            try:
                async for event in conn:
                    etype = event.type
                    event_counter[etype] = event_counter.get(etype, 0) + 1

                    if etype == "session.created":
                        print(f"[evt] session.created", flush=True)
                    elif etype == "session.updated":
                        print(f"[evt] session.updated — server confirmed config",
                              flush=True)
                    elif etype == "input_audio_buffer.speech_started":
                        print(f"\n[turn {timer.turn_count + 1}] 🎤 user started speaking…",
                              flush=True)
                    elif etype == "input_audio_buffer.speech_stopped":
                        timer.mark_speech_stop()
                        print(f"[turn {timer.turn_count}] 🛑 user stopped — awaiting agent",
                              flush=True)
                    elif etype == "input_audio_buffer.committed":
                        print(f"[evt] input_audio_buffer.committed", flush=True)
                    elif etype == "conversation.item.input_audio_transcription.completed":
                        print(f"[turn {timer.turn_count}] 📝 user transcript: "
                              f"{getattr(event, 'transcript', '?')!r}", flush=True)
                    elif etype == "response.created":
                        print(f"[evt] response.created (id={getattr(event.response, 'id', '?')})",
                              flush=True)
                    elif etype == "response.audio.delta":
                        ttft = timer.mark_first_audio()
                        if ttft is not None:
                            print(f"[turn {timer.turn_count}] ⚡ TTFT = {ttft:.0f}ms",
                                  flush=True)
                        # Decode + push to speaker queue
                        pcm = base64.b64decode(event.delta)
                        for i in range(0, len(pcm), CHUNK_SAMPLES * 2):
                            speaker_q.put(pcm[i : i + CHUNK_SAMPLES * 2])
                    elif etype == "response.audio_transcript.done":
                        print(f"[turn {timer.turn_count}] 🤖 agent: "
                              f"{event.transcript!r}", flush=True)
                    elif etype == "response.done":
                        resp = getattr(event, "response", None)
                        usage = getattr(resp, "usage", None) if resp else None
                        if usage is not None:
                            in_tok = getattr(usage, "input_tokens", "?")
                            out_tok = getattr(usage, "output_tokens", "?")
                            print(f"[turn {timer.turn_count}] ✓ done — "
                                  f"usage in={in_tok} out={out_tok}\n", flush=True)
                    elif etype == "error":
                        # Surface full error for diagnostics
                        err = getattr(event, "error", None)
                        print(f"\n[POC] ❌ ERROR: type={getattr(err, 'type', '?')} "
                              f"code={getattr(err, 'code', '?')} "
                              f"msg={getattr(err, 'message', '?')}", flush=True)
                    # else: silently ignore (rate_limits.updated, response.output_item.added, ...)
            except asyncio.CancelledError:
                # On exit, dump event histogram
                print(f"\n[POC] event histogram:", flush=True)
                for k, v in sorted(event_counter.items(), key=lambda x: -x[1]):
                    print(f"        {v:4d} × {k}", flush=True)
                return

        try:
            await asyncio.gather(pump_mic(), pump_events())
        except KeyboardInterrupt:
            print("\n[POC] interrupted — closing")
        finally:
            mic_stream.stop()
            mic_stream.close()
            spk_stream.stop()
            spk_stream.close()

    print(f"[POC] ✓ Phase 1.2 audio echo session ended — {timer.turn_count} turns")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[POC] bye")
