# Spec: DeepSeek terminal in the speech-to-text pane

| Field | Value |
|---|---|
| Status | Draft rev 5 (2026-10-12): **P0 done**, the user looked at the live window (§7.3: typing lag and no scroll-back to fix); next P1 |
| Date | 2026-10-12 |
| Owner | shoonya0 |
| Test plan | `_docs/test/deepseek-terminal.md` (written in P6) |
| Replaces | the reverted 2026-10-11 assistant design (headless `deepseek` behind New context / Send buttons, never committed) |

## 1. Problem

The user wants to talk to DeepSeek (their `deepseek` command: Claude Code on DeepSeek) from
Wisper and hear its answers. They want to **see and use the real CLI**, not buttons in
front of a hidden one: speech is typed into the CLI's input line, they edit it and press
Enter themselves, and each answer is narrated automatically. Listening and narrating
never run at the same time.

## 2. Decisions (user, 2026-10-12)

| # | Decision |
|---|---|
| D1 | **Remove Copy all, Clear and Save…** from the speech-to-text pane: the buttons and their code (`copy_all`, `clear`, `save`). The narration pane keeps its own Copy all / Clear / Save… |
| D2 | **Remove the transcript box.** A terminal takes its place |
| D3 | The terminal runs **`deepseek` directly** (Wisper starts it at app start), not a general PowerShell. Every answer is then narrated, and Wisper always knows whether it's running. Other PowerShell commands can't be run there. `deepseek` itself (the profile function, `~\.claude-deepseek`, the Claude Code install) **is not changed**: Wisper only adds command-line options |
| D4 | **No folder limit**: `deepseek` runs with the user's normal settings (shell, permission mode), as in PowerShell. It starts in **`D:\projects\wisper\AI-workspace\`** (user, 2026-10-12; gitignored, created if missing), not the home folder, which Claude Code asked to trust as a whole. A folder inside the Wisper repo also loads Wisper's project setup (`CLAUDE.md`, skills, MCP server, git status); P0 measures what that costs |
| D5 | **Every final answer goes to the narration**: Wisper stops any narration in progress, **replaces** the narration box text with the answer and **starts Speak automatically** from the beginning. Only the final reply is narrated: no tool output, thinking or progress |
| D6 | The answer reaches Wisper through a **Claude Code `Stop` hook** passed with `--settings`, not an MCP server. The hook runs on every turn and passes the exact reply. An MCP "narrate" tool would let DeepSeek decide whether and what to narrate (it may skip, shorten or reword it) and would cost tokens on every call |
| D7 | **All three modes type into the terminal's input line.** Wisper never presses Enter: the user reviews, edits and sends |
| D8 | **File mode types at most 100 words, and the transcription stops there** (Q1: yes) |
| D9 | **Listening and narrating take turns (Q2)**: only one runs at a time. Starting speech to text (▶ Start, or Transcribe in File mode) while the narration plays **pauses the narration**. It stays paused until the user resumes it, clears it, or a new answer arrives (which replaces the text and starts from the beginning). Starting or resuming the narration (Speak, Resume, Ctrl+Enter, or a new answer) **pauses speech to text**. Details in §3.2 |
| D10 | **It dies with Wisper**, however Wisper ends (✕, Ctrl+C in a console, a crash, `taskkill /F`): Wisper puts itself into a Windows Job Object with kill-on-close at start-up, so the pseudo-console, PowerShell, `claude.exe` and anything they start are killed with it. VERIFIED in the reverted 2026-10-11 spike (normal exit, crash, `taskkill /F`, and a hung child) |
| D11 | The CLI is drawn by Wisper itself (a pseudo-console plus a terminal-screen emulator), so there's no separate window. New dependencies: **`pywinpty`** (Windows ConPTY; 3.0.5, 2026-06, used by Jupyter's terminal) and **`pyte`** (VT100 screen emulator; 0.8.2, last release 2023-11, so P0 checks it copes with Claude Code's screen) |

## 3. User experience

```text
┌ Speech to text ─────────────────────────────┐┌ Text to speech ──────────────┐
│ [▶ Start] Mode [Live captions] Model [...]  ││ [🔊 Speak] [⏹ Stop] voice …  │
│ Device: [Speakers (default)            ]    ││                              │
│ ┌ DeepSeek ──────────────────────────────┐  ││  narration box               │
│ │ (the real deepseek screen: banner,     │  ││  (DeepSeek's last answer,    │
│ │  messages, tool calls, answers)        │  ││   being spoken)              │
│ │ > what is the capital of france_       │  ││                              │
│ └────────────────────────────────────────┘  ││ [Save…] [Clear] [Copy all]   │
│ Listening • small.en • queue: 0      Level ▮ ││                              │
└─────────────────────────────────────────────┘└──────────────────────────────┘
```

### 3.1 The terminal

| Action | Result |
|---|---|
| App starts | The terminal shows `deepseek` starting, in `AI-workspace`. The STT controls work as before |
| Speech (Dictation, Live captions) | Each transcribed chunk is typed at the end of the input line, with a space between chunks. Nothing is sent |
| File mode | Types the file's words until 100 are typed, then the transcription stops; the status says "File: typed the first 100 words." A shorter file is typed whole |
| Click in the terminal, type | Keys go to `deepseek` (letters, Enter, Backspace, arrows, Tab, Esc, Ctrl+C) |
| Select with the mouse, Ctrl+C | Copies the selection (as Windows Terminal does); Ctrl+C without a selection goes to `deepseek` (interrupt) |
| Ctrl+V | Pastes the clipboard into the input line |
| DeepSeek finishes an answer | Narration stops if it was playing or paused, the narration box gets the answer, Speak starts from the beginning (and §3.2 pauses speech to text) |
| Empty answer (e.g. `/clear`, a cancelled turn) | Nothing is narrated and the narration box is unchanged |
| `/exit`, or `deepseek` crashes | The terminal shows "DeepSeek ended. Press Enter to start it again." |
| `deepseek` isn't found | The terminal shows "`deepseek` wasn't found: it's a function in your PowerShell profile." |
| Wisper closes, any way | The terminal and everything it started end with it (D10) |

### 3.2 Listening and narrating take turns (D9)

"Speech to text paused" means Wisper stopped listening because the narration started.
The ▶ Start button shows that it can be started again.

| Situation | What happens |
|---|---|
| Narration playing, the user presses ▶ Start (Dictation or Live captions) | The narration **pauses** (⏸ → ▶ Resume, status "Paused 3/12."), then listening starts |
| Narration playing, File mode Transcribe | The narration pauses, then the file is transcribed |
| Narration paused this way, the user presses ▶ Resume (or Ctrl+Enter) | Listening **stops**, then the narration continues from the same spot |
| Narration paused this way, the user presses Clear or ⏹ Stop | The narration ends as today; listening carries on |
| Narration paused this way, a new answer arrives | The old text is wiped, the answer goes into the box, Speak starts from the beginning, and listening stops |
| Listening, the user presses Speak (or Ctrl+Enter), or a new answer arrives | Listening **stops** ("Speech to text paused while narrating."), then the narration starts |
| File transcription running, the narration starts | The file transcription is stopped (the typed words stay), then the narration starts |
| Narration ends by itself (last sentence played), or the user stops it | Speech to text stays stopped. The user presses ▶ Start to listen again (Q3) |
| The user pauses the narration with ⏸ | Speech to text stays stopped until the user presses ▶ Start (which keeps the narration paused) |

The mic pass-through (N8) isn't part of this: it keeps sending the user's mic to the call
whether Wisper is listening or narrating.

## 4. Design

1. **Pseudo-console.** `pywinpty` starts
   `powershell.exe -NoLogo -Command "deepseek '--settings' '<hook settings>'"` in `AI-workspace`
   (the profile is loaded, so the `deepseek` function exists; every argument is single-quoted
   for PowerShell, a lesson from the 2026-10-11 spike). A reader thread reads its output and
   feeds a `pyte` screen. The UI redraws the changed lines into a Tk `Text` widget (colours
   and bold as tags, the cursor as a tag) on a timer. The terminal's size follows the widget
   (font metrics → columns and rows → `setwinsize` and `screen.resize`).
2. **Keys.** ConPTY turns on **win32-input-mode** (`ESC[?9001h`), so special keys are sent as
   `ESC[vk;sc;uc;down;state;repeat_` pairs (key down, key up), as Windows Terminal does. A
   plain `ESC[B` was read as Esc and cancelled a dialog (P0). Printable characters and
   Ctrl+letters (Ctrl+U) are plain characters. Enter, Backspace, Tab and Esc are also sent as
   key events (P1, as the P0 live window did), so Shift+Enter and Shift+Tab carry the Shift
   (a plain `\r` and `\x7f` work too, P0). A pure function maps Tk key events to
   these. Paste is written as one plain line (newlines become spaces), not as a bracketed paste.
   Sequences `pyte` doesn't know (`ESC[?u`, `ESC[<u`, `ESC[>0q`) are removed before feeding it,
   or it prints their last letter. The child gets Wisper's environment without `CLAUDE*`
   variables, so a Wisper started from a Claude Code session doesn't hand them down (P0 saw
   "Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION").
