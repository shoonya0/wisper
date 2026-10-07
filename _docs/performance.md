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
- File mode streams 25 s windows so text appears progressively.

For profiling or optimization work, use the project skill
`.claude/skills/optimized-app-research/` (measure first, optimize what matters).
