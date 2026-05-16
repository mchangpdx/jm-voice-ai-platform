# 2026-05-17 Bug 2 fix — greeting race-condition protection.
# (그리팅 race condition 보호 단위 테스트)
#
# Live triggers documented in the session log:
#   * CA438ad0… (JM Taco) — "JM Taco — welcome back," cut mid-sentence.
#   * CAe51612… (JM Taco) — 7-second silent window before caller spoke
#     "Halo?" and then got "Welcome back, Michael!".
#   * CA78068c… (JM Taco) — "Welcome back," cut, agent never recovered.
#
# Root cause: server_vad with `interrupt_response: True` cancelled the
# in-flight greeting when PSTN handshake noise hit the input buffer
# before the first response.audio.delta flipped bot_speaking to True.
#
# The fix runs three coordinated steps at call start:
#   1. session.update with `interrupt_response: False` (greeting is
#      uninterruptible while the line settles).
#   2. input_audio_buffer.clear + 300 ms wait so any PSTN line noise
#      captured during the handshake is discarded.
#   3. response.create greeting → on the first response.done, re-issue
#      session.update with `interrupt_response: True` so normal in-call
#      barge-in resumes for every subsequent turn.
#
# These tests anchor the three steps against the source text — if any of
# them is reverted the regression alarm fires before the code reaches a
# live call.

from __future__ import annotations

from pathlib import Path


_SOURCE = (
    Path(__file__).resolve().parents[3] / "app" / "api" / "realtime_voice.py"
).read_text()


# ── Step 1: initial session.update starts with interrupt_response=False ────

def test_initial_session_update_disables_interrupt_response() -> None:
    """The session.update issued during call start MUST set
    interrupt_response=False so the greeting can't be cancelled by
    server VAD before bot_speaking flips True.
    (초기 session.update는 interrupt_response False로 시작)
    """
    # Locate the first turn_detection block (initial session.update).
    head = _SOURCE.split('"silence_duration_ms":  1200', 1)
    assert len(head) == 2, "initial turn_detection block not found"
    # The next interrupt_response setting must be False — anchors the
    # pre-greeting protective configuration. Whitespace-tolerant so the
    # column-alignment polish in the source can drift without breaking
    # the regression alarm.
    next_chunk = head[1][:1200]
    import re as _re
    m = _re.search(r'"interrupt_response"\s*:\s*(True|False)', next_chunk)
    assert m and m.group(1) == "False", (
        "initial session.update must start with interrupt_response=False "
        "to protect the greeting from PSTN noise cancellation"
    )


# ── Step 2: pre-greeting buffer clear + 300 ms wait ─────────────────────────

def test_pregreeting_input_buffer_clear_and_settle() -> None:
    """Before response.create greeting fires, the code MUST clear the
    input_audio_buffer (drops any PSTN noise from the handshake) and
    then sleep ~0.3 s so server VAD has a quiet baseline before audio
    starts streaming.
    (response.create 전 buffer clear + 300ms 대기)
    """
    # Order matters — clear must come before the asyncio.sleep, both
    # must come before the greeting response.create.
    clear_idx   = _SOURCE.find("oai.input_audio_buffer.clear()")
    sleep_idx   = _SOURCE.find("asyncio.sleep(0.3)")
    greeting_idx = _SOURCE.find("initial greeting response.create sent")

    assert clear_idx    > 0, "input_audio_buffer.clear() missing pre-greeting"
    assert sleep_idx    > 0, "300ms settle wait missing pre-greeting"
    assert greeting_idx > 0, "greeting response.create marker missing"
    assert clear_idx < sleep_idx < greeting_idx, (
        "pre-greeting order broken — must be clear → sleep → response.create"
    )


# ── Step 3: response.done promotes interrupt_response to True ───────────────

def test_response_done_promotes_interrupt_response_to_true_once() -> None:
    """The first response.done after the greeting MUST re-issue
    session.update with interrupt_response=True so normal in-call
    barge-in is restored. The latch (`greeting_done`) prevents the
    promotion from firing on every subsequent response.done.
    (greeting_done one-shot으로 interrupt mode 정상 복귀)
    """
    # Latch initialized False.
    assert '"greeting_done": False,' in _SOURCE, (
        "greeting_done one-shot latch missing from stats init"
    )
    # The promotion block must guard on the latch and flip it BEFORE
    # awaiting session.update — otherwise a tightly-packed pair of
    # response.done events could double-issue the update.
    promotion_block = _SOURCE.split('if not stats.get("greeting_done"):', 1)
    assert len(promotion_block) == 2, "promotion guard missing"
    tail = promotion_block[1][:1500]
    assert 'stats["greeting_done"] = True' in tail, (
        "latch must flip True before issuing the post-greeting session.update"
    )
    import re as _re
    m = _re.search(r'"interrupt_response"\s*:\s*(True|False)', tail)
    assert m and m.group(1) == "True", (
        "post-greeting session.update must set interrupt_response=True"
    )


# ── Cross-cutting: the initial session.update still configures the rest ────

def test_initial_session_update_still_configures_tools_and_audio() -> None:
    """The initial session.update is a full configuration call — it
    sets tools, transcription, audio formats, etc. The Bug 2 fix only
    relaxed interrupt_response; the rest of the config must remain.
    (interrupt_response만 완화 — 나머지 config 보존)
    """
    head = _SOURCE.split('"silence_duration_ms":  1200', 1)[0]
    # Anchors that prove the surrounding session config is intact.
    assert '"type": "realtime"' in head
    assert '"audio/pcmu"' in head            # input format
    assert '"server_vad"' in head            # detection type
    assert '"threshold":            0.5' in head
