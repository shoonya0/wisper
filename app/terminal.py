"""A program in a Windows pseudo-console (ConPTY), kept as a screen of styled text. No Tk.

`Terminal` starts a command in a pseudo-console (pywinpty), reads its output on its own
thread into a `pyte` screen, and keeps the lines that scroll off the top. The UI asks for a
`snapshot()` on its timer: only the rows that changed since the last one, as runs of text
with colours. `key_bytes()` turns a Tk key event into what to write: ConPTY turns on
win32-input-mode (`ESC[?9001h`), so special keys go as win32 key events, as Windows Terminal
sends them; a plain `ESC[B` is read as Esc (spec 2026-10-12-deepseek-terminal §4.2).
"""

import ctypes
import ctypes.wintypes as W
import os
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pyte
from winpty import PtyProcess

# pyte ends a CSI at `<` or `=` and then prints the rest ("u"): drop the kitty keyboard
# queries and XTVERSION before feeding it. An unfinished escape at the end of a read is held
# back until the next read, so a sequence split across two reads is still dropped.
UNKNOWN    = re.compile(r"\x1b\[[?<>=][0-9;]*u|\x1b\[>[0-9;]*q")
UNFINISHED = re.compile(r"\x1b(\[[0-9;?<>=]*)?\Z")

PALETTE = {"black": "#0c0c0c", "red": "#c50f1f", "green": "#13a10e", "brown": "#c19c00", "blue": "#0037da",
           "magenta": "#881798", "cyan": "#3a96dd", "white": "#cccccc", "brightblack": "#767676",
           "brightred": "#e74856", "brightgreen": "#16c60c", "brightbrown": "#f9f1a5", "brightblue": "#3b78ff",
           "brightmagenta": "#b4009e", "brightcyan": "#61d6d6", "brightwhite": "#f2f2f2"}
HEX = re.compile(r"[0-9a-fA-F]{6}")

# Tk keysym -> (virtual key, scan code, enhanced, character) for win32-input-mode
WIN32_KEYS = {
    "Up":     (38, 72, True, 0),  "Down":   (40, 80, True, 0),  "Left":   (37, 75, True, 0),
    "Right":  (39, 77, True, 0),  "Home":   (36, 71, True, 0),  "End":    (35, 79, True, 0),
    "Prior":  (33, 73, True, 0),  "Next":   (34, 81, True, 0),  "Insert": (45, 82, True, 0),
    "Delete": (46, 83, True, 0),  "Escape": (27, 1, False, 27), "Tab":    (9, 15, False, 9),
    "BackSpace": (8, 14, False, 8), "Return": (13, 28, False, 13),
}
TK_SHIFT, TK_CONTROL = 0x1, 0x4
SHIFT_PRESSED, LEFT_CTRL_PRESSED, ENHANCED_KEY = 0x10, 0x8, 0x100

SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF

# Variables a Claude Code session sets for its children; `deepseek` started from inside one
# would think it's a sub-session ("Transcript saving is off", P0).
INHERITED = ("CLAUDE", "MSYSTEM")

Run = tuple[str, str | None, str | None, bool, bool]   # text, fg, bg, bold, reverse (None: default colour)
Row = tuple[Run, ...]


@dataclass(frozen=True)
class Snapshot:
    lines:    int
    columns:  int
    rows:     dict[int, Row]          # only the rows that changed since the last snapshot
    cursor:   tuple[int, int] | None  # (row, index in the row's text); None when hidden or scrolled away
    scrolled: int                     # lines scrolled back from the bottom (0: following the output)
    history:  int                     # lines kept above the screen


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """`environ` without the Claude Code session variables."""
    return {k: v for k, v in environ.items() if not k.upper().startswith(INHERITED)}


def win32_key(vk: int, scan: int, char: int, enhanced: bool, shift: bool = False, ctrl: bool = False) -> str:
    """Key down + key up in win32-input-mode: `ESC [ vk ; sc ; uc ; down ; state ; repeat _`."""
    state = (ENHANCED_KEY if enhanced else 0) | (SHIFT_PRESSED if shift else 0) | (LEFT_CTRL_PRESSED if ctrl else 0)
    return f"\x1b[{vk};{scan};{char};1;{state};1_\x1b[{vk};{scan};{char};0;{state};1_"


def key_bytes(keysym: str, char: str, state: int) -> str | None:
    """What to write for a Tk key event, or None when there's nothing to send (a lone Shift)."""
    if keysym in WIN32_KEYS:
        vk, scan, enhanced, code = WIN32_KEYS[keysym]
        return win32_key(vk, scan, code, enhanced, shift=bool(state & TK_SHIFT), ctrl=bool(state & TK_CONTROL))
    return char or None


