"""Update window and main-window glue: check GitHub for a newer version and install it.

At start-up the check runs quietly (no message when offline or up to date);
Help ▸ Check for updates… reports every outcome.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.dependencies import tools_dir
from core.updater import Release, UpdateError, check, launch_swap, running_app_dir, stage
from gui.dialogs import MUTED, OK, _Dialog, run_in_background
from version import UPDATE_REPO, __version__


class UpdateDialog(_Dialog):
    def __init__(self, master: Any, release: Release, on_done: Callable[[bool], None]) -> None:
        super().__init__(master, "Update available", f"Version {release.version} is available",
                         f"You have version {__version__}. Your papers, settings and sign-ins are kept.")
        self.release, self.on_done = release, on_done
        self.app_dir = running_app_dir()
        if release.notes:
            self.label("What's new:")
            notes = ctk.CTkTextbox(self.body, width=460, height=150, wrap="word")
            notes.insert("1.0", release.notes[:3000])
            notes.configure(state="disabled")
            notes.grid(row=self._row, column=0, sticky="ew", pady=(0, 8))
            self._row += 1
        self.bar = ctk.CTkProgressBar(self.body, width=460)
        self.bar.set(0)
        if self.app_dir is None:
            self.label("You are running the app from its source code - update it with Git (git pull) instead.",
                       color=MUTED)
            self.finish_layout("Open release page", lambda: webbrowser.open(release.page))
        else:
            self.bar.grid(row=self._row, column=0, sticky="ew", pady=(4, 4))
            self._row += 1
            self.finish_layout("Update now", self.start)
        for child in self.buttons.winfo_children():
            if isinstance(child, ctk.CTkButton) and child.cget("text") == "Cancel":
                child.configure(text="Later")
        self._progress = (0, 0)
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        blocked = self.master.update_blocked()
        if blocked:
            self.fail(blocked)
            return
        self._running = True
        self.busy(f"Downloading version {self.release.version}…")
        run_in_background(self, lambda: stage(self.release, self.app_dir, progress=self._on_progress),
                          self._staged, self._failed)
        self.after(200, self._poll)

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)

    def _poll(self) -> None:
        done, total = self._progress
        if total:
            self.bar.set(done / total)
            self.status.configure(text=f"{done / 1e6:.0f} of {total / 1e6:.0f} MB", text_color=MUTED)
        if self._running:
            self.after(200, self._poll)

    def _staged(self, staged: Any) -> None:
        self._running = False
        self.bar.set(1)
        self.status.configure(text="Installing - the app restarts in a few seconds…", text_color=OK)
        launch = lambda: launch_swap(self.app_dir, staged, tools_dir() / "updates")  # noqa: E731
        if not self.master.quit_for_update(launch):
            self.fail("Update not installed: the app was not closed. It is downloaded; choose Update now again.")

    def _failed(self, exc: Exception) -> None:
        self._running = False
        self.fail(f"The update could not be installed: {exc}")

    def cancel(self) -> None:
        if not self._running:
            self.close(False)

    def close(self, ok: bool) -> None:
        super().close(ok)
        self.on_done(ok)


class UpdateMixin:
    """Needs ``self._workflow_running()``, ``self._editor_may_close()``, ``self._save_state()``."""

    def check_for_updates(self, then: Callable[[], None] | None = None, verbose: bool = False) -> None:
        """Ask GitHub in the background; show the update window if there is a newer version."""
        def done(release: Release | None) -> None:
            if release is not None:
                UpdateDialog(self, release, on_done=lambda _ok: then() if then else None)
                return
            if verbose:
                messagebox.showinfo("Updates", f"You have the latest version ({__version__}).", parent=self)
            if then:
                then()

        def failed(exc: Exception) -> None:
            if verbose:
                messagebox.showwarning("Updates", str(exc), parent=self)
            if then:
                then()

        run_in_background(self, lambda: check(__version__, UPDATE_REPO), done, failed)

    def update_blocked(self) -> str | None:
        if self._workflow_running() or self._todo_busy:
            return "A task is running - update when it has finished."
        return None

    def quit_for_update(self, launch: Callable[[], None]) -> bool:
        """Close the app so the update can replace it; ``False`` if the user kept it open."""
        if not self._editor_may_close():
            return False
        try:
            launch()
        except (OSError, UpdateError) as exc:
            messagebox.showerror("Update", f"Could not start the update: {exc}", parent=self)
            return False
        self._save_state()
        if self.cancel_token:
            self.cancel_token.cancel()
        self.after(200, self.destroy)
        return True
