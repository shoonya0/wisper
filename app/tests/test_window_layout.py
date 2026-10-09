"""Window layout: speech to text on the left, text to speech on the right, nothing cut off.

Builds the real Tk window with a fake Whisper model and a fake PyAudio, so no GPU or
audio device is needed. Narration spec §3.1 and test plan T-UI-1.
"""

import tkinter as tk

import pytest

import app


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


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setattr(app, "Whisper", FakeWhisper)
    monkeypatch.setattr(app.capture.pyaudio, "PyAudio", FakePyAudio)
    monkeypatch.setattr(app.capture, "list_sources", lambda pa, kind: [])
    # No skip on TclError: Wisper is Windows-only, where Tk always has a display, and a
    # skip here once hid a flaky Tcl start-up (see --capture=sys in pyproject.toml).
    root = tk.Tk()
    # Invisible but still mapped, so geometry can be measured: these tests run on every
    # verify (Stop hook, pre-commit) and must not flash windows on the user's desktop.
    root.attributes("-alpha", 0.0)
    root.attributes("-toolwindow", True)
    win = app.App(root)
    root.update()
    yield win
    # Cancel pending after() timers (_poll): destroy() leaves them in Tcl's notifier and the
    # next test's update() would fire them ("invalid command name ..._poll").
    for after_id in root.tk.splitlist(root.tk.call("after", "info")):
        root.after_cancel(after_id)
    win.on_close()
    # Wait for the worker before monkeypatch restores the real Whisper: a worker that
    # hasn't taken its "model" job yet would otherwise load the real GPU model.
    win.worker.join(timeout=5)
    assert not win.worker.is_alive(), "worker thread didn't stop after on_close()"


def panes_of(win):
    (paned,) = [w for w in win.root.winfo_children() if isinstance(w, tk.PanedWindow)]
    return [win.root.nametowidget(str(p)) for p in paned.panes()]


def inside(widget, container):
    """True when widget is mapped and lies fully within container's visible area."""
    widget.update_idletasks()
    left, top = widget.winfo_rootx(), widget.winfo_rooty()
    c_left, c_top = container.winfo_rootx(), container.winfo_rooty()
    return (widget.winfo_ismapped() and widget.winfo_height() > 1
            and left >= c_left and left + widget.winfo_width() <= c_left + container.winfo_width()
            and top >= c_top and top + widget.winfo_height() <= c_top + container.winfo_height())


def is_descendant(widget, ancestor):
    return str(widget).startswith(str(ancestor) + ".")


def test_speech_to_text_left_text_to_speech_right(window):
    stt, tts = panes_of(window)
    for w in (window.start_btn, window.model_box, window.lang_box, window.text, window.level_bar):
        assert is_descendant(w, stt), f"{w} should be in the left (speech to text) pane"
    assert stt.winfo_rootx() < tts.winfo_rootx()


def test_status_line_and_level_meter_visible_at_default_size(window):
    # Before N1 the transcript's requested height pushed the status row off the window,
    # so "Ready • model • queue" and the level meter were never shown at 940x640.
    stt, tts = panes_of(window)
    assert inside(window.level_bar, stt), "level meter is cut off"
    assert inside(window.level_bar.master, stt), "STT status line is cut off"
    tts_status = [w for w in tts.winfo_children() if isinstance(w, tk.Widget) and w.winfo_class() == "TFrame"]
    assert any(inside(f, tts) for f in tts_status), "TTS status line is cut off"


def test_every_stt_control_visible_at_minimum_window_size(window):
    root = window.root
    width, height = root.minsize()
    if root.winfo_screenwidth() < width:  # e.g. a 1024x768 CI runner caps the window
        pytest.skip(f"screen ({root.winfo_screenwidth()} px) is narrower than the minimum window ({width} px)")
    root.geometry(f"{width}x{height}")
    root.update()
    root.update()
    assert (root.winfo_width(), root.winfo_height()) == (width, height), "window didn't reach its minimum size"
    stt, _ = panes_of(window)
    controls = [window.start_btn, window.model_box, window.lang_box, window.device_box, window.level_bar]
    cut = [str(w) for w in controls if not inside(w, stt)]
    assert not cut, f"cut off at the minimum size {width}x{height}: {cut}"
