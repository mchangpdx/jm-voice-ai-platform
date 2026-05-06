"""Phase 1.2 디버그 — macOS 마이크 권한 + 캡처 검증.
(OpenAI 무관, 순수 sounddevice 테스트)

3초간 마이크에서 캡처해 RMS 레벨 표시.
- RMS == 0  → macOS Terminal 마이크 권한 거부 (또는 다른 입력 장치 활성)
- RMS > 100 → 정상 (조용한 환경에서도 100~500 정도 자연 노이즈 발생)
- RMS > 1000 → 사용자 발화 감지 정상
"""

import sys
import time

sys.stdout.reconfigure(line_buffering=True)
print("[MIC] starting mic-only sanity test (3 seconds)…", flush=True)

import numpy as np
import sounddevice as sd

print(f"[MIC] sounddevice={sd.__version__} numpy={np.__version__}", flush=True)
print(f"[MIC] default input device idx={sd.default.device[0]} → "
      f"{sd.query_devices(sd.default.device[0])['name']}", flush=True)

SAMPLE_RATE = 24_000
DURATION = 3.0
print(f"[MIC] Speak loudly NOW — recording {DURATION}s @ {SAMPLE_RATE}Hz mono PCM16",
      flush=True)

t0 = time.time()
data = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16",
    blocking=True,
)
t1 = time.time()
print(f"[MIC] recording done in {t1 - t0:.1f}s — shape={data.shape}", flush=True)

arr = data.astype(np.float64).flatten()
rms = float(np.sqrt(np.mean(arr ** 2)))
peak = float(np.max(np.abs(arr)))

print(f"[MIC] RMS:  {rms:.1f}  (PCM16 max=32767)", flush=True)
print(f"[MIC] Peak: {peak:.0f}", flush=True)

if rms < 5:
    print("[MIC] ❌ FAIL — RMS≈0. macOS 마이크 권한 미부여 가능성. 해결:", flush=True)
    print("       System Settings → Privacy & Security → Microphone → Terminal ON",
          flush=True)
    print("       또는 다른 input device 활성 (sd.default.device[0] 확인)", flush=True)
    sys.exit(1)
elif rms < 100:
    print("[MIC] ⚠ very quiet — 마이크는 동작하나 음성 거의 없음. 더 큰 소리로 다시.",
          flush=True)
elif peak > 16000:
    print("[MIC] ✅ PASS — 마이크 정상 + 발화 감지됨", flush=True)
else:
    print("[MIC] ✅ PASS — 마이크 동작 (자연 노이즈 감지)", flush=True)
