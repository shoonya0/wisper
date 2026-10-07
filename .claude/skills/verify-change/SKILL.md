---
name: verify-change
description: Run Wisper's verification ladder (ruff, pyright, pytest, and when relevant a GPU engine smoke test and a manual app check) and report evidence in a fixed format. Use before claiming any change is done, after implementing a plan step, or when the user asks "does it work?".
---

# Verify change

Prove the current change works. Report **evidence, not claims**.

## 1. Scope

- `git status` and `git diff --stat`: what changed?
- Choose the rungs needed. Rung 1 always runs. Add the others when the change
  touches them:

| Rung | Command | Run when |
|---|---|---|
| 1 Fast | `node tools/verify.mjs` (ruff check + pyright + pytest incl. architecture test) | Always |
| 2 Engine smoke | `whisper.cpp\build\bin\Release\whisper-cli.exe -m whisper.cpp\models\ggml-base.en-q5_1.bin -f whisper.cpp\samples\jfk.wav -nt` | `whisper_native.py`, model paths, or the whisper.cpp build changed |
| 3 Binding smoke | `app\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'app'); import audio_io, whisper_native as w; m=w.Whisper('whisper.cpp/build/bin/Release','whisper.cpp/models/ggml-base.en-q5_1.bin'); print(m.transcribe(audio_io.decode_to_16k_mono('whisper.cpp/samples/jfk.wav'),'en'))"` | `whisper_native.py` changed (struct layouts!) |
| 4 App (manual) | `cd app` then `.venv\Scripts\python.exe app.py` (console shows tracebacks; `run.bat` hides them) | Any UI, capture, or worker-loop change |

Rungs 2–4 use the GPU and audio devices. Ask before the first run in a session.

## 2. Run

- Run each chosen rung. On failure, find the **root cause** and fix it, then rerun
  from rung 1.
- Never delete, skip or weaken a test to get green. If a test is wrong, stop and
  explain why.
- Compare failures against the **baseline** in `_docs/current-state.md` by test name.
  A pre-existing failure is reported as such, with evidence. It is never silently
  ignored.

## 3. App check (rung 4): manual

The agent has no access to the Tkinter UI, so **UI verification is manual**. Start the
app only if the user agrees, then list the exact steps for the user to check (mode,
model, device, expected result). Put them under "Requires physical verification".
Microphone and loopback behavior always need a human check.

## 4. Report (exact format)

```markdown
### Verification
| Rung | Command | Result | Notes |
|---|---|---|---|
| Fast | `node tools/verify.mjs` | ✅ pass (6 s) | 25/25 pytest, ruff 0, pyright 0 |
| Engine smoke | whisper-cli jfk.wav | ✅ | "And so my fellow Americans…" |

- New failures vs baseline @<sha>: none
- Not verified: <list, or "nothing">
- Requires physical verification on Windows / RX 580: <list, or "nothing">
```

If any rung fails and can't be fixed in scope, stop and report it. Don't claim done.
