# ADR 0001: Text-to-speech engine: Kokoro-82M through `kokoro-onnx` on the CPU

| Field | Value |
|---|---|
| Status | **Accepted** (2026-10-07, after spike N0). One check is still open: the user hasn't yet listened to the language samples (see the Languages row) |
| Date | 2026-10-07 |
| Spec | [`_docs/specs/2026-10-07-kokoro-narration.md`](../specs/2026-10-07-kokoro-narration.md) |

## Context

The user asked for Kokoro-82M (Apache-2.0 weights, 24 kHz, 54 voices in 8 languages)
for the new narration feature. Wisper runs on Windows with an RX 580 (Polaris), which has
**no ROCm**, so PyTorch can't use the GPU (`architecture-overview.md`, engine notes). The
GPU is already busy with Whisper (Vulkan) in Dictation and Live captions.

## Options

| Option | Runtime on this PC | Install weight | Notes |
|---|---|---|---|
| **A. `kokoro-onnx` (CPU onnxruntime)** | CPU | onnxruntime (~15 MB) + model 80–300 MB | Same v1.0 weights; espeak-ng bundled through `espeakng-loader`; MIT package; simple sync `create()` API |
| B. Official `kokoro` (hexgrad, PyTorch) | CPU (no ROCm) | torch ~2 GB + `misaki` | Reference implementation; heavy; needs an espeak-ng system install for non-English |
| C. `kokoro-onnx` + `onnxruntime-directml` | GPU through DirectX 12 | swaps the onnxruntime wheel | **Ruled out for now (user, 2026-10-07): the GPU is reserved for Whisper.** It would also share the GPU with Whisper, is less tested with Kokoro, and can't be installed alongside the CPU onnxruntime |
| D. kokoro.cpp / GGUF builds | CPU or Vulkan | C++ build + ctypes binding | Smaller ecosystem; another hand-written binding to maintain, like `whisper_native.py` |

## Decision

**A**: `kokoro-onnx` (`>=0.6.1,<0.7` in `app/requirements.txt`; 0.6.1 measured) on the **CPU only**, with the **fp32** model and **4** onnxruntime intra-op threads. The CPU-only part is a user decision
(2026-10-07): the GPU runs Whisper, and Kokoro must not compete with it. N0 only
measures CPU variants (fp32 vs int8, thread counts). Revisit C only if the user asks to
move TTS to the GPU later.

## Evidence before the spike (VERIFIED 2026-10-07)

- PyPI: `kokoro-onnx 0.6.1`, released 2026-08-19, `requires-python >=3.10,<3.14`.
  Dependencies: `onnxruntime>=1.20.1`, `espeakng-loader>=0.2.4`, `phonemizer>=3.4.0`,
  `numpy>=2.0.2`.
- `app\.venv\Scripts\python.exe -m pip install --dry-run kokoro-onnx==0.6.1` →
  kokoro-onnx 0.6.1, onnxruntime 1.30.0, espeakng-loader 0.2.4, phonemizer 3.4.0,
  protobuf 7.36.2, flatbuffers, attrs, dlinfo, joblib, cloudpickle. numpy 2.5.3 is kept,
  so there's no conflict.
- Public API (`src/kokoro_onnx/__init__.py`): `Kokoro(model_path, voices_path)`,
  `create(text, voice, speed=1.0, lang="en-us") -> (samples, sample_rate)`, `get_voices()`.
- A third-party Android ONNX benchmark reports RTF 0.58 for Kokoro-82M. That's not this
  hardware, so it's only a hint that CPU real time is plausible.

## Spike N0 results (VERIFIED 2026-10-07, details in [performance.md](../performance.md))

| Check | Result |
|---|---|
| RTF ≤ 0.5 on this CPU (i5-10400F) | ✅ fp32 with 4 threads on an idle CPU: **RTF 0.36–0.40** total over 61 s of audio (two runs) |
| First sound ≤ 1.0 s | ✅ with the first chunk capped at 6 words: a 5-word chunk is ready in **0.73–0.84 s** p50 (max 0.91 s). ❌ a 16-word first sentence takes 1.80 s → spec §5.2 adds the 6-word first-chunk cap. ⚠ under CPU contention the 5-word chunk rose to 1.33 s; N5 must measure it with Whisper running |
| int8 model | ❌ **~10× slower** than fp32 on this CPU (RTF 3.25–4.54). Rejected; the default is fp32 (`kokoro-v1.0.onnx`, 325 MB) |
| Offline | ✅ every benchmark run with `--offline` had all Python socket calls blocked; espeak-ng loads from the venv |
| Languages | ⏳ en-us, en-gb, es, fr-fr, hi, it, pt-br all produce non-silent audio (peak 0.33–0.79). **Intelligibility is pending:** the user listens to `models/kokoro/samples/*.wav`. If hi, es or fr is unintelligible, that voice is dropped from the v1 voice list (the engine choice stays) |
| Load time | ✅ 1.3–1.5 s session load + ~2.0 s first-call warm-up, done in the background |

## Consequences

- New runtime dependency `kokoro-onnx` (plus the transitive ones above) in
  `app/requirements.txt`.
- `phonemizer` and espeak-ng are **GPL-3.0**. That's fine for local or personal use;
  revisit if Wisper is distributed (spec open decision 3).
- Model files (`kokoro-v1.0.onnx` 325 MB + `voices-v1.0.bin` 28 MB, sha256 in `current-state.md`) are downloaded manually into the gitignored `models/kokoro/`.
  Setup steps go into `current-state.md`.
- TTS on the CPU leaves the GPU to Whisper, so STT and narration can run together.
