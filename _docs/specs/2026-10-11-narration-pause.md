# Spec: Pause and resume the narration (narration N9)

| Field | Value |
|---|---|
| Status | Done (2026-10-11): automated checks pass; T-PAUSE-1 passed (user, 2026-10-11); **pending: T-PAUSE-2** (in a call) |
| Date | 2026-10-11 |
| Owner | shoonya0 |
| Parent spec | [`2026-10-07-kokoro-narration.md`](./2026-10-07-kokoro-narration.md) §3.2, §3.3 |
| Test plan | [`_docs/test/kokoro-narration.md`](../test/kokoro-narration.md) (N9 rows) |

## 1. Problem

The narration can only be stopped, and the next Speak starts again from the top. The user
wants to **pause** it and **resume from the exact spot** where it paused, with the same button.

## 2. Decisions (user, 2026-10-11)

1. Pause applies to the **narration** (text to speech), not to speech to text.
2. The main button cycles **🔊 Speak → ⏸ Pause → ▶ Resume**. A new **⏹ Stop** button ends
   the narration, so the next Speak starts over. `Ctrl+Enter` follows the main button.
3. While paused, changing the **voice, speed, output mode or a device stops** the narration,
   as rule 3.3.5 does while speaking. **Editing the text doesn't**: Resume continues the
   snapshot taken at Speak (rule 3.3.1).

## 3. User experience

```text
[🔊 Speak]             idle            Stop disabled
[⏸ Pause] [⏹ Stop]    speaking        status "Speaking 2/5…"
[▶ Resume] [⏹ Stop]   paused          status "Paused 2/5."
```

| Action | Result |
|---|---|
| Pause (button or Ctrl+Enter) while speaking | Every device goes silent within one 50 ms block; the button becomes ▶ Resume; status "Paused i/n." |
| Resume (button or Ctrl+Enter) | Playback continues from the next block of the same sentence (no word repeated or skipped); status back to "Speaking i/n…" (with the Live captions hint if it was shown) |
| Stop, while speaking or paused | As today: "Narration stopped.", the button back to Speak, Stop disabled |
| Clear, while paused | Stops (rule 3.3.2), then empties the box |
| Voice / speed / mode / Me / Others change while paused | Stops (rule 3.3.5) |
| Edit the text while paused | Nothing changes; Resume continues the old snapshot |
| Pause before the first sound | Allowed: the first sentence is synthesized, then waits; Resume plays it from the start |
| Close the app while paused | Same as while speaking: the narration stops and the streams close |

The mic pass-through (N8) is unaffected: pausing the narration doesn't pause the mic.

## 4. Design

- **`playback.Player`** gets `pause()`, `resume()` and `paused`. `play()` checks a resume
  `Event` before every block and waits while it is cleared (re-checking stop every 20 ms),
  so the position inside the sentence is simply the loop index: Resume writes the next block.
  The streams **stay open** while paused (resume is instant; an idle WASAPI stream plays
  silence). `stop()` ends a paused `play()` within 20 ms. `pause` / `resume` are safe from
  any thread (they only set or clear an Event), like `stop()`. `start()` doesn't touch the
  pause state, so a Pause pressed before the worker starts the narration still holds.
- **`narrator.Narrator`**: no change. While `play()` waits, the player thread holds piece k,
  so the worker's one-ahead rule keeps piece k+1 ready and synthesizes nothing more.
- **`app.py`**: `self.tts_paused`; `tts_toggle` = Speak, Pause or Resume; `tts_pause` /
  `tts_resume`; a `stop_btn`; Speak calls `player.resume()` before queueing (a stale pause
  from a stopped narration never carries over); the last progress `(i, n)` is kept so the
  paused and resumed status lines show it.
- Imports and threads don't change.

## 5. Acceptance criteria

| # | Criterion | How checked |
|---|---|---|
| P1 | Pause silences every device within one block; no block is written while paused | `test_playback.py` |
| P2 | Resume continues with the next block: the concatenated writes equal the sentence | `test_playback.py` |
| P3 | Stop while paused ends `play()` quickly and closes the streams | `test_playback.py` + `test_narration_ui.py` |
| P4 | The button cycles Speak → Pause → Resume; Stop is enabled only during a narration; Ctrl+Enter follows the button | `test_narration_ui.py` |
| P5 | Paused status keeps the progress; a voice/speed/mode change while paused stops; editing the text doesn't | `test_narration_ui.py` |
| P6 | The narration really pauses and resumes mid-word on the speakers and in a call | manual T-PAUSE-1, T-PAUSE-2 |
| P7 | `node tools/verify.mjs` passes; Stop fits at the minimum window size | verify output, `test_window_layout.py` |