def one_line(text: str) -> str:
    """Text as one line: a multi-line write is folded into "[Pasted text]" by Claude Code (P0)."""
    return " ".join(text.split())


def typed(text: str) -> str:
    """What speech types: one line and a space, so the next chunk doesn't run into it; "" for nothing."""
    line = one_line(text)
    return line + " " if line else ""


def pasted(text: str) -> str:
    """A paste as one line: line breaks become spaces, other spacing stays (§4.2)."""
    return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def clean(data: str) -> tuple[str, str]:
    """`data` ready for pyte (unknown sequences dropped), and an unfinished escape at its end to hold back."""
    cut = UNFINISHED.search(data)
    held = data[cut.start():] if cut else ""
    return UNKNOWN.sub("", data[:len(data) - len(held)]), held


def colour(name: str) -> str | None:
    if name == "default":
        return None
    if HEX.fullmatch(name):
        return "#" + name.lower()
    return PALETTE.get(name)


def render(line: Mapping[int, "pyte.screens.Char"], columns: int) -> tuple[Row, list[int]]:
    """A pyte line as runs of same-styled text, and the text index of every column.

    A wide character fills two columns; pyte leaves the second one empty, and it's skipped.
    """
    runs: list[Run] = []
    index: list[int] = []
    text: list[str] = []
    style = None
    at = 0
    for x in range(columns):
        index.append(at)
        ch = line[x]
        if ch.data == "":
            continue
        s = (colour(ch.fg), colour(ch.bg), ch.bold, ch.reverse)
        if s != style and text:
            runs.append(("".join(text), *style))  # type: ignore[misc]
            text = []
        style = s
        text.append(ch.data)
        at += len(ch.data)                             # a cell can hold a character + combining marks
    if text:
        runs.append(("".join(text), *style))  # type: ignore[misc]
    return tuple(runs), index


class _Screen(pyte.Screen):
    """A pyte screen that keeps the lines scrolling off its top and answers the program's queries."""

    def __init__(self, columns: int, lines: int, history: int):
        super().__init__(columns, lines)
        self.history: deque[Row] = deque(maxlen=history)
        self.pushed = 0                                # lines ever pushed into the history
        self.reply: Callable[[str], None] = lambda data: None

    def write_process_input(self, data: str) -> None:
        # Device attributes (`ESC[c`) and cursor position (`ESC[6n`). ConPTY asks for the
        # attributes at start and holds the program's output for 3 s until they come (P1).
        self.reply(data)

    def index(self) -> None:
        top, bottom = self.margins or pyte.screens.Margins(0, self.lines - 1)
        if self.cursor.y == bottom and top == 0:
            self.history.append(render(self.buffer[0], self.columns)[0])
            self.pushed += 1
        super().index()

    def erase_in_display(self, how: int = 0, *args, **kwargs) -> None:
        if how == 3:                                   # the scroll-back only (`cls`, `/clear`); pyte would
            self.history.clear()                       # also erase the screen, as for 2
            return
        super().erase_in_display(how, *args, **kwargs)


