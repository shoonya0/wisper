"""The DeepSeek terminal drawn in a Tk Text widget (spec 2026-10-12-deepseek-terminal, P2).

Draws a snapshot (rows of styled runs, the cursor) and turns keys, pastes, the mouse wheel and
its own size into callbacks. It knows nothing about pseudo-consoles: app.py passes the
snapshots in and the callbacks out. Ctrl+C copies a selection (as Windows Terminal does) and
is a key for the program when nothing is selected. Ctrl+A selects the text typed in the
prompt; Ctrl+Shift+A is the program's Ctrl+A (issue #14). The prompt acts like a text box
(T-TERM-4): a click in it moves the program's cursor there, and with a selection inside it
Backspace or Delete deletes the selection, a typed character or a paste replaces it. Claude Code
takes no mouse events, so these become ← / → and Backspace keys.
"""

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

FONTS = ("Cascadia Mono", "Consolas")
FONT_SIZE = 11
PAD = 6
WHEEL_LINES = 3
TK_SHIFT, TK_CONTROL = 0x1, 0x4
PROMPT = "❯"                                               # Claude Code's input box starts with it
MODIFIERS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Caps_Lock", "Num_Lock",
             "Win_L", "Win_R"}                             # pressed on their own, they keep a selection
ERASE = ("BackSpace", "Delete")
STALE = (-1, -1)                                           # no snapshot reports it: the next caret always wins


Span = tuple[tuple[int, int], tuple[int, int]]


def _row_length(lines: list[str], c0: int, r: int, caret: tuple[int, int] | None) -> int:
    """A prompt row's text length; the program's cursor shows how far trailing spaces go."""
    length = len(lines[r].rstrip()) - c0
    if caret is not None and caret[0] == r:
        length = max(length, caret[1] - c0)
    return max(0, length)


def prompt_index(lines: list[str], span: Span, cell: tuple[int, int],
                 caret: tuple[int, int] | None = None) -> int | None:
    """Where `cell` (row, column) is in the prompt's text, counted as ← and → count it; None outside it.

    The rows of the box start at the prompt's column. A wrapped row adds its text and one
    character (the space at the wrap, or a line break); a cell past a row's text is its end.
    Trailing spaces don't show, so the row with the program's cursor (`caret`) reaches at least
    to it (typed speech ends with a space). Checked with real `deepseek` (T-TERM-4).
    """
    (r0, c0), (r1, _) = span
    row, col = cell
    if not r0 <= row <= r1:
        return None
    before = sum(_row_length(lines, c0, r, caret) + 1 for r in range(r0, row))
    return before + max(0, min(col - c0, _row_length(lines, c0, row, caret)))


def cell_at(lines: list[str], span: Span, index: int, caret: tuple[int, int] | None = None) -> tuple[int, int]:
    """The cell of `index` in the prompt's text: the inverse of `prompt_index`."""
    (r0, c0), (r1, _) = span
    for r in range(r0, r1 + 1):
        length = _row_length(lines, c0, r, caret)
        if index <= length or r == r1:
            return r, c0 + min(index, length)
        index -= length + 1
    return r1, c0


def is_rule(line: str) -> bool:
    """A line of Claude Code's `─` rules, above and below the input box."""
    text = line.strip()
    return len(text) >= 3 and set(text) == {"─"}


def input_span(lines: list[str], cursor_row: int | None) -> Span | None:
    """Where the text typed in the prompt is: ((row, column), (row, end column)), or None if it's empty.

    The input box is the rows between the rules around the cursor; its text starts after `❯ `.
    Claude Code hides the terminal's cursor and draws its own, so without one the last `❯` row is used.
    """
    if cursor_row is None:
        cursor_row = next((r for r in range(len(lines) - 1, -1, -1) if PROMPT in lines[r]), -1)
    if not 0 <= cursor_row < len(lines):
        return None
    top = cursor_row
    while top > 0 and not is_rule(lines[top - 1]):
        top -= 1
    bottom = cursor_row
    while bottom + 1 < len(lines) and not is_rule(lines[bottom + 1]):
        bottom += 1
    start = next(((r, lines[r].index(PROMPT) + 1) for r in range(top, bottom + 1) if PROMPT in lines[r]), None)
    if start is None:
        return None
    row, col = start
    while col < len(lines[row]) and lines[row][col].isspace():   # Claude Code puts a no-break space there
        col += 1
    end = next(((r, len(lines[r].rstrip())) for r in range(bottom, row - 1, -1) if lines[r].strip()), None)
    if end is None or (end[0] == row and end[1] <= col):
        return None                                        # nothing typed yet
    return (row, col), end


