# Spec: Narration (text-to-speech with Kokoro-82M)

| Field | Value |
|---|---|
| Status | In progress: N0 (spike) and N1 (split window) done 2026-10-07, N2 (narration box) done 2026-10-09, next N3 |
| Date | 2026-10-07 |
| Owner | shoonya0 |
| Test plan | [`_docs/test/kokoro-narration.md`](../test/kokoro-narration.md) |
| Decision record | [`_docs/adr/0001-tts-engine-kokoro-onnx.md`](../adr/0001-tts-engine-kokoro-onnx.md) (Accepted) |

Claims are marked **VERIFIED** (run, read in code or read in the upstream source) or
**ASSUMED** (to be confirmed in increment N0).

## 1. Problem

Wisper only listens today: dictation, live captions and file transcription. The user also
wants the app to **speak**. They type or paste text, and the app reads it aloud with
Kokoro-82M, either to themselves, to the other people on a call (Meet, Zoom, Discord, …),
or to both.

## 2. Goals and non-goals

**Goals**

1. Split the window: **left = speech to text** (today's app, unchanged behavior),
   **right = text to speech** (new).
2. Narrate the text in the right-hand box with Kokoro-82M, offline, on this PC.
3. Three output modes:
   1. **Only me**: plays on my speakers or headphones.
   2. **Only others**: goes into the call as if it were my microphone. I don't hear it.
   3. **Both**: I hear it and the call hears it.
4. The narration box has its own **Save… / Clear / Copy all**, like the transcript box.
   The two boxes are separate.
5. **Clear during narration stops the narration at that point**: no more audio on any
   device, and the remaining sentences are dropped.

**Non-goals (v1)**

- Voice cloning or custom voices. Only Kokoro's built-in voices.
- Japanese and Chinese voices. They need the `misaki` G2P extras, not espeak-ng (ASSUMED).
- Exporting narration to a WAV/MP3 file (future, §10).
- Reading the speech-to-text transcript aloud automatically. The boxes stay independent.
- Installing a virtual audio driver for the user. The app detects one and explains the
  setup steps (§5.3).
- Linux or macOS. Wisper is Windows only.

## 3. User experience

### 3.1 Layout

```text
┌──────────────── Speech to text ────────────────┬──────────────── Text to speech ─────────────┐
│ [▶ Start] Mode:[Dictation ▾] Model:[…▾] Lang:[…]│ [🔊 Speak] Voice:[af_heart ▾] Speed:[1.0 ▾] │
│ Device: [Microphone (Realtek) ▾]                │ Output: (•) Only me ( ) Only others ( ) Both│
│                     [Save…] [Clear] [Copy all] │ Me: [Speakers ▾]  Others: [CABLE Input ▾]  │
│ ┌────────────────────────────────────────────┐ │                     [Save…] [Clear] [Copy all]│
│ │ transcript (read-only, as today)           │ │ ┌──────────────────────────────────────────┐│
│ │                                            │ │ │ narration text (editable: type or paste) ││
│ └────────────────────────────────────────────┘ │ └──────────────────────────────────────────┘│
├────────────────────────────────────────────────┴──────────────────────────────────────────────┤
│ STT status … Level ▮▮▯                         │ TTS status: "Speaking 3/12…" / "Ready"        │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

- A `tk.PanedWindow` (horizontal) with two equal panes. The user can drag the divider.
  It's the classic tk widget rather than `ttk`, because only it supports a per-pane
  `minsize`, which keeps every control visible however far the divider is dragged.
- Default window size goes from 940×640 to 1440×680. Minimum width is 1126 px
  (`STT_MIN_W` 700 + `TTS_MIN_W` 420 + 6 px divider). The STT control row needs 653 px
  (measured in N1). `TTS_MIN_W` is rechecked when N2 and N6 add controls (N2: still 420, every TTS control fits; test-checked).
- Each pane has its own status line. STT status messages don't overwrite TTS ones, and
  TTS messages don't overwrite STT ones.
- Same dark theme (`DARK` palette) and same button styles as today.

### 3.2 Narration controls

| Control | Behavior |
|---|---|
| **Speak / Stop** button (accent) | Speak: reads the whole box from the start. While speaking, the label changes to "⏹ Stop". Disabled while the Kokoro model is loading or missing, or when the box is empty |
| Voice | Kokoro voices from `voices-v1.0.bin`, grouped by language prefix (`af_`/`am_` = US English, `bf_`/`bm_` = UK English, `e`, `f`, `h`, `i`, `p`). Default `af_heart` (VERIFIED present among the 54 voices; how it sounds is checked in T-TTS-1). The language passed to Kokoro is derived from the voice prefix |
| Speed | 0.8 / 0.9 / 1.0 / 1.1 / 1.25 / 1.5. Default 1.0 |
| Output | Radio buttons: Only me · Only others · Both |
| Me device | Output devices (WASAPI). Default = the Windows default output |
| Others device | Output devices. Pre-selects a detected virtual cable (§5.3). Hidden or disabled in "Only me" mode |
| Save… | Saves the box text to `.txt` (UTF-8), the same as the transcript Save… |
| Clear | Empties the box **and stops any narration in progress** |
| Copy all | Copies the box text to the clipboard and shows "Copied narration text to clipboard." |

Keyboard: `Ctrl+Enter` in the narration box = Speak/Stop. `Ctrl+A` selects all, as in
the transcript box.

### 3.3 Narration behavior rules

1. **Snapshot**: Speak takes a snapshot of the box text. Editing the box while it is
   speaking doesn't change what is being read. Only Stop, Clear, a new Speak, switching
   the output mode, or closing the app interrupts it.
2. **Clear = stop**: Clear stops audio on **all** target devices within **≤ 200 ms**,
   drops the sentences that haven't played, and throws away any synthesis that finishes
   afterwards. The status line shows "Narration stopped." Then the box is emptied.
3. **Stop** does the same as rule 2 but keeps the text.
4. **Speak while speaking** isn't possible, because the button is Stop while speaking.
   `Ctrl+Enter` follows the button.
5. Changing the output mode, a device, the voice or the speed **while speaking** stops the
   narration. The new setting applies to the next Speak. This keeps v1 simple.
6. **Sentence streaming**: the text is split into sentences (§5.2), and sentence *k + 1* is
   synthesized while sentence *k* plays, so the first sound doesn't wait for the whole text.
7. Empty or whitespace-only text: Speak does nothing and flashes "Nothing to narrate."
8. If the narration finishes normally, the status shows "Narration complete." and the
   button goes back to Speak.
9. If a device disappears or fails mid-narration (for example headphones unplugged), the
   narration stops, the error is shown in the TTS status line (not a modal dialog), and the
   app keeps running.

## 4. Output modes in detail

| Mode | Plays to | What the user must set up |
|---|---|---|
| Only me | "Me" device (default speakers or headphones) | nothing |
| Only others | "Others" device = the **playback** side of a virtual audio cable (for example `CABLE Input (VB-Audio Virtual Cable)`) | Install a virtual cable once. In Meet/Zoom/Discord, choose the cable's **recording** side (`CABLE Output`) as the microphone |
| Both | Me device **and** Others device at the same time, same samples | as above |

**Why a virtual cable is needed (VERIFIED, general Windows behavior):** a normal Windows
app can't create a microphone device. Only a driver can. VB-Audio Virtual Cable is the
common free (donationware) driver: whatever plays into "CABLE Input" comes out of
"CABLE Output", which call apps can pick as their microphone.

**Known limitation:** while the call app uses `CABLE Output` as its microphone, the
user's **real** microphone doesn't reach the call. v1 documents the workarounds (Windows
"Listen to this device" on the real mic, routed to CABLE Input, or VoiceMeeter). Increment
N8 (optional, open decision 2) would have Wisper itself mix the real mic into the cable.

**Feedback risk:** if the Live captions mode (loopback) is running on the same speakers
as "Only me" or "Both", Wisper transcribes its own narration. v1 accepts this and
documents it. "Only others" doesn't have this problem, because loopback listens to the
speakers, not the cable.

## 5. Design

### 5.1 Engine: `kokoro-onnx` on the CPU

Full reasoning is in ADR 0001. In short:

- The RX 580 has no ROCm, so the official `kokoro` package (PyTorch) would run on the
  CPU anyway and pull in ~2 GB of torch. `kokoro-onnx` runs the same Kokoro-82M v1.0
  weights through **onnxruntime** (CPU), with espeak-ng **bundled** through
  `espeakng-loader`. No system install is needed.
- **VERIFIED (2026-10-07):** `kokoro-onnx 0.6.1` (released 2026-08-19, MIT, requires
  Python ≥3.10,<3.14). `pip install --dry-run kokoro-onnx==0.6.1` in `app/.venv`
  resolves to: kokoro-onnx 0.6.1, onnxruntime 1.30.0, espeakng-loader 0.2.4,
  phonemizer 3.4.0, protobuf, flatbuffers, attrs, dlinfo, joblib, cloudpickle. It
  **keeps the installed numpy 2.5.3**, so there's no conflict.
- **Licensing note:** `phonemizer` and espeak-ng are **GPL-3.0**. That's fine for
  personal or local use. It matters only if Wisper is ever distributed as a closed
  binary (open decision 3).
- The API used (VERIFIED from `kokoro_onnx/__init__.py`):
  `Kokoro(model_path, voices_path)`, `get_voices()`,
  `create(text, voice, speed, lang) -> (float32 samples, sample_rate)`. The output is
  24 kHz mono (VERIFIED from the model card).
- Model files (gitignored, downloaded once from the `kokoro-onnx` GitHub release
  `model-files-v1.1`): **`kokoro-v1.0.onnx` (fp32, 325 MB)** plus `voices-v1.0.bin`
  (28 MB). They live in **`models/kokoro/`**, which is gitignored (`/models/`).
  **N0 result:** the int8 variant is ~10× *slower* than fp32 on this CPU, so fp32 is the
  only supported variant (`performance.md`).
- **Kokoro runs on the CPU only (user decision, 2026-10-07):** the GPU is reserved for
  Whisper, so dictation and narration can run at the same time without competing for it.
  A GPU path (DirectML) is out of scope for now and isn't measured in N0.

### 5.2 Modules (all new modules are leaves; only `app.py` wires them)

| Module | Responsibility | Pure / testable parts |
|---|---|---|
| `app/tts.py` (new) | Load Kokoro once; list voices; `lang_for_voice()`; `split_sentences()`; `synthesize(sentence, voice, speed) -> float32 @ 24 kHz` | `split_sentences`, `lang_for_voice` |
| `app/playback.py` (new) | List WASAPI output devices; detect virtual cables by name; `targets_for(mode, me, others)`; resample 24 kHz → device rate; `Player`: writes the same samples to 1–2 output streams in ~50 ms blocks, checking a stop `Event` between blocks | `targets_for`, `find_virtual_cable`, `resample_to`, `Player` with an injected stream factory |
| `app/narrator.py` (new) | Narration pipeline, with no Tk or device code: takes `synthesize` and `play` callables (dependency injection). Splits, prefetches one sentence ahead, plays in order, `stop()`, a generation id so late results are thrown away, and progress or done callbacks | All of it, with fakes |
| `app/app.py` (changed) | Two panes; the TTS pane widgets; owns the **TTS worker thread** (the only thread that touches the Kokoro session) and wires narrator ↔ tts ↔ playback ↔ UI through a queue, the same way the STT side does | UI: manual |

Sentence splitting (`split_sentences`) rules:

- Split after `.` `!` `?` `…` `।` (Hindi danda) followed by whitespace or the end, and at
  blank lines.
- Don't split after common abbreviations (`Mr.`, `Mrs.`, `Dr.`, `e.g.`, `i.e.`, `etc.`,
  `vs.`) or inside decimals (`3.14`).
- A piece longer than `MAX_CHARS` (**120**) is split again at `,` `;` `:`, and as a last
  resort at a space. `kokoro-onnx` already splits anything over its 510-phoneme window
  (VERIFIED, `kokoro_onnx/chunker.py`), so `MAX_CHARS` isn't about the model limit. It
  keeps each piece's synthesis short: N0 measured 89 characters → 5.07 s of audio, so
  120 characters ≈ 7 s of audio ≈ 3 s of synthesis at RTF ≈ 0.4. Stop never waits for
  synthesis (late results are dropped by generation id), but the TTS worker is busy
  until the current piece finishes, so this bounds how long a new Speak right after
  Stop can wait.
- **Short first chunk (from N0):** if the **first** piece of a narration has more than
  `FIRST_CHUNK_WORDS` (6) words, it is cut at the first `,` `;` `:` that falls **within
  its first 6 words**, otherwise **at word 6**. So the first chunk is never longer than
  6 words. Measured on an idle CPU: a 5-word first chunk is synthesized in
  0.73–0.84 s versus 1.80 s for a 16-word sentence. Only the first piece gets this treatment.
- Pieces are stripped. Empty pieces are dropped. **Joining the pieces gives back the
  original words in the original order** (tested).

Allowed imports after this feature (`architecture-overview.md` and
`app/tests/test_architecture.py` change in the same increment that adds each module):

| From \ To | app | capture | audio_io | whisper_native | priority | tts | playback | narrator |
|---|---|---|---|---|---|---|---|---|
| **app** | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **every other module** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### 5.3 Virtual cable detection

`find_virtual_cable(devices)` returns the first output device whose name contains (case
insensitive) one of: `CABLE Input`, `VB-Audio`, `VoiceMeeter Input`,
`Virtual Audio Cable`, `Line 1 (Virtual`. If none is found:

- "Only others" and "Both" stay selectable, but the Others list shows all output devices
  with nothing pre-selected, and a **"How to set up…"** link opens a short dialog:
  install VB-Audio Virtual Cable, reboot, then in the call app pick
  "CABLE Output" as the microphone.
- Speak in those modes with no Others device selected → flash
  "Choose the device the call should hear (Others)."

### 5.4 Threads

```text
UI thread (Tk) ──("speak", gen, text, voice, speed, targets)──► tts_jobs ──► TTS worker thread
     ▲                                                                      owns Kokoro session
     │                                                                      Narrator(gen): split → synth k+1 ║ play k
     └──── tts_results ◄── ("tts_progress", i, n) / ("tts_done", gen) / ("tts_error", msg) ──┘
                                         play k → Player thread: blocks → stream(me) [+ stream(others)]
Stop/Clear (UI thread): narrator.stop() → sets stop Event + gen += 1 → Player aborts within one block (~50 ms)
```

- **Rule (same as Whisper):** only the TTS worker thread calls into the Kokoro session.
  It gets its own `jobs` / `results` queues and is drained by the existing `_poll`.
- `stop()` is the **one** call that is safe from the UI thread. It only sets an `Event`
  and bumps the generation counter. It never touches the ONNX session.
- Synthesis of the next sentence runs on the TTS worker, playback on a player thread,
  so a sentence plays while the next one is computed.
- On close: stop the narration, put `("stop",)` on `tts_jobs`, then close the streams.
- `priority.boost_process()` already raises the process priority. onnxruntime intra-op
  threads are capped at **`intra_op_num_threads = 4`** (N0: as fast as 6 on the
  i5-10400F, and leaves 2 cores free) so the UI and the STT worker stay responsive.
  The session uses `providers=["CPUExecutionProvider"]` explicitly.

### 5.5 Errors and missing files

- Missing `models/kokoro/*` → TTS pane shows "Kokoro model not found: see
  _docs/current-state.md (Narration setup)". Speak stays disabled. **STT is unaffected.**
- A Kokoro load or synthesis error → TTS status line plus one modal dialog, the same as
  STT `("error", …)`.
- A device open or write error → rule 3.3.9 (status line, no crash).

## 6. Performance targets (N0 results recorded in `performance.md`)

| Metric | Target | Why | N0 result (fp32, 4 threads) |
|---|---|---|---|
| Kokoro load (cold) | ≤ 5 s, done in the background at app start | the app must open instantly; STT must not wait | ✅ 1.3–1.5 s load + ~2.0 s warm-up |
| First sound after Speak | **≤ 1.0 s** p50, ≤ 1.5 s p95 | feels immediate in a call | ✅ 0.73–0.84 s p50, max 0.91 s, with the 6-word first-chunk cap (❌ 1.80 s without). ⚠ 1.33 s under CPU contention, so re-measure with Dictation running in N5 |
| Real-time factor on CPU (synthesis time ÷ audio time) | **≤ 0.5** (2× faster than real time) | prefetching then always stays ahead, so there are no gaps between sentences | ✅ 0.36–0.40 |
| Stop/Clear → silence | **≤ 200 ms** on all devices | requirement 5 | measure in N5 |
| Gap between sentences | ≤ 300 ms of silence beyond Kokoro's own pause | sounds natural | measure in N5 |
| STT impact while narrating | dictation RTF changes by < 10% | GPU vs CPU split should keep them independent | measure in N5 |

If N0 measures RTF > 0.5 on this CPU, try int8 and different onnxruntime thread counts,
and record each result. If RTF > 1.0 even then, stop and ask the user before building
the UI. Moving Kokoro to the GPU is not a fallback (§5.1).

## 7. Acceptance criteria

| # | Criterion | How checked |
|---|---|---|
| AC1 | Window shows STT on the left and TTS on the right. STT works exactly as before (3 modes, model swap, Save/Clear/Copy) | pytest baseline unchanged + manual T-UI-1 |
| AC2 | Typing or pasting text and pressing Speak plays it in the chosen voice and speed on the Me device | manual T-TTS-1 |
| AC3 | Only others: the call hears it, I don't (checked with a Discord, Meet or Zoom test call, or Windows Voice Recorder on CABLE Output) | manual T-MODE-2 |
| AC4 | Both: I and the call hear it, in sync to within about 100 ms | manual T-MODE-3 |
| AC5 | Clear during narration: silence on all devices within 200 ms, box empty, no later audio | `test_narrator.py` + `test_playback.py` + manual T-TTS-3 |
| AC6 | Narration Save… / Clear / Copy all behave like the transcript ones and only touch the narration box | manual T-UI-2 |
| AC7 | Missing Kokoro files: the app starts, STT works, TTS shows the setup message | manual T-ERR-1 |
| AC8 | Performance targets in §6 measured and recorded | `performance.md` table from N0 and N5 |
| AC9 | `node tools/verify.mjs` passes; architecture test covers the new modules | verify output |

## 8. Increments (each one is a separate commit: spec → plan → steps → `/verify-change` → `code-reviewer` → `/close-increment`)

| # | Increment | Changes | Tests added | Done when |
|---|---|---|---|---|
| **N0** | **Spike: measure Kokoro on this PC** (no app code) | `kokoro-onnx>=0.6.1,<0.7` → `app/requirements.txt` (measured: 0.6.1 with onnxruntime 1.30.0); model files → `models/kokoro/`; `tools/tts_bench.py` (load time, RTF, first-sentence latency; fp32 vs int8; thread counts; CPU only); `.gitignore` comment for `/models/` | none (bench script) | Numbers in `performance.md`, ADR 0001 → Accepted or Rejected, default model variant chosen. Confirms: espeak works offline, voice list, `hi`/`es`/`fr` voices produce speech |
| **N1** | **Split layout** (refactor, no behavior change) | `app.py`: STT widgets move into a left frame of a `PanedWindow`; the right pane is a placeholder "Text to speech (coming soon)"; window size; per-pane status line. Also fixes a bug found while doing this: the STT status line and level meter were never visible at the default size | `test_window_layout.py` (3 tests: pane order, status lines visible, controls visible at the minimum size) + the 26 baseline tests | T-UI-1 manual checklist passes |
| **N2** | **Narration box + Save/Clear/Copy all** (no audio yet) | `app.py`: editable text box, the three buttons, `Ctrl+A`; Speak button present but disabled | `test_window_layout.py` += 6 tests (box editable, Speak disabled, `Ctrl+A`, Save/Clear/Copy only touch the narration box, transcript Clear leaves it alone, cancelled Save, TTS controls visible at the minimum size). Manual T-UI-2 | Box works on its own, STT box untouched |
| **N3** | **`tts.py` engine leaf** | `load`, `voices`, `lang_for_voice`, `split_sentences`, `synthesize` | `test_tts_split.py` (≈12 cases: abbreviations, decimals, `…`, `।`, blank lines, long piece re-split, round trip, empty); `test_tts_voices.py` (`lang_for_voice` table); `test_tts_engine.py` (**slow**, skipped with a reason when `models/kokoro/` is missing: "Hello world." → float32, 24 kHz, 0.4–3 s) | tests pass; architecture test lists `tts` |
| **N4** | **`playback.py` leaf** | WASAPI output list, `find_virtual_cable`, `targets_for`, `resample_to`, `Player(stream_factory)` | `test_playback.py`: cable detection names; `targets_for` for all 3 modes, including a missing Others device; resample length and dtype; `Player` with fake streams: both streams get identical blocks, `stop()` → no writes after the current block, stop latency < 1 block, a device error → error callback, not an exception | tests pass; architecture test lists `playback` |
| **N5** | **`narrator.py` + wiring, mode "Only me"** | narrator pipeline; TTS worker thread and queues in `app.py`; Speak/Stop, voice, speed; Clear and Stop stop the narration; background model load at start; missing-model message | `test_narrator.py` (fakes): order is kept; prefetch is one ahead; `stop()` mid-sentence → later sentences never play; a late synthesis result after stop is dropped (generation id); a new speak after stop works; empty text → done immediately; synthesis error → error callback, the narration ends | AC2, AC5, AC7 manual; first-sound and stop latency measured in the real app and added to `performance.md` |
| **N6** | **Modes "Only others" and "Both"** | Output radio buttons; Me and Others device pickers; cable auto-select; "How to set up…" dialog; changing mode or device stops the narration (rule 3.3.5) | `test_playback.py` += mode → targets with a detected cable / no cable; `Player` with 2 fake streams stops both | AC3, AC4 manual with a real call app |
| **N7** | **Polish** | `Ctrl+Enter`; status "Speaking 3/12…"; device-unplugged handling (rule 3.3.9); the Live captions feedback note in the UI help | `test_narrator.py` += progress callback counts; `test_playback.py` += write error mid-stream | T-ERR-2 manual |
| N8 *(optional, open decision 2)* | **Mic pass-through** into the cable, so the user can talk *and* narrate in one call | `playback.py` mixer: real mic → cable plus narration (mix and clip) | mixer sum/clip unit tests | only if the user wants it |

After N7: update `current-state.md` (what a user can do), `architecture-overview.md`
(diagram, module table, threads, layer table) and the README feature list.

## 9. Open decisions (user)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Edit the box while it is speaking? | Snapshot (rule 3.3.1) · lock the box while speaking | Snapshot: you can prepare the next text while it speaks |
| 2 | Real mic plus narration in the same call | document the Windows/VoiceMeeter workaround (v1) · build N8 | v1 documents it; decide on N8 after using v1 |
| 3 | GPL-3 deps (`phonemizer`, espeak-ng) | accept (personal or local use) · look for a non-GPL G2P | Accept unless you plan to distribute Wisper |
| 4 | ~~Default model variant~~ | **Resolved by N0: fp32.** int8 is ~10× slower on this CPU | — |

## 10. Future (not in this spec)

- Highlight the sentence being spoken in the box.
- Export narration to WAV.
- "Speak selection" (only the selected text).
- Japanese and Chinese voices (misaki G2P).
- Global hotkey: speak the clipboard.
