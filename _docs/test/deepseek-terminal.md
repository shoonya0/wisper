# Test plan: DeepSeek terminal (speech → `deepseek` CLI → narration)

Spec: [`_docs/specs/2026-10-12-deepseek-terminal.md`](../specs/2026-10-12-deepseek-terminal.md).
Baseline after the T-TERM-4 fix: **357 fast + 2 slow pytest pass** (`current-state.md`). Every change must keep
them passing **by name**, plus its own new tests.

Fast check after every step: `node tools/verify.mjs`. Single file:
`app\.venv\Scripts\python.exe -m pytest app/tests/test_taking_turns.py -v`.

## 1. Automated tests (pytest, `app/tests/`)

None of these runs the real `deepseek` or calls DeepSeek's API. Window tests use the real Tk
window, kept invisible, with the fakes in `conftest.py` (`FakeTerminal`, `FakeEngine`,
`FakeWhisper`, fake streams).

| File | Phase | Needs | Cases |
|---|---|---|---|
| `test_terminal.py` | P1 | a real pseudo-console with a **Python child** (not `deepseek`) | key map: printable keys as they are, a lone modifier writes nothing, special keys and modifiers as win32-input-mode key events; `clean` drops the queries `pyte` would print and holds back an escape split across reads; the child's environment has no `CLAUDE*` variables; typed speech is one line ending in one space (blank → nothing); a paste stays one line; wide and combining characters; scroll-back keeps the lines that scroll off (`ESC[3J` drops only them), stops at both ends and returns on typing; output arrives at once; colours as runs; an unchanged screen gives an empty snapshot; a hidden cursor is still reported as `caret`; typing and resize reach the program; exit is reported; a notice shows and isn't sent; close ends the program |
| `test_terminal_view.py` | P1, P2, #14 | Tk window | rows drawn with colours and the cursor; only changed rows redrawn; a new size redraws blank; keys go to the callback and the text stays unedited; Ctrl+C copies a selection, else goes to the program; Ctrl+V pastes; wheel and Shift+PgUp/PgDn scroll; the size in lines and columns follows the widget; **#14:** the prompt's span across wrapped rows (no cursor → the last `❯` row, the no-break space skipped; empty prompt → none); Ctrl+A selects the prompt text and Ctrl+C copies it; **T-TERM-4 fix:** `prompt_index` counts as the arrows do (across a wrap, a trailing space before the cursor); after Ctrl+A Backspace/Delete move to the end and delete everything, a character replaces it (also after a lone Shift), another key drops the selection; a mouse selection in the prompt (a word, across the wrap) is deleted, replaced by typing or by a paste; one outside the prompt keeps Backspace a single key; a click moves the cursor there (a second click before the redraw counts from the first, the redraw wins; past the end → the end; outside the prompt nothing); after a replacement the program's next cursor wins; Shift+PgUp still scrolls with the prompt selected; a triple-clicked last row is deleted; Ctrl+Shift+A is `deepseek`'s Ctrl+A; a message replaces the screen |
| `test_deepseek_terminal_ui.py` | P2, P3, P4 | Tk window, `FakeTerminal` | `deepseek '--settings' '<hook file>'` starts with the window in `AI-workspace`; the hook file is outside the workspace and quoted for PowerShell (`O''Neil`); the hook runs under `python.exe`, not `pythonw.exe`; the transcript box and its buttons are gone; speech is typed and never sent; keys, paste, scroll and resize reach the terminal; the end shows the restart line and Enter restarts it; an end from an older run is ignored; "not found" says so; a start failure shows in the terminal; speech while it's down isn't typed; a file cut at 100 words says so; **P4:** an answer replaces the narration text and is spoken; a new answer stops the narration and starts over; a paused narration gives way to an answer; an empty answer changes nothing; without Kokoro the answer waits in the box; the real hook script reaches the narration |
| `test_answers.py` | P4 | no (localhost socket) | `extract_answer` on the recorded hook inputs in `fixtures/deepseek-hook/` (no reply → nothing); `plain_text` (Markdown → speech); `hook_settings`; the Inbox takes an answer with the token, ignores a wrong token and junk and keeps working, listens on 127.0.0.1 only with a fresh token, stops on close; the hook script sends the answer, never fails `deepseek`, sends nothing for an empty answer |
| `test_file_stitching.py` | P3, P5 | no | a long file types the first 100 words, then stops; a chunk crossing 100 words is cut; exactly 100 words is typed whole; no header is typed; **P5:** the narration starting stops the file and keeps the typed words (`("done", "stopped")`) |
| `test_taking_turns.py` | P5 | Tk window, fake capture | one test per row of spec §3.2 (see §1.1) |
| `test_job_object.py` | P5 | real processes, `taskkill` | `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` has Windows' size; a child dies within 5 s when its parent (in the job) is killed with `taskkill /F`, and survives without the job |
| `test_architecture.py` | P1, P2, P4 | no | `terminal`, `terminal_view`, `answers` are leaves; `app` may import them |