3. **Speech in.** The worker's `("text", …)` results (each chunk is final; Whisper doesn't
   revise it later) go to the terminal instead of the transcript box: newlines become spaces,
   then the text is written to the pseudo-console in one write. VERIFIED in P0: 100 words in
   one write stay editable text, while a multi-line bracketed paste is folded into
   "[Pasted text #1 +11 lines]". File mode counts words, types up to 100,
   then asks the worker to stop the file (D8; whisper.cpp's abort callback, checked in P3).
   The prompt context (`last_text`) is unchanged.
4. **Answer out (D6).** Wisper starts a listener on `127.0.0.1` (random port) that accepts
   only messages carrying a random per-run token. The `--settings` JSON adds one `Stop` hook:
   `"<app python>" "<app>\answers.py" <port> <token>`. Claude Code runs it at the end of
   every turn with the hook input on stdin. The final reply is its **`last_assistant_message`**
   field (VERIFIED in P0: exactly the reply, no tool output or thinking). The script sends it to
   Wisper. Claude Code runs the hook through Git Bash inside the same pseudo-console, so no
   window flashes. The hook doesn't fire for `/clear` or a turn interrupted with Esc. Claude Code runs the
   hook, not the model, so it opens nothing new to DeepSeek. The hook merges with any hooks
   in the user's own settings.
5. **Answer → narration (D5).** The listener thread puts `("ai_answer", text)` on a queue
   that the UI drains: `tts_stop()`, replace the narration box text, then the Speak path. An
   empty text does nothing. Answers arrive as **Markdown** (`**Fruits**`, `- Apple`, P0), so a
   pure `plain_text()` removes the marks (bold, headings, bullets, code fences, link targets)
   before the text goes into the box, so Kokoro never reads symbols out.
6. **Taking turns (D9).** Two small hooks in `app.py`, no new thread:
   - Every path that starts or resumes the narration (`tts_toggle`'s Speak and Resume, the
     answer path) first calls `_stop_listening()`: it stops the capture (or the file job),
     and sets the status line and the ▶ Start button.
   - Every path that starts listening (`toggle`'s Start, `start_file`) first calls
     `tts_pause()` if the narration is playing (N9's pause, so ▶ Resume continues the spot).
7. **Lifecycle (D10).** `main()` puts the app process into a kill-on-close Job Object before
   anything starts. `on_close` ends the pseudo-console process (then the job covers anything
   left). If `deepseek` exits, the terminal shows the restart line (§3.1) and Enter starts it again.
8. **Modules.** New leaves (stdlib and their own dependency only; `test_architecture.py` and
   `architecture-overview.md` updated):
   - `terminal.py`: the pseudo-console process, the reader thread, the `pyte` screen,
     `write()`, `resize()`, a snapshot of changed lines, and the pure key map. No Tk.
   - `terminal_view.py`: the Tk widget that draws a snapshot and turns key/mouse events into
     calls; it gets the snapshot from `app.py` and imports no app module.
   - `answers.py`: the listener (`Inbox`) and, run as a script, the hook (`extract_answer`
     is pure and unit-tested on recorded hook inputs).
   - Job Object helper: in `priority.py` (it's the Windows-process leaf) or its own leaf;
     decided in P5.

## 5. Out of scope

- A general PowerShell terminal (D3), several tabs, or scroll-back beyond what `pyte` keeps.
- Pressing Enter by voice ("send" keyword): Wisper never sends (D7).
- Changing `deepseek`, its config folder or the Claude Code install (D3).
- A folder limit or tool limits (D4).
- Pausing the mic pass-through while narrating (§3.2).

## 6. Phases

Each phase is one increment: tests in the same session → `node tools/verify.mjs` →
`code-reviewer` agent → `/close-increment` → the user approves the commit. A phase starts
only when the one before it is done. P1, P2 and P4 don't need `deepseek` and could be done in
another order; P3 needs P1 and P2.

### P0: Spike (scratchpad scripts, no app code)

Goal: find out whether the plan works before writing app code. If step 2 fails, stop and
choose again with the user.

1. Install `pywinpty` and `pyte` in a throwaway venv (not `app/.venv`).
2. **Drawing:** run interactive `deepseek` in a pseudo-console, feed a `pyte` screen and draw
   it in a bare Tk window. Check the banner, the input box, colours, box characters, emoji and
   the spinner. Measure the time from a keystroke to its redraw and the CPU while DeepSeek streams.
3. **Typing in:** write a sentence into the input line as typed characters, then as a
   bracketed paste. Check which one stays editable (not folded into "[Pasted text]").
4. **Hook:** start `deepseek` with `--settings` holding a `Stop` hook that writes its stdin
   to a file. Ask 2 questions and run `/clear`. Check: it fires once per turn, which fields
   its input has (a final-reply field, or only `transcript_path`), how Claude Code runs the
   command on Windows (which shell), and whether a console window flashes.
5. **Job Object:** with Wisper-like parent under the kill-on-close job, end the parent
   normally, by a crash and by `taskkill /F`. Check that the pseudo-console, PowerShell and
   `claude.exe` are gone within 2 s.
6. **Exit:** `/exit` and a killed `claude.exe`: what the pseudo-console reports and the exit code.
7. Save the hook inputs from step 4 as fixtures in `app/tests/fixtures/deepseek-hook/` (user
   name and paths scrubbed, no keys). Fill §7 and report.

Done when: §7 has the results, and the user agrees to go on.

### P1: The terminal module (`terminal.py`)

1. Add `pywinpty` and `pyte` to `app/requirements.txt`; install them in `app/.venv`.
2. `Terminal`: start a command in a pseudo-console with a size and a folder; a reader thread
   feeding a `pyte` screen; `write()`, `resize()`, `alive`, `close()`.
3. `snapshot()`: the lines that changed since the last call, with colours, bold and the cursor;
   scroll-back from `pyte.HistoryScreen` (§7.3).
4. The pure key map (Tk key name and modifiers → bytes).
5. Tests: a small Python child (no `deepseek`, no network) through a real pseudo-console:
   echo, resize, exit, scroll-back; plus key-map tests. `test_architecture.py` knows the new leaf.
6. Find the typing lag (§7.3): time a key from Tk's event to the redraw, with a fake child and
   with `deepseek`; fix it (target under 50 ms) before P2 builds on it.

Done when: tests pass.

### P2: The terminal in the window (`terminal_view.py`, `app.py`)

1. `TerminalView`: a Tk widget that draws a snapshot (colour tags, the cursor), sends keys and
   pastes, copies a selection with Ctrl+C, and reports its size in columns and rows.
2. `app.py`: remove the transcript box and Copy all / Clear / Save… with their code (D1, D2).
   Put the terminal in their place, start `deepseek` at app start (§4.1, without the hook
   yet), redraw on the poll timer.
3. Speech results are typed into the terminal (§4.3), all modes.
4. The "ended" and "not found" lines (§3.1), Enter restarts.
5. Update the window-layout tests (§9) and add tests with a fake terminal: speech is typed,
   nothing presses Enter, every STT control is still visible at the minimum window size.

Done when: tests pass, and manually: the terminal shows `deepseek`, typing works, speech lands
in its input line.

### P3: File mode stops at 100 words

1. Word counting on the typed text; at 100 words the rest of the chunk is cut and the worker
   is asked to stop the file.
2. Stop the file job early (whisper.cpp's abort callback, after diffing the header per
   CLAUDE.md, or stop between segments), and the status line from §3.1.
3. Tests: with the fake model of `test_file_stitching.py`, a long file types exactly 100 words
   and stops; a short file types everything.

Done when: tests pass.

### P4: Answer → narration (`answers.py`)

1. The listener (`Inbox`): `127.0.0.1`, random port, per-run token; the answer goes to a queue.
2. The hook script: read the hook input, take `last_assistant_message`, send it with the token.
   `plain_text()` turns Markdown into speakable text (§4.5).
3. Start `deepseek` with the hook in `--settings` (§4.4).
4. The UI path (§4.5): stop, replace the narration text, Speak.
5. Tests: `extract_answer` and `plain_text` on the P0 fixtures in
   `app/tests/fixtures/deepseek-hook/` (a missing or empty field gives nothing); the inbox
   with a fake hook (a wrong token is ignored); the UI path with the fake TTS engine from
   `conftest.py` (text replaced, narration started, an empty answer changes nothing).

Done when: tests pass, and manually: a DeepSeek answer is spoken.

### P5: Taking turns and lifecycle

1. Taking turns (§3.2, §4.6): `_stop_listening()` before every narration start or resume;
   `tts_pause()` before every listening start.
2. Job Object at start-up (§4.7); `on_close` ends the terminal.
3. Tests: every row of the §3.2 table with the fake capture and the fake TTS engine; a child
   started under the job dies when its parent is killed with `taskkill /F`.

Done when: tests pass, and manually: closing Wisper by ✕, Ctrl+C and Task Manager leaves no
`claude.exe`.

### P6: Docs and the manual test plan

1. `_docs/test/deepseek-terminal.md`: manual tests for the terminal, speech typing, File mode
   100 words, answer narration, every §3.2 row, and closing Wisper each way.
2. `_docs/architecture-overview.md` (modules, threads, flows, imports), `current-state.md`,
   the status log.

Done when: the user runs the manual plan.

## 7. Spike findings (P0, 2026-10-12)

Scripts in the session scratchpad (`p0/run.py`: `deepseek` in a ConPTY with a `pyte` screen and
scripted keys; `p0/tkview.py`: a minimal Tk terminal; `p0/jobtest.py`), not committed. A
throwaway venv held `pywinpty` 3.0.5 and `pyte` 0.8.2; `app/.venv` is unchanged. Claude Code
2.1.296, DeepSeek Flash, `AI-workspace` (100 × 32).

### 7.1 Results by step

| Step | Result | Evidence |
|---|---|---|
| 1 Install | ✅ both install from wheels on Python 3.12 | pip |
| 2 Drawing | ✅ `pyte` keeps a correct screen: the logo blocks, `─` rules, `❯` prompt, `●` replies, `✻` status, accents. ⚠ It prints the last letter of `ESC[?u` / `ESC[<u` (kitty keyboard queries) as text: filter them (§4.2). Tk redraw of the changed lines: median 2.9–3.3 ms, p95 3.5–4.6 ms, max 4.6 ms; a full-screen redraw 17–23 ms (invisible window, recorded output replayed) | `tkview.py bench` |
| 2 Keys | ⚠ ConPTY switches on win32-input-mode (`?9001h`). Down sent as `ESC[B` cancelled the trust dialog ("No, exit"); sent as a win32-input key it moved the selection. Plain characters, `\r`, `\x7f` and Ctrl+U work. Keystroke → on the `pyte` screen: 7.5–20 ms | `screens.txt` |
| 3 Typing in | ✅ typed text and one 100-word write stay editable in the input line; a 12-line bracketed paste is folded into "[Pasted text #1 +11 lines]". `café naïve` intact | `screens.txt` |
| 4 Hook | ✅ `--settings <file>` with a `Stop` hook: fires once per answered turn, not for `/clear`, not for an Esc-interrupted turn. Its stdin has `last_assistant_message` = the final reply only ("OK", "Teal.", raw Markdown). Run through Git Bash (`SHELL`), inside the pseudo-console: no window. `--settings` takes a **file path**, which avoids quoting JSON through PowerShell 5.1 | `hook-log.jsonl`, fixtures |
| 5 Job Object | ✅ with the kill-on-close job: normal exit, a crash and `taskkill /F` leave none of `OpenConsole.exe`, 2 × `powershell.exe`, `claude.exe` after 2 s. Without the job `taskkill /F` also ended them here (closing the pseudo-console ends its programs); the job stays for the hung-child case found on 2026-10-11 | `jobtest.py` |
| 6 Exit | ✅ `/exit` ends with exit status 0 and EOF on the pty; a forced end gives status 2. ⚠ `pywinpty`'s `read()` blocks while there's no output: read on its own thread (a loop that polled it hung) | `events.jsonl` |
| 7 Fixtures | ✅ 3 hook inputs in `app/tests/fixtures/deepseek-hook/`, user name scrubbed | README there |

**Timing**: a short answer 1.4–3.4 s from Enter to the hook. **Memory** across turns works
("Teal."). **Tokens**: the first turn costs about 24.4k input tokens (Claude Code's own prompt
and tools plus Wisper's project context); later turns read ~24.3k from cache and add ~155.

### 7.2 One-time prompts in `AI-workspace`

`deepseek` asked once to **trust the folder** (accepted in P0: the user chose this folder), and
once about the **project MCP server `code-review-graph`** from Wisper's `.mcp.json` ("Continue
without using this MCP server" was confirmed, so it stays off). Both answers are saved in
`~\.claude-deepseek\.claude.json` and weren't asked again. They'd show in the Wisper terminal on
a fresh config, where the user answers them by keyboard.

### 7.3 The user's look at the live window (`tkview.py live`, 2026-10-12)

| Check | Result |
|---|---|
| Start screen, colours, font | ✅ |
| Typing | ⚠ **noticeable lag** when typing; Backspace and Left/Right ✅ |
| An answer streaming, the screen after it | ✅ |
| Long answer, paste | ✅ smooth; ❌ **no scroll-back**: the mouse wheel does nothing (the earlier turns stay visible while they fit) |
| `/` menu with Up/Down, Esc | ✅ |
| Resize | ✅ redraws to the new size |
| Close with ✕ | ✅ its `claude.exe` ended (the user saw 4 → 3; the other 3 were this agent's session, a Claude Code in the Antigravity IDE, and a leftover P0 `jobtest.py` hold, not the window) |

Changes for P1/P2:

- **Typing lag**: find the cause before P2. Suspects: the spike redraws on a fixed 16 ms timer
  even when idle and re-tags whole lines; `pywinpty`'s blocking `read()` may hold the GIL and
  stall Tk's loop; or Claude Code echoes slowly in any ConPTY (compare with `deepseek` in
  Windows Terminal). P1 measures key → Tk-redraw time end to end, and the target is under 50 ms.
- **Scroll-back**: keep the lines that scroll off the top (`pyte.HistoryScreen`) and scroll
  them with the mouse wheel and Shift+PageUp/PageDown; typing jumps back to the bottom.

### 7.4 P1 measurements (`terminal.py`, 2026-10-12)

The user confirmed that `deepseek` in plain PowerShell doesn't lag. P1 timed the whole path
with `deepseek` running in `AI-workspace` and an invisible Tk window drawing `snapshot()` on a
16 ms timer. Keys were written as the view will write them, with no Enter, so no tokens were
spent. Scripts `p1/lag.py` and `p1/burst.py` are in the session scratchpad.

| Run | Key → drawn in Tk |
|---|---|
| A key every 150 ms (31 keys) | median 16.4 ms, p90 18.4 ms; the first key after start ~350 ms (Claude Code still starting after `❯` shows) |
| A key every 80 ms / 40 ms (46 keys each) | median 16.6 / 16.2 ms, max 32.9 / 31.6 ms; no keys queued up |
| An 8 ms timer instead of 16 | median 15.8 ms: Tk's `after` can't go below the Windows timer tick |

Draw time per snapshot, including `snapshot()`: median 0.15 ms, max 3 ms. That's because
`snapshot()` returns only the rows whose text or colours really changed. ConPTY repaints rows
that didn't change, and the spike redrew every one of them. Typing in P1 is under the 50 ms
target, and the user checks it by hand in P2.

Found and fixed in P1:

- **ConPTY waits 3 s at start.** It asks for the device attributes (`ESC[c`) and holds the
  program's output for 3 s until an answer comes (`deepseek`'s `❯` appeared at 3.8 s in P0).
  pyte now answers the queries (`write_process_input` → the pseudo-console), and `❯` appears
  at 0.8 s.
- **The end is seen 5 s late.** pywinpty's reader gets EOF about 5 s after the program ends. A
  thread waits on the process handle instead, so `on_exit` comes at once. `close()` closes the
  reader's socket itself, because `PtyProcess.close()` does nothing once `isalive()` has seen
  the end.
- **Scroll-back**: a small `pyte.Screen` subclass keeps the lines leaving the top (up to 5000)
  instead of `HistoryScreen`, whose paging rewrites the screen buffer. `ESC[3J` (`cls`,
  `/clear`) empties the history. While scrolled back, new output keeps the same lines in view;
  `write()` goes back to the bottom.
- An escape sequence split across two reads is held back until the next read, so the
  `ESC[<u` filter still catches it.

## 8. Open questions

| # | Question | Answer or proposal |
|---|---|---|
| Q1 | File mode: after 100 words, stop the transcription too? | **Yes** (user, 2026-10-12) → D8 |
| Q2 | Live captions would hear the narration on the speakers: what then? | **Take turns** (user, 2026-10-12) → D9, §3.2 |
| Q3 | When the narration ends by itself, should listening start again on its own (if the narration had paused it)? | **No** (user, 2026-10-12): the user presses ▶ Start |

## 9. Tests that change (approved by the user, 2026-10-12)

In `app/tests/test_window_layout.py`, these tests check the transcript box or its buttons,
which D1 and D2 remove:

- `test_speech_to_text_left_text_to_speech_right`: checks `window.text`; it'll check the
  terminal widget instead.
- `test_narration_clear_copy_save_only_touch_the_narration_box`: puts text in the
  transcript box to show the narration buttons don't touch it; it'll keep only the
  narration-box half.
- `test_transcript_clear_leaves_the_narration_box_alone`: tests the removed Clear button;
  it's **deleted**.
