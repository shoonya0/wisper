# Wisper: performance and why this stack

Moved from the original root README. Numbers are **as recorded by the author**; not
re-run during the harness setup (ASSUMED until re-measured).

## Why whisper.cpp + Vulkan

The RX 580 is a Polaris card (gfx803) and **ROCm dropped it**. The CUDA-equivalent AMD
paths (PyTorch-ROCm, CTranslate2 / faster-whisper on GPU, NVIDIA NeMo/Parakeet)
therefore **can't use this GPU** and fall back to the CPU. The only real GPU-compute path
for Polaris is **Vulkan**, and **whisper.cpp** is the only actively maintained engine
that both uses the GPU via Vulkan *and* runs the top-accuracy models.

Widely cited posts claim Windows AMD Vulkan is ~13× slower than Linux and would be
sub-real-time. **Measured on this card, that's false**: recent whisper.cpp Vulkan work
closed the gap.

## Measured on this RX 580 (11 s JFK sample, model resident, greedy)

| Model | Inference | Real-time factor | Use |
|---|---|---|---|
| `base.en-q5_1` | ~0.7 s | ~11× | absolute lowest latency (English) |
| `small.en-q5_1` | ~1.4 s | ~7.6× | **default for dictation** (English) |
| `large-v3-turbo-q5_0` | ~1.7 s | ~6.3× | **default for accuracy** (multilingual) |

All three run comfortably faster than real-time, so there's no need to trade accuracy
for latency. `flash_attn` stays **off** because Polaris has no usable fp16.

> Note: an earlier measurement recorded large-v3-turbo at **~4.6× real-time**. The
> difference is probably the sample or settings. Re-measure with `whisper-bench.exe` /
> `whisper-cli.exe` before relying on either number (open decision in
> `current-state.md`).

## Latency levers already in the code

- Model loaded once and kept GPU-resident, with a warm-up pass after each load.
- Energy (RMS) gate: no ML VAD, so it adds no latency (`capture.py`).
- Per-mode segmentation profiles: Dictation cuts after a 0.4 s pause (1–8 s chunks);
  Captions after 0.6 s (2–12 s chunks).
- `priority.py`: HIGH process priority, highest worker-thread priority, HIGH GPU
  scheduling class, EcoQoS throttling off. This keeps the token-by-token decode from
  stalling the GPU.
- File mode runs one long-form `whisper_full` pass and streams each segment through a
  callback, so text appears progressively. 66 s file (jfk.wav ×6), full File-mode path:
  base.en 4.5 s (~15× RT), small.en 8.2 s (~8×), large-v3-turbo 7.0 s (~9.4×) (2026-10-09).

For profiling or optimization work, use the project skill
`.claude/skills/optimized-app-research/` (measure first, optimize what matters).

## Kokoro-82M text to speech on the CPU (narration spike N0, 2026-10-07)

Measured, **VERIFIED**. Kokoro runs on the **CPU only**, because the GPU is reserved for
Whisper (user decision, [ADR 0001](./adr/0001-tts-engine-kokoro-onnx.md)). Machine:
Intel i5-10400F (6 cores / 12 threads), 16 GB RAM, Windows 11, power plan "performance".
`kokoro-onnx` 0.6.1, onnxruntime 1.30.0, `CPUExecutionProvider`, voice `af_heart`,
speed 1.0. Every timing is a full `Kokoro.create()` call (phonemize + model + trim)
unless a table says otherwise. RTF = synthesis time ÷ audio length (lower is faster).

**Reproduce:** `app\.venv\Scripts\python.exe tools/tts_bench.py --variants fp32 --threads 4 --runs 10 --first-chunks --offline`
(about 2 minutes). Close other CPU-heavy work first, because contention changes the
numbers a lot (see the last table).

### Model variant: fp32, not int8

| Variant (`models/kokoro/`) | Size | Command | First sentence (16 words) | RTF total |
|---|---|---|---|---|
| `kokoro-v1.0.onnx` (fp32) | 325 MB | `--variants fp32 --threads 4` | 1.80 s | **0.36–0.40** |
| `kokoro-v1.0.int8.onnx` | 114 MB | `--variants int8 --threads 4 --runs 3` | 20.77 s | 4.54 (**~10× slower**) |

