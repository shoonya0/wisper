# Wisper: current state (snapshot 2026-10-07)

Snapshot taken at `a1dc6b3` + AI harness commits on `chore/ai-harness` (not pushed).
One page; update it when an increment lands.
Claims are marked **VERIFIED** (run or read in code) or **ASSUMED**.

## At a glance

| Area | State | Notes |
|---|---|---|
| App (3 modes) | ✅ working (ASSUMED: the author's use, not run during setup) | `app/app.py` |
| Engine build | ✅ present (VERIFIED) | `whisper.cpp/build/bin/Release/whisper.dll` + `ggml-vulkan.dll`, `GGML_VULKAN=1` in CMakeCache |
| Models | ✅ present (VERIFIED) | base.en-q5_1, small.en-q5_1, large-v3-turbo-q5_0 in `whisper.cpp/models/` |
| Tests | ✅ 26 characterization + architecture tests | baseline below |
| AI harness | ✅ set up (guard-hook live probe and CI run pending) | [`ai-harness-setup.md`](./ai-harness-setup.md) |

## What a user can do today

- **Dictation**: transcribe the microphone as they speak (low latency, `small.en` default).
- **Live captions**: transcribe desktop/meeting audio via WASAPI loopback
  (`large-v3-turbo` default).
- **File**: transcribe WAV/MP3/FLAC/OGG with progressive text (`large-v3-turbo` default).
- Choose model (fastest ↔ most accurate) and language; Copy all / Save… / Clear.

## How to build, run, test

- **Run:** `app\run.bat` (uses `app\.venv\Scripts\pythonw.exe`), or
  `cd app` then `.venv\Scripts\python.exe app.py` to see tracebacks.
- **Setup (fresh clone):** `py -3.12 -m venv app\.venv`, then
  `app\.venv\Scripts\python.exe -m pip install -r app\requirements-dev.txt`. The venv
  is Python 3.12.10 (VERIFIED).
- **Engine (gitignored, rebuild if missing).** This needs the Vulkan SDK (for `glslc`)
  and CMake. The current build used Visual Studio 18 2026 (VERIFIED from CMakeCache):
  ```bat
  git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp && git checkout 6e4ab85
  cmake -B build -DGGML_VULKAN=1
  cmake --build build --config Release -j
  ```
  Then put `ggml-base.en-q5_1.bin`, `ggml-small.en-q5_1.bin` and
  `ggml-large-v3-turbo-q5_0.bin` in `whisper.cpp/models/`.
  **Keep `6e4ab85` unless you also re-check the ctypes structs** (architecture-overview).
- **Fast check:** `node tools/verify.mjs` (ruff check → pyright → pytest, ~6 s). **Full:** `node tools/verify.mjs --full` (same today; slow GPU checks go there).
- **Tests only:** `app\.venv\Scripts\python.exe -m pytest` (config in root `pyproject.toml`).

## Test baseline (at `a1dc6b3` + the harness tests)

| Suite | Result | Known failures (by name) |
|---|---|---|
| pytest (`app/tests/`, 26 tests: architecture, audio_io, capture segmenter, hallucination filter) | 26/26 pass (1.9 s) | none |
| ruff check | 0 findings (after `a1dc6b3` sorted imports) | — |
| pyright (basic) | 0 errors (`live_transcriber.py` excluded, open decision 1) | — |

Compare new runs against this list **by test name**.

## Open decisions

| # | Decision needed | Options | Owner | Blocking? |
|---|---|---|---|---|
| 1 | `app/live_transcriber.py` (legacy, unused) | delete · keep as reference · fold its differences into `app.py` | user | no |
| 2 | How to pin whisper.cpp | gitignored + documented commit (current) · git submodule | user | no |
| 3 | large-v3-turbo speed: README says ~6.3× RT, an earlier note says ~4.6× | re-measure with `whisper-bench` | user | no |

## Known issues and risks

1. **File mode repeats words at window boundaries** (VERIFIED by reading code).
   `audio_io.split_windows` overlaps windows by 1 s and its docstring says "the caller
   trims the overlap", but `App._transcribe_file` (`app/app.py:441`) appends every
   window's full text.
2. ~~**`.m4a` is offered but can't be decoded**~~ FIXED (2026-10-07): `.m4a` removed
   from `AUDIO_EXTS`; undecodable files now raise a `ValueError` naming the supported
   formats instead of miniaudio's bare `('failed to decode file', -1)`. AAC support
   would need an ffmpeg/PyAV dependency (not added).
3. **ctypes struct drift**: `app/whisper_native.py` hard-codes `whisper.h` layouts at
   `6e4ab85`. A newer whisper.cpp build can crash or mis-set params silently.
4. **Cross-thread attributes without locks**: `busy`, `language`, `loaded_model_path`,
   `last_text` in `app/app.py`. This is safe today under the GIL, and fragile if the
   logic grows.
5. **No logs under `pythonw`**: errors are only visible as dialogs or status flashes.
6. **Duplicate code**: `app/live_transcriber.py` duplicates the capture/segmenter and
   UI. Fixes made in `capture.py` won't reach it.
7. **Line endings**: `core.autocrlf` converts LF→CRLF. There's no `.gitattributes`.

## Possible next steps (from the original README)

- Swap the RMS gate for **Silero VAD** to cut false triggers on noisy input.
- **Global hotkey + type-into-focused-window** for system-wide dictation.
- Word-level timestamps / **SRT export** for File mode.
- A second resident model so Dictation and Captions can run different models without
  a reload.

## Next task

- **Planned feature: Narration (text to speech with Kokoro-82M).** The window splits
  into STT (left) and TTS (right), with output modes Only me / Only others / Both.
  Spec: [`specs/2026-10-07-kokoro-narration.md`](./specs/2026-10-07-kokoro-narration.md).
  Test plan: [`test/kokoro-narration.md`](./test/kokoro-narration.md).
  ADR: [`adr/0001-tts-engine-kokoro-onnx.md`](./adr/0001-tts-engine-kokoro-onnx.md) (Proposed).
  Spec status: draft, waiting for user review. First increment: **N0** (measure Kokoro on
  this PC).
- Still open: fix known issue 1 (overlap trimming), with characterization tests on
  `audio_io.split_windows` first.
