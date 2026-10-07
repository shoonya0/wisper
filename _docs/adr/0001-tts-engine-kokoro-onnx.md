# ADR 0001: Text-to-speech engine: Kokoro-82M through `kokoro-onnx` on the CPU

| Field | Value |
|---|---|
| Status | **Proposed** (moves to Accepted or Rejected after spike N0 measures it on this PC) |
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

## Decision (proposed)

**A**: `kokoro-onnx==0.6.1` on the **CPU only**. The CPU-only part is a user decision
(2026-10-07): the GPU runs Whisper, and Kokoro must not compete with it. N0 only
measures CPU variants (fp32 vs int8, thread counts). Revisit C only if the user asks to
move TTS to the GPU later.

## Evidence so far (VERIFIED 2026-10-07)

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

## To confirm in N0 (blocks Accepted)

- RTF ≤ 0.5 and first sentence ≤ 1 s on this CPU (spec §6), fp32 vs int8.
- espeak-ng works with networking off (fully offline).
- Hindi, Spanish and French voices produce intelligible speech with the espeak G2P.

## Consequences

- New runtime dependency `kokoro-onnx` (plus the transitive ones above) in
  `app/requirements.txt`.
- `phonemizer` and espeak-ng are **GPL-3.0**. That's fine for local or personal use;
  revisit if Wisper is distributed (spec open decision 3).
- Model files (80–300 MB) are downloaded manually into the gitignored `models/kokoro/`.
  Setup steps go into `current-state.md`.
- TTS on the CPU leaves the GPU to Whisper, so STT and narration can run together.
