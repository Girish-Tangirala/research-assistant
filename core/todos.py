"""Shared to-do list stored in the paper's repository (``todo.md``).

Everyone with access to the paper (Overleaf or GitHub) shares the list through
the normal Git sync. The file stays human-readable - it can be ticked or edited
in Overleaf - while each task line carries its metadata in an HTML comment::

    - [ ] Fix Fig. 3 caption — @Girish · due 2026-10-01 · § Results <!-- todo {"id": "7f3a1c", ...} -->

Concurrency: every change is an *operation* applied to the freshly pulled file,
committed on its own and pushed. If someone else pushed first, the local commit
is dropped, the file is pulled again and the operation is re-applied, so
simultaneous edits by different users never overwrite each other (for the same
task, the last change wins).
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

from core.git_manager import GitManager, GitOperationError
from core.protection import SHARED_TODO_FILE as TODO_FILE
HEADER = ("# To-do list\n\n"
          "<!-- Shared by the Research Assistant Agent app. One task per line: you can tick [x] or edit the task "
          "text here in Overleaf; the app keeps the details in the comment at the end of each line. -->\n")
COMMIT_PREFIX = "To-do: "
MAX_ATTEMPTS = 3
_TASK_RE = re.compile(r"^\s*[-*]\s+\[(?P<mark>[ xX])\]\s+(?P<body>.*?)\s*(?:<!--\s*todo\s+(?P<meta>\{.*\})\s*-->)?\s*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEPARATOR = " — "


class TodoError(RuntimeError):
    """A to-do operation failed (message is user-facing)."""


def _clean(text: str) -> str:
    return " ".join((text or "").replace("<!--", "").replace("-->", "").split())


def validate_due(value: str) -> str:
    value = (value or "").strip()
    if value and (not _DATE_RE.match(value) or not _is_date(value)):
        raise TodoError(f"Due date must look like 2026-10-01, got {value!r}.")
    return value


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


@dataclass
class TodoItem:
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    done: bool = False
    assignee: str = ""
    due: str = ""
    section: str = ""
    by: str = ""
    created: str = field(default_factory=lambda: date.today().isoformat())
    done_by: str = ""

    def is_overdue(self, today: date | None = None) -> bool:
        return bool(not self.done and self.due and _is_date(self.due)
                    and date.fromisoformat(self.due) < (today or date.today()))

    def render(self) -> str:
        details = [f"@{self.assignee}" if self.assignee else "", f"due {self.due}" if self.due else "",
                   f"§ {self.section}" if self.section else "", f"done by {self.done_by}" if self.done and self.done_by else ""]
        visible = _clean(self.text) + (_SEPARATOR + " · ".join(d for d in details if d) if any(details) else "")
        meta = {k: v for k, v in asdict(self).items() if k not in {"text", "done"} and v}
        return f"- [{'x' if self.done else ' '}] {visible} <!-- todo {json.dumps(meta, ensure_ascii=False)} -->"

    @classmethod
    def parse(cls, line: str) -> "TodoItem | None":
        match = _TASK_RE.match(line)
        if not match:
            return None
        body = match.group("body")
        item = cls(text="")
        if match.group("meta"):
            try:
                meta = json.loads(match.group("meta"))
            except ValueError:
                meta = {}
            for key in ("id", "assignee", "due", "section", "by", "created", "done_by"):
                if isinstance(meta.get(key), str):
                    setattr(item, key, meta[key])
            body = body.split(_SEPARATOR, 1)[0]  # details after the separator are regenerated from meta
        item.text = _clean(body)
        item.done = match.group("mark").lower() == "x"  # ticking in Overleaf is honoured
        return item if item.text else None


class TodoDoc:
    """A parsed ``todo.md``: task lines become items; other lines are kept verbatim."""

    def __init__(self, lines: list[str | TodoItem]) -> None:
        self.lines = lines

    @classmethod
    def parse(cls, text: str) -> "TodoDoc":
        if not text.strip():
            return cls(HEADER.rstrip("\n").split("\n") + [""])
        lines: list[str | TodoItem] = []
        seen: set[str] = set()
        for raw in text.splitlines():
            item = TodoItem.parse(raw)
            if item is not None and item.id in seen:
                item.id = uuid.uuid4().hex[:8]  # copy-pasted line: give it its own identity
            if item is not None:
                seen.add(item.id)
            lines.append(item if item is not None else raw)
        return cls(lines)

    @property
    def items(self) -> list[TodoItem]:
        return [line for line in self.lines if isinstance(line, TodoItem)]

    def get(self, item_id: str) -> TodoItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise TodoError("This task no longer exists - someone may have deleted it.")

    def add(self, item: TodoItem) -> None:
        last = max((i for i, line in enumerate(self.lines) if isinstance(line, TodoItem)), default=None)
        if last is None:
            while self.lines and isinstance(self.lines[-1], str) and not self.lines[-1].strip():
                self.lines.pop()
            self.lines += ["", item]
        else:
            self.lines.insert(last + 1, item)

    def delete(self, item_id: str) -> TodoItem:
        item = self.get(item_id)
        self.lines.remove(item)
        return item

    def render(self) -> str:
        return "\n".join(line.render() if isinstance(line, TodoItem) else line for line in self.lines).rstrip() + "\n"


Operation = Callable[[TodoDoc], str]


def op_add(text: str, author: str, assignee: str = "", due: str = "", section: str = "") -> Operation:
    text = _clean(text)
    if not text:
        raise TodoError("Enter the task text.")
    item = TodoItem(text=text, assignee=_clean(assignee), due=validate_due(due), section=_clean(section),
                    by=_clean(author))

    def apply(doc: TodoDoc) -> str:
        doc.add(TodoItem(**asdict(item)))
        return f"add '{text[:60]}'"
    return apply


def op_update(item_id: str, author: str, **fields: object) -> Operation:
    if "due" in fields:
        fields["due"] = validate_due(str(fields["due"]))
    if "text" in fields and not _clean(str(fields["text"])):
        raise TodoError("The task text cannot be empty.")

    def apply(doc: TodoDoc) -> str:
        item = doc.get(item_id)
        for key, value in fields.items():
            setattr(item, key, value if isinstance(value, bool) else _clean(str(value)))
        if "done" in fields:
            item.done_by = _clean(author) if item.done else ""
            return f"{'complete' if item.done else 'reopen'} '{item.text[:60]}'"
        return f"update '{item.text[:60]}'"
    return apply


def op_delete(item_id: str) -> Operation:
    def apply(doc: TodoDoc) -> str:
        return f"delete '{doc.delete(item_id).text[:60]}'"
    return apply


class TodoStore:
    """Reads and changes ``todo.md`` in one paper's repository, safely for many users."""

    _locks: dict[str, threading.Lock] = {}  # one Git operation at a time per repository folder
    _locks_guard = threading.Lock()

    def __init__(self, git: GitManager, author: str, push: bool = True,
                 log: Callable[[str], None] | None = None) -> None:
        self.git = git
        with self._locks_guard:
            self._lock = self._locks.setdefault(str(git.local_path).lower(), threading.Lock())
        self.author = author or git.settings.author_name
        self.push = push
        self._log = log or (lambda _msg: None)

    @property
    def path(self):
        return self.git.local_path / TODO_FILE

    def read(self) -> TodoDoc:
        return TodoDoc.parse(self.path.read_text(encoding="utf-8") if self.path.exists() else "")

    def refresh(self) -> TodoDoc:
        """Pull the latest version of the paper and return the list."""
        with self._lock:
            self.git.sync()
            return self.read()

    def apply(self, operation: Operation) -> TodoDoc:
        """Apply ``operation`` to the latest list, commit it and push it (with retries)."""
        with self._lock:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                self.git.sync()
                doc = self.read()
                description = operation(doc)
                new_text = doc.render()
                old_text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
                if new_text == old_text:
                    return doc
                self.path.write_text(new_text, encoding="utf-8", newline="\n")
                try:
                    self.git.commit([TODO_FILE], COMMIT_PREFIX + description)
                except GitOperationError:
                    if old_text:
                        self.git.discard_changes([TODO_FILE])
                    else:
                        self.path.unlink(missing_ok=True)
                    raise
                if not self.push:
                    self._log("Push is off - this to-do change stays on this computer until you push.")
                    return doc
                try:
                    self.git.push(self.git.default_branch)
                    return doc
                except GitOperationError as exc:
                    self.git.undo_last_commit(COMMIT_PREFIX)
                    if attempt == MAX_ATTEMPTS or "remote has new commits" not in str(exc):
                        raise
                    self._log("Someone else changed the paper at the same time - retrying the to-do update.")
        raise TodoError("Could not save the to-do change.")  # pragma: no cover

    def people(self) -> list[str]:
        """Names for the assignee picker: recent committers, current assignees and you."""
        names = {self.author} | {i.assignee for i in self.read().items if i.assignee}
        try:
            names |= set(self.git.recent_authors())
        except GitOperationError:
            pass
        return sorted(n for n in names if n and n != "Overleaf")
