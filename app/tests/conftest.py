"""Shared fixture: the real Tk window with a fake Whisper, PyAudio, Kokoro engine, output, terminal and
ear channels router.

No GPU, model file, audio device or restore journal is touched. Used by test_window_layout.py,
test_narration_ui.py, test_ears_ui.py and the other UI tests.
"""

import gc
import time
import tkinter as tk

import numpy as np
import pytest

import app
import terminal


class FakeWhisper:
    def __init__(self, dll_dir, model_path):
        pass

    def transcribe(self, audio, language, prompt=""):
        return ""

    def close(self):
        pass


class FakePyAudio:
    def terminate(self):
        pass


class FakeEngine:
    """Stands in for tts.Engine: 0.2 s of silence per piece, after an optional delay."""

    def __init__(self, synth_s=0.0, piece_s=0.2):
        self.synth_s, self.piece_s = synth_s, piece_s
        self.calls = []

    def voices(self):
        return ["af_heart", "bf_emma", "hf_alpha"]

    def synthesize(self, text, voice="af_heart", speed=1.0):
        time.sleep(self.synth_s)
        self.calls.append((text, voice, speed))
        return np.zeros(int(24000 * self.piece_s), dtype=np.float32)


class FakeOutput:
    """Stands in for playback.PaStream: records blocks; the speakers take them in real time.

    Real streams buffer in parallel, so only one fake paces: in "Both" the cable's writes
    return at once, as in test_playback.py.
    """

    instances = []

    def __init__(self, pa, device, block_s=None):
        self.name, self.rate = device["label"], 24000
        self.realtime = device is not CABLE
        self.blocks = 0
        self.closed = False
        FakeOutput.instances.append(self)

    def write(self, block):
        if self.realtime:
            time.sleep(len(block) / self.rate)
        self.blocks += 1

    def close(self):
        self.closed = True


class FakeInput:
    """Stands in for playback.PaInput: 10 ms blocks of 0.1 in real time; raises once failing is set."""

    instances = []
    failing: Exception | None = None

    def __init__(self, pa, device, block_s=None):
        self.name, self.rate = device["label"], 24000
        self.reads = 0
        self.closed = False
        FakeInput.instances.append(self)

    def available(self):
        return 0

    def read(self, frames):
        if FakeInput.failing is not None:
            raise FakeInput.failing
        time.sleep(frames / self.rate)
        self.reads += 1
        return np.full(frames, 0.1, dtype=np.float32)

    def close(self):
        self.closed = True


class FakeTerminal:
    """Stands in for terminal.Terminal: records what's written; `end()` acts as the program ending.

    `screen` is what `text()` returns (e.g. PowerShell's "not recognized" error).
    """

    instances = []

    def __init__(self, argv, cwd, *, lines=24, columns=80, history=5000, env=None, on_output=None, on_exit=None):
        self.argv, self.cwd, self.size, self.on_exit = argv, cwd, (lines, columns), on_exit
        self.written, self.notices, self.scrolled = [], [], 0
        self.screen = []
        self.alive, self.closed = True, False
        FakeTerminal.instances.append(self)

    def write(self, text):
        self.written.append(text)

    def type_text(self, text):
        if line := terminal.typed(text):
            self.write(line)

    def paste(self, text):
        if line := terminal.pasted(text):
            self.write(line)

    def resize(self, lines, columns):
        self.size = (lines, columns)

    def scroll(self, lines):
        self.scrolled += lines

    def snapshot(self):
        return terminal.Snapshot(*self.size, {}, None, 0, 0)

    def text(self):
        return list(self.screen)

    def notice(self, text):
        self.notices.append(text)

    def end(self):
        self.alive = False
        if self.on_exit:
            self.on_exit()

    def close(self):
        self.alive, self.closed = False, True


class FakeRouter:
    """Stands in for channels.Router: records the UI's commands; `update` / `error` act as the router thread.

    The last one made is `FakeRouter.last` (each window makes one).
    """

    last = None

    def __init__(self, on_update, on_error):
        self.on_update, self.on_error = on_update, on_error
        self.calls = []
        FakeRouter.last = self

    def start(self):
        self.calls.append(("start",))

    def choose(self, side, selection):
        self.calls.append(("choose", side, selection))

    def volume(self, side, v):
        self.calls.append(("volume", side, v))

    def app_volume(self, key, v):
        self.calls.append(("app_volume", key, v))

    def reset(self):
        self.calls.append(("reset",))

    def close(self, timeout=2.0):
        self.calls.append(("close",))

    def update(self, device, apps, warnings=()):
        self.on_update(device, list(apps), list(warnings))

    def error(self, msg):
        self.on_error(msg)


