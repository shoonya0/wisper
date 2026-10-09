# Wisper: current state (snapshot 2026-10-09)

Snapshot taken at `1c99622` (narration N1 done) on `chore/ai-harness` (pushed; PR into `master` pending).
One page; update it when an increment lands.
Claims are marked **VERIFIED** (run or read in code) or **ASSUMED**.

## At a glance

| Area | State | Notes |
|---|---|---|
| App (3 modes) | ✅ working (ASSUMED: the author's use, not run during setup) | `app/app.py`. Since N1 the window is split: STT on the left, a TTS placeholder on the right. The app starts and loads a model on the GPU (VERIFIED by screenshot, N1) |
| Engine build | ✅ present (VERIFIED) | `whisper.cpp/build/bin/Release/whisper.dll` + `ggml-vulkan.dll`, `GGML_VULKAN=1` in CMakeCache |
| Models | ✅ present (VERIFIED) | base.en-q5_1, small.en-q5_1, large-v3-turbo-q5_0 in `whisper.cpp/models/` |
| Narration (TTS) | 🚧 N0 spike + N1 layout done, no narration yet | Kokoro-82M fp32 on the CPU: RTF 0.36–0.40 with 4 threads ([performance.md](./performance.md)); model in `models/kokoro/` |
| Tests | ✅ 37 tests (characterization, architecture, window layout, file stitching) | baseline below |
| AI harness | ✅ set up; CI runs on GitHub (guard-hook live probe pending) | [`ai-harness-setup.md`](./ai-harness-setup.md) |

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
- **Narration setup (Kokoro TTS model, gitignored, ~353 MB).** `kokoro-onnx` comes in
  through `app/requirements.txt`; espeak-ng is bundled, so there's nothing to install
  system-wide. Download the model files from the `kokoro-onnx` release `model-files-v1.1`
  into `models/kokoro/` and check the hashes (VERIFIED 2026-10-07):
  ```bash
  mkdir -p models/kokoro && cd models/kokoro
  B=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1
  curl -LO $B/kokoro-v1.0.onnx && curl -LO $B/voices-v1.0.bin
  # sha256 kokoro-v1.0.onnx  beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a
  # sha256 voices-v1.0.bin   bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
  sha256sum kokoro-v1.0.onnx voices-v1.0.bin
  ```
  Use fp32 only: `kokoro-v1.0.int8.onnx` is ~10× slower on this CPU. Benchmark:
  `app\.venv\Scripts\python.exe tools/tts_bench.py --variants fp32 --threads 4`.
- **Fast check:** `node tools/verify.mjs` (ruff check → pyright → pytest, ~6 s). **Full:** `node tools/verify.mjs --full` (same today; slow GPU checks go there).
- **Tests only:** `app\.venv\Scripts\python.exe -m pytest` (config in root `pyproject.toml`).

## Test baseline (after the file-overlap fix)

| Suite | Result | Known failures (by name) |
|---|---|---|
| pytest (`app/tests/`, 37 tests: architecture, audio_io, capture segmenter, file stitching, hallucination filter, window layout) | 37/37 pass (2.4 s) | none |
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

1. ~~**File mode repeats words at window boundaries**~~ FIXED (2026-10-09): File mode
   now makes one `whisper_full` call on the whole file (`Whisper.transcribe_long`), so
   whisper.cpp seeks by its own timestamps and streams segments through a callback.
   Trimming the 1 s overlap of fixed 25 s windows by timestamps didn't work: Whisper
   invents words for the speech cut off at each window's end. Segments with more than
   60 characters per second are dropped (`is_too_dense`): long-form turbo invented a
   whole sentence in the last 0.62 s of a file. GPU check: jfk.wav ×6 (66 s) gives
   exactly 135 words with base.en, small.en and large-v3-turbo (the old code gave
   140 / 141 / 133). `audio_io.split_windows` was removed with its 4 tests (user, 2026-10-09).
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
8. ~~**Status line and level meter never visible**~~ FIXED in N1 (2026-10-07): at the
   default 940×640 the transcript's requested height pushed the status row off the
   window (VERIFIED: `winfo_ismapped()` = 0 on the pre-N1 code). The status row is now
   packed at the bottom before the transcript; `test_window_layout.py` guards it.

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
  ADR: [`adr/0001-tts-engine-kokoro-onnx.md`](./adr/0001-tts-engine-kokoro-onnx.md) (Accepted).
  **N0 (spike) done 2026-10-07:** CPU only, fp32, 4 threads, RTF 0.36–0.40, a 5-word
  first chunk in 0.73–0.84 s; ADR Accepted; the user listened to all 7 language
  samples (2026-10-09): all acceptable, `af_heart` (en-us) the best. **N1 (split window) done 2026-10-07.** **Next: N2**
  (narration box with Save… / Clear / Copy all, no audio yet).
- Known issue 1 (File mode repeated words) is fixed on `fix/file-overlap` (2026-10-09).
