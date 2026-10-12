"""The DeepSeek terminal drawn in a Tk Text widget (spec 2026-10-12-deepseek-terminal, P2).

Draws a snapshot (rows of styled runs, the cursor) and turns keys, pastes, the mouse wheel and
its own size into callbacks. It knows nothing about pseudo-consoles: app.py passes the
snapshots in and the callbacks out. Ctrl+C copies a selection (as Windows Terminal does) and
is a key for the program when nothing is selected.
"""

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

FONTS = ("Cascadia Mono", "Consolas")
FONT_SIZE = 11
PAD = 6
WHEEL_LINES = 3
TK_SHIFT, TK_CONTROL = 0x1, 0x4


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
        self.size: tuple[int, int] = (24, 80)              # (lines, columns) that fit the widget
        w = self.widget
        w.bind("<Key>", self._key)
        w.bind("<Control-v>", self._paste)
        w.bind("<Control-V>", self._paste)
        w.bind("<Shift-Insert>", self._paste)
        w.bind("<MouseWheel>", self._wheel)
        w.bind("<Button-1>", lambda e: w.focus_set())       # a disabled Text doesn't take focus by itself
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
        elif state & TK_SHIFT and e.keysym in ("Prior", "Next"):
            page = max(1, self.size[0] - 1)
            self._on_scroll(page if e.keysym == "Prior" else -page)
        else:
            self._on_key(e.keysym, e.char, state)
        return "break"                                     # the Text never edits itself; Tab doesn't move focus

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
