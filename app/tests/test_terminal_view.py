"""terminal_view: drawing snapshots and turning keys, pastes, the wheel and the size into callbacks.

An invisible Tk window and hand-made snapshots: no pseudo-console. Spec
2026-10-12-deepseek-terminal, P2.
"""

import tkinter as tk

import pytest

from terminal import Snapshot
from terminal_view import TerminalView

COLOURS = {"fg": "#d4d4d4", "bg": "#252526", "sel": "#264f78", "border": "#3c3c3c"}


@pytest.fixture
def view():
    root = tk.Tk()
    root.attributes("-alpha", 0.0)                                     # invisible, still measurable
    root.attributes("-toolwindow", True)
    calls = {"key": [], "paste": [], "scroll": [], "resize": []}
    v = TerminalView(root, COLOURS, on_key=lambda *a: calls["key"].append(a),
                     on_paste=calls["paste"].append, on_scroll=calls["scroll"].append,
                     on_resize=lambda *a: calls["resize"].append(a))
    v.widget.pack(fill="both", expand=True)
    root.geometry("600x300")
    root.update()
    v.calls = calls                                                    # type: ignore[attr-defined]
    yield v
    root.destroy()


def snap(rows, cursor=None, lines=3, columns=10):
    return Snapshot(lines, columns, rows, cursor, 0, 0)


def shown(view):
    return view.widget.get("1.0", "end-1c").split("\n")


def test_draws_rows_with_colours_and_the_cursor(view):
    view.draw(snap({0: (("ab", None, None, False, False), ("cd", "#c50f1f", None, True, False))}, cursor=(0, 3)))
    assert shown(view) == ["abcd", " " * 10, " " * 10]
    names = view.widget.tag_names("1.2")
    assert any(view.widget.tag_cget(n, "foreground") == "#c50f1f" for n in names)
    assert view.widget.tag_ranges("cursor")[0].string == "1.3"


def test_only_the_rows_in_a_snapshot_change(view):
    view.draw(snap({0: (("one", None, None, False, False),), 1: (("two", None, None, False, False),)}))
    view.draw(snap({1: (("TWO", None, None, False, False),)}))
    assert shown(view)[:2] == ["one", "TWO"]


def test_a_new_size_redraws_blank(view):
    view.draw(snap({0: (("x", None, None, False, False),)}))
    view.draw(snap({}, lines=2, columns=4))
    assert shown(view) == ["    ", "    "]


def test_the_cursor_moves_without_row_changes(view):
    view.draw(snap({0: (("abc", None, None, False, False),)}, cursor=(0, 0)))
    view.draw(snap({}, cursor=(0, 2)))
    assert [str(i) for i in view.widget.tag_ranges("cursor")] == ["1.2", "1.3"]


def test_keys_go_to_the_callback_and_the_text_stays_unedited(view):
    view.widget.focus_force()
    view.widget.event_generate("<Key>", keysym="a")
    view.widget.event_generate("<Key>", keysym="Return")
    assert [k[0] for k in view.calls["key"]] == ["a", "Return"]
    assert view.widget.get("1.0", "end-1c") == "", "the view must not type into itself"


def test_ctrl_c_copies_a_selection_and_otherwise_goes_to_the_program(view, monkeypatch):
    clipboard = []                                                     # stub: the real clipboard is the user's
    monkeypatch.setattr(view.widget, "clipboard_clear", clipboard.clear)
    monkeypatch.setattr(view.widget, "clipboard_append", clipboard.append)
    view.draw(snap({0: (("hello     ", None, None, False, False),)}))
    view.widget.focus_force()
    view.widget.tag_add("sel", "1.0", "1.10")
    view.widget.event_generate("<Control-c>")
    assert clipboard == ["hello"] and not view.calls["key"]          # trailing spaces trimmed
    view.widget.event_generate("<Control-c>")                          # nothing selected now
    assert view.calls["key"] and view.calls["key"][-1][0] == "c"


def test_ctrl_v_pastes_the_clipboard(view, monkeypatch):
    monkeypatch.setattr(view.widget, "clipboard_get", lambda: "two\nlines")
    view.widget.focus_force()
    view.widget.event_generate("<Control-v>")
    assert view.calls["paste"] == ["two\nlines"] and not view.calls["key"]


def test_wheel_and_shift_page_scroll(view):
    view.widget.focus_force()
    view.widget.event_generate("<MouseWheel>", delta=120)
    view.widget.event_generate("<MouseWheel>", delta=-240)
    view.widget.event_generate("<Key>", keysym="Prior", state=0x1)
    page = view.size[0] - 1
    assert view.calls["scroll"] == [3, -6, page]
    assert not view.calls["key"]


def test_the_size_in_lines_and_columns_follows_the_widget(view):
    lines, columns = view.size
    assert view.calls["resize"] and view.calls["resize"][-1] == (lines, columns)
    view.widget.master.geometry("900x400")
    view.widget.update()
    assert view.size[1] > columns and view.calls["resize"][-1] == view.size


def test_a_message_replaces_the_screen(view):
    view.draw(snap({0: (("x", None, None, False, False),)}, cursor=(0, 0)))
    view.message("Couldn't start DeepSeek")
    assert shown(view) == ["Couldn't start DeepSeek"]
    assert not view.widget.tag_ranges("cursor")
