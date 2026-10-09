"""Window layout: speech to text on the left, text to speech on the right, nothing cut off.

Builds the real Tk window with fakes (the `window` fixture in conftest.py), so no GPU,
model or audio device is needed. Narration spec §3.1 and test plan T-UI-1.
"""

import tkinter as tk

import pytest

import app


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


# ---- Narration box (spec N2, test plan T-UI-2): its own Save/Clear/Copy all, no audio yet.

HINDI = "नमस्ते दुनिया। Hello world."


def put_transcript(win, text):
    win._write_locked(lambda: win.text.insert("end", text))


def test_narration_box_is_editable_and_speak_is_disabled(window):
    _, tts = panes_of(window)
    for w in (window.tts_text, window.speak_btn):
        assert is_descendant(w, tts), f"{w} should be in the right (text to speech) pane"
    window.tts_text.insert("end", HINDI)  # the user types or pastes here
    assert window.tts_text.get("1.0", "end-1c") == HINDI
    assert window.speak_btn.instate(["disabled"]), "Speak must stay disabled while the Kokoro files are missing"


def test_ctrl_a_selects_all_in_the_narration_box(window):
    window.tts_text.insert("end", "line one\nline two")
    window.tts_text.focus_force()
    window.tts_text.event_generate("<Control-a>")
    assert window.tts_text.get("sel.first", "sel.last") == "line one\nline two"


def test_narration_clear_copy_save_only_touch_the_narration_box(window, monkeypatch, tmp_path):
    put_transcript(window, "transcript stays")
    window.tts_text.insert("end", HINDI)
    stt_status = window.status_var.get()

    clipboard = []  # stub: the real clipboard belongs to the user's desktop
    monkeypatch.setattr(window.root, "clipboard_clear", clipboard.clear)
    monkeypatch.setattr(window.root, "clipboard_append", clipboard.append)
    window.tts_copy_all()
    assert clipboard == [HINDI]
    assert window.tts_status_var.get() == "Copied narration text to clipboard."

    out = tmp_path / "narration.txt"
    monkeypatch.setattr(app.filedialog, "asksaveasfilename", lambda **kw: str(out))
    window.tts_save()
    assert out.read_text(encoding="utf-8") == HINDI, "Unicode must survive Save…"

    window.tts_clear()
    assert window.tts_text.get("1.0", "end-1c") == ""
    assert window.text.get("1.0", "end-1c") == "transcript stays"
    assert window.status_var.get() == stt_status, "TTS actions must not write the STT status line"


def test_transcript_clear_leaves_the_narration_box_alone(window):
    put_transcript(window, "transcript")
    window.tts_text.insert("end", "narration")
    window.clear()
    assert window.text.get("1.0", "end-1c") == ""
    assert window.tts_text.get("1.0", "end-1c") == "narration"


def test_save_cancelled_writes_nothing(window, monkeypatch):
    window.tts_text.insert("end", "x")
    before = window.tts_status_var.get()
    monkeypatch.setattr(app.filedialog, "asksaveasfilename", lambda **kw: "")

    def no_write(*args, **kwargs):
        raise AssertionError("a cancelled Save… must not write a file")
    monkeypatch.setattr(app.Path, "write_text", no_write)
    window.tts_save()
    assert window.tts_status_var.get() == before


def test_every_tts_control_visible_at_minimum_window_size(window):
    root = window.root
    width, height = root.minsize()
    if root.winfo_screenwidth() < width:
        pytest.skip(f"screen ({root.winfo_screenwidth()} px) is narrower than the minimum window ({width} px)")
    root.geometry(f"{width}x{height}")
    root.update()
    root.update()
    _, tts = panes_of(window)
    buttons = [b for f in tts.winfo_children() for b in f.winfo_children() if b.winfo_class() == "TButton"]
    assert len(buttons) == 4, "Speak, Save…, Clear, Copy all"
    controls = [window.tts_text, window.voice_box, window.speed_box, *buttons]
    cut = [str(w) for w in controls if not inside(w, tts)]
    assert not cut, f"cut off at the minimum size {width}x{height}: {cut}"
