"""Thread-safe plumbing between the agent worker thread and the GUI.

* :class:`EventBus` – a queue of :class:`AgentEvent` objects the GUI drains on a
  timer, so the worker never touches Tk widgets directly.
* :class:`ProposedChange` – a staged, not-yet-written file modification.
* :class:`ApprovalGate` – blocks the worker until a human approves or rejects a
  :class:`ProposedChange` in the diff window (human-in-the-loop).
* :class:`CancelToken` – cooperative cancellation for long-running workflows.
"""

from __future__ import annotations

import difflib
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class EventKind(str, Enum):
    """Categories of events streamed to the live log."""

    INFO = "info"
    STATE = "state"
    THOUGHT = "thought"
    LLM_TEXT = "llm_text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    ARTIFACT = "artifact"
    APPROVAL_REQUEST = "approval_request"
    AUTH_REQUIRED = "auth_required"
    PREVIEW = "preview"              # data: result=PreviewResult | compiling=<label>
    CONFIRM_PUSH = "confirm_push"    # data: request_id, summary, target
    FINISHED = "finished"


@dataclass
class AgentEvent:
    """A single log/stream event."""

    kind: EventKind
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    """Unbounded thread-safe event queue."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[AgentEvent]" = queue.Queue()

    def emit(self, kind: EventKind, message: str, **data: Any) -> None:
        """Publish an event from any thread."""
        self._queue.put(AgentEvent(kind=kind, message=message, data=data))

    def drain(self, limit: int = 1000) -> list[AgentEvent]:
        """Return up to ``limit`` pending events without blocking."""
        events: list[AgentEvent] = []
        while len(events) < limit:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events


@dataclass
class ProposedChange:
    """A file modification awaiting human approval.

    Attributes:
        repo_root: Root directory of the Git repository.
        rel_path: File path relative to ``repo_root``.
        original: Current file content (empty string for new files).
        proposed: Content that will be written on approval.
        description: Human-readable summary shown in the approval window.
        source_file: For binary assets (e.g. figures): the local file copied
            to ``rel_path`` on approval. ``original``/``proposed`` are unused.
        requires: Repo-relative paths of other changes this one depends on;
            it is dropped if any of them is rejected.
        replaces: For binary assets: overwrite the existing file at
            ``rel_path`` (replacing a figure) instead of adding a new one.
        moves: ``(from, to)`` repo-relative pairs for files that are only moved
            (used when a paper is organised into folders). One change carries the
            whole set, so the reviewer approves the move once.
    """

    repo_root: Path
    rel_path: str
    original: str
    proposed: str
    description: str
    approved: bool | None = None
    source_file: Path | None = None
    requires: tuple[str, ...] = ()
    replaces: bool = False
    moves: tuple[tuple[str, str], ...] = ()

    @property
    def abs_path(self) -> Path:
        return self.repo_root / self.rel_path

    @property
    def is_binary(self) -> bool:
        return self.source_file is not None

    def unified_diff(self, context: int = 3) -> str:
        """Return a unified diff of the change (a summary for binary assets and moves)."""
        if self.moves:
            lines = [f"{len(self.moves)} file(s) move; their content is not changed.", ""]
            width = max(len(old) for old, _new in self.moves)
            lines += [f"{old.ljust(width)}  ->  {new}" for old, new in self.moves]
            return "\n".join(lines) + "\n"
        if self.source_file is not None:
            size = self.source_file.stat().st_size if self.source_file.exists() else 0
            action = "Replace" if self.replaces else "New file"
            return (f"{action} {self.rel_path} ({size / 1024:,.0f} KB)\n"
                    f"copied from {self.source_file}\n")
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.proposed.splitlines(keepends=True),
                fromfile=f"a/{self.rel_path}",
                tofile=f"b/{self.rel_path}",
                n=context,
            )
        )

    @property
    def is_noop(self) -> bool:
        if self.moves:
            return not [m for m in self.moves if m[0] != m[1]]
        return self.source_file is None and self.original == self.proposed


class CancelledError(RuntimeError):
    """Raised inside the worker when the user presses Cancel."""


class CancelToken:
    """Cooperative cancellation flag shared by the GUI and worker."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledError("Workflow cancelled by user")


class ApprovalGate:
    """Blocks the worker thread until the GUI resolves an approval request."""

    def __init__(self, bus: EventBus, cancel: CancelToken) -> None:
        self._bus = bus
        self._cancel = cancel
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, list[bool]]] = {}
        self._next_id = 0

    def request(self, change: ProposedChange) -> bool:
        """Ask the user to approve ``change``; returns the decision.

        Raises:
            CancelledError: if the workflow is cancelled while waiting.
        """
        change.approved = self.ask(EventKind.APPROVAL_REQUEST, f"Approval required: {change.description}",
                                   change=change)
        return change.approved

    def ask(self, kind: EventKind, message: str, **data: Any) -> bool:
        """Emit ``kind`` with a ``request_id`` and block until the GUI resolves it."""
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            done = threading.Event()
            result: list[bool] = []
            self._pending[request_id] = (done, result)
        self._bus.emit(kind, message, request_id=request_id, **data)
        try:
            while not done.wait(timeout=0.25):
                self._cancel.raise_if_cancelled()
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        return bool(result and result[0])

    def resolve(self, request_id: int, approved: bool) -> None:
        """Called from the GUI thread with the user's decision."""
        with self._lock:
            entry = self._pending.get(request_id)
        if entry is None:
            return
        done, result = entry
        result.append(approved)
        done.set()
