# Spec: Mic pass-through into the call (narration N8)

| Field | Value |
|---|---|
| Status | Done (2026-10-10): user checked it in a call and reported it working (2026-10-10) |
| Date | 2026-10-10 |
| Owner | shoonya0 |
| Parent spec | [`2026-10-07-kokoro-narration.md`](./2026-10-07-kokoro-narration.md) §4 "Known limitation", §8 row N8, open decision 2 (resolved: build N8) |
| Test plan | [`_docs/test/kokoro-narration.md`](../test/kokoro-narration.md) (N8 rows) |

Claims are marked **VERIFIED** (run or read in code) or **ASSUMED**.

## 1. Problem

With the call app's microphone set to `CABLE Output`, the call hears Wisper's narration
but **not the user's own voice** (VERIFIED by the user in Google Meet, 2026-10-10). The
user wants the call to hear **both at the same time**.

## 2. Goals and non-goals

**Goals**

1. Wisper copies the user's real microphone into `CABLE Input` continuously, so the call
   hears the voice and the narration together through one mic (`CABLE Output`).
2. On by default when a virtual cable is detected (user decision, 2026-10-10).
3. Works in every output mode (Only me, Only others, Both) and while Dictation uses the
   same microphone.
4. The delay Wisper adds to the voice stays small (§6).

**Non-goals**

- Muting or ducking the mic while narrating. The user uses headphones (user decision,
  2026-10-10). With speakers in "Both", the call hears the narration twice (direct and
  through the mic); this is documented in the setup dialog, not handled.
- Echo cancellation, noise suppression, gain control: the call app does these.
- Saving the setting between runs (no settings file yet; the default applies at each start).

## 3. User experience

A new row in the TTS pane, under Others:

```text
│ Others: [CABLE Input ▾      ] [How to set up…]│
│ Mic:    [Microphone (Realtek) ▾] [x] Send my mic to the call │
```

| Control | Behavior |
|---|---|
| Mic | WASAPI microphones (`playback.list_inputs`), Windows default first, **without virtual-cable recording sides** (`CABLE Output`, VoiceMeeter outputs, …): feeding the cable into itself would loop. Not `capture.list_sources`: it lists every host API, and the MME "Sound Mapper" it puts first made the delay grow from 16 to 266 ms in 8 s (§6) |
| Send my mic to the call | Checkbox. **Checked at start when a cable was pre-selected as Others and a mic exists.** While checked, the chosen mic plays into the Others device without pause |
| Others | Enabled when the output mode isn't Only me **or** pass-through is checked (pass-through uses it in Only me too) |

Rules:

1. Pass-through runs when the box is checked, a Mic is chosen and an Others device is
   chosen; it is independent of narration (it runs before, during and after Speak).
2. Changing Mic or Others, or toggling the box, restarts or stops pass-through at once.
   It doesn't stop the narration because of the Mic change (Others still does, rule 3.3.5).
3. Narration and the mic share the cable: Windows' shared-mode mixer sums the two streams
   (VERIFIED §5.1), so the call hears both.
4. A mic or cable error (unplugged, device busy) stops pass-through, unchecks the box and
   shows "Mic to call stopped: <device>: <error>" in the TTS status line. No dialog. The
   app keeps running; checking the box again retries.
5. Closing the app stops pass-through before PyAudio is terminated.

## 4. Why no mixer in Wisper

### 4.1 Windows mixes the streams (VERIFIED, 2026-10-10)

Two PyAudio WASAPI shared-mode output streams opened on `CABLE Input` at once, a 440 Hz
and a 1 kHz tone at 0.2 each: `CABLE Output` carried both (peak 0.40 = the sum, nothing
at 700 Hz). So pass-through is a **separate stream** into the cable; the narration
`Player` stays as it is (no mixing, no clipping, no synchronisation code in Wisper).

### 4.2 Rejected: a Wisper mixer

Routing narration through a mixer that also reads the mic would give one cable stream,
but needs back-pressure so `Player.play` still paces in real time, buffer flushing on
Stop, and changes to N4/N5 code that is tested and in use. No benefit over 4.1.

## 5. Design

### 5.1 `playback.py` (leaf, grows)

