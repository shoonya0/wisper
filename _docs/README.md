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

## Where new docs go

| Kind | Path |
|---|---|
| Feature spec | `_docs/specs/<date>-<feature>.md` |
| Test plan | `_docs/test/<feature>.md` |
| Increment / status notes | `_docs/status/` |
| Decision record | `_docs/adr/NNNN-<title>.md` |
| Screenshots and other evidence | `_docs/evidence/` |