SPEAKERS = {"index": 0, "name": "Speakers", "label": "Speakers", "defaultSampleRate": 24000,
            "maxOutputChannels": 2}
MIC = {"index": 2, "name": "Microphone (Realtek)", "label": "Microphone (Realtek)", "defaultSampleRate": 24000,
       "maxInputChannels": 2}
CABLE = {"index": 1, "name": "CABLE Input (VB-Audio Virtual Cable)",
         "label": "CABLE Input (VB-Audio Virtual Cable)", "defaultSampleRate": 24000, "maxOutputChannels": 2}


@pytest.fixture
def make_window(monkeypatch):
    """make_window(engine=None, outputs=(SPEAKERS, CABLE), mics=(), ear_router=FakeRouter): engine None = Kokoro
    files missing; ear_router(on_update, on_error) stands in for app.make_ear_router.

    No mics by default, so the mic pass-through (N8) stays off unless a test asks for it.
    """
    windows = []

    def make(engine=None, outputs=(SPEAKERS, CABLE), mics=(), ear_router=FakeRouter):
        def load():
            if engine is None:
                raise FileNotFoundError(app.tts.MISSING_MESSAGE)
            return engine

        monkeypatch.setattr(app, "Whisper", FakeWhisper)
        monkeypatch.setattr(app.capture.pyaudio, "PyAudio", FakePyAudio)
        monkeypatch.setattr(app.capture, "list_sources", lambda pa, kind: [])
        monkeypatch.setattr(app.playback, "list_inputs", lambda pa: [dict(m) for m in mics])
        monkeypatch.setattr(app.tts, "load", load)
        monkeypatch.setattr(app.playback, "list_outputs", lambda pa: list(outputs))
        monkeypatch.setattr(app.playback, "PaStream", FakeOutput)
        monkeypatch.setattr(app.playback, "PaInput", FakeInput)
        monkeypatch.setattr(app.terminal, "Terminal", FakeTerminal)          # never a real `deepseek`
        monkeypatch.setattr(app, "prepare_workspace", lambda path: None)     # no folder, no `git init`
        monkeypatch.setattr(app, "make_ear_router", ear_router)              # no COM, no real journal
        FakeTerminal.instances = []
        FakeOutput.instances = []
        FakeInput.instances, FakeInput.failing = [], None
        # No skip on TclError: Wisper is Windows-only, where Tk always has a display, and a
        # skip here once hid a flaky Tcl start-up (see --capture=sys in pyproject.toml).
        root = tk.Tk()
        # Invisible but still mapped, so geometry can be measured: these tests run on every
        # verify (Stop hook, pre-commit) and must not flash windows on the user's desktop.
        root.attributes("-alpha", 0.0)
        root.attributes("-toolwindow", True)
        win = app.App(root)
        root.update()
        windows.append(win)
        return win

    yield make
    for win in windows:
        root = win.root
        # Cancel pending after() timers (_poll): destroy() leaves them in Tcl's notifier and
        # the next test's update() would fire them ("invalid command name ..._poll").
        for after_id in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(after_id)
        win.on_close()
        # Wait for the workers before monkeypatch restores the real Whisper and tts.load: a
        # worker that hasn't taken its job yet would otherwise load a real model.
        for worker in (win.worker, win.tts_worker):
            worker.join(timeout=5)
            assert not worker.is_alive(), f"{worker.name} didn't stop after on_close()"
        assert not win.passthrough.running, "the mic pass-through didn't stop after on_close()"
        assert win.terminal is None or win.terminal.closed, "the DeepSeek terminal didn't end with the window"
    # An App lives in reference cycles (lambdas holding self), so only the cyclic GC frees its Tk
    # interpreter, on whichever thread triggers it. Freed from a worker thread of the next test's
    # window, Tcl aborts the run ("Tcl_AsyncDelete: async handler deleted by the wrong thread").
    # Collect here, on the main thread that created it.
    windows.clear()
    win = root = None
    gc.collect()


@pytest.fixture
def window(make_window):
    return make_window()


def pump(win, until, timeout=3.0):
    """Run the Tk loop (and so _poll) until until() is true; fail after timeout seconds."""
    deadline = time.monotonic() + timeout
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out; TTS status: {win.tts_status_var.get()!r}")
        win.root.update()
        time.sleep(0.01)