class Terminal:
    """`argv` running in a pseudo-console of `lines` × `columns` in folder `cwd`.

    The reader thread feeds the screen and calls `on_output` (from that thread) after each
    read; `on_exit` once when the program ends (from a waiting thread). Everything else is
    for the UI thread.
    """

    def __init__(self, argv: list[str], cwd: str, *, lines: int = 24, columns: int = 80, history: int = 5000,
                 env: Mapping[str, str] | None = None, on_output: Callable[[], None] | None = None,
                 on_exit: Callable[[], None] | None = None):
        self._lock = threading.Lock()
        self._screen = _Screen(columns, lines, history)
        self._stream = pyte.Stream(self._screen)
        self._drawn: dict[int, Row] = {}
        self._offset = 0
        self._changed = True
        self._cursor_at: tuple[int, int] | None = None
        self._on_output = on_output
        self._on_exit = on_exit
        self._ended = threading.Event()
        self._proc = PtyProcess.spawn(argv, cwd=cwd, env=dict(child_env(os.environ if env is None else env)),
                                      dimensions=(lines, columns), backend=0)   # 0 = ConPTY
        self._screen.reply = self._reply
        self._reader = threading.Thread(target=self._read, name="terminal-reader", daemon=True)
        self._reader.start()
        # The reader sees EOF only ~5 s after the program ends (pywinpty, P1): wait on the process.
        threading.Thread(target=self._wait, name="terminal-exit", daemon=True).start()

    @property
    def alive(self) -> bool:
        return self._proc.isalive()

    @property
    def exit_status(self) -> int | None:
        return None if self.alive else self._proc.exitstatus

    def _read(self) -> None:
        pending = ""
        while True:
            try:
                data = self._proc.read(65536)
            except (EOFError, OSError):
                break
            if not data:
                continue
            data, pending = clean(pending + data)
            with self._lock:
                pushed = self._screen.pushed
                self._stream.feed(data)
                if self._offset:                       # scrolled back: keep the same lines in view
                    self._offset = min(len(self._screen.history), self._offset + self._screen.pushed - pushed)
                self._changed = True
            if self._on_output:
                self._on_output()
        self._exited()

    def _wait(self) -> None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = W.HANDLE
        k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        k32.CloseHandle.argtypes = [W.HANDLE]
        handle = k32.OpenProcess(SYNCHRONIZE, False, self._proc.pid)
        if handle:                                     # no handle: it has already ended
            k32.WaitForSingleObject(handle, INFINITE)
            k32.CloseHandle(handle)
        self._exited()

    def _exited(self) -> None:
        with self._lock:
            if self._ended.is_set():
                return
            self._ended.set()
        if self._on_exit:
            self._on_exit()

    def _reply(self, data: str) -> None:
        try:
            self._proc.write(data)
        except EOFError:
            pass

    def write(self, text: str) -> None:
        """Send keys or text to the program, and follow the output again."""
        self.scroll_to_bottom()
        try:
            self._proc.write(text)
        except EOFError:
            pass                                       # it has ended; `alive` says so

    def type_text(self, text: str) -> None:
        """Type `text` into the input line as one line in one write (§4.3), without Enter."""
        line = typed(text)
        if line:
            self.write(line)

    def paste(self, text: str) -> None:
        line = pasted(text)
        if line:
            self.write(line)

    def notice(self, text: str) -> None:
        """Show a line of Wisper's own below the program's output (it isn't sent to the program)."""
        with self._lock:
            self._stream.feed(f"\r\n\x1b[93m{text}\x1b[0m")
            self._changed = True

    def resize(self, lines: int, columns: int) -> None:
        with self._lock:
            if (lines, columns) == (self._screen.lines, self._screen.columns):
                return
            self._screen.resize(lines, columns)
            self._drawn = {}
            self._changed = True
        if self.alive:
            self._proc.setwinsize(lines, columns)

    def scroll(self, lines: int) -> None:
        """Scroll back (`lines` > 0) or forward through the lines above the screen."""
        with self._lock:
            self._scroll_to(self._offset + lines)

    def scroll_to_bottom(self) -> None:
        with self._lock:                               # under the lock: new output may move `_offset`
            self._scroll_to(0)

    def _scroll_to(self, offset: int) -> None:
        offset = max(0, min(len(self._screen.history), offset))
        if offset != self._offset:
            self._offset = offset
            self._drawn = {}                           # every row shows other lines now: look at all of them
            self._changed = True

    def snapshot(self) -> Snapshot:
        with self._lock:
            screen = self._screen
            if not self._changed:
                return Snapshot(screen.lines, screen.columns, {}, self._cursor_at, self._offset, len(screen.history))
            self._changed = False
            history = screen.history
            self._offset = min(self._offset, len(history))
            # Rows to look at: pyte's dirty rows, or all of them when scrolled back or after a resize.
            rows = range(screen.lines) if self._offset or not self._drawn else sorted(screen.dirty)
            screen.dirty.clear()
            changed: dict[int, Row] = {}
            cursor_index = None
            for y in rows:
                source = y - self._offset              # < 0: a history line
                if source < 0:
                    row = history[len(history) + source]
                else:
                    row, index = render(screen.buffer[source], screen.columns)
                    if source == screen.cursor.y:
                        cursor_index = index
                if self._drawn.get(y) != row:          # ConPTY repaints rows that didn't change
                    changed[y] = row
                    self._drawn[y] = row
            self._cursor_at = self._cursor(cursor_index)
            return Snapshot(screen.lines, screen.columns, changed, self._cursor_at, self._offset, len(history))

    def _cursor(self, index: list[int] | None) -> tuple[int, int] | None:
        screen = self._screen
        y = screen.cursor.y + self._offset
        if screen.cursor.hidden or y >= screen.lines:
            return None
        if index is None:
            index = render(screen.buffer[screen.cursor.y], screen.columns)[1]
        return y, index[min(screen.cursor.x, screen.columns - 1)]

    def text(self) -> list[str]:
        """The screen as plain lines (for tests and copying)."""
        with self._lock:
            rows = [render(self._screen.buffer[y], self._screen.columns)[0] for y in range(self._screen.lines)]
        return ["".join(run[0] for run in row) for row in rows]

    def close(self) -> None:
        """End the program (and whatever it started inside the pseudo-console)."""
        if self.alive:
            self._proc.terminate(force=True)
        # The reader is blocked on pywinpty's socket until its late EOF; closing the socket frees it.
        # (`PtyProcess.close()` skips this once `isalive()` has seen the end.)
        self._proc.fileobj.close()
        self._reader.join(timeout=2)
