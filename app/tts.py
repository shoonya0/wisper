"""Kokoro-82M text to speech on the CPU (kokoro-onnx), plus sentence splitting for narration.

Narration spec _docs/specs/2026-10-07-kokoro-narration.md §5.1, §5.2. A leaf module: it
imports no other project module. Only the TTS worker thread in app.py may call into an
Engine (one ONNX session, not shared across threads); split_sentences and lang_for_voice
are pure.
"""

import re
from pathlib import Path

import numpy as np

MODEL_DIR   = Path(__file__).resolve().parent.parent / "models" / "kokoro"
MODEL_FILE  = "kokoro-v1.0.onnx"     # fp32: int8 is ~10x slower on this CPU (N0)
VOICES_FILE = "voices-v1.0.bin"
SAMPLE_RATE = 24000
THREADS     = 4                       # N0: as fast as 6, and leaves 2 cores for UI + STT
DEFAULT_VOICE = "af_heart"
MISSING_MESSAGE = "Kokoro model not found: see _docs/current-state.md (Narration setup)"

# First letter of a Kokoro voice name -> espeak-ng language. Japanese (j) and Chinese (z)
# need misaki instead of espeak-ng: out of scope (spec §2).
LANG_BY_PREFIX = {
    "a": "en-us",
    "b": "en-gb",
    "e": "es",
    "f": "fr-fr",
    "h": "hi",
    "i": "it",
    "p": "pt-br",
}

MAX_CHARS         = 120   # ~7 s of audio, ~3 s of synthesis at RTF 0.4 (spec §5.2)
FIRST_CHUNK_WORDS = 6     # N0: a 5-word first chunk is ready in 0.73-0.84 s, 16 words in 1.8 s

SENTENCE_END = ".!?…।"
CLAUSE_END   = ",;:"
CLOSERS      = "\"'”’)]»"
OPENERS      = "\"'“‘([«"
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "e.g.", "i.e.", "etc.", "vs."}


def lang_for_voice(voice):
    lang = LANG_BY_PREFIX.get(voice[:1])
    if lang is None:
        raise ValueError(f"Unsupported Kokoro voice {voice!r}: its language prefix isn't one of "
                         f"{', '.join(sorted(LANG_BY_PREFIX))}")
    return lang


# ------------------------------------------------------------------ splitting

def _ends_sentence(word):
    core = word.rstrip(CLOSERS)
    if not core or core[-1] not in SENTENCE_END:
        return False
    return core.lstrip(OPENERS).lower() not in ABBREVIATIONS


def _length(words):
    return len(" ".join(words))


def _fit(words):
    """Cut a piece longer than MAX_CHARS: at the last , ; : that fits, else at the last space."""
    pieces = []
    while _length(words) > MAX_CHARS and len(words) > 1:
        fits = 1                     # most words that fit (at least 1: a word is never cut)
        while _length(words[:fits + 1]) <= MAX_CHARS:
            fits += 1
        clause = [k for k in range(1, fits + 1) if words[k - 1].rstrip(CLOSERS).endswith(tuple(CLAUSE_END))]
        cut = clause[-1] if clause else fits
        pieces.append(words[:cut])
        words = words[cut:]
    pieces.append(words)
    return pieces


def _shorten_first(words):
    """The first piece is at most FIRST_CHUNK_WORDS words: cut at an early , ; : or at the cap."""
    if len(words) <= FIRST_CHUNK_WORDS:
        return [words]
    clause = [k for k in range(1, FIRST_CHUNK_WORDS + 1)
              if words[k - 1].rstrip(CLOSERS).endswith(tuple(CLAUSE_END))]
    cut = clause[0] if clause else FIRST_CHUNK_WORDS
    return [words[:cut], words[cut:]]


def split_sentences(text):
    """Split narration text into short pieces to synthesize one at a time (spec §5.2).

    Joining the pieces with spaces gives back the original words in the original order.
    """
    sentences = []
    for paragraph in re.split(r"\n\s*\n", text):
        current = []
        for word in paragraph.split():
            current.append(word)
            if _ends_sentence(word):
                sentences.append(current)
                current = []
        if current:
            sentences.append(current)

    pieces = [p for s in sentences for p in _fit(s)]
    if pieces:
        pieces[:1] = _shorten_first(pieces[0])
    return [" ".join(p) for p in pieces if p]


# ------------------------------------------------------------------ engine

def missing_files(model_dir=MODEL_DIR):
    return [name for name in (MODEL_FILE, VOICES_FILE) if not (Path(model_dir) / name).is_file()]


class Engine:
    """One Kokoro ONNX session on the CPU. Not thread safe: only the TTS worker uses it."""

    def __init__(self, kokoro):
        self._kokoro = kokoro

    def voices(self):
        """Voices whose language this app supports, sorted (US English first, as Kokoro lists them)."""
        return sorted(v for v in self._kokoro.get_voices() if v[:1] in LANG_BY_PREFIX)

    def synthesize(self, text, voice=DEFAULT_VOICE, speed=1.0):
        """Speak one piece of text. Returns mono float32 samples at SAMPLE_RATE."""
        samples, rate = self._kokoro.create(text, voice=voice, speed=speed, lang=lang_for_voice(voice))
        if rate != SAMPLE_RATE:
            raise RuntimeError(f"Kokoro returned {rate} Hz audio, expected {SAMPLE_RATE} Hz")
        return np.asarray(samples, dtype=np.float32).reshape(-1)


def load(model_dir=MODEL_DIR, threads=THREADS):
    """Load Kokoro (~1.5 s). Raises FileNotFoundError(MISSING_MESSAGE) when the model files are absent."""
    model_dir = Path(model_dir)
    if missing_files(model_dir):
        raise FileNotFoundError(MISSING_MESSAGE)
    # Imported here so the pure helpers above don't pull in onnxruntime.
    import onnxruntime as rt
    from kokoro_onnx import Kokoro

    opts = rt.SessionOptions()
    opts.intra_op_num_threads = threads
    session = rt.InferenceSession(str(model_dir / MODEL_FILE), opts, providers=["CPUExecutionProvider"])
    return Engine(Kokoro.from_session(session, str(model_dir / VOICES_FILE)))