class TerminalView:
    """`on_key(keysym, char, state)`, `on_paste(text)`, `on_scroll(lines)` (> 0: back),
    `on_resize(lines, columns)`; colours: `fg`, `bg`, `sel`, `border`."""

    def __init__(self, parent: tk.Misc, colours: dict[str, str], *, on_key: Callable[[str, str, int], None],
                 on_paste: Callable[[str], None], on_scroll: Callable[[int], None],
                 on_resize: Callable[[int, int], None]):
        self.fg, self.bg = colours["fg"], colours["bg"]
        families = set(tkfont.families(parent))
        family = next((f for f in FONTS if f in families), "TkFixedFont")
        self.font = tkfont.Font(parent, family=family, size=FONT_SIZE)
        self.bold = tkfont.Font(parent, family=family, size=FONT_SIZE, weight="bold")
        self.widget = tk.Text(parent, font=self.font, bg=self.bg, fg=self.fg, wrap="none", width=20, height=5,
                              padx=PAD, pady=PAD, borderwidth=0, highlightthickness=1, cursor="xterm",
                              highlightbackground=colours["border"], highlightcolor=colours["border"],
                              selectbackground=colours["sel"], selectforeground=self.fg,
                              insertwidth=0, takefocus=True, state="disabled")
        self.widget.tag_configure("cursor", background=self.fg, foreground=self.bg)
        self.widget.tag_raise("sel")
        self._on_key, self._on_paste, self._on_scroll, self._on_resize = on_key, on_paste, on_scroll, on_resize
        self._tags: dict[tuple, str] = {}
        self._shape: tuple[int, int] = (0, 0)              # (lines, columns) of the drawn text
        self._cursor_at: tuple[int, int] | None = None
        self._caret: tuple[int, int] | None = None  # the program's (hidden) cursor, or where it's been moved
        self._seen_caret: tuple[int, int] | None = None   # the last one a snapshot reported
        self.size: tuple[int, int] = (24, 80)              # (lines, columns) that fit the widget
        w = self.widget
        w.bind("<Key>", self._key)
        w.bind("<Control-v>", self._paste)
        w.bind("<Control-V>", self._paste)
        w.bind("<Shift-Insert>", self._paste)
        w.bind("<MouseWheel>", self._wheel)
        w.bind("<Button-1>", lambda e: w.focus_set())       # a disabled Text doesn't take focus by itself
        w.bind("<ButtonRelease-1>", self._click)
        w.bind("<Configure>", self._configure)

    # ------------------------------------------------------------------ drawing

    def _tag(self, fg: str | None, bg: str | None, bold: bool, reverse: bool) -> str:
        key = (fg, bg, bold, reverse)
        name = self._tags.get(key)
        if name is None:
            fore, back = fg or self.fg, bg or self.bg
            if reverse:
                fore, back = back, fore
            name = f"s{len(self._tags)}"
            # The default background is left to the widget, so a selection shows on it.
            self.widget.tag_configure(name, foreground=fore, background="" if back == self.bg else back,
                                      font=self.bold if bold else self.font)
            self.widget.tag_lower(name)                    # under "sel" and "cursor"
            self._tags[key] = name
        return name

    def draw(self, snap) -> None:
        """Draw a `terminal.Snapshot`: its changed rows and the cursor."""
        w = self.widget
        if snap.caret != self._seen_caret:                # the program moved it (or our moves arrived)
            self._seen_caret = self._caret = snap.caret
        if not snap.rows and (snap.lines, snap.columns) == self._shape and self._cursor_at == snap.cursor:
            return
        w.configure(state="normal")
        try:
            if (snap.lines, snap.columns) != self._shape:  # a new size: blank rows, then the snapshot's
                w.delete("1.0", "end")
                w.insert("1.0", "\n".join(" " * snap.columns for _ in range(snap.lines)))
                self._shape = (snap.lines, snap.columns)
            w.tag_remove("cursor", "1.0", "end")
            for y, row in snap.rows.items():
                if y >= snap.lines:
                    continue
                w.delete(f"{y + 1}.0", f"{y + 1}.end")
                parts: list[str] = []
                for text, fg, bg, bold, reverse in row:
                    parts += [text, self._tag(fg, bg, bold, reverse)]
                if parts:
                    w.insert(f"{y + 1}.0", *parts)
            if snap.cursor is not None:
                y, x = snap.cursor
                w.tag_add("cursor", f"{y + 1}.{x}")
        finally:
            w.configure(state="disabled")
        self._cursor_at = snap.cursor

    def message(self, text: str) -> None:
        """Replace the screen with a message (no program running at all)."""
        w = self.widget
        w.configure(state="normal")
        w.delete("1.0", "end")
        w.insert("1.0", text)
        w.configure(state="disabled")
        self._shape = (0, 0)
        self._cursor_at = None

    # ------------------------------------------------------------------ input

    def _key(self, e: tk.Event) -> str:
        state = e.state if isinstance(e.state, int) else 0  # a str only for events other than keys
        if state & TK_CONTROL and e.keysym.lower() == "c" and self.widget.tag_ranges("sel"):
            self.copy_selection()
        elif state & TK_CONTROL and e.keysym.lower() == "a":
            if state & TK_SHIFT:                           # Ctrl+Shift+A: the program's Ctrl+A (start of line)
                self._on_key("a", "\x01", TK_CONTROL)
            else:                                          # Ctrl+A: select the text in the prompt (#14)
                self.select_input()
        elif state & TK_SHIFT and e.keysym in ("Prior", "Next"):
            page = max(1, self.size[0] - 1)
            self._on_scroll(page if e.keysym == "Prior" else -page)
        elif e.keysym not in MODIFIERS and (sel := self._prompt_selection()):
            typed = bool(e.char) and e.char.isprintable() and not state & TK_CONTROL
            if e.keysym in ERASE or typed:
                self._delete(*sel)
            else:
                self.widget.tag_remove("sel", "1.0", "end")
            if e.keysym not in ERASE:
                self._on_key(e.keysym, e.char, state)
        else:
            self._on_key(e.keysym, e.char, state)
        return "break"                                     # the Text never edits itself; Tab doesn't move focus

    def _prompt(self) -> tuple[list[str], Span] | None:
        """The screen's lines and the span of the text typed in the prompt, or None if it's empty."""
        lines = self.widget.get("1.0", "end-1c").split("\n")
        cursor = self._caret or self._cursor_at
        span = input_span(lines, cursor[0] if cursor else None)
        return (lines, span) if span else None

    def select_input(self) -> None:
        """Select what's typed in the prompt's input box, so Ctrl+C copies it."""
        w = self.widget
        w.tag_remove("sel", "1.0", "end")
        if prompt := self._prompt():
            (r0, c0), (r1, c1) = prompt[1]
            if self._caret is not None and self._caret[0] == r1:
                c1 = max(c1, self._caret[1])                 # a trailing space before the cursor is typed text
            w.tag_add("sel", f"{r0 + 1}.{c0}", f"{r1 + 1}.{c1}")

    def _cell(self, index: str) -> tuple[int, int]:
        row, col = self.widget.index(index).split(".")
        return int(row) - 1, int(col)

    def _prompt_selection(self) -> tuple[int, int] | None:
        """The selection as (start, end) in the prompt's text, if it's inside the prompt and the cursor is known."""
        w = self.widget
        if not w.tag_ranges("sel") or self._caret is None or not (prompt := self._prompt()):
            return None
        lines, span = prompt
        last = self._cell("sel.last")
        if last[1] == 0 and last[0] == span[1][0] + 1:     # a triple-click selects to the next line's start
            last = (span[1][0], len(lines[span[1][0]]))
        a = prompt_index(lines, span, self._cell("sel.first"), self._caret)
        b = prompt_index(lines, span, last, self._caret)
        if a is None or b is None or prompt_index(lines, span, self._caret, self._caret) is None:
            return None
        return a, b

    def _move_to(self, target: int) -> None:
        """Move the program's cursor to `target` in the prompt's text with ← / →."""
        prompt = self._prompt()
        if self._caret is None or prompt is None:
            return
        lines, span = prompt
        here = prompt_index(lines, span, self._caret, self._caret)
        if here is None:
            return
        key = "Right" if target > here else "Left"
        for _ in range(abs(target - here)):
            self._on_key(key, "", 0)
        self._caret = cell_at(lines, span, target, self._caret)   # until the program's own redraw arrives

    def _delete(self, a: int, b: int) -> None:
        """Delete [a, b) of the prompt's text: the cursor goes to b, then b - a Backspaces."""
        self.widget.tag_remove("sel", "1.0", "end")
        self._move_to(b)
        for _ in range(b - a):
            self._on_key("BackSpace", "", 0)
        prompt = self._prompt()
        if prompt is not None and b > a:
            self._caret = cell_at(*prompt, a, self._caret)
        # What's typed or pasted next moves the program's cursor past `a`, perhaps back to where it
        # was reported: take the next snapshot's caret even if it looks unchanged (review finding 1).
        self._seen_caret = STALE

    def _click(self, e: tk.Event) -> None:
        """A click (not a drag) in the prompt moves the program's cursor there."""
        w = self.widget
        if w.tag_ranges("sel") or not (prompt := self._prompt()):
            return
        target = prompt_index(*prompt, self._cell(f"@{e.x},{e.y}"), self._caret)
        if target is not None:
            self._move_to(target)

    def copy_selection(self) -> None:
        lines = self.widget.get("sel.first", "sel.last").split("\n")
        self.widget.clipboard_clear()
        self.widget.clipboard_append("\n".join(line.rstrip() for line in lines))
        self.widget.tag_remove("sel", "1.0", "end")

    def _paste(self, _e: tk.Event) -> str:
        try:
            text = self.widget.clipboard_get()
        except tk.TclError:                                # empty clipboard, or not text
            return "break"
        if sel := self._prompt_selection():             # a paste replaces the selected text
            self._delete(*sel)
        self._on_paste(text)
        return "break"

    def _wheel(self, e: tk.Event) -> str:
        steps = int(e.delta / 120) or (1 if e.delta > 0 else -1)
        self._on_scroll(steps * WHEEL_LINES)
        return "break"

    def _configure(self, e: tk.Event) -> None:
        inner_w = e.width - 2 * (PAD + 1)
        inner_h = e.height - 2 * (PAD + 1)
        size = (max(5, inner_h // self.font.metrics("linespace")), max(20, inner_w // self.font.measure("M")))
        if size != self.size:
            self.size = size
            self._on_resize(*size)
