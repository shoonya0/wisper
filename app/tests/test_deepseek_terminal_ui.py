"""The DeepSeek terminal in the window: start-up, speech typed into it, keys, its end and restart.

The real window with a fake terminal (`FakeTerminal` in conftest.py): `deepseek` never runs.
Spec 2026-10-12-deepseek-terminal §3.1, P2.
"""

from conftest import FakeTerminal, pump
from test_window_layout import panes_of

import app


def term(win):
    return win.terminal


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def test_deepseek_starts_with_the_window_in_the_workspace(window):
    assert len(FakeTerminal.instances) == 1
    t = term(window)
    assert t.argv == ["powershell.exe", "-NoLogo", "-Command", "deepseek"]
    assert t.cwd == str(app.WORKSPACE) and app.WORKSPACE.name == "AI-workspace"


def test_the_transcript_box_and_its_buttons_are_gone(window):
    assert not hasattr(window, "text")
    for name in ("copy_all", "clear", "save", "_append", "_write_locked"):
        assert not hasattr(window, name), name
    stt, _ = panes_of(window)
    assert not {"Copy all", "Clear", "Save…"} & {w["text"] for w in descendants(stt) if w.winfo_class() == "TButton"}


def test_speech_is_typed_into_the_input_line_and_never_sent(window):
    window.results.put(("text", " What is"))
    window.results.put(("text", "the capital of France?\n"))
    pump(window, lambda: len(term(window).written) == 2)
    assert term(window).written == ["What is ", "the capital of France? "]
    assert not any("\r" in w or "\n" in w for w in term(window).written), "Wisper never presses Enter (D7)"


def test_keys_from_the_view_reach_deepseek(window):
    window._terminal_key("a", "a", 0)
    window._terminal_key("Return", "\r", 0)
    window._terminal_key("Shift_L", "", 0x1)                          # a lone modifier sends nothing
    assert term(window).written == ["a", app.terminal.key_bytes("Return", "\r", 0)]


def test_a_paste_is_one_line(window):
    window._terminal_paste("line one\nline two")
    assert term(window).written == ["line one line two"]


def test_scroll_and_resize_go_to_the_terminal(window):
    window.term_view._on_scroll(3)
    window.term_view._on_resize(20, 90)
    assert term(window).scrolled == 3 and term(window).size == (20, 90)


def test_the_end_shows_the_restart_line_and_enter_starts_it_again(window):
    first = term(window)
    first.end()
    pump(window, lambda: first.notices)
    assert first.notices == [app.DEEPSEEK_ENDED]
    window._terminal_key("a", "a", 0)                                  # other keys do nothing now
    assert first.written == [] and len(FakeTerminal.instances) == 1
    window._terminal_key("Return", "\r", 0)
    assert len(FakeTerminal.instances) == 2 and term(window) is not first
    assert first.closed


def test_an_end_from_an_older_run_is_ignored(window):
    first = term(window)
    first.alive = False
    window._terminal_key("Return", "\r", 0)                            # restarted before the end arrived
    first.end()
    window._poll()
    assert first.notices == [] and term(window).notices == []


def test_deepseek_not_found_says_so(window):
    t = term(window)
    t.screen = ["deepseek : The term 'deepseek' is not recognized as the name of a cmdlet, function, ..."]
    t.end()
    pump(window, lambda: t.notices)
    assert t.notices == [app.DEEPSEEK_MISSING]


def test_speech_while_deepseek_is_down_is_not_typed(window):
    t = term(window)
    t.alive = False
    window.results.put(("text", "hello"))
    pump(window, lambda: "isn't running" in window.status_var.get())
    assert t.written == []


def test_a_start_failure_shows_in_the_terminal(window, monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("powershell.exe")
    monkeypatch.setattr(app.terminal, "Terminal", fail)
    window.terminal.alive = False
    window._terminal_key("Return", "\r", 0)
    assert window.terminal is None
    assert window.term_view.widget.get("1.0", "end-1c").startswith("Couldn't start DeepSeek")
    window.results.put(("text", "hello"))                              # nothing to type into: no crash
    pump(window, lambda: "isn't running" in window.status_var.get())

# Closing the window ends the terminal: checked for every window by make_window's teardown.
