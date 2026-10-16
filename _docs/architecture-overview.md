# Wisper: architecture overview

Snapshot at `b48a3ff`. Source: code read during setup (VERIFIED) and the original root
README (moved here). Keep this under about 250 lines; link deeper docs instead of
inlining them.

## Overview diagram

```text
                       ┌───────────────── app/app.py (Tkinter UI thread) ─────────────────┐
 mic / loopback ──►  capture.Capture ──on_chunk──►  jobs Queue  ──►  worker thread  ──►  results Queue ──► _poll() (every 100 ms) ──► DeepSeek terminal (typed, no Enter)
 (pyaudiowpatch)     RMS gate → 16 kHz chunks         ("audio",…)     owns the ONE        ("text"|"ready"|…)
                                                       ("file",…)     Whisper model
 audio file ──────►  audio_io.decode_to_16k_mono ─ whole file, one long-form pass ─────┘        │
                                                                                         whisper_native.Whisper
                                                                                         ctypes → whisper.dll (Vulkan, GPU)

 narration box ──Speak──►  tts_jobs Queue ──► TTS worker thread ──────────────► tts_results Queue ──► _poll_tts() ──► button / TTS status
 (snapshot of text)        ("speak", gen, …)  owns the ONE Kokoro engine        ("tts_done"|"tts_error", gen, …)
                                              narrator.Narrator: split → synth k+1 ║ play k (narration-player thread)
                                                                                    └─► playback.Player ─► PaStream (speakers)
 Stop / Clear (UI thread): narrator.stop() (generation id + Event) and player.stop() → silent within one 50 ms block
```

## Modules

