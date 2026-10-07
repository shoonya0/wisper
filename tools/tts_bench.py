"""Kokoro-82M on this PC: load time, first-sentence latency, real-time factor (CPU only).

Spike N0 of _docs/specs/2026-10-07-kokoro-narration.md. Not part of the app; numbers go
into _docs/performance.md.

    app\\.venv\\Scripts\\python.exe tools/tts_bench.py                      # fp32 + int8, 2/4/6 threads
    app\\.venv\\Scripts\\python.exe tools/tts_bench.py --variants int8 --threads 4
    app\\.venv\\Scripts\\python.exe tools/tts_bench.py --variants fp32 --threads 4 --no-bench --first-chunks
    app\\.venv\\Scripts\\python.exe tools/tts_bench.py --variants fp32 --threads 4 --no-bench --samples OUT_DIR

--first-chunks and --samples use the first variant and thread count given. Add --offline
to any of these to block Python networking first (proves nothing is downloaded at runtime).

RTF = synthesis time / audio duration (lower is faster; 0.5 = twice real time). Every
timing is a full Kokoro.create() call: phonemizing, model run(s) and silence trimming.
"""

import argparse
import socket
import statistics
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as rt
from kokoro_onnx import Kokoro

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "kokoro"
VARIANTS = {
    "fp32": "kokoro-v1.0.onnx",
    "int8": "kokoro-v1.0.int8.onnx",
}
VOICES = MODEL_DIR / "voices-v1.0.bin"
VOICE = "af_heart"

# 16 words: the "first sentence" of a typical narration. --first-chunks times its prefixes.
FIRST ="Hi everyone, thanks for joining the call today, let me quickly walk you through the plan."
FIRST_PREFIXES = [
    "Hi everyone,",
    "Hi everyone, thanks for joining,",
    "Hi everyone, thanks for joining the call today,",
    FIRST,
]

# Mixed lengths (3 to 40 words), like real narration text split into sentences.
SENTENCES = [
    "Okay, sounds good.",
    "I can hear you clearly now.",
    "The build finished without errors, and all twenty six tests passed on the first try.",
    "Could you share your screen for a moment?",
    "We measured the large model at about six times real time on the graphics card.",
    "Let me read the summary out loud so everyone is on the same page before we decide.",
    "Thanks!",
    "The next step is to split the window into two halves, with speech to text on the left "
    "and text to speech on the right, and to keep both of them working at the same time.",
    "Does anyone have questions about the timeline or the budget?",
    "I'll send the notes after the meeting.",
]

# One voice per language Kokoro v1.0 supports through espeak-ng (ja/zh need misaki: out of scope).
LANG_SAMPLES = [
    ("af_heart",  "en-us", "Hello, this is the American English voice."),
    ("bf_emma",   "en-gb", "Hello, this is the British English voice."),
    ("ef_dora",   "es",    "Hola, esta es la voz en español."),
    ("ff_siwis",  "fr-fr", "Bonjour, ceci est la voix française."),
    ("hf_alpha",  "hi",    "नमस्ते, यह हिंदी आवाज़ है।"),
    ("if_sara",   "it",    "Ciao, questa è la voce italiana."),
    ("pf_dora",   "pt-br", "Olá, esta é a voz em português."),
]


def load(variant, threads):
    opts = rt.SessionOptions()
    opts.intra_op_num_threads = threads
    t0 = time.perf_counter()
    session = rt.InferenceSession(str(MODEL_DIR / VARIANTS[variant]), opts, providers=["CPUExecutionProvider"])
    kokoro = Kokoro.from_session(session, str(VOICES))
    return kokoro, time.perf_counter() - t0


def synth(kokoro, text, voice=VOICE, lang="en-us"):
    t0 = time.perf_counter()
    samples, sr = kokoro.create(text, voice=voice, speed=1.0, lang=lang)
    return samples, sr, time.perf_counter() - t0


def p95(values):
    """Nearest-rank 95th percentile (with 5 or 10 samples this is the maximum)."""
    return sorted(values)[max(0, round(0.95 * len(values)) - 1)]


