# Wisper docs

All project docs live here (`_docs/`). The project is small (one Python app), so there
are no per-area `_docs/` folders. `whisper.cpp/` is upstream code and isn't documented here.

## Read in this order

| # | Doc | What it answers |
|---|---|---|
| 1 | [current-state.md](./current-state.md) | What works, how to run/build/test, test baseline, known issues, next task |
| 2 | [architecture-overview.md](./architecture-overview.md) | Modules, threads, main flows, allowed imports |
| 3 | [performance.md](./performance.md) | Why whisper.cpp + Vulkan on the RX 580, measured speeds, latency levers |
| — | [ai-harness-setup.md](./ai-harness-setup.md) | Record of the AI-harness setup (tools, decisions, evidence) |

## Active work

| Feature | Spec | Test plan | Decisions |
|---|---|---|---|
| Narration (Kokoro-82M TTS) | [specs/2026-10-07-kokoro-narration.md](./specs/2026-10-07-kokoro-narration.md); N8 mic pass-through: [specs/2026-10-10-mic-passthrough.md](./specs/2026-10-10-mic-passthrough.md); N9 pause and resume: [specs/2026-10-11-narration-pause.md](./specs/2026-10-11-narration-pause.md); N10 narrated marks: [specs/2026-10-11-narration-highlight.md](./specs/2026-10-11-narration-highlight.md) | [test/kokoro-narration.md](./test/kokoro-narration.md) | [adr/0001-tts-engine-kokoro-onnx.md](./adr/0001-tts-engine-kokoro-onnx.md) |
| DeepSeek terminal (speech → `deepseek` CLI in the STT pane → narration) | [specs/2026-10-12-deepseek-terminal.md](./specs/2026-10-12-deepseek-terminal.md) | `test/deepseek-terminal.md` (written in P6) | in the spec, §2 |

## Where new docs go

| Kind | Path |
|---|---|
| Feature spec | `_docs/specs/<date>-<feature>.md` |
| Test plan | `_docs/test/<feature>.md` |
| Increment / status notes | `_docs/status/` |
| Decision record | `_docs/adr/NNNN-<title>.md` |
| Screenshots and other evidence | `_docs/evidence/` |
