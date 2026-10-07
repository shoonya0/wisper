# Wisper — local speech-to-text for the AMD RX 580

Fast, fully-offline speech-to-text on an **AMD Radeon RX 580** (Polaris / gfx803),
running **whisper.cpp with the Vulkan backend** on Windows. Three modes:

- **Dictation** — transcribe your microphone as you speak (low latency).
- **Live captions** — transcribe desktop / meeting audio (WASAPI loopback).
- **File** — transcribe an audio file, text appearing progressively.

## Why this stack (the short version)

The RX 580 is a Polaris card, and **ROCm dropped it** — so the CUDA-equivalent AMD
path (PyTorch-ROCm, CTranslate2 / *faster-whisper* on GPU, NVIDIA NeMo/Parakeet)
**cannot use this GPU**; those fall back to CPU. The only real GPU-compute path for
Polaris in 2025 is **Vulkan**, and **whisper.cpp** is the only actively-maintained
engine that both uses the GPU via Vulkan *and* runs the top-accuracy models.

Widely-cited posts claim Windows AMD Vulkan is ~13× slower than Linux and would be
sub-real-time. **Measured on this card, that's false** — recent whisper.cpp Vulkan
work closed the gap.

### Measured on this RX 580 (11 s JFK sample, model resident, greedy)

| Model | Inference | Real-time factor | Use |
|---|---|---|---|
| `base.en-q5_1`   | ~0.7 s | ~11× | absolute lowest latency (English) |
| `small.en-q5_1`  | ~1.4 s | ~7.6× | **default for dictation** (English) |
| `large-v3-turbo-q5_0` | ~1.7 s | ~6.3× | **default for accuracy** (multilingual) |

All three run comfortably faster than real-time, so there's no need to sacrifice
accuracy for latency. `flash_attn` is kept **off** — Polaris has no usable fp16.

## Layout

```
whisper.cpp/                  cloned + built with -DGGML_VULKAN=1 (Vulkan backend)
  build/bin/Release/          whisper.dll, ggml-vulkan.dll, whisper-cli.exe, ...
  models/                     ggml-{base.en,small.en}-q5_1.bin, ggml-large-v3-turbo-q5_0.bin
app/
  whisper_native.py           ctypes binding to whisper.dll (loads model once, GPU-resident)
  capture.py                  mic + loopback capture, energy-based speech segmentation
  audio_io.py                 decode audio files to 16 kHz mono via miniaudio (no ffmpeg)
  app.py                      the 3-mode Tkinter app
  run.bat                     launches the app with the project venv
```

## Run

```bat
app\run.bat
```

Or from a shell:

```bat
cd app
.venv\Scripts\python.exe app.py
```

Pick a **Mode**, choose a **Model** (fastest ↔ most accurate), select the mic /
loopback device (or a file), and press **Start**. `Save…` / `Copy all` export the
transcript.

## Architecture notes

- The model is loaded **once** and kept in GPU memory by a single worker thread.
  Whisper contexts aren't thread-safe, so only that thread runs inference; the UI
  and audio-capture threads talk to it through queues.
- Live modes use an **energy (RMS) gate** to cut chunks at pauses — no ML VAD
  dependency, no added latency. A hallucination filter drops Whisper's
  common noise inventions ("thank you", "[music]", …).
- File mode decodes with miniaudio and transcribes in **overlapping windows** so
  text streams out as it goes (perceived-speed win) instead of blocking to the end.

## Possible next steps

- Swap the RMS gate for **Silero VAD** to cut false triggers on noisy input.
- **Global hotkey + type-into-focused-window** for system-wide dictation.
- Word-level timestamps / **SRT export** for the File mode.
- A second resident model so Dictation and Captions can run different models
  without a reload.

## Rebuilding whisper.cpp (if needed)

Requires the Vulkan SDK (for `glslc`) and CMake:

```bat
cd whisper.cpp
cmake -B build -DGGML_VULKAN=1
cmake --build build --config Release -j
```