def bench(variant, threads, runs):
    kokoro, load_s = load(variant, threads)
    _, _, warm_s = synth(kokoro, FIRST)  # first call pays espeak + graph warm-up

    first = [synth(kokoro, FIRST)[2] for _ in range(runs)]

    rtfs, audio_total, synth_total = [], 0.0, 0.0
    for text in SENTENCES:
        samples, sr, secs = synth(kokoro, text)
        dur = len(samples) / sr
        rtfs.append(secs / dur)
        audio_total += dur
        synth_total += secs

    return {
        "variant": variant, "threads": threads, "load": load_s, "warm": warm_s,
        "first_p50": statistics.median(first), "first_p95": p95(first),
        "rtf_p50": statistics.median(rtfs), "rtf_p95": p95(rtfs),
        "rtf_total": synth_total / audio_total, "audio_s": audio_total,
    }


def first_chunks(variant, threads, runs):
    """Synthesis time of growing prefixes of FIRST, after a warm-up call."""
    kokoro, _ = load(variant, threads)
    synth(kokoro, FIRST)
    print("\n| first chunk | words | audio s | synth p50 s | synth max s |\n|---|---|---|---|---|")
    for text in FIRST_PREFIXES:
        times, dur = [], 0.0
        for _ in range(runs):
            samples, sr, secs = synth(kokoro, text)
            times.append(secs)
            dur = len(samples) / sr
        print(f"| {text} | {len(text.split())} | {dur:.2f} "
              f"| {statistics.median(times):.2f} | {max(times):.2f} |", flush=True)


def block_network():
    def blocked(*_args, **_kwargs):
        raise OSError("network blocked by tts_bench.py --offline")
    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    socket.getaddrinfo = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]


def write_wav(path, samples, sr):
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def languages(out_dir, variant, threads):
    kokoro, _ = load(variant, threads)
    voices = kokoro.get_voices()
    print(f"\n{len(voices)} voices: {', '.join(voices)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print("\n| voice | lang | audio s | synth s | peak | file |\n|---|---|---|---|---|---|")
    for voice, lang, text in LANG_SAMPLES:
        if voice not in voices:
            print(f"| {voice} | {lang} | — | — | — | voice missing |")
            continue
        samples, sr, secs = synth(kokoro, text, voice, lang)
        path = out_dir / f"{lang}-{voice}.wav"
        write_wav(path, samples, sr)
        peak = np.abs(samples).max()
        print(f"| {voice} | {lang} | {len(samples) / sr:.2f} | {secs:.2f} | {peak:.2f} | {path.name} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", default="fp32,int8")
    ap.add_argument("--threads", default="2,4,6")
    ap.add_argument("--runs", type=int, default=5, help="repeats of each first-sentence / first-chunk timing")
    ap.add_argument("--first-chunks", action="store_true", help="time 2/5/8/16-word prefixes of a sentence")
    ap.add_argument("--samples", type=Path, help="write one WAV per language into this folder")
    ap.add_argument("--no-bench", action="store_true", help="skip the variant x threads timing table")
    ap.add_argument("--offline", action="store_true", help="block Python networking before loading anything")
    args = ap.parse_args()
    if args.runs < 1:
        ap.error("--runs must be at least 1")
    if args.offline:
        block_network()
    variant0, threads0 = args.variants.split(",")[0], int(args.threads.split(",")[0])

    print(f"onnxruntime {rt.__version__}, providers used: CPUExecutionProvider"
          f"{', Python networking blocked' if args.offline else ''}")
    if not args.no_bench:
        print("\n| variant | threads | load s | warm-up s | first p50 s | first p95 s "
              "| RTF p50 | RTF p95 | RTF total |\n|---|---|---|---|---|---|---|---|---|")
        for variant in args.variants.split(","):
            for threads in (int(t) for t in args.threads.split(",")):
                r = bench(variant, threads, args.runs)
                print(f"| {r['variant']} | {r['threads']} | {r['load']:.2f} | {r['warm']:.2f} "
                      f"| {r['first_p50']:.2f} | {r['first_p95']:.2f} "
                      f"| {r['rtf_p50']:.2f} | {r['rtf_p95']:.2f} | {r['rtf_total']:.2f} |", flush=True)

    if args.first_chunks:
        first_chunks(variant0, threads0, args.runs)
    if args.samples:
        languages(args.samples, variant0, threads0)


if __name__ == "__main__":
    main()
