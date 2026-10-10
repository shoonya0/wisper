# Wisper: local speech-to-text for the AMD RX 580

Fast, fully offline speech-to-text on an **AMD Radeon RX 580**, running
**whisper.cpp with the Vulkan backend** on Windows. There are three modes:

- **Dictation**: transcribes your microphone as you speak.
- **Live captions**: transcribes desktop or meeting audio (WASAPI loopback).
- **File**: transcribes an audio file, and the text appears as it goes.

It also speaks: the right-hand pane reads typed or pasted text aloud with **Kokoro-82M**
(offline, on the CPU), to yourself, into a call (Meet, Zoom, Discord) through a virtual
cable, or both. With "Send my mic to the call", the call hears your voice and the
narration together. Ctrl+Enter speaks or stops. Setup: `_docs/current-state.md`.

## Run

```bat
app\run.bat
```

Pick a **Mode** and a **Model** (fastest ↔ most accurate), select a device or file, and
press **Start**.

The app needs a Vulkan build of whisper.cpp in `whisper.cpp/` (gitignored). See
[_docs/current-state.md](./_docs/current-state.md#how-to-build-run-test) for setup and
the rebuild steps.

## Docs

Everything else is in **[`_docs/`](./_docs/README.md)**: architecture, current state and
known issues, and benchmarks with the reasons for this stack.
