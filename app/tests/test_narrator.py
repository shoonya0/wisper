"""narrator.Narrator with fake synth/play (test plan §1.3): order, prefetch, stop, errors."""

import threading
import time

import numpy as np
import pytest

from narrator import Narrator


class Fakes:
    """synth returns np.full(4, i) for piece i; play records what played and honors stop."""

    def __init__(self, synth_s=0.0, play_s=0.0, slow_synth=None, fail_synth=None, fail_play=None):
        self.synth_s, self.play_s = synth_s, play_s
        self.slow_synth = slow_synth or {}        # piece index -> seconds
        self.fail_synth, self.fail_play = fail_synth, fail_play
        self.events = []                           # (what, index, time)
        self.played = []
        self.done, self.errors = [], []
        self.finished = threading.Event()
        self.narrator = Narrator(self.synth, self.play, self.split, self.on_done, self.on_error)

    def split(self, text):
        return text.split("|") if text.strip() else []

    def synth(self, piece, **options):
        i = int(piece.removeprefix("s"))
        self.events.append(("synth start", i, time.perf_counter()))
        time.sleep(self.slow_synth.get(i, self.synth_s))
        if i == self.fail_synth:
            raise RuntimeError(f"synthesis failed on {piece}")
        self.events.append(("synth end", i, time.perf_counter()))
        return np.full(4, i)

    def play(self, samples, stop_event):
        i = int(samples[0])
        if i == self.fail_play:
            raise OSError("device unplugged")
        self.events.append(("play start", i, time.perf_counter()))
        if stop_event.wait(self.play_s):
            return
        self.played.append(i)
        self.events.append(("play end", i, time.perf_counter()))

    def on_done(self, stopped):
        self.done.append(stopped)
        self.finished.set()

    def on_error(self, message):
        self.errors.append(message)
        self.finished.set()

    def when(self, what, i):
        return next(t for w, j, t in self.events if (w, j) == (what, i))

    def speak_in_background(self, text):
        gen = self.narrator.begin()
        worker = threading.Thread(target=self.narrator.speak, args=(gen, text))
        worker.start()
        return worker


def test_pieces_play_in_order_each_exactly_once():
    f = Fakes()
    f.narrator.speak(f.narrator.begin(), "s1|s2|s3")
    assert f.played == [1, 2, 3]
    assert f.done == [False] and not f.errors


def test_prefetch_is_one_ahead_never_more():
    f = Fakes(synth_s=0.02, play_s=0.1)
    f.narrator.speak(f.narrator.begin(), "s1|s2|s3|s4")
    assert f.played == [1, 2, 3, 4]
    for i in (2, 3, 4):
        # piece i is synthesized while piece i-1 plays ...
        assert f.when("synth start", i) < f.when("play end", i - 1)
        # ... but not before piece i-1 has started (that would be two ahead)
        assert f.when("synth start", i) >= f.when("play start", i - 1)


def test_stop_mid_sentence_never_plays_the_rest():
    f = Fakes(play_s=0.3)
    worker = f.speak_in_background("s1|s2|s3")
    time.sleep(0.1)                                 # s1 is playing
    t0 = time.perf_counter()
    f.narrator.stop()
    worker.join(timeout=2)
    assert time.perf_counter() - t0 < 0.2, "speak() didn't return soon after stop()"
    assert f.played == []                           # s1 was cut off, s2/s3 never started
    assert not [e for e in f.events if e[0] == "play start" and e[1] > 1]
    assert f.done == [True] and not f.errors


def test_a_late_synthesis_result_after_stop_is_dropped():
    f = Fakes(play_s=0.05, slow_synth={2: 0.3})
    worker = f.speak_in_background("s1|s2|s3")
    time.sleep(0.15)                                # s1 done, s2 still synthesizing
    f.narrator.stop()
    worker.join(timeout=2)
    assert f.played == [1]
    assert ("synth end", 2) in [(w, i) for w, i, _ in f.events]   # it did finish ...
    assert ("play start", 2) not in [(w, i) for w, i, _ in f.events]  # ... and was dropped
    assert f.done == [True]


def test_stop_before_speak_starts_drops_that_speak():
    f = Fakes()
    gen = f.narrator.begin()
    f.narrator.stop()                               # user pressed Stop while it was queued
    f.narrator.speak(gen, "s1|s2")
    assert f.played == [] and f.events == []
    assert f.done == [True]


def test_speak_after_stop_plays_fully():
    f = Fakes(play_s=0.2)
    worker = f.speak_in_background("s1|s2")
    time.sleep(0.05)
    f.narrator.stop()
    worker.join(timeout=2)
    f.narrator.speak(f.narrator.begin(), "s3|s4")
    assert f.played == [3, 4]
    assert f.done == [True, False]


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_is_done_at_once_without_synthesis(text):
    f = Fakes()
    f.narrator.speak(f.narrator.begin(), text)
    assert f.done == [False] and f.events == []


def test_synthesis_error_plays_what_was_ready_then_reports_once():
    f = Fakes(play_s=0.05, fail_synth=2)
    f.narrator.speak(f.narrator.begin(), "s1|s2|s3")
    assert f.played == [1]
    assert f.errors == ["synthesis failed on s2"] and f.done == []
    f.narrator.speak(f.narrator.begin(), "s4")      # the worker is still usable
    assert f.played == [1, 4] and f.done == [False]


def test_device_error_ends_the_narration_with_one_error():
    f = Fakes(fail_play=2)
    f.narrator.speak(f.narrator.begin(), "s1|s2|s3")
    assert f.played == [1]
    assert f.errors == ["device unplugged"] and f.done == []
    assert 3 not in f.played


def test_options_reach_synth():
    seen = []

    def synth(piece, **options):
        seen.append(options)
        return np.zeros(4)

    n = Narrator(synth, lambda s, e: None, lambda t: [t], lambda stopped: None, lambda m: None)
    n.speak(n.begin(), "hello", voice="bf_emma", speed=1.25)
    assert seen == [{"voice": "bf_emma", "speed": 1.25}]


def test_split_error_is_reported_and_the_worker_survives():
    errors, done = [], []

    def split(text):
        if text == "bad":
            raise ValueError("split failed")
        return [text]

    n = Narrator(lambda p, **o: np.zeros(4), lambda s, e: None, split, done.append, errors.append)
    n.speak(n.begin(), "bad")                       # must not raise out of the worker
    assert errors == ["split failed"] and done == []
    n.speak(n.begin(), "fine")
    assert done == [False]


# ---------------------------------------------------------------- progress (N7)

def test_progress_reports_each_piece_as_it_starts_playing():
    f = Fakes()
    progress = []
    f.narrator = Narrator(f.synth, f.play, f.split, f.on_done, f.on_error,
                          on_progress=lambda i, n: progress.append((i, n, list(f.played))))
    f.narrator.speak(f.narrator.begin(), "s1|s2|s3")
    assert [(i, n) for i, n, _ in progress] == [(1, 3), (2, 3), (3, 3)]
    assert [played for _, _, played in progress] == [[], [1], [1, 2]], "reported before the piece plays"


def test_no_progress_after_stop():
    f = Fakes(play_s=0.3)
    progress = []
    f.narrator = Narrator(f.synth, f.play, f.split, f.on_done, f.on_error,
                          on_progress=lambda i, n: progress.append(i))
    worker = f.speak_in_background("s1|s2|s3")
    time.sleep(0.1)
    f.narrator.stop()
    worker.join(2)
    assert progress == [1]


def test_progress_is_optional():
    f = Fakes()
    f.narrator.speak(f.narrator.begin(), "s1|s2")
    assert f.played == [1, 2]
