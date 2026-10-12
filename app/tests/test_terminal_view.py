"""terminal_view: drawing snapshots and turning keys, pastes, the wheel and the size into callbacks.

An invisible Tk window and hand-made snapshots: no pseudo-console. Spec
2026-10-12-deepseek-terminal, P2.
"""

import tkinter as tk

import pytest

from terminal import Snapshot
from terminal_view import TerminalView, input_span, prompt_index

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


def snap(rows, cursor=None, lines=3, columns=10, caret=None):
    return Snapshot(lines, columns, rows, cursor, 0, 0, caret)


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


# ---- Ctrl+A selects the prompt's text, Ctrl+Shift+A is the program's Ctrl+A (issue #14)

RULE = "─" * 30
SCREEN = ["● Paris.", "", RULE, "❯ what is the capital", "  of France", RULE, "  ⏵⏵ auto mode on"]


def test_input_span_covers_the_typed_text_across_wrapped_rows():
    assert input_span(SCREEN, cursor_row=4) == ((3, 2), (4, 11))
    assert input_span(SCREEN, cursor_row=3) == ((3, 2), (4, 11))


def test_input_span_without_a_cursor_uses_the_last_prompt_and_skips_the_no_break_space():
    # Real `deepseek`: the cursor is hidden and the prompt is "❯\xa0" (P2 check, issue #14).
    screen = ["❯ an earlier question", "● answer", RULE, "❯\xa0What is the capital of France?", RULE, "  ⏵⏵ auto"]
    assert input_span(screen, cursor_row=None) == ((3, 2), (3, 32))


def test_input_span_is_none_for_an_empty_prompt_or_no_prompt():
    assert input_span(["", RULE, "❯ ", RULE], cursor_row=2) is None
    assert input_span(["plain output", "more"], cursor_row=1) is None
    assert input_span(SCREEN, cursor_row=99) is None


def test_ctrl_a_selects_the_prompt_text_and_ctrl_c_copies_it(view, monkeypatch):
    clipboard = []
    monkeypatch.setattr(view.widget, "clipboard_clear", clipboard.clear)
    monkeypatch.setattr(view.widget, "clipboard_append", clipboard.append)
    rows = {y: ((line, None, None, False, False),) for y, line in enumerate(SCREEN)}
    view.draw(snap(rows, cursor=(4, 10), lines=len(SCREEN), columns=30))
    view.widget.focus_force()
    view.widget.event_generate("<Control-a>")
    assert view.widget.get("sel.first", "sel.last") == "what is the capital\n  of France"
    assert not view.calls["key"], "Ctrl+A must not reach the program"
    view.widget.event_generate("<Control-c>")
    assert clipboard == ["what is the capital\n  of France"]


# SCREEN's prompt as ← / → count it: "what is the capital" is 0-19, the wrap 19-20, "of France" 20-29.
CARET = (4, 10)                                                         # `deepseek`'s hidden cursor: before "e", 28


def draw_prompt(view):
    """SCREEN with the program's cursor hidden (as Claude Code does) at CARET."""
    rows = {y: ((line, None, None, False, False),) for y, line in enumerate(SCREEN)}
    view.draw(snap(rows, cursor=None, lines=len(SCREEN), columns=30, caret=CARET))
    view.widget.focus_force()


def select_prompt(view):
    draw_prompt(view)
    view.widget.event_generate("<Control-a>")


def keys(*pairs):
    return [(key, "", 0) for key, n in pairs for _ in range(n)]


