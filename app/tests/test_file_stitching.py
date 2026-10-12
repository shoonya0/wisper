"""File mode: each word appears once and in order (known issue 1, current-state.md).

A fake model "hears" a word every 0.5 s of the file. The audio samples hold their own
time in seconds, so the fake knows which part of the file it was given. The old code
transcribed 25 s windows that overlap by 1 s and repeated the words in each overlap;
File mode now hands the whole file to whisper.cpp (transcribe_long), which streams
each segment once.

File mode types at most 100 words, then stops the file (D8, spec 2026-10-12-deepseek-terminal).
"""

import queue
import threading
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
        self.said = 0                   # words handed to on_text before should_stop() said stop

    def transcribe(self, audio, language, prompt=""):
        return " ".join(words_in(audio))

    def transcribe_long(self, audio, language, on_text, on_progress=None, should_stop=None):
        self.long_calls += 1
        words = words_in(audio)
        for i, word in enumerate(words):
            if should_stop and should_stop():
                return                  # whisper.cpp's abort callback: the run ends early
            self.said += 1
            on_text(f" {word}")
            if on_progress:
                on_progress(100 * (i + 1) // len(words))
        for text in self.extra_segments:
            on_text(text)


def transcribe_file(monkeypatch, seconds, model=None, worker=None):
    audio = (np.arange(int(seconds * SR)) / SR).astype(np.float32)
    monkeypatch.setattr(audio_io, "decode_to_16k_mono", lambda path: audio)
    worker = worker or SimpleNamespace(results=queue.Queue(), language="en", busy=False, file_stop=threading.Event())
    # Only results/language/busy/file_stop are used, so a stand-in avoids building a Tk window.
    app.App._transcribe_file(worker, model or FakeWhisper(), "talk.wav")  # pyright: ignore[reportArgumentType]
    items = []
    while not worker.results.empty():
        items.append(worker.results.get())
    return items


def text_words(items):
    return "".join(payload for kind, payload in items if kind == "text").split()


@pytest.mark.parametrize("seconds", [10, 49, 50])   # 20, 98 and exactly 100 words: typed whole
def test_each_word_appears_once_and_in_order(monkeypatch, seconds):
    model = FakeWhisper()
    items = transcribe_file(monkeypatch, seconds, model)
    expected = [f"w{k}" for k in range(int(seconds / 0.5)) if k * 0.5 + 0.4 <= seconds]
    assert text_words(items) == expected
    assert model.long_calls == 1
    assert items[-2:] == [("progress", 100), ("done", None)]


@pytest.mark.parametrize("seconds", [60, 600])
def test_a_long_file_types_the_first_100_words_then_stops(monkeypatch, seconds):
    model = FakeWhisper()
    items = transcribe_file(monkeypatch, seconds, model)
    assert text_words(items) == [f"w{k}" for k in range(100)]
    assert model.said == 101            # the 101st word asked for the stop; nothing after it
    assert items[-1] == ("done", "limit")
    assert ("progress", 100) not in items


def test_a_chunk_that_crosses_100_words_is_cut(monkeypatch):
    class Chunky(FakeWhisper):          # segments of 30 words: the 4th holds words 91-120
        def transcribe_long(self, audio, language, on_text, on_progress=None, should_stop=None):
            words = words_in(audio)
            for i in range(0, len(words), 30):
                if should_stop and should_stop():
                    return
                on_text(" " + " ".join(words[i:i + 30]))

    items = transcribe_file(monkeypatch, 60, Chunky())
    assert text_words(items) == [f"w{k}" for k in range(100)]
    assert items[-1] == ("done", "limit")


def test_the_narration_starting_stops_the_file_and_keeps_the_typed_words(monkeypatch):   # D9, §3.2
    class Results(queue.Queue):
        def put(self, item, block=True, timeout=None):
            super().put(item, block, timeout)
            if item == ("text", "w9 "):
                worker.file_stop.set()     # what _stop_listening() does from the UI thread

    worker = SimpleNamespace(results=Results(), language="en", busy=False, file_stop=threading.Event())
    model = FakeWhisper()
    items = transcribe_file(monkeypatch, 60, model, worker)
    assert text_words(items) == [f"w{k}" for k in range(10)]
    assert model.said == 10
    assert items[-1] == ("done", "stopped")
    assert ("progress", 100) not in items


def test_no_header_is_typed(monkeypatch):      # known issue 13: the name goes to the status line
    items = transcribe_file(monkeypatch, 2)
    assert "".join(payload for kind, payload in items if kind == "text").split() == ["w0", "w1", "w2", "w3"]
    assert ("status", "Decoding talk.wav…") in items


def test_junk_segments_are_dropped(monkeypatch):
    items = transcribe_file(monkeypatch, 2, FakeWhisper(extra_segments=[" [Music]", " Thank you.", "  "]))
    assert text_words(items) == ["w0", "w1", "w2", "w3"]


def test_model_error_is_reported(monkeypatch):
    class Broken(FakeWhisper):
        def transcribe_long(self, audio, language, on_text, on_progress=None, should_stop=None):
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
            if p.abort_callback and whisper_native.AbortCallback(p.abort_callback)(None):
                return -6               # whisper.cpp: "failed to encode" after an abort
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


def long_text(segments, on_text=None, should_stop=None, rc=0):
    out, progress = [], []
    model = fake_model(segments)
    if rc:
        model.lib.whisper_full = lambda *args: rc  # pyright: ignore[reportAttributeAccessIssue]
    model.transcribe_long(np.zeros(16000, np.float32), "en", on_text or out.append, progress.append,
                          should_stop=should_stop)
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


def test_transcribe_long_stops_when_asked():
    out = []

    def on_text(text):
        out.append(text)

    text, _ = long_text([(b" one", 0, 100, 0.0), (b" two", 100, 200, 0.0), (b" three", 200, 300, 0.0)],
                        on_text, should_stop=lambda: len(out) >= 1)
    assert out == [" one"]              # whisper_full returned -6, and that isn't an error


def test_transcribe_long_still_raises_a_failure_it_did_not_ask_for():
    with pytest.raises(RuntimeError, match=r"whisper_full failed \(-6\)"):
        long_text([(b" hi", 0, 100, 0.0)], should_stop=lambda: False, rc=-6)