| Name | Responsibility |
|---|---|
| `list_inputs(pa)` | WASAPI microphones, not loopback, without cables, Windows default first |
| `is_virtual_cable(name)` | True for either side of a virtual cable (`CABLE_NAMES` plus `cable output`, `voicemeeter out`). `find_virtual_cable` uses it for outputs; the app uses it to drop cables from the Mic list |
| `PaInput(pa, device, block_s)` | Real mic stream: float32, the device's rate and channels (shared mode), `read(frames)` → mono float32 (channel mean), `available()`, `close()` |
| `LinearResampler(src, dst)` | Stateful, block by block, for a mic and a cable at different rates (e.g. 44.1 → 48 kHz). Same rate → returns the block unchanged |
| `Passthrough(open_input, open_output, on_error, block_s=PASS_BLOCK_S)` | `start(mic, cable)` opens both streams and starts the `mic-passthrough` thread; the thread reads a block, resamples it if needed, writes it to the cable; `stop()` (idempotent) ends the thread, joins it (`join_s`) and closes both streams; each run has its own stop Event and `run_id`, so a run slower than `join_s` still ends and never reports; `close()` also waits for such runs (before `pa.terminate()`); `running` |

Thread loop details:

- Block size **`PASS_BLOCK_S` = 10 ms** (the shared-mode buffers are ~22 ms anyway, §6).
- **Bounded delay:** when the mic has more than `MAX_BACKLOG_BLOCKS` (3) blocks waiting
  (the cable consumed slower, or the thread was late), the extra frames are read and
  dropped, so the delay can't grow over a long call (mic and cable clocks drift).
- An exception from `read`, `write` or opening a stream → close both streams,
  `on_error(device_name, exception)` once, thread ends. Nothing escapes the thread.
- `start` and `stop` are called from the UI thread only; the loop thread only touches its
  own two streams. No Kokoro or Whisper access (CLAUDE.md thread rules unchanged).

### 5.2 `app.py`

- Builds the Mic row, the checkbox and a `playback.Passthrough` whose factories are
  `PaInput(self.pa, d)` and `PaStream(self.pa, d, block_s=PASS_BLOCK_S)`.
- `_update_passthrough()`: stop, then start when rule 3.1 holds. Called at start-up and
  on every Mic / Others / checkbox change.
- `on_error` runs on the pass-through thread: it only puts `("pass_error", run_id, msg)` on
  `tts_results`; `_poll_tts` ignores a stale `run_id`, else unchecks the box and shows the
  message (rule 3.4).
- `on_close`: `passthrough.close()` before `pa.terminate()`.

Imports don't change (`playback` stays a leaf; only `app` imports it).

## 6. Latency (VERIFIED, measured 2026-10-10, silent)

| Part | Value |
|---|---|
| Mic input stream (PortAudio reported, 10 ms and 5 ms blocks) | 22.3 ms |
| Cable output stream (PortAudio reported) | 22.0 ms |
| Wisper loop: one block | 10 ms |
| VB-Cable internal buffer (+ recorder), from the N6 beep round trip | 0.12–0.18 s |
| Expected voice delay to `CABLE Output` | ≈ 0.18–0.24 s |
| **Measured (real `Passthrough`, WASAPI mic, 20 s)** | **125–130 ms, no drift** ([performance.md](../performance.md)); the call app and network come on top |

Target: Wisper's own part (mic stream + loop + cable stream) ≤ 60 ms, and the voice
doesn't drift later over a 10-minute run (bounded by `MAX_BACKLOG_BLOCKS`). The largest
part is VB-Cable's buffer: lowering its "Max Latency" in the VB-Cable control panel is
the lever (latency increment, measured then). The user judges the result in a call.

## 7. Acceptance criteria

| # | Criterion | How checked |
|---|---|---|
| P1 | In Google Meet (mic = `CABLE Output`) the call hears my voice **and** the narration at the same time | manual T-PASS-1 |
| P2 | Default: box checked and pass-through running at start when a cable is found; unchecked without a cable | `test_narration_ui.py` |
| P3 | Cables never appear in the Mic list | `test_playback.py` + `test_narration_ui.py` |
| P4 | Mic blocks reach the cable in order; stop ends the thread and closes both streams; backlog is dropped; errors reported once | `test_playback.py` with fakes |
| P5 | A mic error unchecks the box with a status message, no dialog | `test_narration_ui.py` + manual T-PASS-3 |
| P6 | Dictation keeps working with pass-through on (same mic) | manual T-PASS-2 |
| P7 | `node tools/verify.mjs` passes | verify output |

## 8. Manual checks

| ID | Steps | Pass when |
|---|---|---|
| T-PASS-1 | Meet test call (or the mic test in Meet settings), mic = `CABLE Output`, headphones on. Talk, then Speak in Both, then talk while it narrates | the other side (or the level dots) gets my voice and the narration, also together; my voice delay isn't bothersome |
| T-PASS-2 | Pass-through on; start Dictation on the same mic; talk | transcript appears as before; the call still hears me |
| T-PASS-3 | Unplug a USB mic (or pick a busy one) with pass-through on | box unchecks, status "Mic to call stopped: …", app keeps running |
| T-PASS-4 | Uncheck the box | the call no longer hears my voice; narration still reaches it |
