# Test plan: Narration (Kokoro-82M text to speech)

Spec: [`_docs/specs/2026-10-07-kokoro-narration.md`](../specs/2026-10-07-kokoro-narration.md).
Baseline before N1: **26/26 pytest pass** (`current-state.md`). Every increment must keep
those 26 passing **by name**, plus its own new tests.

Fast check after every step: `node tools/verify.mjs`. Single file:
`app\.venv\Scripts\python.exe -m pytest app/tests/test_narrator.py -v`.

## 1. Automated tests (pytest, `app/tests/`)

| File | Increment | Needs GPU / model / device? | Cases |
|---|---|---|---|
| `test_architecture.py` (changed) | N3, N4, N5 | no | `tts`, `playback`, `narrator` added to `PROJECT_MODULES` and `LEAVES`; leaves import no project module; `app` may import them |
| `test_window_layout.py` | N1 | Tk window, **invisible** (alpha 0, no taskbar button) with fake Whisper and PyAudio; needs `--capture=sys` (set in `pyproject.toml`) | STT widgets in the left pane, left of the TTS pane; STT status line + level meter and TTS status line visible at the default size (regression for the pre-N1 bug); start/model/lang/device/level controls inside the left pane at the minimum window size. **N2:** narration box editable and in the right pane; Speak disabled; `Ctrl+A` selects all; narration Copy all / Save… (Hindi survives) / Clear only touch the narration box and TTS status; transcript Clear leaves the narration box; cancelled Save writes nothing; Speak, Save…, Clear, Copy all and the box inside the right pane at the minimum size. The clipboard is stubbed (never touches the user's real clipboard) |
| `test_tts_split.py` | N3 | no | see §1.1 |
| `test_tts_voices.py` | N3 | no | `lang_for_voice`: `af_heart`→`en-us`, `bm_george`→`en-gb`, `ef_dora`→`es`, `ff_siwis`→`fr-fr`, `hf_alpha`→`hi`, `if_sara`→`it`, `pf_dora`→`pt-br`; an unknown prefix → `ValueError` naming the voice |
| `test_tts_engine.py` | N3 | **model files** (marked `slow`: runs in `node tools/verify.mjs --full`, not the fast check; skipped with reason `"models/kokoro/ missing: see current-state.md"` when absent, as on CI). One fast test: missing files → `FileNotFoundError` with the setup message | load; `voices()` non-empty and contains the default voice; `synthesize("Hello world.")` → `float32`, 1-D, 24 kHz, duration 0.4–3 s, peak in (0.01, 1.0] |
| `test_playback.py` | N4, N6, N7 | no (fake streams, fake PyAudio) | see §1.2. N4 also covers: `list_outputs` (WASAPI outputs only, no loopback, default first), each device gets audio at its own rate (48 k / 44.1 k), streams stay open between sentences, an open error reports the device and closes streams already open, play after stop does nothing until the next `start` |
| `test_narrator.py` | N5, N7 | no (fake synth/play) | see §1.3 |

### 1.1 `split_sentences`

| Case | Input | Expected |
|---|---|---|
| simple | `"Hi. How are you? Fine!"` | `["Hi.", "How are you?", "Fine!"]` |
| abbreviation | `"Dr. Rao met Mr. Iyer."` | 1 piece |
| e.g. / i.e. / etc. | `"Use tools, e.g. ruff. Then test."` | 2 pieces |
| decimal | `"Pi is 3.14 today."` | 1 piece |
| ellipsis | `"Wait… what?"` | `["Wait…", "what?"]` |
| Hindi danda | `"नमस्ते। आप कैसे हैं?"` | 2 pieces |
| blank line | `"Title\n\nBody text."` | `["Title", "Body text."]` |
| long piece | 700 chars, commas inside, no full stop | every piece ≤ `MAX_CHARS`, split at commas first |
| no punctuation, long | 700 chars of words | every piece ≤ `MAX_CHARS`, split at spaces, no word cut |
| round trip | any of the above | `" ".join(pieces).split() == text.split()` |
| empty / whitespace | `""`, `"  \n "` | `[]` |
| quotes | `'He said "Go." Then left.'` | 2 pieces, the closing quote stays with the first |
| first chunk, clause | `"Hi everyone, thanks for joining the call today, let me walk you through it."` | first piece `"Hi everyone,"`; the rest follows in order |
| first chunk, no clause mark | 16 words, no `,;:` | first piece = first 6 words; second = the remaining 10 |
| first chunk, late clause mark | 16 words, first `,` after word 10 | first piece = first 6 words (the late comma is ignored) |
| first chunk, already short | `"Okay. Let's begin the meeting now, everyone."` | first piece `"Okay."` unchanged (≤ 6 words) |
| first chunk only | 3 long sentences | only the first piece is shortened; the others follow the normal rules |

### 1.2 `playback`

| Case | Expected |
|---|---|
| `find_virtual_cable` | finds `CABLE Input (VB-Audio Virtual Cable)`, `VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)`, `Line 1 (Virtual Audio Cable)`; returns `None` for `Speakers (Realtek)` only; case insensitive |
| `targets_for("me", me, others)` | `[me]` |
| `targets_for("others", me, others)` | `[others]`; `others=None` → `ValueError` with the "Choose the device the call should hear" message |
| `targets_for("both", me, others)` | `[me, others]`; the same device chosen for both → one entry (no double play) |
| `resample_to(x24k, 48000)` | length ×2 (±1), `float32`, no NaN; same rate → returns the input unchanged |
| `Player`, 2 fake streams | both receive identical block sequences; the concatenated writes equal the input (padded to a block) |
| `Player.stop()` from another thread mid-play | returns; no `write` after the block in progress; elapsed < 2 × block duration; both streams closed |
| fake stream raises on `write` | `on_error` callback called once with the device name; the other stream closed; no exception escapes the thread |

### 1.3 `narrator`

Fakes: `synth(text)` returns `np.full(n, i)` and records calls with timestamps; it can
be made slow or raise. `play(samples, stop_event)` records what played and honors
`stop_event`.

| Case | Expected |
|---|---|
| order | 3 sentences → played in order, each exactly once |
| prefetch | sentence 2's synthesis starts before sentence 1's playback ends (one ahead, never more than one) |
| stop mid-sentence | `stop()` while sentence 1 plays → sentences 2 and 3 never played; `on_done(stopped=True)` once |
| late result dropped | slow synthesis of sentence 2 finishes after `stop()` → not played (generation id) |
| speak after stop | a new `speak()` after `stop()` plays its own sentences fully |
| empty text | `on_done(stopped=False)` immediately; `synth` never called |
| synthesis error | `synth` raises on sentence 2 → sentence 1 played, `on_error` once, narration ends, worker still alive for the next speak |
| progress (N7) | `on_progress(i, n)` called with 1..n in order |

## 2. Performance checks (N0 and N5; record in `performance.md`)

Run `app\.venv\Scripts\python.exe tools/tts_bench.py` (N0). It prints a table: variant
(fp32/int8), threads, load s, first-sentence s, RTF p50/p95 over 10 sentences.
**N0 done (2026-10-07):** fp32 with 4 threads, RTF 0.36–0.40; a 5-word first chunk is
ready in 0.73–0.84 s; int8 is rejected (~10× slower). Numbers are in `performance.md`. Then
measure in the real app (N5): Speak → first sound and Clear → silence, with a stopwatch
or by logging `time.perf_counter()` at the button press and at the first `write`. Targets
are in spec §6.

Concurrency check (N5): run Dictation and narration at the same time and compare the
dictation per-chunk time with dictation alone (target < 10% slower).

## 3. Manual checks (Tkinter UI: the user runs these; the agent lists them in the report)

Run with `cd app` then `.venv\Scripts\python.exe app.py`, so tracebacks are visible.

| ID | Increment | Steps | Pass when |
|---|---|---|---|
| T-UI-1 | N1 | Open the app. Use Dictation, Live captions and File once each; change model; Save…, Clear, Copy all in the transcript | Left pane works as before; the bottom of the left pane shows "Ready • model • queue" and the Level meter moves while you speak; right pane shows the narration box (N2+); dragging the divider resizes both; at the minimum window width every control is still visible |
| T-UI-2 | N2 | Type and paste text in the narration box; Copy all → paste in Notepad; Save… → open the `.txt`; Clear | Each action only touches the narration box; the transcript is unchanged; Unicode (Hindi) survives Save |
| T-TTS-1 | N5 | Paste 3 paragraphs; pick `af_heart`, 1.0; Speak | First sound within about 1 s; reads all of it in order; no gaps longer than about 0.3 s; button returns to Speak; status "Narration complete." |
| T-TTS-2 | N5 | Change voice (UK English, Hindi, Spanish, French) and speed 1.5; Speak text in that language | Voice and speed change; each voice pronounces its language intelligibly |
| T-TTS-3 | N5 | Speak a long text; press **Clear** after about 3 s | Silence within 200 ms (no trailing sentence); box empty; status "Narration stopped." |
| T-TTS-4 | N5 | Speak; press **Stop**; then Speak again | Stops quickly, text kept; the second Speak starts from the beginning |
| T-TTS-5 | N5 | Speak while Dictation is running | Both work; dictation latency not noticeably worse |
| T-MODE-2 | N6 | VB-Cable installed. Discord/Meet/Zoom test call (or Windows Voice Recorder) with mic = `CABLE Output`. Mode Only others; Speak | The call or recording hears it; nothing on my speakers |
| T-MODE-3 | N6 | Mode Both; Speak | I hear it and the call hears it; Clear stops both |
| T-MODE-4 | N6 | Uninstall or disable the cable (or test on a PC without one); choose Only others | No cable pre-selected; "How to set up…" opens the steps; Speak without an Others device → flash message, no crash |
| T-MODE-5 | N6 | Change the mode while speaking | Narration stops; the next Speak uses the new mode |
| T-ERR-1 | N5 | Rename `models/kokoro` temporarily; start the app | App opens; STT works; TTS shows the setup message; Speak disabled. Rename it back |
| T-ERR-2 | N7 | Speak to USB/Bluetooth headphones; unplug mid-sentence | Narration stops; error in the TTS status line; app keeps running; Speak works again on another device |
| T-KEY-1 | N7 | `Ctrl+Enter` in the box; `Ctrl+A` | Toggles Speak/Stop; selects all narration text only |

## 4. Not tested automatically (and why)

- Tk widget layout and real audio devices: no agent UI access for Tkinter (`CLAUDE.md`),
  and CI has no audio devices. The logic sits behind pure functions and injected fakes
  (`narrator`, `Player`) so it is unit-tested; the wiring is checked manually.
- Sound quality of Kokoro voices: subjective. The user judges it in T-TTS-1 and T-TTS-2.
