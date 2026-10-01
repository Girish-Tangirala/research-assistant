"""The shared to-do list: one list for every paper, in its own small repository.

Until 1.2.0 each paper carried its own ``todo.md``. That tied a task to a
manuscript, so cross-paper work had nowhere to live and every change pushed to
Overleaf. The list now lives in a repository of its own
(:class:`~core.app_state.TodoRepoSettings`), cloned into ``workspace/todo``:

* one list, whichever paper is selected - each task may *name* a paper instead;
* to-do changes never touch a manuscript, so they never wait for **Sync**;
* :class:`~core.todos.TodoStore` is unchanged - it only ever needed a repository.

:func:`migrate_paper_lists` moves the old per-paper lists in and removes them
from the papers. It is safe to run twice: tasks keep their ids, so a task that
is already in the shared list is skipped rather than duplicated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from core.app_state import TodoRepoSettings
from core.credentials import GitCredential, host_of
from core.git_manager import GitManager, GitOperationError
from core.protection import SHARED_TODO_FILE as TODO_FILE
from core.todos import TodoDoc, TodoError, TodoItem, TodoStore

FOLDER = "todo"          # inside the app's workspace, next to papers/ and reports/
LogFn = Callable[[str], None]


def clone_path(workspace: Path) -> Path:
    return Path(workspace) / FOLDER


def open_store(workspace: Path, settings: TodoRepoSettings, author: str,
               credential: GitCredential | None = None, git_settings=None,
               log: LogFn | None = None) -> TodoStore:
    """The store for the shared list.

    Raises:
        TodoError: with a user-facing reason when it is not set up or not signed in.
    """
    if not settings.configured:
        raise TodoError("The shared to-do list is not set up yet - choose "
                        "Options ▸ Shared to-do list… and paste the repository link.")
    host = host_of(settings.url)
    if host and credential is None:
        raise TodoError("Sign in to {host} (Accounts menu) to use the shared to-do list.", host=host)
    git = GitManager(clone_path(workspace), settings.url, settings.branch, git_settings,
                     credential=credential, log=_quiet(log))
    # Always push: this repository holds nothing but the list, so there is no
    # half-finished manuscript to protect and nothing for Sync to decide.
    return TodoStore(git, author, push=True, log=log)


# Routine Git chatter from the background refresh, which runs every 45 seconds. The
# first clone and anything unusual still reach the log; "Pulling origin/main" does not.
ROUTINE = ("Pulling ", "Checking out ")


def _quiet(log: LogFn | None) -> LogFn | None:
    if log is None:
        return None

    def filtered(message: str) -> None:
        if not message.startswith(ROUTINE):
            log(message)
    return filtered


@dataclass
class MigrationReport:
    """What :func:`migrate_paper_lists` did, in the user's words."""

    imported: int = 0
    skipped: int = 0
    papers_cleared: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.imported or self.papers_cleared)

    def as_text(self) -> str:
        lines = []
        if self.imported:
            lines.append(f"Moved {self.imported} task(s) into the shared list.")
        if self.skipped:
            lines.append(f"{self.skipped} task(s) were already there.")
        if not self.imported and not self.skipped:
            lines.append("There were no tasks to move.")
        if self.papers_cleared:
            lines.append("Removed todo.md from: " + ", ".join(self.papers_cleared)
                         + ". Press Sync on each of those papers to remove it from Overleaf too.")
        lines += [f"Could not finish {p}" if not p.endswith(".") else p for p in self.problems]
        return "\n".join(lines)


def read_paper_items(root: Path, paper_name: str) -> list[TodoItem]:
    """Tasks in a paper's own ``todo.md``, each tagged with the paper's name."""
    path = Path(root) / TODO_FILE
    if not path.is_file():
        return []
    items = TodoDoc.parse(path.read_text(encoding="utf-8", errors="replace")).items
    for item in items:
        item.paper = item.paper or paper_name
    return items


def migrate_paper_lists(store: TodoStore, papers: list[tuple[str, GitManager]],
                        log: LogFn | None = None) -> MigrationReport:
    """Move every paper's ``todo.md`` into the shared list, then remove it from the paper.

    The removal is committed locally only: it reaches Overleaf when the user
    presses Sync, like every other change to a paper.
    """
    say = log or (lambda _m: None)
    report = MigrationReport()

    existing = {item.id for item in store.refresh().items}
    for name, git in papers:
        try:
            items = read_paper_items(git.local_path, name)
        except OSError as exc:
            report.problems.append(f"Could not read the to-do list of {name}: {exc}.")
            continue
        for item in items:
            if item.id in existing:
                report.skipped += 1
                continue
            store.apply(_op_import(item))
            existing.add(item.id)
            report.imported += 1
            say(f"Moved '{item.text[:60]}' from {name} into the shared list.")

        path = Path(git.local_path) / TODO_FILE
        if not path.is_file():
            continue
        try:
            path.unlink()
            git.commit([TODO_FILE], "To-do: move the list into the shared to-do repository")
            report.papers_cleared.append(name)
            say(f"Removed todo.md from {name} (committed locally - press Sync to send it to Overleaf).")
        except (OSError, GitOperationError) as exc:
            report.problems.append(f"Could not remove todo.md from {name}: {exc}.")
    return report


def _op_import(item: TodoItem):
    """Add ``item`` to the shared list exactly as it was, keeping its id and history."""
    def apply(doc: TodoDoc) -> str:
        doc.add(TodoItem(**asdict(item)))
        return f"move '{item.text[:60]}' from {item.paper or 'a paper'}"
    return apply
