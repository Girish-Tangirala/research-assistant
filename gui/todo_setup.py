"""Setting up the shared to-do list, and moving the old per-paper lists into it.

Kept out of :mod:`gui.app` so that file stays under the 500-line limit.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.agent_engine import with_identity
from core.app_state import TodoRepoSettings, validate_todo_repo
from core.credentials import host_of
from core.events import EventKind
from core.git_manager import GitManager
from gui.dialogs import _Dialog, run_in_background

HELP = ("One shared to-do list for all your papers, kept in a small Git repository of its own - "
        "not in a paper, so a to-do change never touches a manuscript and never waits for Sync.\n\n"
        "Create an empty private repository (tick “Add a README”), invite the people you work "
        "with, and paste its link below. Everyone signs in to that host under Accounts with their "
        "own token.")


class TodoRepoDialog(_Dialog):
    """Where the shared to-do list lives."""

    def __init__(self, master: Any, settings: TodoRepoSettings,
                 on_save: Callable[[TodoRepoSettings], None]) -> None:
        super().__init__(master, "Shared to-do list", "Shared to-do list", HELP)
        self.on_save = on_save
        self.url = self.entry("Repository link", settings.url,
                              placeholder="https://github.com/you/research-todo.git")
        self.branch = self.entry("Branch (optional)", settings.branch, placeholder="leave empty for the default")
        self.hint = ctk.CTkLabel(self.body, text="", text_color="#8b949e", anchor="w", justify="left",
                                 wraplength=460)
        self.hint.grid(row=self._row, column=0, sticky="ew", pady=(0, 8))
        self._row += 1
        self.finish_layout("Save", self.submit)
        self._show_host()
        self.url.bind("<KeyRelease>", lambda _e: self._show_host())

    def _show_host(self) -> None:
        host = host_of(self.url.get().strip())
        self.hint.configure(text=f"You will need a sign-in for {host} under Accounts, with permission to "
                                 f"read and write this repository." if host else "")

    def submit(self) -> None:
        settings = TodoRepoSettings(url=self.url.get().strip(), branch=self.branch.get().strip())
        problems = validate_todo_repo(settings)
        if problems:
            self.fail(" ".join(problems))
            return
        super().close(True)
        self.on_save(settings)


class TodoSetupMixin:
    """Needs ``self.app_state``, ``self.config_``, ``self.store``, ``self.todo`` and ``self.panel``."""

    def _edit_todo_repo(self) -> None:
        TodoRepoDialog(self, self.app_state.todo_repo, self._save_todo_repo)

    def _save_todo_repo(self, settings: TodoRepoSettings) -> None:
        self.app_state.todo_repo = settings
        self._save_state()
        self.todo.doc = None
        self.todo.paper_changed()
        if settings.configured:
            self.panel.append(EventKind.INFO, f"Shared to-do list: {settings.url}")
            self.todo.refresh()

    def _migrate_todo_lists(self) -> None:
        """Move every paper's todo.md into the shared list, then remove it from the paper."""
        from core.global_todos import migrate_paper_lists
        from core.todos import TodoError

        papers = self.app_state.papers
        if not papers:
            messagebox.showinfo("Move the to-do lists", "There are no papers to move a list from.", parent=self)
            return
        if not messagebox.askyesno(
                "Move the to-do lists",
                f"Move the tasks from {len(papers)} paper(s) into the shared list, then delete todo.md "
                "from each paper?\n\nThe deletion is committed on this computer only - press Sync on each "
                "paper afterwards to remove it from Overleaf too.\n\nTasks already in the shared list are "
                "left alone, so this is safe to run twice.", parent=self):
            return
        try:
            store = self.todo.ctx.make_store()
        except TodoError as exc:
            messagebox.showwarning("Move the to-do lists", str(exc), parent=self)
            return

        def job():
            return migrate_paper_lists(store, self._paper_repos(),
                                       log=lambda m: self.bus.emit(EventKind.INFO, m))

        def ok(report) -> None:
            self.panel.append(EventKind.SUCCESS if report.changed else EventKind.INFO, report.as_text())
            messagebox.showinfo("Move the to-do lists", report.as_text(), parent=self)
            self.todo.refresh()

        run_in_background(self, job, ok, self._todo_error)

    def _paper_repos(self) -> list[tuple[str, Any]]:
        """``(name, GitManager)`` for every paper, for the migration."""
        config = with_identity(self.config_, self.app_state.author_name, self.app_state.author_email)
        repos = []
        for spec in self.app_state.papers:
            host, _ = self._paper_host(spec)
            credential = self._safe(lambda h=host: self.store.get_git(h)) if host else None
            local = spec.local_path.strip() or str(self.config_.papers_dir / spec.name)
            repos.append((spec.name, GitManager(Path(local), spec.remote_url, spec.branch, config.git,
                                                credential=credential,
                                                log=lambda m: self.bus.emit(EventKind.INFO, m))))
        return repos
