# Wisper: current state (snapshot 2026-10-12)

Snapshot taken at `46664f5` on `master` (narration N0–N10 merged: PRs #1, #3, #4, #5, #6, #8, #9, #10, #13; File-mode
fix PR #2; start-up defaults and run docs PR #11). Open issues: #12, #14 (fixed on the branch below).
Since then, on branch `feat/deepseek-terminal` (2026-10-12): the DeepSeek terminal spec, its P0 spike, P1
(`app/terminal.py`), P2 (the terminal replaces the transcript box), the #14 fix (Ctrl+A), P3 (File mode stops at
100 words), P4 (answers narrated) and P5 (taking turns, Job Object); no PR yet.
One page; update it when an increment lands.
Claims are marked **VERIFIED** (run or read in code) or **ASSUMED**.

## At a glance

| Area | State | Notes |
|---|---|---|
| App (3 modes) | ✅ working (ASSUMED: the author's use, not run during setup) | `app/app.py`. Since N1 the window is split: STT on the left, TTS on the right (narration box with Save… / Clear / Copy all, Speak/Stop, voice and speed since N5; Output Only me / Only others / Both and Me / Others devices since N6; Mic + "Send my mic to the call" since N8). The app starts and loads a model on the GPU (VERIFIED by screenshot, N1) |
| Engine build | ✅ present (VERIFIED) | `whisper.cpp/build/bin/Release/whisper.dll` + `ggml-vulkan.dll`, `GGML_VULKAN=1` in CMakeCache |
| Models | ✅ present (VERIFIED) | base.en-q5_1, small.en-q5_1, large-v3-turbo-q5_0 in `whisper.cpp/models/` |
| Narration (TTS) | 🚧 N0–N6 done and merged: Speak/Stop with voice and speed (T-TTS-1…5 passed). N6 (Only me / Only others / Both, default Both, PR #8): Google Meet heard the narration through VB-Cable (T-MODE-2, 2026-10-10). N8 (mic pass-through: the call hears the user's voice and the narration together, PR #9): user checked it in a call and reported it working (2026-10-10). N7 (Ctrl+Enter, "Speaking 3/12…", Live captions feedback hint, PR #10): T-KEY-1 and the progress check passed (user, 2026-10-10); T-ERR-2 deferred. N9 (pause and resume, PR #13): T-PAUSE-1 passed (user, 2026-10-11); **pending: T-PAUSE-2** (in a call). N10 (mark the narrated text, PR #13): T-MARK-1 passed (user, 2026-10-11) | Kokoro-82M fp32 on the CPU: RTF 0.36–0.40 with 4 threads ([performance.md](./performance.md)); model in `models/kokoro/` |
| Tests | ✅ 337 fast + 2 slow tests on `feat/deepseek-terminal` (220 on `master`; see Test baseline) (characterization, architecture, capture devices, window layout + narration box, file stitching, TTS splitting/spans/voices/engine, playback, narrator, narration UI + output modes + mic pass-through + pause + narrated marks) | baseline below |
| DeepSeek terminal | 🚧 in progress: spec agreed, **P0–P5 done** 2026-10-12: the transcript box and Copy all / Clear / Save… are gone; `deepseek` runs in their place (`terminal_view.py`) from start-up, speech is typed into its input line (never Enter), "DeepSeek ended…" / "not found" lines, Enter restarts it. The user's manual check passed (no typing lag, speech, scroll-back, copy/paste, resize, restart, close); select-all in the prompt (issue #14) fixed after it: Ctrl+A selects the prompt's text, Ctrl+Shift+A is `deepseek`'s Ctrl+A. P3: File mode types at most 100 words, then whisper.cpp's abort callback stops the file (GPU check: base.en, 66 s file, the abort returns cleanly at 3.0 s vs 6.1 s for the whole file, and the next run works) and the status says "File: typed the first 100 words."; the `--- name ---` header is no longer typed. Code review: no blocking findings. **Manual check of P3: on hold with File mode** (a long file types exactly 100 words; a short one is typed whole). P4: each answer `deepseek` finishes comes back through its `Stop` hook (`answers.py`, given with `--settings`, settings file in `%TEMP%`) to a 127.0.0.1 listener with a per-run token; the Markdown becomes plain text, replaces the narration box and is spoken (an empty answer changes nothing; without Kokoro it waits in the box). VERIFIED: the hook command from a real settings file, run through Git Bash with a recorded hook input, delivers the answer in 0.19 s. **P4 VERIFIED by the user** (an answer is spoken without its Markdown marks, a second question while it's speaking replaces it, `/clear` narrates nothing; 2026-10-12). **P5 VERIFIED by the user** (2026-10-12; the File-mode row not checked: File mode is on hold): listening and narrating take turns (§3.2; Speak/Resume/an answer stop listening, ▶ Start/Transcribe pause the narration) and Wisper runs in a kill-on-close Job Object (`priority.kill_children_with_me`; VERIFIED by test: a child dies when its parent is `taskkill /F`-ed, survives without the job). N7's Live captions feedback hint is gone (impossible under D9). P1 VERIFIED: `deepseek` ready in 0.8 s (was 3.8 s: ConPTY waited for a device-attributes reply), key → drawn median 16 ms / max 33 ms (target 50), scroll-back 5000 lines, exit seen at once. P0: Interactive `deepseek` in a pseudo-console (`pywinpty`) drawn by `pyte` + Tk works, the `Stop` hook returns the final reply (`last_assistant_message`) and the Job Object kills the tree (all VERIFIED in the spike). The user's look at the spike window: typing lagged and there was no scroll-back; P1 addresses both (the user checks typing in P2) | [spec](./specs/2026-10-12-deepseek-terminal.md) §7 (§7.4 P1); workspace `AI-workspace/` (gitignored); hook fixtures in `app/tests/fixtures/deepseek-hook/` |
| AI harness | ✅ set up; CI runs on GitHub; guard hook verified live | [`ai-harness-setup.md`](./ai-harness-setup.md) |

## What a user can do today

- **Dictation**: transcribe the microphone as they speak (low latency, `small.en` default).
- **Live captions** (the start-up mode): transcribe desktop/meeting audio via WASAPI
  loopback (`small.en` default; the Windows default speakers are pre-selected).
- **File**: transcribe WAV/MP3/FLAC/OGG with progressive text (`large-v3-turbo` default).
  On `feat/deepseek-terminal` it types at most 100 words into the prompt, then stops (D8).
- Choose model (fastest ↔ most accurate) and language. On `master` the transcript box has
  Copy all / Save… / Clear; on `feat/deepseek-terminal` it's replaced by the DeepSeek terminal.
- **DeepSeek terminal** (branch `feat/deepseek-terminal`, P2): the real `deepseek` CLI runs in
  the left pane from start-up; speech is typed into its prompt (never sent); type, scroll back,
  copy, paste; Ctrl+A selects the prompt's text (Ctrl+Shift+A is `deepseek`'s Ctrl+A); `/exit`
  then Enter restarts it. Each answer DeepSeek finishes replaces the narration text and is spoken (P4; Markdown marks removed).
- **Narration box** (right pane): type or paste text; its own Copy all / Save… / Clear.
- **Narration**: Speak reads the narration box aloud with a chosen Kokoro voice and
  speed. The same button then **pauses** and **resumes** from the exact spot (N9: Speak →
  ⏸ Pause → ▶ Resume, status "Paused 3/12."); **Stop** or Clear ends it at once.
  **Ctrl+Enter** in the box follows the button, and the status line shows "Speaking 3/12…" (N7).
  While it plays, the sentence being spoken is highlighted and the ones already narrated
  are dimmed (N10); the marks go back to the start on Stop and at the end. **Output (N6):** Only me (Me device),
  Only others (Others device = the virtual cable, the call's microphone) or **Both**
  (default). CABLE Input is pre-selected as Others when found; **How to set up…** shows
  the steps. Changing the mode or a device while speaking stops the narration.
  **Verified in Google Meet** (mic = CABLE Output): the call hears the narration.
  If Live captions is running on a device the narration plays on (usually the speakers
  in Only me / Both), the status adds "Live captions will transcribe it too" (N7).
- **Mic pass-through (N8)**: "Send my mic to the call" (on by
  default when a cable is found) copies the chosen WASAPI mic into the cable, so the call
  hears the user's voice and the narration together. Measured voice delay to CABLE
  Output: 125–130 ms, no drift over 20 s. Use headphones (with speakers in Both, the call
  hears the narration twice). Why it's needed: with Meet's mic set to CABLE Output,
  Meet hears only the cable, never the real mic; untick it when the call app uses the
  real mic directly. The Mic list has WASAPI mics only, without cables.
- **Call setup on this PC**: VB-Audio Virtual Cable is installed: `CABLE Input` (output)
  and `CABLE Output` (microphone for Meet/Zoom/Discord) exist, and
  `playback.find_virtual_cable` picks `CABLE Input (VB-Audio Virtual Cable)` (VERIFIED).
  In Meet: ⋮ → Settings → Audio → Microphone = CABLE Output ("Default" is the real mic).

## How to build, run, test

- **Run:** `cd app` then `.venv\Scripts\pythonw.exe app.py` (no console), or
  `.venv\Scripts\python.exe app.py` to see tracebacks. `app\run.bat` runs the same
  `pythonw` command but doesn't start the app (reported 2026-10-11, cause not found yet).
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
- **Fast check:** `node tools/verify.mjs` (ruff check → pyright → pytest, ~6 s). **Full:** `node tools/verify.mjs --full` (adds the `slow` pytest tests: real Kokoro model, ~4 s).
- **Tests only:** `app\.venv\Scripts\python.exe -m pytest` (config in root `pyproject.toml`).

## Test baseline (after DeepSeek terminal P5, branch `feat/deepseek-terminal`)

| Suite | Result | Known failures (by name) |
|---|---|---|
| pytest fast (`-m "not slow"`, 337 tests: architecture, taking turns (§3.2), Job Object, terminal (pseudo-console with a Python child, key map, escape filter, scroll-back), terminal view (incl. Ctrl+A select-all), DeepSeek terminal in the window (fake terminal) + answers narrated, answers (hook input, Markdown → speech, Inbox, the hook script), audio_io, capture segmenter + devices, file stitching + 100-word File limit + abort, hallucination filter, window layout + narration box + start-up defaults, TTS split/spans/voices, playback + pause, narrator, narration UI + output modes + mic pass-through, polish, pause, narrated marks) | 337/337 pass (63.6 s) | none |
| pytest slow (`-m slow`, 2 tests: Kokoro voices + "Hello world." synthesis; skipped without `models/kokoro/`) | 2/2 pass (3.4 s) | none |
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
9. **Dictation's device list mixes host APIs**: `capture.list_sources(pa, "mic")` lists
   MME, DirectSound and WASAPI devices, with `Microsoft Sound Mapper - Input` (MME)
   first. Found in N8: the pass-through used it at first and its delay grew from 16 to
   266 ms in 8 s, so N8 uses the WASAPI-only `playback.list_inputs`. Dictation is
   unchanged (not measured whether it matters there).
10. **Live captions holds short phrases** ([#12](https://github.com/shoonya0/wisper/issues/12),
    2026-10-11): a phrase under 2 s (e.g. a 1.17 s "hi how are you" narration) isn't
    transcribed until more audio plays. `CAPTIONS.min_chunk_s` is 2.0 and loopback sends
    no blocks in silence, so the pause is never counted. Fix proposed in the issue.
11. **`app\run.bat` doesn't start the app** (reported 2026-10-11, cause not found): it runs
    the same `pythonw` command as the documented one; LF line endings were ruled out. Run
    from `app\` with `.venv\Scripts\pythonw.exe app.py` instead.
12. **DeepSeek terminal: no select-all in the prompt** ([#14](https://github.com/shoonya0/wisper/issues/14),
    2026-10-12): Ctrl+A went to `deepseek`. Fixed on `feat/deepseek-terminal` (`a3e4452`):
    Ctrl+A selects the prompt's text, Ctrl+Shift+A is `deepseek`'s Ctrl+A. Typing doesn't
    replace the selection (keys go to `deepseek`). Closes when the branch is merged.
13. ~~**DeepSeek terminal: File mode types its `--- name ---` header**~~ FIXED in P3
    (2026-10-12, branch only): the name shows in the status line ("Decoding name…") only.

## Possible next steps (from the original README)

- Swap the RMS gate for **Silero VAD** to cut false triggers on noisy input.
- **Global hotkey + type-into-focused-window** for system-wide dictation.
- Word-level timestamps / **SRT export** for File mode.
- A second resident model so Dictation and Captions can run different models without
  a reload.

## Next task

- **Next: DeepSeek terminal, P6** (manual test plan `_docs/test/deepseek-terminal.md` and docs), then
  a PR to `master`. P5 done (taking turns; the Job Object so closing Wisper always ends `deepseek`).
  **File mode is on hold** (user, 2026-10-12): no File-mode work or checks for now. P0–P4 are done (2026-10-12, spec §7;
  the user checked P2 and P4 by hand; issue #14, select-all, fixed). **Pending manual checks (on hold with File mode):** P3 (a long file types 100 words and stops) and
  P5's File row (a narration stops a running file).
  The feature: the transcript box
  becomes the real `deepseek` CLI (pseudo-console drawn in Tk), speech is typed into its input
  line, and each final answer replaces the narration text and is spoken; listening and
  narrating take turns. Hook fixtures in `app/tests/fixtures/deepseek-hook/`. Spec,
  decisions D1–D11 and phases P0–P6:
  [`specs/2026-10-12-deepseek-terminal.md`](./specs/2026-10-12-deepseek-terminal.md).
- **Planned feature: Narration (text to speech with Kokoro-82M).** The window splits
  into STT (left) and TTS (right), with output modes Only me / Only others / Both.
  Spec: [`specs/2026-10-07-kokoro-narration.md`](./specs/2026-10-07-kokoro-narration.md).
  Test plan: [`test/kokoro-narration.md`](./test/kokoro-narration.md).
  ADR: [`adr/0001-tts-engine-kokoro-onnx.md`](./adr/0001-tts-engine-kokoro-onnx.md) (Accepted).
  **N0 (spike) done 2026-10-07:** CPU only, fp32, 4 threads, RTF 0.36–0.40, a 5-word
  first chunk in 0.73–0.84 s; ADR Accepted; the user listened to all 7 language
  samples (2026-10-09): all acceptable, `af_heart` (en-us) the best.

  | Increment | State |
  |---|---|
  | N1 split window | done 2026-10-07 (PR #1) |
  | N2 narration box, Save… / Clear / Copy all, Speak disabled | done 2026-10-09 (PR #3), T-UI-2 passed |
  | N3 `tts.py` engine leaf | done 2026-10-09 (PR #4) |
  | N4 `playback.py` leaf | done 2026-10-09 (PR #5); real-device stop → 34 ms |
  | N5 `narrator.py` + wiring, mode "Only me" | done (PR #6): first sound 0.48 s, stop → silence ≤ 34 ms (silent-stream measurement); manual T-TTS-1…5 passed 2026-10-10 |
  | N6 "Only others" / "Both" (default Both) | done 2026-10-10 (PR #8, 145/145 fast). T-MODE-2 passed in Google Meet once Meet's microphone was set to CABLE Output (Meet's "Default" is the real mic). T-MODE-3/4/5 not reported yet. Wisper → cable round trip: Kokoro sentence peak 0.43 in, 0.44 out of CABLE Output; a beep arrives 5/5 times, ~0.12–0.18 s later ([performance.md](./performance.md)) |
  | N8 mic pass-through | done (PR #9, 174/174 fast). Spec: [`specs/2026-10-10-mic-passthrough.md`](./specs/2026-10-10-mic-passthrough.md). Windows mixes the mic stream and the narration stream in the cable (VERIFIED), so Wisper has no mixer. On by default with a cable; no ducking (the user uses headphones). Voice delay 125–130 ms ([performance.md](./performance.md)). Manual: user checked it in a call and reported it working (2026-10-10) |
  | N7 polish | done (PR #10, 189/189 fast): Ctrl+Enter = Speak/Stop (no newline; a held key counts once; nothing while Kokoro is missing); "Speaking i/n…" from `Narrator(on_progress=…)`; Live captions feedback hint at Speak; after a device error Speak works on another device (test). Device errors themselves were already handled in N5. Manual: T-KEY-1 and progress passed (2026-10-10); T-ERR-2 deferred by the user |
  | N9 pause and resume | done (PR #13, 205/205 fast; an earlier note said 207 by mistake). Spec: [`specs/2026-10-11-narration-pause.md`](./specs/2026-10-11-narration-pause.md). Speak → Pause → Resume on one button, a Stop button; `Player` waits between blocks with the streams open, so Resume continues mid-sentence. Manual: T-PAUSE-1 passed (user, 2026-10-11); **pending: T-PAUSE-2** (pause during a call) |
  | N10 mark the narrated text | done (PR #13, 220/220 fast). Spec: [`specs/2026-10-11-narration-highlight.md`](./specs/2026-10-11-narration-highlight.md). Piece by piece (Kokoro has no word timings): the piece playing is highlighted, the ones before it dimmed; cleared on Stop, at the end, on an error and when the text is edited. Manual: T-MARK-1 passed (user, 2026-10-11) |
  | **Latency** (next, user goal: lowest possible delay in live calls) | measure the whole chain in a real call first (`optimized-app-research`), then: synthesize while typing, phrase cache, smaller player blocks, smaller VB-Cable buffer |
- Known issue 1 (File mode repeated words) is fixed and merged (PR #2, 2026-10-09).