| Module | Path | Responsibility | Owns state? |
|---|---|---|---|
| UI + orchestration | `app/app.py` | 3-mode Tkinter app, model picker, job/result queues, worker loop; the DeepSeek terminal (starts `deepseek`, types speech into it, redraws it every 16 ms, restarts it on Enter; narrates each answer its Stop hook sends to `answers.Inbox`); the TTS pane (Speak/Stop, voice, speed, output mode, Me/Others devices, How to set up…, narration box) and the TTS worker loop; the ear channels strip at the bottom (C4: two ear menus, volumes, App volume, Reset; builds the `channels.Router` through `make_ear_router`, drains its `ear_results` in `_poll`, closes it in `on_close`) | Yes: UI state, the DeepSeek terminal, the loaded model (worker thread only), the Kokoro engine (TTS worker only) |
| Capture | `app/capture.py` | List mic/loopback devices; record; energy-gate segmentation into 16 kHz mono chunks; `DICTATION` / `CAPTIONS` profiles | Per-session capture thread + block queue |
| File decode | `app/audio_io.py` | Decode WAV/MP3/FLAC/OGG to 16 kHz mono via miniaudio | No |
| Engine binding | `app/whisper_native.py` | ctypes binding to `whisper.dll`; load the model once (GPU-resident); `transcribe()` | The whisper context (not thread safe) |
| Platform | `app/priority.py` | Windows-only: raise process/thread/GPU scheduling priority, turn off EcoQoS throttling; P5: `kill_children_with_me()` puts the process in a kill-on-close Job Object (called first in `main()`, never by tests). Best effort, never raises | No |
| Text to speech | `app/tts.py` | Narration engine (N3): `load()` Kokoro-82M fp32 on the CPU (onnxruntime, 4 threads); `Engine.voices()` / `Engine.synthesize()` → float32 @ 24 kHz; pure `split_sentences()`, `piece_spans()` (N10: where each piece is in the text) and `lang_for_voice()` | The Kokoro ONNX session (not thread safe: TTS worker only) |
| Narration output | `app/playback.py` | N4: `list_outputs()` (WASAPI, default first), `find_virtual_cable()`, `targets_for(mode, me, others)`, `resample_to()`; `Player` writes the same audio to 1–2 output streams in 50 ms blocks, `stop()` silences them within a block; N9: `pause()` / `resume()` hold `play()` between blocks with the streams open (`stop`, `pause`, `resume` are the only cross-thread calls); `PaStream` is the real PyAudio stream. N8: `list_inputs()` (WASAPI mics, no cables), `is_virtual_cable()`, `PaInput`, `LinearResampler`, `Passthrough` copies the mic into the cable in 10 ms blocks on its own thread (Windows mixes it with the narration) | Open output streams (player thread only); the pass-through's mic and cable streams (`mic-passthrough` thread only) |
| Narration pipeline | `app/narrator.py` | N5: no Tk or device code; `synth`, `play`, `split` are passed in. `speak(gen, text)` (TTS worker, blocks) synthesizes piece k+1 while a player thread plays piece k, one ahead; `stop()` / `begin()` (any thread) bump a generation id, so a stop before `speak` starts and late synthesis results are dropped; exactly one terminal callback: `on_done(stopped)` or `on_error(msg)`; N7: optional `on_progress(i, n)` as each piece starts playing (the app shows "Speaking i/n…") | Per-narration player thread and stop Event |
| Terminal | `app/terminal.py` | DeepSeek terminal P1 (spec `2026-10-12-deepseek-terminal`): no Tk. `Terminal` runs a command in a ConPTY pseudo-console (pywinpty), a reader thread feeds a `pyte` screen that keeps scroll-back and answers the program's queries; `write()`, `type_text()` (one line, no Enter), `resize()`, `scroll()`, `close()`; `snapshot()` returns only the rows that changed. Pure `key_bytes()` (Tk key → win32-input-mode keys), `clean()`, `child_env()` | The pseudo-console process and its `terminal-reader` thread; the screen (behind a lock) |
| Terminal view | `app/terminal_view.py` | DeepSeek terminal P2: the Tk `Text` that draws a `terminal.Snapshot` (colour tags, the cursor), turns keys, Ctrl+V, the wheel, Shift+PageUp/PageDown and its own size (lines × columns) into callbacks; Ctrl+C copies a selection, otherwise it's a key for the program. Imports no project module | The drawn text and style tags (UI thread) |
| DeepSeek answers | `app/answers.py` | DeepSeek terminal P4: stdlib only. `Inbox` listens on 127.0.0.1 (random port, per-run token) and passes each answer to a callback on its `answers-inbox` thread; run as a script it is `deepseek`'s `Stop` hook (`main`: hook input on stdin → `extract_answer` → `send`, always exit 0, prints nothing). `hook_settings()` builds the `--settings` JSON; pure `plain_text()` turns Markdown into speakable text | The listening socket and its `answers-inbox` thread |
| Ear channels | `app/channels.py` | Ear channels (spec `2026-10-15-ear-channels`). C3: `Router` runs the `ear-channels` thread (COM multi-threaded): every 1 s or on a command it follows the default output, journals then sets each session's gains, re-applies changed or drifted ones, restores journaled sessions when the state is untouched; `choose` / `volume` / `app_volume` / `reset` / `close` only queue commands; `on_update(device, apps, warnings)` / `on_error(msg)` never touch Tk. C2: `WasapiAudio` is the only COM code (comtypes): `default_output()`, `sessions(device_id)` → `Session`s (app key = exe path, name from the exe's FileDescription, identifier, volumes), `get` / `set` channel volumes; one thread only. C1: Pure `gains()` (§3.2: an app's left/right volume from both ears' `Selection`, the ear volumes and the app's volume), `Selection` (one ear: All apps or a set of apps), `menu_items()` / `silent()` (menu rows, apps in neither ear), `untouched()`; `Journal` keeps the volumes each session had before Wisper's first change in `%LOCALAPPDATA%\Wisper\ear-channels-restore.json` (atomic writes) | The journal file; the router's state and its `ear-channels` thread, which alone uses `WasapiAudio`'s COM objects |
| Legacy | `app/live_transcriber.py` | Older standalone loopback-only transcriber (large-v3-turbo). Duplicates capture logic. Not imported by `app.py`, `run.bat` or docs | Its own copy of everything |
| Launcher | `app/run.bat` | Starts `app.py` with the venv's `pythonw.exe` | — |
| Engine (upstream) | `whisper.cpp/` (gitignored) | ggml-org/whisper.cpp clone at `6e4ab85`, built with `-DGGML_VULKAN=1`. DLLs in `build/bin/Release/`, models in `models/` | Not our code; no `_docs/` there |

## Layers and allowed imports (target, enforced by import-linter once H9 lands)

| From \ To | app | capture | audio_io | whisper_native | priority | tts | playback | narrator | terminal | terminal_view | answers | channels | live_transcriber |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **app** | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **capture** | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **audio_io** | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **whisper_native** | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **priority** | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **tts** | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **playback** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **narrator** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ |
| **terminal** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ |
| **terminal_view** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ |
| **answers** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ |
| **channels** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ |

`app.py` is the only module that wires things together. The eleven lower modules are
independent leaves: each depends only on third-party libraries or the stdlib.
`live_transcriber.py` is legacy; nothing may import it.

## Main flows

1. **Model load**: `App._request_model` (`app/app.py:578`) → `jobs.put(("model", path))`
   → `_worker_loop` (`app/app.py:849`) closes the old model, creates `Whisper(DLL_DIR, path)`,
   runs a 1 s silent warm-up, then posts `("ready", None)`.
   English-only models pin the language to `en` and lock the language box.
2. **Dictation / live captions**: `toggle` (`app/app.py:595`) starts `capture.Capture`
   with the mode's `Profile` → `_segment_loop` (`app/capture.py:143`) cuts chunks at
   pauses (RMS < 0.006) → `_on_audio_chunk` queues `("audio", chunk, last 200 chars)`
   (the prompt gives context) → the worker transcribes, drops `is_junk` text, then posts
   `("text", …)`.
3. **File**: `start_file` → `("file", path)` → `_transcribe_file` (`app/app.py:898`)
   decodes, then `Whisper.transcribe_long` runs one `whisper_full` on the whole file.
   whisper.cpp's segment and progress callbacks run on the worker thread and post
   `("text", …)` and `("progress", %)`; overly dense segments (hallucinations) are dropped.
   At most `FILE_WORDS` (100) words are typed: a word past the limit cuts its chunk and
   `should_stop` makes whisper.cpp's `abort_callback` end the run, then `("done", "limit")`
   shows "File: typed the first 100 words." (D8). The file's name isn't typed.
4. **UI loop**: `_poll` (`app/app.py:1025`) drains `results` every 100 ms, types each
   `("text", …)` chunk into the DeepSeek terminal (`_type_speech`: one line + a space, never
   Enter), and updates the status line and level meter.
4a. **DeepSeek terminal (branch `feat/deepseek-terminal`)**: `_start_terminal` starts
   `powershell -Command "deepseek '--settings' '<hook file>'"` in `AI_workspace` at start-up; `terminal.Terminal`'s reader
   thread feeds the screen; `_draw_terminal` (every 16 ms) draws `snapshot()` in
   `TerminalView`; keys from the view go through `terminal.key_bytes`. The end
   (`on_exit`, from a waiting thread) goes through `results` as `("terminal_ended", run)`;
   Enter restarts it; `on_close` closes it.
4b. **DeepSeek answer → narration (P4)**: `App.__init__` starts `answers.Inbox` and writes the
   hook settings to `%TEMP%\wisper-deepseek-hook-<pid>.json` (outside the workspace). At the end of
   each answered turn Claude Code runs `python answers.py <port> <token>` through Git Bash in the
   pseudo-console; it sends `last_assistant_message` to the Inbox, whose thread posts
   `("ai_answer", text)` to `results`. `_poll` → `_narrate_answer`: `plain_text()`, nothing if
   empty, else `tts_stop()`, replace the narration box, `tts_toggle()` (Speak) if Kokoro is
   ready. `on_close` closes the Inbox and deletes the settings file.
5. **Narration (N5; output modes N6)**: at start the TTS worker (`_tts_worker_loop`,
   `app/app.py:941`) loads Kokoro and warms it up, then posts `("tts_ready", voices)`;
   missing files post the setup message and Speak stays disabled. `tts_toggle`
   (`app/app.py:745`) snapshots the box, takes `narrator.begin()`'s generation id and
   queues `("speak", gen, text, voice, speed, devices)`, where `devices` =
   `playback.targets_for(mode, me, others)` (Only me / Only others / Both, default Both;
   no Others device → the §5.3 message and nothing is queued). The output list is read
   once when the pane is built and a detected cable is pre-selected as Others. The worker starts the
   `Player`, runs `Narrator.speak` and closes the streams. `_poll_tts` ignores results
   whose generation isn't the one on screen. Stop, Clear and a voice/speed/mode/device change call
   `tts_stop` (narrator and player stop at once; the UI resets without waiting).
5a. **Taking turns (P5, D9)**: before the narration starts or resumes (Speak, Resume,
   Ctrl+Enter, an answer), `_stop_listening` (`app/app.py:626`) stops the capture and sets the
   `file_stop` event, which the file job's `should_stop` reads (it ends with `("done", "stopped")`).
   Before ▶ Start or Transcribe, `_pause_narration` (`app/app.py:635`) pauses a playing narration.
   Listening never restarts by itself.
6. **Lifetime (P5, D10)**: `main()` (`app/app.py:1081`) calls `priority.kill_children_with_me()`
   before anything starts, so `deepseek` and all it starts die with Wisper however it ends.
7. **Ear channels (spec `2026-10-15-ear-channels`)**: `App.__init__` builds the strip (`_build_ears`, packed
   at the bottom before the panes) and starts `channels.Router` (`make_ear_router`). Every 1 s or on a command
   the `ear-channels` thread reads the default output, journals each new session's volumes to
   `%LOCALAPPDATA%\Wisper\ear-channels-restore.json`, then sets its left/right channel volumes from `gains()`
   (no audio passes through Wisper). Menu checks, scales and Reset call `router.choose` / `volume` /
   `app_volume` / `reset`, which only queue commands; the router posts `("ear_update", …)` / `("ear_error", msg)`
   to `ear_results`, which `_poll` drains to rebuild the menus and the status line. Back to All apps at 100 %,
   Reset, a device change and `on_close` (before `pa.terminate()`) restore the journaled volumes; a journal
   left by a crash is replayed as each session reappears.

## Threading and state

- **Exactly one thread touches the model**, the worker started in `App.__init__`. Whisper
  contexts aren't thread safe (`whisper_native.Whisper` docstring).
- **Exactly one thread touches the Kokoro engine**, the TTS worker (`_tts_worker_loop`).
  It runs each narration; `Narrator.speak` plays on a short-lived `narration-player`
  thread. From the UI thread only `Narrator.stop/begin` and `Player.stop/pause/resume` are
  called (they set or clear an Event and bump a counter).
- The **`mic-passthrough`** thread (N8) only reads the mic and writes the cable through its
  own two streams. `Passthrough.start/stop` are called from the UI thread; errors come
  back as `("pass_error", run_id, msg)` on `tts_results`; `on_close` calls
  `Passthrough.close()`, which also waits for a run that outlived `stop()`.
- One `PyAudio` instance is shared: capture streams open on the UI thread, narration
  streams on the narration-player thread. PortAudio doesn't promise that two threads
  can open streams at the same instant; the window for that is tiny (Start pressed as a
  narration opens its stream) and is accepted for now.
- The capture thread only produces chunks. The UI thread only reads `results`.
- The **`answers-inbox`** thread (P4) only accepts hook connections and puts
  `("ai_answer", text)` on `results`; it touches no Tk or audio object.
- The **`ear-channels`** thread alone touches COM audio objects (`WasapiAudio`; COM multi-threaded,
  initialised and uninitialised on that thread). The UI thread only queues commands; results come back on
  `ear_results` as plain `App` data (keys and names), never `Session`s. `on_close` joins it (2 s cap).
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
- Narration: `tts.split_sentences`, `playback` (fake streams) and `narrator` (fake synth
  and play) are unit-tested; the window's TTS wiring runs with a fake engine and fake
  output streams (`app/tests/conftest.py`, `test_narration_ui.py`).
- `whisper_native.Whisper` needs the DLL and the GPU. Treat it as a manual/integration
  test (`whisper.cpp/models/for-tests-*.bin` are tiny models usable for smoke tests).
