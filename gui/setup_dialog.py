"""First-start setup: offer to install Git and MiKTeX when they are missing.

Shown at start-up (and from Help ▸ Install Git / MiKTeX…). Everything runs in the
background; the window shows one line per tool and a progress bar. Programs found at
start-up are what the app uses, so it offers to restart itself when it is done.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import customtkinter as ctk

from core.dependencies import (
    DependencyError, download, download_folder, git_installer, install_git, install_miktex, miktex_installer,
    missing_tools,
)
from gui.dialogs import MUTED, OK, _Dialog

WARN = "#e3b341"
LABELS = {"git": "Git (history of your papers, talking to Overleaf)",
          "miktex": "MiKTeX (builds the PDF of your paper)"}
STEPS = {"git": (git_installer, install_git), "miktex": (miktex_installer, install_miktex)}


def restart_app() -> None:
    """Start a fresh copy of the app (packaged .exe or ``python main.py``)."""
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable])  # noqa: S603 - our own executable
    else:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "main.py")])  # noqa: S603


class SetupDialog(_Dialog):
    def __init__(self, master: Any, missing: list[str], on_done: Callable[[bool], None]) -> None:
        heading = "Two helper programs are needed" if len(missing) > 1 else "A helper program is needed"
        super().__init__(master, "Set up the Research Assistant", heading,
                         "The Research Assistant installs them for you - only for your Windows account, without "
                         "administrator rights, from their official websites (each download is checked "
                         "against its published checksum). This takes a few minutes, mostly for MiKTeX "
                         "(about 140 MB) and Git (about 60 MB).")
        self.on_done = on_done
        self.missing = missing
        self.rows: dict[str, ctk.CTkLabel] = {}
        for tool in ("git", "miktex"):
            state = "needed" if tool in missing else "already installed ✓"
            self.rows[tool] = self.label(f"• {LABELS[tool]}: {state}", color=None if tool in missing else OK)
        self.bar = ctk.CTkProgressBar(self.body, width=460)
        self.bar.set(0)
        self.bar.grid(row=self._row, column=0, sticky="ew", pady=(6, 4))
        self._row += 1
        self.label("You can also do it later: Help ▸ Install Git / MiKTeX…", color=MUTED)
        self.finish_layout("Install now", self.start)
        self._cancel_requested = False
        self._running = False
        self._progress = (0, 0)
        self._messages: dict[str, tuple[str, str | None]] = {}  # latest line per tool, set by the worker
        self._finished: tuple[bool, list[str]] | None = None

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.busy("Starting…")
        threading.Thread(target=self._work, daemon=True, name="setup").start()
        self.after(150, self._poll)

    def _work(self) -> None:
        errors: list[str] = []
        for tool in self.missing:
            find, install = STEPS[tool]
            try:
                self._messages[tool] = ("finding the current version…", None)
                installer = find()
                self._messages[tool] = (f"downloading {installer.file_name}…", None)
                path = download(installer, download_folder(), progress=self._on_progress,
                                cancelled=lambda: self._cancel_requested)
                self._messages[tool] = ("installing (a window of the installer may appear)…", None)
                self._progress = (0, 0)
                install(path)
                self._messages[tool] = ("installed ✓", OK)
            except (DependencyError, OSError, subprocess.SubprocessError) as exc:
                errors.append(f"{tool}: {exc}")
                self._messages[tool] = (f"not installed - {exc}", WARN)
            if self._cancel_requested:
                break
        self._finished = (not errors and not self._cancel_requested, errors)

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)

    def _poll(self) -> None:
        default = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        for tool, (text, color) in list(self._messages.items()):
            self.rows[tool].configure(text=f"• {LABELS[tool]}: {text}", text_color=color or default)
        done, total = self._progress
        if total:
            self.bar.configure(mode="determinate")
            self.bar.set(done / total)
            self.status.configure(text=f"{done / 1e6:.0f} of {total / 1e6:.0f} MB", text_color=MUTED)
        elif done:
            self.status.configure(text=f"{done / 1e6:.0f} MB", text_color=MUTED)
        if self._finished is None:
            self.after(200, self._poll)
            return
        ok, errors = self._finished
        self._running = False
        self.bar.set(1 if ok else 0)
        if ok:
            self.missing = []
            self.bind("<Return>", lambda _e: self._restart())
            self.status.configure(text="Done. Restart the Research Assistant to use them.", text_color=OK)
            self.primary.configure(text="Restart now", state="normal", command=self._restart)
        else:
            still = missing_tools()
            self.fail("Not everything could be installed:\n" + "\n".join(errors) if errors else "Cancelled.")
            self.primary.configure(text="Try again" if still else "Restart now",
                                   command=self._retry if still else self._restart)
            self.missing = still

    def _retry(self) -> None:
        self._finished, self._cancel_requested = None, False
        self.start()

    def _restart(self) -> None:
        restart_app()
        self.close(True)
        quit_app = getattr(self.master, "_on_close", self.master.destroy)  # saves settings, asks about edits
        self.master.after(100, quit_app)

    def cancel(self) -> None:
        if self._running:
            self._cancel_requested = True  # stops a download; a running installer finishes first
            self.status.configure(text="Stopping after the current step…", text_color=MUTED)
            return
        self.close(False)

    def close(self, ok: bool) -> None:
        super().close(ok)
        self.on_done(ok)
