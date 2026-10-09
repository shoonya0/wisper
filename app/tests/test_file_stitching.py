"""File mode: each word appears once and in order (known issue 1, current-state.md).

A fake model "hears" a word every 0.5 s of the file. The audio samples hold their own
time in seconds, so the fake knows which part of the file it was given. The old code
transcribed 25 s windows that overlap by 1 s and repeated the words in each overlap;
File mode now hands the whole file to whisper.cpp (transcribe_long), which streams
each segment once.
"""

import queue
from types import SimpleNamespace

import numpy as np
import pytest

import app
import audio_io
import whisper_native

SR = audio_io.TARGET_SR


def words_in(audio):
    """Word k is spoken at k * 0.5 s for 0.4 s; return the ones wholly inside audio."""
    start = float(audio[0])
    end = start + len(audio) / SR
    return [f"w{k}" for k in range(int(end / 0.5) + 1) if start <= k * 0.5 and k * 0.5 + 0.4 <= end]


class FakeWhisper:
    def __init__(self, extra_segments=()):
        self.extra_segments = list(extra_segments)
        self.long_calls = 0

    def transcribe(self, audio, language, prompt=""):
        return " ".join(words_in(audio))

    def transcribe_long(self, audio, language, on_text, on_progress=None):
        self.long_calls += 1
        words = words_in(audio)
        for i, word in enumerate(words):
            on_text(f" {word}")
            if on_progress:
                on_progress(100 * (i + 1) // len(words))
        for text in self.extra_segments:
            on_text(text)


def transcribe_file(monkeypatch, seconds, model=None):
    audio = (np.arange(int(seconds * SR)) / SR).astype(np.float32)
    monkeypatch.setattr(audio_io, "decode_to_16k_mono", lambda path: audio)
    worker = SimpleNamespace(results=queue.Queue(), language="en", busy=False)
    # Only results/language/busy are used, so a stand-in avoids building a Tk window.
    app.App._transcribe_file(worker, model or FakeWhisper(), "talk.wav")  # pyright: ignore[reportArgumentType]
    items = []
    while not worker.results.empty():
        items.append(worker.results.get())
    return items


def text_words(items):
    return "".join(payload for kind, payload in items if kind == "text").split()[3:]  # skip "--- talk.wav ---"


@pytest.mark.parametrize("seconds", [10, 49, 60])
def test_each_word_appears_once_and_in_order(monkeypatch, seconds):
    model = FakeWhisper()
    items = transcribe_file(monkeypatch, seconds, model)
    expected = [f"w{k}" for k in range(int(seconds / 0.5)) if k * 0.5 + 0.4 <= seconds]
    assert text_words(items) == expected
    assert model.long_calls == 1
    assert items[-2:] == [("progress", 100), ("done", None)]


def test_junk_segments_are_dropped(monkeypatch):
    items = transcribe_file(monkeypatch, 2, FakeWhisper(extra_segments=[" [Music]", " Thank you.", "  "]))
    assert text_words(items) == ["w0", "w1", "w2", "w3"]


def test_model_error_is_reported(monkeypatch):
    class Broken(FakeWhisper):
        def transcribe_long(self, audio, language, on_text, on_progress=None):
            raise RuntimeError("whisper_full failed (-1)")

    items = transcribe_file(monkeypatch, 2, Broken())
    assert items[-1] == ("error", "File transcription failed: whisper_full failed (-1)")


@pytest.mark.parametrize(("text", "t0", "t1", "dense"), [
    (" And so, my fellow Americans, ask not what your country can do for you,"
     " ask what you can do for your country.", 65.38, 66.00, True),    # measured turbo tail hallucination
    (" And so, my fellow Americans, ask not what your country can do for you,"
     " ask what you can do for your country.", 0.00, 10.38, False),    # the same sentence, real timing
    (" Yes.", 3.00, 3.10, False),                                      # short real word: 0.5 s floor
    (" नमस्ते, आप कैसे हैं?", 0.0, 1.5, False),                          # Hindi at a normal rate
])
def test_is_too_dense(text, t0, t1, dense):
    assert whisper_native.is_too_dense(text, t0, t1) is dense


class FakeLib:
    """Stands in for whisper.dll: whisper_full "decodes" scripted segments and fires the callbacks."""

    def __init__(self, segments):
        self.script = segments          # [(text_bytes, t0_10ms, t1_10ms, no_speech_prob)]
        self.done = []

    def whisper_full(self, ctx, p, samples, n):
        for seg in self.script:
            self.done.append(seg)
            whisper_native.SegmentCallback(p.new_segment_callback)(None, None, 1, None)
            if p.progress_callback:
                percent = 100 * len(self.done) // len(self.script)
                whisper_native.ProgressCallback(p.progress_callback)(None, None, percent, None)
        return 0

    def whisper_full_n_segments(self, ctx):
        return len(self.done)

    def whisper_full_get_segment_text(self, ctx, i):
        return self.done[i][0]

    def whisper_full_get_segment_t0(self, ctx, i):
        return self.done[i][1]

    def whisper_full_get_segment_t1(self, ctx, i):
        return self.done[i][2]

    def whisper_full_get_segment_no_speech_prob(self, ctx, i):
        return self.done[i][3]


def fake_model(segments):
    model = whisper_native.Whisper.__new__(whisper_native.Whisper)  # no DLL, no GPU
    model.ctx = 1
    model._defaults = whisper_native.WhisperFullParams()
    model.lib = FakeLib(segments)  # pyright: ignore[reportAttributeAccessIssue]  (duck-typed CDLL)
    return model


def long_text(segments, on_text=None):
    out, progress = [], []
    fake_model(segments).transcribe_long(np.zeros(16000, np.float32), "en", on_text or out.append, progress.append)
    return "".join(out), progress


def test_transcribe_long_streams_segments_and_drops_silence_and_dense_ones():
    text, progress = long_text([
        (b" price \xe2\x82", 0, 100, 0.0),       # "€" is split across two segments
        (b"\xac 5.", 100, 200, 0.0),
        (b" ghost", 200, 300, 0.9),              # no_speech_prob above 0.6
        (b" " + b"x" * 108, 6538, 6600, 0.0),    # 108 chars in 0.62 s: t0/t1 are 10 ms units
        (b" Bye.", 6600, 6700, 0.0),
    ])
    assert text == " price € 5. Bye."
    assert progress == [20, 40, 60, 80, 100]


def test_transcribe_long_flushes_a_cut_off_character():
    text, _ = long_text([(b" end\xe2\x82", 0, 100, 0.0)])
    assert text == " end�"


def test_transcribe_long_reraises_a_callback_error():
    def on_text(text):
        raise ValueError("queue closed")

    with pytest.raises(ValueError, match="queue closed"):
        long_text([(b" hi", 0, 100, 0.0)], on_text)
