# Wisper

Local, offline speech-to-text for an AMD RX 580 (Polaris): a Tkinter app with three modes
(dictation, live captions, file) on whisper.cpp's Vulkan backend via ctypes.
Stack: Python 3.12 (`app/.venv`), numpy/scipy, pyaudiowpatch, miniaudio; whisper.cpp
(C++, upstream clone, gitignored). Platform: **Windows only**.

## Read first (map, not manual)

| Need | Read |
|---|---|
| Where the project stands, how to run/build, test baseline, known issues, next task | `_docs/current-state.md` |
| Modules, threads, main flows, allowed imports | `_docs/architecture-overview.md` |
| Why whisper.cpp + Vulkan, measured speeds, latency levers | `_docs/performance.md` |
| Docs index and where new docs go (specs, test plans, ADRs, status) | `_docs/README.md` |

All docs live in `_docs/`. Never create a `docs/` folder.

## Commands

- Setup: `app\.venv\Scripts\python.exe -m pip install -r app\requirements-dev.txt`
- Run: `app\run.bat` (no console), or `cd app` + `.venv\Scripts\python.exe app.py` (tracebacks visible)
- **Fast check, run before saying done: `node tools/verify.mjs`** (ruff check + pyright + pytest, ~6 s)
- Full check: `node tools/verify.mjs --full` (what CI runs)
- Single test: `app\.venv\Scripts\python.exe -m pytest app/tests/test_audio_io.py -k overlap`

## Workflow

- Find code with the code graph (code-review-graph MCP: `semantic_search_nodes`,
  `query_graph` callers_of/tests_for, `get_impact_radius`) before Grep or reading files.
- Non-trivial change: spec (`_docs/specs/`) → plan → small steps → `/verify-change` →
  `code-reviewer` agent → `/close-increment`.
- Speed or latency work: use the `optimized-app-research` skill (measure first, then
  record numbers in `_docs/performance.md`).
- Bugs: write a failing test that reproduces the bug first.
- Write tests in the same session as the feature. Never delete, skip or weaken a test
  without explaining why and getting approval.
- Commit only the files you changed for this increment. **No AI co-author or
  "Generated with" trailers**: commits are authored by the git user only. Ask before committing.
- Report evidence (commands + output), not claims. The UI is Tkinter, so **UI
  verification is manual**: list the steps for the user to check.

## Rules (each one exists because something went wrong)

- IMPORTANT: Only the worker thread in `app/app.py` touches the `Whisper` model. Whisper
  contexts aren't thread safe. Other threads talk to it through the `jobs`/`results` queues.
- IMPORTANT: `app/whisper_native.py` mirrors the C structs in `whisper.cpp/include/whisper.h`
  at commit `6e4ab85`. Never change those structs, or rebuild whisper.cpp from another
  commit, without diffing the header first.
- Keep `flash_attn` off: Polaris has no usable fp16.
- Imports follow `_docs/architecture-overview.md` (app.py wires everything; capture,
  audio_io, whisper_native and priority are independent leaves; nothing imports
  `live_transcriber.py`). `app/tests/test_architecture.py` enforces this.
- Don't edit `whisper.cpp/`, `app/.venv/` or `*.bin` model files (protect hook). Never
  delete `whisper.cpp/`: it's gitignored, 1.3 GB, and git can't restore it.
- The code is hand-formatted (aligned tables): no `ruff format` or auto-formatting. Line
  length is 120.
- Tests that build a Tk window keep it invisible (`-alpha 0`, `-toolwindow`) and rely on
  `--capture=sys`: verify runs after every turn, and visible test windows flicker on the
  user's desktop. Don't launch the real app from the agent without asking.
- New dependency: say why and check that it exists and is maintained. Runtime deps go in
  `app/requirements.txt`, tools in `app/requirements-dev.txt`.

## When compacting

Keep: the list of modified files, the current task and its spec path, and the test
commands with their latest results.
