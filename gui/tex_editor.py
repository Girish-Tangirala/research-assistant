"""The "Edit .tex" tab: an Overleaf-style source editor for the selected paper.

* Pick any text file of the paper (``.tex``, ``.bib``, ``.cls`` ...) from the file list.
* **Save & Recompile** (Ctrl+S) writes the file, commits it locally (so Sync and the
  agent keep working - they refuse uncommitted changes) and rebuilds the PDF.
* A click in the PDF (click mode "Edit .tex") opens the source line here.
* Files changed on disk by a task or a sync are reloaded; unsaved edits are never
  overwritten silently.
* Read-only files (reference-manager ``.bib``, ``data/``, ``code/``) open read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.events import EventKind
from core.latex_parser import find_main_tex
from core.paper import read_text, write_text_preserving_eol
from gui.dialogs import run_in_background
from gui.tex_highlight import CodeText

EDITABLE_SUFFIXES = {".tex", ".bib", ".cls", ".sty", ".bst", ".bbx", ".cbx", ".md", ".txt"}
NO_FILE = "— no file —"
WATCH_MS = 1500
MUTED, WARN, OK = "#8b949e", "#e3b341", "#3fb950"


@dataclass
class EditorContext:
    paper_root: Callable[[], Path | None]
    read_only_reason: Callable[[Path, str], str | None]
    save_blocked: Callable[[], str | None]      # why saving is not possible right now (a task is running)
    commit: Callable[[Path, str], str]          # background thread: commit one file, return a short note
    recompile: Callable[[], None]
    notify: Callable[[EventKind, str], None]


def editable_files(root: Path) -> list[str]:
    """Text files of the paper, main document first."""
    if not root.is_dir():
        return []
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in EDITABLE_SUFFIXES and ".git" not in p.parts)
    main = find_main_tex(root)
    if main is not None and main.relative_to(root).as_posix() in files:
        first = main.relative_to(root).as_posix()
        files.remove(first)
        files.insert(0, first)
    return files


class TexEditor(ctk.CTkFrame):
    def __init__(self, master: Any, ctx: EditorContext) -> None:
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.root: Path | None = None   # the paper folder the open file belongs to
        self.rel: str | None = None
        self._saved_text = ""
        self._mtime: float | None = None
        self._saving = False

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 4))
        self.file_menu = ctk.CTkOptionMenu(bar, values=[NO_FILE], width=260, dynamic_resizing=False,
                                           command=lambda rel: self.open_file(rel))
        self.file_menu.pack(side="left")
        ctk.CTkButton(bar, text="↻", width=30, fg_color="transparent", border_width=1,
                      command=self.refresh_files).pack(side="left", padx=(4, 0))
        self.save_button = ctk.CTkButton(bar, text="💾 Save & Recompile", width=150, fg_color="#1f6f3a",
                                         hover_color="#27894a", command=self.save)
        self.save_button.pack(side="right")

        find = ctk.CTkFrame(self, fg_color="transparent")
        find.pack(fill="x", pady=(0, 4))
        self.find_entry = ctk.CTkEntry(find, placeholder_text="Find (Ctrl+F)", width=200)
        self.find_entry.pack(side="left")
        self.find_entry.bind("<Return>", lambda _e: self._find())
        self.find_entry.bind("<Shift-Return>", lambda _e: self._find(backwards=True))
        ctk.CTkButton(find, text="▼", width=28, command=self._find).pack(side="left", padx=(4, 0))
        ctk.CTkButton(find, text="▲", width=28, command=lambda: self._find(True)).pack(side="left", padx=(2, 0))
        self.reload_button = ctk.CTkButton(find, text="Reload from disk", width=120, fg_color="#9e5a1c",
                                           hover_color="#b86a23", command=lambda: self._load(self.rel))
        self.status = ctk.CTkLabel(find, text="", text_color=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8)

        self.code = CodeText(self)
        self.code.pack(fill="both", expand=True)
        text = self.code.text
        text.bind("<<Modified>>", self._modified)
        for widget in (text, self.find_entry):
            widget.bind("<Control-s>", lambda _e: (self.save(), "break")[1])
            widget.bind("<Control-f>", lambda _e: (self.find_entry.focus_set(), "break")[1])
        self.after(WATCH_MS, self._watch)

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #
    @property
    def dirty(self) -> bool:
        return self.rel is not None and self.code.text.get("1.0", "end-1c") != self._saved_text

    def _modified(self, _event: Any = None) -> None:
        if self.code.text.edit_modified():
            self.code.text.edit_modified(False)
            self.code.changed()
            self._show_status()

    def _show_status(self, text: str | None = None, color: str = MUTED) -> None:
        if text is None:
            if self.rel is None:
                text = "Choose a file of the paper to edit."
            elif self._read_only():
                text, color = f"Read-only: {self._read_only()}", WARN
            elif self.dirty:
                text, color = "● Unsaved changes - Ctrl+S saves and recompiles", WARN
            else:
                text = "Saved"
        self.status.configure(text=text, text_color=color)

    def _read_only(self) -> str | None:
        return self.ctx.read_only_reason(self.root, self.rel) if self.rel and self.root else None

    def _path(self, rel: str | None) -> Path | None:
        return self.root / rel if self.root is not None and rel else None

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #
    def refresh_files(self) -> list[str]:
        files = editable_files(self.root) if self.root is not None else []
        self.file_menu.configure(values=files or [NO_FILE])
        self.file_menu.set(self.rel if self.rel in files else (NO_FILE if not files else self.file_menu.get()))
        return files

    def paper_changed(self) -> None:
        """Another paper was selected (or the folder appeared): offer to save, then open its main file."""
        if self.dirty and messagebox.askyesno("Unsaved changes", f"Save your changes to {self.rel} first?",
                                              parent=self):
            self.save(recompile=False, blocking=True)  # commit before the paper (and its folder) changes
        self.rel, self._saved_text, self._mtime = None, "", None
        self.root = self.ctx.paper_root()
        self.code.text.configure(state="normal")
        self.code.text.delete("1.0", "end")
        files = self.refresh_files()
        if files:
            self._load(files[0])
        else:
            self.file_menu.set(NO_FILE)
            self._show_status()

    def open_file(self, rel: str, line: int | None = None) -> None:
        """Show ``rel`` (asking about unsaved edits in another file) and jump to ``line``."""
        if rel == NO_FILE:
            return
        if rel != self.rel:
            if not self._confirm_leave():
                self.file_menu.set(self.rel or NO_FILE)
                return
            if not self._load(rel):
                return
        if line:
            self.code.flash_line(line)

    def _confirm_leave(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", f"Save your changes to {self.rel}?", parent=self)
        if answer is None:
            return False
        if answer:
            self.save(recompile=False)
        return True

    def _load(self, rel: str | None, keep_view: bool = False) -> bool:
        path = self._path(rel)
        if path is None or not path.is_file():
            self._show_status(f"{rel} does not exist (any more).", WARN)
            return False
        view, cursor = self.code.text.yview()[0], self.code.text.index("insert")
        content = read_text(path).replace("\r\n", "\n")
        text = self.code.text
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", content)
        text.edit_reset()
        text.edit_modified(False)
        self.rel, self._saved_text, self._mtime = rel, content, path.stat().st_mtime
        self.refresh_files()
        self.file_menu.set(rel)
        text.configure(state="disabled" if self._read_only() else "normal")
        if keep_view:
            text.mark_set("insert", cursor)
            text.yview_moveto(view)
        else:
            text.mark_set("insert", "1.0")
            text.yview_moveto(0)
        self.reload_button.pack_forget()
        self.code.highlight()
        self.code.changed()
        self._show_status()
        return True

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def save(self, recompile: bool = True, blocking: bool = False) -> None:
        """Write the file, commit it locally in the background, then recompile the PDF."""
        if self.rel is None or self._read_only() or self._saving:
            return
        path = self._path(self.rel)
        if not self.dirty:
            if recompile:
                self.ctx.recompile()
            return
        blocked = self.ctx.save_blocked()
        if blocked:
            self._show_status(blocked, WARN)
            return
        if path is not None and path.exists() and path.stat().st_mtime != self._mtime \
                and read_text(path).replace("\r\n", "\n") != self._saved_text:
            if not messagebox.askyesno("Changed on disk", f"{self.rel} was changed outside the editor (by a task "
                                       "or a sync) after you opened it.\n\nOverwrite it with your version?",
                                       parent=self):
                return
        content = self.code.text.get("1.0", "end-1c")
        write_text_preserving_eol(path, content)
        self._saved_text, self._mtime = content, path.stat().st_mtime
        self.reload_button.pack_forget()
        self._saving = True
        root, rel = self.root, self.rel
        self._show_status(f"Saved {rel} - committing…")

        def done(note: str) -> None:
            self._saving = False
            self._show_status(f"Saved {rel} · {note}", OK)
            if recompile:
                self.ctx.recompile()

        def failed(exc: Exception) -> None:
            self._saving = False
            self._show_status(f"Saved {rel}, but not committed: {exc}", WARN)
            self.ctx.notify(EventKind.WARNING, f"{rel} was saved but not committed: {exc}")
            if recompile:
                self.ctx.recompile()

        if blocking:  # the window is closing - a background thread would be killed mid-commit
            try:
                done(self.ctx.commit(root, rel))
            except Exception as exc:  # noqa: BLE001 - reported like a background failure
                failed(exc)
            return
        run_in_background(self, lambda: self.ctx.commit(root, rel), done, failed)

    def has_unsaved(self) -> bool:
        return self.dirty

    # ------------------------------------------------------------------ #
    # Find and watching the disk
    # ------------------------------------------------------------------ #
    def _find(self, backwards: bool = False) -> None:
        needle = self.find_entry.get()
        if needle and not self.code.find(needle, backwards):
            self._show_status(f"'{needle}' not found", WARN)

    def _watch(self) -> None:
        try:
            path = self._path(self.rel)
            if path is not None and path.exists() and not self._saving and path.stat().st_mtime != self._mtime:
                disk = read_text(path).replace("\r\n", "\n")
                if disk == self._saved_text:
                    self._mtime = path.stat().st_mtime
                elif not self.dirty:
                    self._load(self.rel, keep_view=True)
                    self._show_status(f"Reloaded {self.rel} - it was changed on disk", OK)
                else:
                    self._mtime = path.stat().st_mtime
                    self._show_status("Changed on disk too - Save keeps yours, Reload takes the disk version", WARN)
                    self.reload_button.pack(side="left", padx=(8, 0), before=self.status)
        except OSError:
            pass
        finally:
            self.after(WATCH_MS, self._watch)