### 1.1 Taking turns (spec §3.2)

| §3.2 row | Test |
|---|---|
| Narration playing, ▶ Start | `start_while_the_narration_plays_pauses_it_then_listens` |
| Narration playing, Transcribe | `transcribe_while_the_narration_plays_pauses_it_then_transcribes` |
| Paused this way, ▶ Resume or Ctrl+Enter | `resume_stops_listening_then_continues_the_narration[resume, ctrl-enter]` |
| Paused this way, Clear or ⏹ Stop | `clear_or_stop_ends_the_paused_narration_and_listening_carries_on[tts_clear, tts_stop]` |
| Paused this way, a new answer | `a_new_answer_while_paused_this_way_starts_over_and_stops_listening` |
| Listening, Speak / Ctrl+Enter / an answer | `the_narration_starting_stops_listening_first[speak, ctrl-enter, answer]` |
| File running, the narration starts | `the_narration_starting_stops_a_file_and_keeps_its_typed_words` |
| The narration ends (Q3) | `listening_stays_stopped_when_the_narration_ends` |
| The user pauses with ⏸ | `pausing_the_narration_keeps_listening_stopped_until_start` |
| (extra) "Nothing to narrate." | `speak_with_nothing_to_say_keeps_listening` |
| (extra) an old stop doesn't stop a new file | `a_file_started_after_the_narration_isnt_stopped_by_it` |

## 2. Performance checks (recorded in the spec §7.4)

| Check | Target | Result |
|---|---|---|
| `deepseek` ready after start | — | 0.8 s (P1; was 3.8 s) |
| Key → drawn | ≤ 50 ms | median 16 ms, max 33 ms (P1) |
| Hook → Inbox | — | 0.19 s through Git Bash (P4) |
| File stop after 100 words (base.en, 66 s file) | stops early, next run works | 3.0 s vs 6.1 s whole (P3) |

## 3. Manual checks (Tkinter UI: the user runs these)

Run the app with `cd app` + `.venv\Scripts\python.exe app.py` (a console is needed for T-CLOSE-2).
File mode is **on hold** (user, 2026-10-12): skip the T-FILE rows until it's back.

