"""Listening and narrating take turns (D9): every row of the spec's §3.2 table.

The real window with a fake capture, fake Kokoro engine and fake terminal (conftest.py):
no microphone, model or `deepseek` is touched. Spec 2026-10-12-deepseek-terminal §3.2, §4.6, P5.
"""

import time

import numpy as np
import pytest
from conftest import MIC, FakeEngine, FakeWhisper, pump

import app

PARAGRAPH = "First sentence here. Second one follows. And a third."
DICTATION = "Dictation (microphone)"


class FakeCapture:
    instances = []

    def __init__(self, pa, device, profile, on_chunk):
        self.device, self.level = device, 0.0
        self.running = False
        FakeCapture.instances.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


@pytest.fixture
def win(make_window, monkeypatch):
    """A ready window in Dictation with one mic; each narration piece lasts 1 s, so it's still playing."""
    monkeypatch.setattr(app.capture, "Capture", FakeCapture)
    FakeCapture.instances = []
    w = make_window(FakeEngine(piece_s=1.0))
    pump(w, lambda: w.speak_btn.instate(["!disabled"]) and w.start_btn.instate(["!disabled"]))
    w.mode_var.set(DICTATION)
    w.devices = [dict(MIC)]
    w.device_box.config(values=[MIC["label"]])
    w.device_box.current(0)
    return w


def listening(w):
    return w.transcribing and w.capture is not None and w.capture.running


def start_listening(w):
    w.toggle()
    assert listening(w)


def speak(w):
    w.tts_text.insert("end", PARAGRAPH)
    w.tts_toggle()
    pump(w, lambda: w.tts_status_var.get().startswith("Speaking"))


def playing(w):
    return w.speaking and not w.tts_paused and w.speak_btn.cget("text") == "⏸  Pause"


def paused(w):
    return w.speaking and w.tts_paused and w.speak_btn.cget("text") == "▶  Resume"


def stt_paused(w):
    """Listening stopped because the narration started: ▶ Start shows it can start again."""
    stopped = not w.transcribing and w.capture is None and all(not c.running for c in FakeCapture.instances)
    return stopped and w.start_btn.cget("text") == "▶  Start" and w.status_var.get() == app.STT_PAUSED


def press_speak_key(w):
    w._speak_key(None)
    w._speak_key_released(None)


def test_start_while_the_narration_plays_pauses_it_then_listens(win):           # row 1
    speak(win)
    start_listening(win)
    assert paused(win)
    assert win.tts_status_var.get().startswith("Paused")


@pytest.fixture
def file_model(monkeypatch):
    """The fake Whisper's file run: types "one" and "two", then runs until it's asked to stop (or 5 s)."""
    calls = []

    def transcribe_long(self, audio, language, on_text, on_progress=None, should_stop=None):
        calls.append(audio)
        on_text(" one")
        on_text(" two")
        deadline = time.monotonic() + 5
        while not (should_stop and should_stop()) and time.monotonic() < deadline:
            time.sleep(0.01)

    monkeypatch.setattr(FakeWhisper, "transcribe_long", transcribe_long, raising=False)
    monkeypatch.setattr(app.audio_io, "decode_to_16k_mono", lambda path: np.zeros(16000, np.float32))
    return calls


def start_file(w):
    w.mode_var.set("File")
    w.selected_file = "talk.wav"
    w.toggle()


def test_transcribe_while_the_narration_plays_pauses_it_then_transcribes(win, file_model):   # row 2
    speak(win)
    start_file(win)
    assert paused(win)
    pump(win, lambda: file_model and "two " in win.terminal.written)


@pytest.mark.parametrize("press", [lambda w: w.tts_toggle(), press_speak_key], ids=["resume", "ctrl-enter"])
def test_resume_stops_listening_then_continues_the_narration(win, press):        # row 3
    speak(win)
    start_listening(win)
    press(win)
    assert stt_paused(win)
    assert playing(win)


@pytest.mark.parametrize("end", ["tts_clear", "tts_stop"])
def test_clear_or_stop_ends_the_paused_narration_and_listening_carries_on(win, end):   # row 4
    speak(win)
    start_listening(win)
    getattr(win, end)()
    assert not win.speaking
    assert listening(win)


def test_a_new_answer_while_paused_this_way_starts_over_and_stops_listening(win):   # row 5
    speak(win)
    start_listening(win)
    win.results.put(("ai_answer", "**Teal.**"))
    pump(win, lambda: win.tts_text.get("1.0", "end-1c") == "Teal.")
    assert stt_paused(win)
    assert playing(win)


@pytest.mark.parametrize("narrate", [
    lambda w: (w.tts_text.insert("end", PARAGRAPH), w.tts_toggle()),
    lambda w: (w.tts_text.insert("end", PARAGRAPH), press_speak_key(w)),
    lambda w: w.results.put(("ai_answer", "Teal.")),
], ids=["speak", "ctrl-enter", "answer"])
def test_the_narration_starting_stops_listening_first(win, narrate):             # row 6
    start_listening(win)
    narrate(win)
    pump(win, lambda: win.speaking)
    assert stt_paused(win)
    assert playing(win)


def test_speak_with_nothing_to_say_keeps_listening(win):
    start_listening(win)
    win.tts_toggle()
    assert win.tts_status_var.get() == "Nothing to narrate."
    assert listening(win)


def test_the_narration_starting_stops_a_file_and_keeps_its_typed_words(win, file_model):   # row 7
    start_file(win)
    pump(win, lambda: "two " in win.terminal.written)
    speak(win)
    pump(win, lambda: win.start_btn.instate(["!disabled"]))              # the file job ended early
    assert win.terminal.written[-2:] == ["one ", "two "]                  # the typed words stay
    assert win.status_var.get() == app.STT_PAUSED
    assert playing(win)


def test_a_file_started_after_the_narration_isnt_stopped_by_it(win, file_model):
    speak(win)
    win.tts_stop()                                                        # set the stop flag
    start_file(win)
    pump(win, lambda: "two " in win.terminal.written)
    time.sleep(0.2)
    assert win.start_btn.instate(["disabled"])                            # still transcribing
    win.file_stop.set()                                                   # end the fake run
    pump(win, lambda: win.start_btn.instate(["!disabled"]))


def test_listening_stays_stopped_when_the_narration_ends(win):              # row 8 (Q3)
    start_listening(win)
    speak(win)
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.", timeout=6)
    assert not win.transcribing and win.capture is None
    assert win.start_btn.cget("text") == "▶  Start"


def test_pausing_the_narration_keeps_listening_stopped_until_start(win):          # row 9
    start_listening(win)
    speak(win)
    win.tts_toggle()                                                      # ⏸
    assert paused(win)
    assert not win.transcribing
    start_listening(win)                                                  # ▶ Start
    assert paused(win)                                                    # the narration stays paused
