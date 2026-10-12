"""The DeepSeek terminal in the window: start-up, speech typed into it, keys, its end and restart,
and its answers narrated.

The real window with a fake terminal (`FakeTerminal` in conftest.py): `deepseek` never runs.
Spec 2026-10-12-deepseek-terminal §3.1, P2 and P4.
"""

import json
import subprocess
import sys
from pathlib import Path

from conftest import FakeEngine, FakeTerminal, pump
from test_window_layout import panes_of

import answers
import app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "deepseek-hook"


def term(win):
    return win.terminal


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def test_deepseek_starts_with_the_window_in_the_workspace(window):
    assert len(FakeTerminal.instances) == 1
    t = term(window)
    assert t.argv == ["powershell.exe", "-NoLogo", "-Command", f"deepseek '--settings' '{window.hook_settings}'"]
    assert t.cwd == str(app.WORKSPACE) and app.WORKSPACE.name == "AI-workspace"


def test_deepseek_gets_the_stop_hook_outside_its_workspace(window):    # §4.4, P4
    settings = json.loads(window.hook_settings.read_text(encoding="utf-8"))
    (stop,) = settings["hooks"]["Stop"]
    (hook,) = stop["hooks"]
    assert hook["type"] == "command"
    assert hook["command"].endswith(f'/answers.py" {window.inbox.port} {window.inbox.token}')
    assert app.WORKSPACE not in window.hook_settings.parents           # `deepseek` can't read the token there


def test_deepseek_argv_quotes_for_powershell():
    assert app.deepseek_argv()[-1] == "deepseek"
    assert app.deepseek_argv(r"C:\Users\O'Neil\h.json")[-1] == r"deepseek '--settings' 'C:\Users\O''Neil\h.json'"


def test_the_hook_runs_under_python_not_pythonw(monkeypatch, tmp_path):
    (tmp_path / "python.exe").touch()
    monkeypatch.setattr(app.sys, "executable", str(tmp_path / "pythonw.exe"))
    assert app.hook_python() == tmp_path / "python.exe"
    monkeypatch.setattr(app.sys, "executable", str(tmp_path / "python.exe"))
    assert app.hook_python() == tmp_path / "python.exe"


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


def test_a_file_cut_at_100_words_says_so(window):                   # §3.1 File mode, P3
    window.start_btn.config(state="disabled")
    window.results.put(("done", "limit"))
    pump(window, lambda: window.status_var.get() == "File: typed the first 100 words.")
    assert str(window.start_btn["state"]) == "normal"


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


# ---------------------------------------------------------------- P4: answers → narration

def ready(make_window, **engine_kw):
    win = make_window(FakeEngine(**engine_kw))
    pump(win, lambda: win.speak_btn.instate(["!disabled"]))
    return win


def box(win):
    return win.tts_text.get("1.0", "end-1c")


def test_an_answer_replaces_the_narration_text_and_is_spoken(make_window):
    win = ready(make_window)
    win.tts_text.insert("1.0", "old notes")
    win.results.put(("ai_answer", "**Fruits**\n\n- Apple\n- Banana"))
    pump(win, lambda: win.speaking)
    assert box(win) == "Fruits\n\nApple.\nBanana."                      # Markdown marks are never read out
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")


def test_a_new_answer_stops_the_narration_and_starts_from_the_beginning(make_window):
    win = ready(make_window, piece_s=1.0)
    win.tts_text.insert("1.0", "One long sentence here. Another one after it. And a third.")
    win.tts_toggle()
    pump(win, lambda: "Speaking 1/" in win.tts_status_var.get())
    first = win.tts_gen
    win.results.put(("ai_answer", "Teal."))
    pump(win, lambda: win.tts_gen != first)
    assert box(win) == "Teal." and win.speaking and not win.tts_paused


def test_a_paused_narration_gives_way_to_a_new_answer(make_window):
    win = ready(make_window, piece_s=1.0)
    win.tts_text.insert("1.0", "One long sentence here. Another one after it.")
    win.tts_toggle()
    win.tts_toggle()                                                   # ⏸ Pause
    assert win.tts_paused
    win.results.put(("ai_answer", "OK"))
    pump(win, lambda: box(win) == "OK")
    assert win.speaking and not win.tts_paused and win.speak_btn.cget("text") == "⏸  Pause"


def test_an_empty_answer_changes_nothing(make_window):
    win = ready(make_window)
    win.tts_text.insert("1.0", "keep me")
    for empty in ("", "   ", "---", "```\n```"):
        win.results.put(("ai_answer", empty))
    win.results.put(("text", "marker"))                                 # after the answers in the queue
    pump(win, lambda: term(win).written == ["marker "])
    assert box(win) == "keep me" and not win.speaking


def test_an_answer_waits_in_the_box_while_narration_is_not_ready(make_window):
    win = make_window(None)                                            # Kokoro's files are missing
    pump(win, lambda: win.tts_status_var.get() == app.tts.MISSING_MESSAGE)
    win.results.put(("ai_answer", "Teal."))
    pump(win, lambda: box(win) == "Teal.")
    assert not win.speaking
    assert win.tts_status_var.get() == "DeepSeek's answer is in the box; narration isn't ready."


def test_the_real_hook_script_reaches_the_narration(make_window):
    win = ready(make_window)
    hook = json.loads(win.hook_settings.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"]
    port, token = hook.split()[-2:]
    done = subprocess.run([sys.executable, answers.__file__, port, token], timeout=10, capture_output=True,
                          input=(FIXTURES / "stop-markdown-answer.json").read_bytes())
    assert done.returncode == 0
    pump(win, lambda: box(win) == "Fruits\n\nApple.\nBanana.\nCherry.")
    assert win.speaking