A raw `session.run` on the same 16-word sentence (no phonemize or trim, 6 threads,
scratch profiling) took 1.86–2.14 s for fp32 and 18.1–18.9 s for int8, so the int8
slowdown is in the model itself, not in the Python around it. int8 is **slower than real
time** on this CPU, so it's unusable. **Use fp32.**

### fp32 by thread count (`--variants fp32 --threads 2,4,6 --runs 5`; 10 sentences, 61 s of audio)

| Threads | Load | Warm-up (first call) | First sentence (16 words) p50 / max | RTF p50 / max | RTF total |
|---|---|---|---|---|---|
| 2 | 1.44 s | 2.82 s | 2.69 / 2.81 s | 0.58 / 0.82 | 0.57 |
| **4** | 1.52 s | 2.29 s | 2.30 / 3.67 s | 0.42 / 0.59 | **0.42** |
| 6 | 1.43 s | 1.95 s | 2.03 / 2.13 s | 0.43 / 0.58 | 0.41 |

**Choice: 4 intra-op threads.** It's as fast as 6 and leaves 2 cores for the UI, capture
and the Whisper worker. This sweep is slower than the idle runs below (its 4-thread row
gives 2.30 s vs 1.80 s for the first sentence), probably because of background CPU load
at the time. That wasn't checked, so compare its rows with each other, not with the idle
runs.

### fp32 with 4 threads on an idle CPU (two runs of the reproduce command, `--runs 10`)

| Run | Load | Warm-up | First sentence (16 words) p50 / max | RTF p50 / max | RTF total |
|---|---|---|---|---|---|
| 1 | 1.30 s | 1.97 s | 1.80 / 1.98 s | 0.37 / 0.48 | 0.36 |
| 2 | 1.47 s | 2.08 s | 1.80 / 2.36 s | 0.40 / 0.68 | 0.40 |

### First sound: cap the first chunk at 6 words (`--first-chunks`, same two idle runs)

Synthesis time grows with text length, and the first sound waits for the whole first
chunk.

| First chunk | Words | Audio | Synthesis p50 (run 1 / run 2) | Max (run 1 / run 2) |
|---|---|---|---|---|
| "Hi everyone," | 2 | 1.15 s | 0.47 / 0.49 s | 0.54 / 0.71 s |
| "Hi everyone, thanks for joining," | 5 | 2.07 s | **0.84 / 0.73 s** | 0.91 / 0.85 s |
| "… the call today," | 8 | 2.79 s | 1.02 / 1.27 s | 1.22 / 1.71 s |
| "… let me quickly walk you through the plan." | 16 | 5.07 s | 1.79 / 1.85 s | 2.16 / 2.18 s |

→ The narrator caps the **first** chunk at 6 words (spec §5.2). A 5-word chunk meets the
≤ 1.0 s p50 / ≤ 1.5 s p95 first-sound target. 8 words already misses it in run 2. Later
chunks don't need the cap: at RTF ≤ 0.42 the next chunk is ready before the current one
finishes playing.

**Contention matters:** one `--first-chunks --runs 10` run happened while a background
8-process indexing job (`code-review-graph build`) was running. There the 5-word chunk
took **1.33 s** p50 (max 1.61 s) and the 8-word chunk 1.89 s. In the app, Kokoro will
share the CPU with capture, the UI and the Whisper worker, so N5 must measure first
sound with Dictation running.

### Languages (`--no-bench --samples DIR --offline`, fp32 with 4 threads)

All 54 voices are in `voices-v1.0.bin`. One sample per espeak-ng language, written to
`models/kokoro/samples/` (gitignored):

| Voice | Lang | Audio | Synthesis | Peak |
|---|---|---|---|---|
| af_heart | en-us | 2.70 s | 1.14 s (first call) | 0.38 |
| bf_emma | en-gb | 2.51 s | 1.26 s | 0.44 |
| ef_dora | es | 2.26 s | 0.90 s | 0.33 |
| ff_siwis | fr-fr | 2.14 s | 0.94 s | 0.56 |
| hf_alpha | hi | 2.29 s | 1.17 s | 0.69 |
| if_sara | it | 2.20 s | 0.96 s | 0.79 |
| pf_dora | pt-br | 2.20 s | 0.83 s | 0.34 |