def click(view, index):
    x, y, w, h = view.widget.bbox(index)
    view.widget.event_generate("<ButtonRelease-1>", x=x + w // 2, y=y + h // 2)


def test_prompt_index_counts_as_the_arrows_do():
    span = input_span(SCREEN, cursor_row=4)
    assert span is not None
    cells = {(3, 2): 0, (3, 0): 0, (3, 21): 19, (3, 29): 19, (4, 2): 20, (4, 10): 28, (4, 11): 29, (4, 25): 29}
    for cell, index in cells.items():
        assert prompt_index(SCREEN, span, cell) == index, cell
    assert prompt_index(SCREEN, span, (2, 5)) is None and prompt_index(SCREEN, span, (6, 2)) is None


def test_a_trailing_space_before_the_cursor_counts():                  # typed speech ends with one (real `deepseek`)
    screen = [RULE, "❯ hello there", RULE]
    span = input_span(screen, cursor_row=1)
    assert span is not None
    assert prompt_index(screen, span, (1, 14), caret=(1, 14)) == 12     # after "hello there "
    assert prompt_index(screen, span, (1, 13), caret=(1, 14)) == 11


def test_ctrl_a_with_a_trailing_space_deletes_it_too(view):
    screen = ["", RULE, "❯ hello there", RULE, ""]
    rows = {y: ((line.ljust(30), None, None, False, False),) for y, line in enumerate(screen)}   # full rows, as drawn
    view.draw(snap(rows, lines=len(screen), columns=30, caret=(2, 14)))
    view.widget.focus_force()
    view.widget.event_generate("<Control-a>")
    view.widget.event_generate("<BackSpace>")
    assert view.calls["key"] == keys(("BackSpace", 12))


@pytest.mark.parametrize("key", ["BackSpace", "Delete"])
def test_backspace_or_delete_after_ctrl_a_clears_the_prompt(view, key):   # T-TERM-4, issue #14
    select_prompt(view)
    view.widget.event_generate(f"<{key}>")
    assert view.calls["key"] == keys(("Right", 1), ("BackSpace", 29))  # to the end, then all of it
    assert not view.widget.tag_ranges("sel")


def test_typing_after_ctrl_a_replaces_the_prompt(view):
    select_prompt(view)
    view.widget.event_generate("<KeyPress-x>")
    assert view.calls["key"] == [*keys(("Right", 1), ("BackSpace", 29)), ("x", "x", 0)]
    assert not view.widget.tag_ranges("sel")


def test_shift_then_a_capital_after_ctrl_a_still_replaces_the_prompt(view):
    select_prompt(view)
    view.widget.event_generate("<KeyPress-Shift_L>")
    view.widget.event_generate("<KeyPress-X>", state=0x1)
    assert view.calls["key"] == [("Shift_L", "", 0), *keys(("Right", 1), ("BackSpace", 29)), ("X", "X", 0x1)]


def test_another_key_after_ctrl_a_drops_the_selection_and_keeps_the_text(view):
    select_prompt(view)
    view.widget.event_generate("<Left>")
    assert view.calls["key"] == [("Left", "", 0)]
    assert not view.widget.tag_ranges("sel")
    view.widget.event_generate("<BackSpace>")                           # the selection is gone: one Backspace
    assert view.calls["key"][-1:] == [("BackSpace", "", 0)]


def test_backspace_deletes_a_word_selected_with_the_mouse(view):         # T-TERM-4: part of the prompt
    draw_prompt(view)
    view.widget.tag_add("sel", "5.5", "5.11")                           # "France": 23-29
    view.widget.event_generate("<BackSpace>")
    assert view.calls["key"] == keys(("Right", 1), ("BackSpace", 6))


def test_a_selection_across_the_wrap_is_deleted_as_one(view):
    draw_prompt(view)
    view.widget.tag_add("sel", "4.14", "5.4")                           # "capital of": 12-22
    view.widget.event_generate("<Delete>")
    assert view.calls["key"] == keys(("Left", 6), ("BackSpace", 10))


def test_typing_replaces_a_word_selected_with_the_mouse(view):
    draw_prompt(view)
    view.widget.tag_add("sel", "4.2", "4.6")                            # "what": 0-4
    view.widget.event_generate("<KeyPress-W>", state=0x1)
    assert view.calls["key"] == [*keys(("Left", 24), ("BackSpace", 4)), ("W", "W", 0x1)]


def test_a_paste_replaces_the_selected_text(view, monkeypatch):
    monkeypatch.setattr(view.widget, "clipboard_get", lambda: "Spain")
    draw_prompt(view)
    view.widget.tag_add("sel", "5.5", "5.11")
    view.widget.event_generate("<Control-v>")
    assert view.calls["key"] == keys(("Right", 1), ("BackSpace", 6))
    assert view.calls["paste"] == ["Spain"]


def test_backspace_with_a_mouse_selection_outside_the_prompt_is_one_backspace(view):
    draw_prompt(view)
    view.widget.tag_add("sel", "1.0", "1.5")                            # output selected to copy, not the prompt
    view.widget.event_generate("<BackSpace>")
    assert view.calls["key"] == [("BackSpace", "", 0)]


def test_a_click_in_the_prompt_moves_the_cursor_there(view):             # T-TERM-4: edit in the middle
    draw_prompt(view)
    click(view, "4.7")                                                  # "i" of "is": 5
    assert view.calls["key"] == keys(("Left", 23))
    click(view, "5.5")                                                  # before the redraw: from 5, not 28
    assert view.calls["key"][23:] == keys(("Right", 18))


def test_a_click_past_the_end_goes_to_the_end_and_outside_the_prompt_does_nothing(view):
    draw_prompt(view)
    click(view, "5.20")
    assert view.calls["key"] == keys(("Right", 1))
    click(view, "1.3")
    click(view, "7.5")
    assert view.calls["key"] == keys(("Right", 1))


def test_after_a_replacement_the_programs_cursor_wins_even_if_unchanged(view):   # review finding 1
    rows = {y: ((line, None, None, False, False),) for y, line in enumerate(SCREEN)}
    view.draw(snap(rows, lines=len(SCREEN), columns=30, caret=(4, 11)))           # at the end: 29
    view.widget.focus_force()
    view.widget.tag_add("sel", "5.10", "5.11")                                    # the last "e"
    view.widget.event_generate("<KeyPress-x>")                                    # the cursor ends at 29 again
    view.draw(snap({}, lines=len(SCREEN), columns=30, caret=(4, 11)))
    sent = len(view.calls["key"])
    click(view, "4.7")                                                            # 5
    assert view.calls["key"][sent:] == keys(("Left", 24))


def test_shift_page_up_scrolls_even_with_the_prompt_selected(view):              # review finding 3
    select_prompt(view)
    view.widget.event_generate("<Prior>", state=0x1)
    assert view.calls["scroll"] and not view.calls["key"]


def test_a_triple_clicked_last_row_is_deleted(view):                             # Tk selects to the next line's start
    draw_prompt(view)
    view.widget.tag_add("sel", "5.0", "6.0")                                      # "  of France" + the line end: 20-29
    view.widget.event_generate("<BackSpace>")
    assert view.calls["key"] == keys(("Right", 1), ("BackSpace", 9))


def test_the_programs_redraw_replaces_where_the_cursor_was_moved(view):
    draw_prompt(view)
    click(view, "4.7")                                                  # moved to 5, as far as the view knows
    rows = {y: ((line, None, None, False, False),) for y, line in enumerate(SCREEN)}
    view.draw(snap(rows, lines=len(SCREEN), columns=30, caret=(3, 9)))   # the program says 7
    click(view, "4.12")                                                 # 10
    assert view.calls["key"][23:] == keys(("Right", 3))


def test_ctrl_shift_a_is_the_programs_ctrl_a(view):
    view.widget.focus_force()
    view.widget.event_generate("<Control-Shift-A>")
    assert view.calls["key"] == [("a", "\x01", 0x4)]
    assert not view.widget.tag_ranges("sel")


def test_a_message_replaces_the_screen(view):
    view.draw(snap({0: (("x", None, None, False, False),)}, cursor=(0, 0)))
    view.message("Couldn't start DeepSeek")
    assert shown(view) == ["Couldn't start DeepSeek"]
    assert not view.widget.tag_ranges("cursor")
