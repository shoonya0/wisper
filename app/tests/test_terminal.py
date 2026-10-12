"""terminal: the pure key map and escape filter, and a real pseudo-console with a small Python child.

No `deepseek` and no network: the child is this venv's Python running a few lines. Spec
2026-10-12-deepseek-terminal, P1.
"""

import sys
import threading
import time

import pyte
import pytest

from terminal import Terminal, _Screen, child_env, clean, key_bytes, one_line, pasted, render, typed, win32_key

# Prints 40 numbered lines and a red word, then answers every input line with its size.
CHILD = """import os, sys
for i in range(40):
    print(f"line {i:02}")
print("\\x1b[31mred\\x1b[0m ready")
while True:
    s = input("> ")
    if s == "exit":
        sys.exit(3)
    print("got", s, "size", *os.get_terminal_size())
"""


# ---------------------------------------------------------------- key map

def test_printable_keys_are_written_as_they_are():
    assert key_bytes("a", "a", 0) == "a"
    assert key_bytes("eacute", "é", 0) == "é"
    assert key_bytes("u", "\x15", 0x4) == "\x15"                  # Ctrl+U clears the input line


def test_a_lone_modifier_writes_nothing():
    assert key_bytes("Shift_L", "", 0x1) is None


def test_special_keys_are_win32_input_mode_key_events():
    # A plain ESC[B is read as Esc in win32-input-mode and cancelled a dialog (P0).
    assert key_bytes("Down", "", 0) == "\x1b[40;80;0;1;256;1_\x1b[40;80;0;0;256;1_"
    assert key_bytes("Escape", "\x1b", 0) == "\x1b[27;1;27;1;0;1_\x1b[27;1;27;0;0;1_"
    assert key_bytes("Return", "\r", 0) == win32_key(13, 28, 13, False)


def test_modifiers_go_into_the_key_state():
    assert key_bytes("Return", "\r", 0x1) == win32_key(13, 28, 13, False, shift=True)
    assert key_bytes("Tab", "\t", 0x1) == win32_key(9, 15, 9, False, shift=True)
    assert key_bytes("Left", "", 0x4) == "\x1b[37;75;0;1;264;1_\x1b[37;75;0;0;264;1_"     # Ctrl + enhanced


# ---------------------------------------------------------------- pure helpers

def test_clean_drops_the_queries_pyte_would_print():
    assert clean("a\x1b[?u\x1b[<u\x1b[>0q b") == ("a b", "")
    assert clean("\x1b[31mred\x1b[0m") == ("\x1b[31mred\x1b[0m", "")


def test_clean_holds_back_an_escape_split_across_reads():
    text, held = clean("abc\x1b[<")
    assert (text, held) == ("abc", "\x1b[<")
    assert clean(held + "u def") == (" def", "")
    assert clean("x\x1b") == ("x", "\x1b")


def test_child_env_drops_the_claude_session_variables():
    env = child_env({"PATH": "p", "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", "claude": "x",
                     "MSYSTEM": "MINGW64", "DEEPSEEK": "k"})
    assert env == {"PATH": "p", "DEEPSEEK": "k"}


def test_one_line_joins_lines_with_spaces():
    assert one_line("open the\nfile  please\r\n") == "open the file please"
    assert one_line(" \n ") == ""


def test_typed_speech_ends_with_one_space_and_nothing_is_typed_for_blank():
    assert typed(" open the\nfile ") == "open the file "
    assert typed(" \n") == ""
    assert "\r" not in typed("a\r\nb")                                # never Enter


def test_a_paste_keeps_its_spacing_on_one_line():
    assert pasted("a  b\r\nc\nd") == "a  b c d"


def test_render_skips_the_second_column_of_a_wide_character():
    screen = pyte.Screen(8, 1)
    pyte.Stream(screen).feed("a界b\x1b[1mB")
    row, index = render(screen.buffer[0], 8)
    assert "".join(run[0] for run in row) == "a界bB   "
    assert index[:5] == [0, 1, 2, 2, 3]                               # column 3 ("b") is text index 2
    assert row[1] == ("B", None, None, True, False)


def test_render_indexes_count_combining_marks():
    screen = pyte.Screen(4, 1)
    pyte.Stream(screen).feed("q́xy")                             # q + acute has no single-character form
    row, index = render(screen.buffer[0], 4)
    text = "".join(run[0] for run in row)
    assert text[index[2]] == "y"


def test_the_screen_keeps_the_lines_that_scroll_off_and_erase_3_drops_only_them():
    screen = _Screen(10, 3, history=2)
    stream = pyte.Stream(screen)
    stream.feed("one\r\ntwo\r\nthree\r\nfour\r\nfive")
    assert ["".join(run[0] for run in row).strip() for row in screen.history] == ["one", "two"]
    stream.feed("\r\nsix")
    assert ["".join(run[0] for run in row).strip() for row in screen.history] == ["two", "three"]
    assert screen.pushed == 3
    stream.feed("\x1b[3J")
    assert not screen.history
    assert screen.display[2].strip() == "six"