Non-silent audio only shows that synthesis ran, not that the speech is intelligible.
**Intelligibility (user listened, 2026-10-09): all 7 acceptable; `af_heart` (en-us) is
the best, so it stays the default voice.** **Offline:** every run
above with `--offline` had all Python socket calls blocked, and espeak-ng loads from the
venv (`espeakng_loader\espeak-ng.dll`).

### Narration pipeline (N5, 2026-10-09)

Real Kokoro (fp32, 4 threads) + `Narrator` + `Player`, output to a **silent fake stream**
that records when blocks arrive (nothing played). Text: the 16-word first sentence
above plus two more. 5 runs, idle CPU.

| Metric | Result | Target |
|---|---|---|
| Load + warm-up ("Ready.") at app start | 1.42–1.59 s + 0.52–0.54 s, in the background | ≤ 5 s |
| Speak → first audio block (first piece "Hi everyone,") | 0.45–0.49 s, median 0.48 s | ≤ 1.0 s p50 |
| Stop → last block finished | 12–34 ms | ≤ 200 ms |
| Stop → worker free again (`speak()` returns) | 0.45–0.53 s: the piece being synthesized finishes, then is dropped | — (bounded by `MAX_CHARS`) |
| Real `PaStream` on the speakers (N4, silence) | `play()` returns 34 ms after `stop()` | — |

The device's own output buffer comes on top of "first block" and "last block" (not
measured; WASAPI shared mode is typically 10–30 ms). Not measured yet: Kokoro and
Whisper dictation at the same time (T-TTS-5, manual).

### VB-Audio Virtual Cable round trip (2026-10-10)

A 150 ms 1 kHz beep played with `playback.Player` + `PaStream` into
`CABLE Input (VB-Audio Virtual Cable)` (WASAPI, 48 kHz, 2 ch) while a 5 ms-buffer
WASAPI recorder listens on `CABLE Output`. Silent for the user (nothing on the speakers).

| Run | Beeps received | `play()` call → beep in the recording |
|---|---|---|
| 5 beeps, 0.6 s apart | 5/5 | 0.123 / 0.183 / 0.183 / 0.183 / 0.183 s (median 0.183 s) |

Approximate: it includes Wisper's output buffer, the cable and the recorder's input
buffer, measured against the samples recorded when `play()` was called. This is larger
than the 10–50 ms first guessed. ASSUMED cause: VB-Cable's default internal buffer
("Max Latency" in its control panel); lowering it is a lever for the latency increment,
to be measured. The call app's own buffering and the network come on top.

### Mic pass-through (N8, 2026-10-10)

Two WASAPI shared-mode streams on `CABLE Input` at once (440 Hz + 1 kHz, 0.2 each):
`CABLE Output` carries both (peak 0.40 = the sum). Windows mixes them, so the mic goes in
on its own stream and the narration `Player` is unchanged.

Real `playback.Passthrough` (`PaInput` → `PaStream`, 10 ms blocks) from
`Microphone (4- High Definition Audio Device)` (WASAPI, 48 kHz) into `CABLE Input`,
20 s, while the mic and `CABLE Output` are recorded at the same time (5 ms buffers).
Delay = cross-correlation of the two recordings (room noise), in 3 s windows. Silent
for the user; nothing saved.

| Window | 1–4 s | 4–7 s | 7–10 s | 10–13 s | 13–16 s | 16–19 s | 19–22 s |
|---|---|---|---|---|---|---|---|
| mic → `CABLE Output` delay | 129 ms | 125 ms | 125 ms | 133 ms | 138 ms* | 127 ms | 130 ms |
| correlation | 0.93 | 0.94 | 0.64 | 0.22 | 0.02 | 0.63 | 0.35 |

\* correlation too low to trust. **≈ 125–130 ms, no drift over 20 s.** That's Wisper
(reported: mic stream 22 ms, cable stream 22 ms, one 10 ms block) plus VB-Cable's
buffer. The call app and the network come on top. PortAudio reports the same 22 ms with
5 ms blocks, so a smaller block wouldn't help; VB-Cable's "Max Latency" is the lever.

A first run picked `Microsoft Sound Mapper - Input` (MME, from `capture.list_sources`)
and the delay went from 16 ms to 266 ms within 8 s. So the pass-through lists WASAPI
mics only (`playback.list_inputs`). Not measured: a run of 10 minutes or more.
