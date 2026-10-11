# Spec: Mark the narrated text (narration N10)

| Field | Value |
|---|---|
| Status | Done (2026-10-11): automated checks pass; T-MARK-1 passed (user, 2026-10-11) |
| Date | 2026-10-11 |
| Owner | shoonya0 |
| Parent spec | [`2026-10-07-kokoro-narration.md`](./2026-10-07-kokoro-narration.md) §3.3, §10 ("highlight the sentence being spoken"); builds on N9 [`2026-10-11-narration-pause.md`](./2026-10-11-narration-pause.md) |
| Test plan | [`_docs/test/kokoro-narration.md`](../test/kokoro-narration.md) (N10 rows) |

## 1. Problem

While the narration plays, the box doesn't show how far it has got. The user wants the part
that has **already been narrated marked** in the box, and the marking to **go back to the
start when the narration is stopped** (user, 2026-10-11).

## 2. Behavior

| When | The narration box shows |
|---|---|
| A piece starts playing | Every piece before it is **narrated** (dimmed text); the piece playing is **speaking** (highlighted background) |
| Paused (N9) | The marks stay where they are; Resume continues them |
| Stop, Clear, or a voice / speed / output / device change | All marks removed: back to the start (the next Speak starts from the top, as before) |
| The narration completes | All marks removed (the box is back to idle, like after Stop) |
| An error ends the narration | All marks removed |
| The text is edited during the narration | All marks removed for the rest of this narration: the box no longer matches the snapshot being read (rule 3.3.1), so the positions would be wrong. The audio isn't affected |

- **Granularity: one piece at a time** (a sentence, or a clause of a long sentence, §5.2 of
  the parent spec). Kokoro returns no word timings, so a word-by-word marker isn't possible.
- The marks are only colours (Tk text tags): the text itself, Copy all and Save… are unchanged.
  The selection still shows on top of them.

## 3. Design

- **`tts.piece_spans(text)`** (pure, new): the `(start, end)` character offsets in `text` of
  each piece `split_sentences(text)` returns. The splitter is word-based, so each piece is a
  run of whole whitespace-separated words of `text`: the spans come from counting words.
  Returns `None` if the pieces don't match the words (defensive: then nothing is marked).
- **`app.py`**: at Speak, keeps the snapshot and its spans. On `("tts_progress", gen, i, n)`
  for the narration on screen, if the spans have `n` entries and the box still equals the
  snapshot, tags `narrated` from the start to piece *i* and `speaking` on piece *i*;
  otherwise removes the marks and stops marking this narration. `_narration_ended` (stop,
  done, error) removes the marks. Tk's `"1.0 + Nc"` indexes match Python string offsets,
  emoji and Hindi included (VERIFIED, Tk 8.6.15).
- Tags: `narrated` = muted foreground, `speaking` = the selection-blue background; `sel` is
  raised above both.
- No thread changes: the marks are set on the UI thread from the existing progress results.

## 4. Acceptance criteria

| # | Criterion | How checked |
|---|---|---|
| H1 | `piece_spans` covers exactly each piece's words, in order (incl. blank lines, Hindi, emoji, the short first chunk) | `test_tts_split.py` |
| H2 | While piece *i* of *n* plays, pieces 1…*i*−1 are `narrated` and piece *i* is `speaking` | `test_narration_ui.py` |
| H3 | Pause keeps the marks; Stop, Clear, a setting change, completion and an error remove them | `test_narration_ui.py` |
| H4 | Editing the text during the narration removes the marks and adds none later | `test_narration_ui.py` |
| H5 | The marks are visible and readable in the dark theme, and follow the audio | manual T-MARK-1 |
| H6 | `node tools/verify.mjs` passes | verify output |
