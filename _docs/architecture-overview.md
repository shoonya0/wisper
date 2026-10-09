# Wisper: architecture overview

Snapshot at `b48a3ff`. Source: code read during setup (VERIFIED) and the original root
README (moved here). Keep this under about 250 lines; link deeper docs instead of
inlining them.

## Overview diagram

```text
                       ┌───────────────── app/app.py (Tkinter UI thread) ─────────────────┐
 mic / loopback ──►  capture.Capture ──on_chunk──►  jobs Queue  ──►  worker thread  ──►  results Queue ──► _poll() (every 100 ms) ──► transcript
 (pyaudiowpatch)     RMS gate → 16 kHz chunks         ("audio",…)     owns the ONE        ("text"|"ready"|…)
                                                       ("file",…)     Whisper model
 audio file ──────►  audio_io.decode_to_16k_mono ─ whole file, one long-form pass ─────┘        │
                                                                                         whisper_native.Whisper
                                                                                         ctypes → whisper.dll (Vulkan, GPU)
```

## Modules

| Module | Path | Responsibility | Owns state? |
|---|---|---|---|
| UI + orchestration | `app/app.py` | 3-mode Tkinter app, model picker, job/result queues, worker loop | Yes: UI state, transcript, the loaded model (worker thread only) |
| Capture | `app/capture.py` | List mic/loopback devices; record; energy-gate segmentation into 16 kHz mono chunks; `DICTATION` / `CAPTIONS` profiles | Per-session capture thread + block queue |
| File decode | `app/audio_io.py` | Decode WAV/MP3/FLAC/OGG to 16 kHz mono via miniaudio | No |
| Engine binding | `app/whisper_native.py` | ctypes binding to `whisper.dll`; load the model once (GPU-resident); `transcribe()` | The whisper context (not thread safe) |
| Platform | `app/priority.py` | Windows-only: raise process/thread/GPU scheduling priority, turn off EcoQoS throttling. Best effort, never raises | No |
| Text to speech | `app/tts.py` | Narration engine (N3, not wired into the UI until N5): `load()` Kokoro-82M fp32 on the CPU (onnxruntime, 4 threads); `Engine.voices()` / `Engine.synthesize()` → float32 @ 24 kHz; pure `split_sentences()` and `lang_for_voice()` | The Kokoro ONNX session (not thread safe: TTS worker only) |
| Legacy | `app/live_transcriber.py` | Older standalone loopback-only transcriber (large-v3-turbo). Duplicates capture logic. Not imported by `app.py`, `run.bat` or docs | Its own copy of everything |
| Launcher | `app/run.bat` | Starts `app.py` with the venv's `pythonw.exe` | — |
| Engine (upstream) | `whisper.cpp/` (gitignored) | ggml-org/whisper.cpp clone at `6e4ab85`, built with `-DGGML_VULKAN=1`. DLLs in `build/bin/Release/`, models in `models/` | Not our code; no `_docs/` there |

## Layers and allowed imports (target, enforced by import-linter once H9 lands)

| From \ To | app | capture | audio_io | whisper_native | priority | tts | live_transcriber |
|---|---|---|---|---|---|---|---|
| **app** | — | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **capture** | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ |
| **audio_io** | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ |
| **whisper_native** | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ |
| **priority** | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ |
| **tts** | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ |

`app.py` is the only module that wires things together. The five lower modules are
independent leaves: each depends only on third-party libraries or the stdlib.
`live_transcriber.py` is legacy; nothing may import it.

## Main flows

1. **Model load**: `App._request_model` (`app/app.py:350`) → `jobs.put(("model", path))`
   → `_worker_loop` (`app/app.py:460`) closes the old model, creates `Whisper(DLL_DIR, path)`,
   runs a 1 s silent warm-up, then posts `("ready", None)`.
   English-only models pin the language to `en` and lock the language box.
2. **Dictation / live captions**: `toggle` (`app/app.py:367`) starts `capture.Capture`
   with the mode's `Profile` → `_segment_loop` (`app/capture.py:135`) cuts chunks at
   pauses (RMS < 0.006) → `_on_audio_chunk` queues `("audio", chunk, last 200 chars)`
   (the prompt gives context) → the worker transcribes, drops `is_junk` text, then posts
   `("text", …)`.
3. **File**: `start_file` → `("file", path)` → `_transcribe_file` (`app/app.py:509`)
   decodes, then `Whisper.transcribe_long` runs one `whisper_full` on the whole file.
   whisper.cpp's segment and progress callbacks run on the worker thread and post
   `("text", …)` and `("progress", %)`; overly dense segments (hallucinations) are dropped.
4. **UI loop**: `_poll` (`app/app.py:550`) drains `results` every 100 ms, appends text,
   and updates the status line and level meter.

## Threading and state

- **Exactly one thread touches the model**, the worker started in `App.__init__`. Whisper
  contexts aren't thread safe (`whisper_native.Whisper` docstring).
- The capture thread only produces chunks. The UI thread only reads `results`.
- Shared attributes read across threads without locks: `busy`, `language`,
  `loaded_model_path`, `last_text`. This is acceptable under the GIL but fragile; see
  current-state known issues.

## Engine notes (from the original README)

- RX 580 = Polaris/gfx803. **ROCm dropped it**, so PyTorch-ROCm, CTranslate2/faster-whisper
  on the GPU and NeMo/Parakeet all fall back to the CPU. **Vulkan is the only GPU-compute
  path**, and whisper.cpp is the maintained engine that uses it with top-accuracy models.
- `flash_attn` stays **off**, since Polaris has no usable fp16 (`app/whisper_native.py`).
- Decoding is greedy, `temperature=0`, `no_context=True`, and segments with
  `no_speech_prob > 0.6` are dropped.
- `whisper_native.py` struct layouts mirror `whisper.cpp/include/whisper.h` at the
  pinned commit. **Rebuilding whisper.cpp from a newer commit requires re-checking every
  struct**, or the result is crashes or silently wrong params.
- Benchmarks and why this stack: [`performance.md`](./performance.md).

## Errors and logging

- Worker exceptions become `("error", msg)` (a modal dialog) or `("status", msg)` (a
  5 s flash). There's no log file and no console, because the app runs under `pythonw`.
- `priority.py` swallows all failures by design.

## Testing seams

- `capture.Profile` with `_segment_loop`, `app.is_junk` and `whisper_native.is_too_dense`
  are pure or near-pure and unit-tested.
- `App._transcribe_file` runs with a fake model and a stand-in `self` (no Tk, no GPU), and
  `Whisper.transcribe_long` runs against a fake `lib` that fires the ctypes callbacks
  (`app/tests/test_file_stitching.py`).
- `whisper_native.Whisper` needs the DLL and the GPU. Treat it as a manual/integration
  test (`whisper.cpp/models/for-tests-*.bin` are tiny models usable for smoke tests).