# ---------------------------------------------------------------- a real pseudo-console

def wait_for(term, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError("timed out; screen:\n" + "\n".join(term.text()))
        time.sleep(0.02)


def screen_has(term, text):
    return lambda: any(text in line for line in term.text())


@pytest.fixture
def child(tmp_path):
    ended = threading.Event()
    term = Terminal([sys.executable, "-c", CHILD], str(tmp_path), lines=10, columns=60, on_exit=ended.set)
    term.ended = ended                                                 # type: ignore[attr-defined]
    yield term
    term.close()


def test_output_arrives_without_conpty_holding_it(child):
    # ConPTY asks for the device attributes at start and holds the output 3 s until answered.
    started = time.monotonic()
    wait_for(child, screen_has(child, "ready"), timeout=2.5)
    assert time.monotonic() - started < 2.5


def test_colours_come_through_as_runs(child):
    wait_for(child, screen_has(child, "ready"))
    snap = child.snapshot()
    rows = [row for row in snap.rows.values() if row and row[0][0] == "red"]
    assert rows and rows[0][0][1] == "#c50f1f"
    assert snap.cursor is not None


def test_a_second_snapshot_without_output_is_empty(child):
    wait_for(child, screen_has(child, "ready"))
    time.sleep(0.2)
    child.snapshot()
    assert child.snapshot().rows == {}


def test_typed_text_reaches_the_program(child):
    wait_for(child, screen_has(child, "ready"))
    child.type_text("hello\nwisper")                                   # one line, no Enter
    wait_for(child, screen_has(child, "> hello wisper"))
    assert not any("got" in line for line in child.text())
    child.write("\r")
    wait_for(child, screen_has(child, "got hello wisper  size 60 10"))  # typed text ends with a space


def test_resize_reaches_the_program(child):
    wait_for(child, screen_has(child, "ready"))
    child.resize(12, 70)
    child.write("x\r")
    wait_for(child, screen_has(child, "got x size 70 12"))
    snap = child.snapshot()
    assert (snap.lines, snap.columns) == (12, 70)


def test_scroll_back_shows_the_lines_above_and_typing_returns(child):
    wait_for(child, screen_has(child, "ready"))
    time.sleep(0.2)
    first = child.snapshot()
    assert first.history >= 30 and first.scrolled == 0
    child.scroll(first.history)                                        # to the top
    top = child.snapshot()
    assert top.scrolled == first.history
    assert "".join(run[0] for run in top.rows[0]).startswith("line 00")
    assert top.cursor is None                                          # the cursor's row is below the view
    child.write("x")
    back = child.snapshot()
    assert back.scrolled == 0
    shown = {y: "".join(run[0] for run in row) for y, row in back.rows.items()}
    assert shown[0].startswith("line ") and not shown[0].startswith("line 00")
    assert any("ready" in line for line in shown.values())          # the live rows are drawn again


def test_scroll_back_and_return_while_idle_redraws_the_live_rows(child):
    wait_for(child, screen_has(child, "ready"))
    time.sleep(0.2)
    live = {y: row for y, row in child.snapshot().rows.items()}
    child.scroll(5)
    child.snapshot()
    child.scroll_to_bottom()
    back = child.snapshot()
    assert back.scrolled == 0
    assert set(back.rows) == set(range(back.lines))
    assert all(back.rows[y] == row for y, row in live.items())


def test_scroll_stops_at_both_ends(child):
    wait_for(child, screen_has(child, "ready"))
    child.scroll(-5)
    assert child.snapshot().scrolled == 0
    child.scroll(10_000)
    snap = child.snapshot()
    assert snap.scrolled == snap.history


def test_exit_is_reported(child):
    wait_for(child, screen_has(child, "ready"))
    child.write("exit\r")
    assert child.ended.wait(2)                                         # type: ignore[attr-defined]
    assert not child.alive                                             # (pywinpty's own EOF comes after ~5 s)
    assert child.exit_status == 3
    child.write("after the end")                                       # doesn't raise
    started = time.monotonic()
    child.close()                                                      # the reader's EOF comes ~5 s late
    assert time.monotonic() - started < 1


def test_a_notice_shows_on_screen_and_is_not_sent(child):
    wait_for(child, screen_has(child, "ready"))
    child.notice("DeepSeek ended.")
    wait_for(child, screen_has(child, "DeepSeek ended."))
    child.write("\r")
    wait_for(child, screen_has(child, "got  size"))                     # the program got an empty line


def test_close_ends_the_program(child):
    wait_for(child, screen_has(child, "ready"))
    child.close()
    assert not child.alive
    assert child.ended.wait(5)                                         # type: ignore[attr-defined]