| ID | Phase | Steps | Expected |
|---|---|---|---|
| T-TERM-1 | P2 (passed, user 2026-10-12) | Start Wisper; type a question in the terminal | `deepseek` starts in `AI-workspace` within about 1 s; typing has no visible lag |
| T-TERM-6 | P2 (passed, user 2026-10-12) | Use arrows, Tab, Esc (in a menu), Shift+Enter, Ctrl+C with nothing selected | Each works as in Windows Terminal: Esc closes the menu, Shift+Enter adds a line, Ctrl+C interrupts |
| T-TERM-2 | P2 (passed, user 2026-10-12) | Ask something with a long answer; scroll up with the wheel; type a letter | Scroll-back shows earlier lines; typing returns to the bottom |
| T-TERM-3 | P2 (passed, user 2026-10-12) | Select text with the mouse, Ctrl+C, paste in Notepad; Ctrl+V a multi-line text into the prompt | The selection is copied; the paste lands on one line |
| T-TERM-4 | #14, #15 (failed, fixed; passed, user 2026-10-12) | Type a question; Ctrl+A, Ctrl+C; Backspace. Type again; Ctrl+A, type `x`. Ctrl+A, then ← | Ctrl+A selects only the typed question and Ctrl+C copies it; Backspace empties the prompt; `x` replaces it; ← drops the selection and keeps the text |
| T-TERM-8 | #16 (passed, user 2026-10-12) | Say or type a long question (2+ rows). Select one word with the mouse (drag or double-click), Backspace. Select another, type a letter. Select one, Ctrl+V. Click in the middle of the prompt, type | Only the selected word goes; the letter replaces the second; the paste replaces the third; the typed text lands where you clicked. A selection in `deepseek`'s output still only copies |
| T-TERM-7 | #14 (passed, user 2026-10-12) | Ctrl+Shift+A | `deepseek`'s cursor moves to the line start |
| T-TERM-5 | P2 (passed, user 2026-10-12) | Resize the window and drag the divider; `/exit`; Enter | The screen re-flows; "DeepSeek ended. Press Enter to start it again."; Enter restarts it |
| T-SPEECH-1 | P2 (passed, user 2026-10-12) | Dictation: say two sentences with a pause between | Both are typed at the end of the prompt, one space apart; nothing is sent |
| T-FILE-1 | P3 (**on hold**) | File mode: transcribe a file longer than 100 words | Exactly 100 words in the prompt, no file-name header, no Enter; status "File: typed the first 100 words."; Transcribe enabled again |
| T-FILE-2 | P3 (**on hold**) | File mode: a short file | Typed whole; "File transcription complete." |
| T-ANS-1 | P4 (passed, user 2026-10-12) | Ask "List three fruits as a bullet list", press Enter | When the answer ends it replaces the narration box without `**` or `-` and is spoken |
| T-ANS-2 | P4 (passed, user 2026-10-12) | Ask a second question while the first answer is being spoken; then `/clear` | The new answer replaces the old one and starts from the beginning; `/clear` narrates nothing |
| T-TURN-1 | P5 (passed, user 2026-10-12) | Speak a long text; press ▶ Start (Dictation) | The narration pauses ("Paused n/m."), then listening starts |
| T-TURN-2 | P5 (passed, user 2026-10-12) | Then press ▶ Resume | Listening stops ("Speech to text paused while narrating."); the narration continues from the same spot |
| T-TURN-3 | P5 (passed, user 2026-10-12) | While listening, ask DeepSeek something | When the answer arrives listening stops and the answer is spoken |
| T-TURN-4 | P5 (**on hold**) | Transcribe a long file; press Speak while it runs | The file stops, its typed words stay; the narration plays |
| T-TURN-5 | P5 (passed, user 2026-10-12) | Let a narration end by itself, then pause one with ⏸ | Listening doesn't start again by itself; ▶ Start listens and keeps the narration paused |
| T-CLOSE-1 | P5 (passed, user 2026-10-12) | Close Wisper with ✕ | Task Manager: no `claude.exe` (or `deepseek`'s PowerShell) left |
| T-CLOSE-2 | P5 (passed, user 2026-10-12) | Close Wisper with Ctrl+C in its console | The same |
| T-CLOSE-3 | P5 (passed, user 2026-10-12) | End Wisper's task in Task Manager | The same |

## 4. Not tested automatically (and why)

- A real `deepseek` turn: it calls DeepSeek's API (cost, network, nondeterministic answers). The
  hook path is covered with recorded hook inputs and the real hook script (`test_answers.py`,
  `the_real_hook_script_reaches_the_narration`).
- Typing feel, colours and layout of Claude Code's screen: visual (T-TERM-1…5).
- Real microphones and loopback while narrating: the capture is faked (T-TURN-1…5).
- Ctrl+C in a console and Task Manager: the Job Object is tested with `taskkill /F`
  (`test_job_object.py`); the other ways are T-CLOSE-1…3.
