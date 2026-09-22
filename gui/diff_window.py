"""Diff / approval window for staged changes (non-modal, so the PDF preview stays usable)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import customtkinter as ctk

from core.events import ProposedChange

DIFF_COLORS = {
    "add": "#3fb950",
    "del": "#f85149",
    "hunk": "#58a6ff",
    "meta": "#8b949e",
}


class DiffWindow(ctk.CTkToplevel):
    """Shows a unified diff and returns the reviewer's decision via callback.

    Closing the window counts as a rejection, so a change can never be applied
    without an explicit click on *Approve*.
    """

    def __init__(self, master: ctk.CTk, change: ProposedChange, on_decision: Callable[[bool], None]) -> None:
        super().__init__(master)
        self._on_decision = on_decision
        self._decided = False
        self.title(f"Review change – {change.rel_path}")
        self.geometry("900x720")
        self.minsize(700, 400)
        self.protocol("WM_DELETE_WINDOW", lambda: self._decide(False))

        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(header, text=change.description, font=ctk.CTkFont(size=15, weight="bold"),
                     wraplength=1000, justify="left", anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        diff = change.unified_diff()
        added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
        ctk.CTkLabel(header, text=f"{change.rel_path}   +{added} / −{removed} lines   "
                                  f"(repository: {change.repo_root})",
                     text_color=DIFF_COLORS["meta"], anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        if change.is_binary:
            self._preview(change)
        self.textbox = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=13), wrap="none",
                                      height=80 if change.is_binary else 200)
        self.textbox.pack(fill="both", expand=True, padx=12, pady=6)
        for tag, color in DIFF_COLORS.items():
            self.textbox.tag_config(tag, foreground=color)
        self._render(diff or "(no textual differences)")
        self.textbox.configure(state="disabled")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkButton(buttons, text="Reject", fg_color="#6e2b2b", hover_color="#8b3535", width=140,
                      command=lambda: self._decide(False)).pack(side="right", padx=(8, 0))
        ctk.CTkButton(buttons, text="Approve & Apply", fg_color="#1f6f3a", hover_color="#27894a", width=180,
                      command=lambda: self._decide(True)).pack(side="right")
        ctk.CTkLabel(buttons, text="Approved changes are written, compiled, committed on a feature branch "
                                   "and pushed (if enabled).",
                     text_color=DIFF_COLORS["meta"]).pack(side="left")

        self.after(100, self._focus)

    def _preview(self, change: ProposedChange) -> None:
        """Thumbnail for image assets; current vs new when an image is replaced."""
        images = [("New", change.source_file)]
        if change.replaces and change.abs_path.exists():
            images.insert(0, ("Current", change.abs_path))
        size = (900, 520) if len(images) == 1 else (430, 480)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(padx=12, pady=6)
        for column, (caption, path) in enumerate(images):
            picture = self._thumbnail(path, size)
            if len(images) > 1:
                ctk.CTkLabel(row, text=caption, font=ctk.CTkFont(weight="bold")).grid(row=0, column=column)
            ctk.CTkLabel(row, image=picture, text="" if picture else f"({path.suffix} file - no preview)").grid(
                row=1, column=column, padx=8)

    @staticmethod
    def _thumbnail(path: Path, size: tuple[int, int]) -> ctk.CTkImage | None:
        try:
            from PIL import Image

            with Image.open(path) as image:
                image.thumbnail(size)
                return ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=image.size)
        except (ImportError, OSError):
            return None

    def _focus(self) -> None:
        """Bring the window forward without grabbing input, so the PDF preview stays usable."""
        master = self.master
        try:
            self.geometry(f"+{master.winfo_rootx() + 20}+{master.winfo_rooty() + 40}")
        except Exception:  # master not mapped yet
            pass
        self.lift()
        self.focus_force()

    def _render(self, diff: str) -> None:
        for line in diff.splitlines(keepends=True):
            if line.startswith(("+++", "---")):
                tag = "meta"
            elif line.startswith("@@"):
                tag = "hunk"
            elif line.startswith("+"):
                tag = "add"
            elif line.startswith("-"):
                tag = "del"
            else:
                tag = None
            self.textbox.insert("end", line, tag) if tag else self.textbox.insert("end", line)

    def _decide(self, approved: bool) -> None:
        if self._decided:
            return
        self._decided = True
        self.destroy()
        self._on_decision(approved)
