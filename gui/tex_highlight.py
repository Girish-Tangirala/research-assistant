"""A LaTeX text area: line numbers, syntax colouring, current-line and "jump here" highlights.

Used by :mod:`gui.tex_editor`. Plain Tk (``tk.Text`` + a gutter canvas), because
colouring needs text tags and the gutter must follow wrapped lines.
"""

from __future__ import annotations

import bisect
import re
import tkinter as tk
from typing import Any

import customtkinter as ctk

PALETTES = {
    "Dark": dict(bg="#1b1f24", fg="#d6dde5", gutter_bg="#161a1f", gutter_fg="#6e7681", cursor="#e6edf3",
                 select="#264f78", command="#79c0ff", comment="#8b949e", math="#e3b341", env="#d2a8ff",
                 section="#7ee787", current="#232931", flash="#5a4a12", found="#3a5a2a"),
    "Light": dict(bg="#ffffff", fg="#1f2328", gutter_bg="#f3f4f6", gutter_fg="#8c959f", cursor="#1f2328",
                  select="#b6d7ff", command="#0550ae", comment="#6e7781", math="#953800", env="#8250df",
                  section="#116329", current="#f6f8fa", flash="#fff2b3", found="#c8f0c0"),
}
# Later entries win where they overlap (a comment hides everything inside it).
PATTERNS = [
    ("command", re.compile(r"\\(?:[A-Za-z@]+|.)")),
    ("section", re.compile(r"\\(?:part|chapter|(?:sub)*section|(?:sub)?paragraph|title|caption)\*?(?![A-Za-z])")),
    ("env", re.compile(r"\\(?:begin|end)\s*\{[^}\n]*\}")),
    ("math", re.compile(r"(?<!\\)\$[^$\n]+?(?<!\\)\$")),
    ("comment", re.compile(r"(?<!\\)%.*$", re.MULTILINE)),
]
HIGHLIGHT_DELAY_MS = 250


def palette() -> dict[str, str]:
    return PALETTES["Dark" if ctk.get_appearance_mode() == "Dark" else "Light"]


class CodeText(tk.Frame):
    """``self.text`` is the ``tk.Text``; call :meth:`changed` after loading new content."""

    def __init__(self, master: Any, font: tuple[str, int] = ("Consolas", 12)) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self._colors = palette()
        self.gutter = tk.Canvas(self, width=46, bd=0, highlightthickness=0)
        self.gutter.pack(side="left", fill="y")
        self.scroll = ctk.CTkScrollbar(self, command=self._yview)
        self.scroll.pack(side="right", fill="y")
        self.text = tk.Text(self, wrap="word", undo=True, maxundo=-1, autoseparators=True, font=font,
                            bd=0, highlightthickness=0, padx=8, pady=6, tabs=("2c",),
                            yscrollcommand=self._on_scroll)
        self.text.pack(side="left", fill="both", expand=True)
        self._font = font
        self._job: str | None = None
        for event in ("<KeyRelease>", "<ButtonRelease-1>", "<Configure>"):
            self.text.bind(event, lambda _e: self._refresh_view(), add="+")
        self.apply_theme()

    # ------------------------------------------------------------------ #
    def apply_theme(self) -> None:
        colors = palette()
        self.configure(bg=colors["bg"])
        self.gutter.configure(bg=colors["gutter_bg"])
        self.text.configure(bg=colors["bg"], fg=colors["fg"], insertbackground=colors["cursor"],
                            selectbackground=colors["select"])
        for tag, _pattern in PATTERNS:
            self.text.tag_configure(tag, foreground=colors[tag])
        self.text.tag_configure("current", background=colors["current"])
        self.text.tag_configure("flash", background=colors["flash"])
        self.text.tag_configure("found", background=colors["found"])
        self.text.tag_configure("comment", font=(self._font[0], self._font[1], "italic"))
        self.text.tag_raise("sel")
        self._colors = colors
        self._draw_gutter()

    def changed(self) -> None:
        """Schedule re-colouring (debounced) and redraw the gutter now."""
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(HIGHLIGHT_DELAY_MS, self.highlight)
        self._draw_gutter()

    def highlight(self) -> None:
        self._job = None
        content = self.text.get("1.0", "end-1c")
        starts = [0] + [m.end() for m in re.finditer("\n", content)]

        def index(offset: int) -> str:
            line = bisect.bisect_right(starts, offset) - 1
            return f"{line + 1}.{offset - starts[line]}"

        for tag, pattern in PATTERNS:
            self.text.tag_remove(tag, "1.0", "end")
            for match in pattern.finditer(content):
                self.text.tag_add(tag, index(match.start()), index(match.end()))
        for tag, _pattern in PATTERNS:
            self.text.tag_raise(tag)
        self.text.tag_raise("sel")

    # ------------------------------------------------------------------ #
    def flash_line(self, line: int) -> None:
        """Scroll to ``line``, put the cursor there and highlight it for a few seconds."""
        self.text.tag_remove("flash", "1.0", "end")
        self.text.tag_add("flash", f"{line}.0", f"{line}.0 lineend+1c")
        self.text.mark_set("insert", f"{line}.0")
        self.text.yview(f"{max(1, line - 3)}.0")  # the line near the top, with a little context above
        self.text.focus_set()
        self._refresh_view()
        self.after(3500, lambda: self.text.tag_remove("flash", "1.0", "end"))

    def find(self, needle: str, backwards: bool = False) -> bool:
        """Select the next (or previous) match of ``needle`` after the cursor, case-insensitively."""
        self.text.tag_remove("found", "1.0", "end")
        if not needle:
            return False
        start = self.text.index("insert" if backwards else "insert+1c")
        where = self.text.search(needle, start, backwards=backwards, nocase=True) or ""
        if not where:
            return False
        end = f"{where}+{len(needle)}c"
        self.text.tag_add("found", where, end)
        self.text.mark_set("insert", where)
        self.text.see(where)
        self._refresh_view()
        return True

    # ------------------------------------------------------------------ #
    def _yview(self, *args: Any) -> None:
        self.text.yview(*args)
        self._draw_gutter()

    def _on_scroll(self, first: str, last: str) -> None:
        self.scroll.set(first, last)
        self._draw_gutter()

    def _refresh_view(self) -> None:
        self.text.tag_remove("current", "1.0", "end")
        self.text.tag_add("current", "insert linestart", "insert lineend+1c")
        self.text.tag_lower("current")
        self._draw_gutter()

    def _draw_gutter(self) -> None:
        self.gutter.delete("all")
        last = int(self.text.index("end-1c").split(".")[0])
        width = 14 + 9 * len(str(last))
        self.gutter.configure(width=width)
        index = self.text.index("@0,0 linestart")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                if self.text.compare(index, "<", "@0,0"):  # a wrapped line whose start is scrolled away
                    index = self.text.index(f"{index}+1line")
                    continue
                break
            line = index.split(".")[0]
            self.gutter.create_text(width - 6, info[1] + 1, anchor="ne", text=line, font=self._font,
                                    fill=self._colors["gutter_fg"])
            nxt = self.text.index(f"{index}+1line")
            if nxt == index:
                break
            index = nxt
