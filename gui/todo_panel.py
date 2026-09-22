"""The shared To-Do tab (backed by ``todo.md`` in the selected paper's repository)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.events import EventKind
from core.todos import TodoDoc, TodoError, TodoItem, TodoStore, op_add, op_delete, op_update
from gui.dialogs import _Dialog, run_in_background

MUTED, OVERDUE, DONE = "#8b949e", "#f85149", "#3fb950"
FILTERS = ("Open", "Mine", "Overdue", "Done", "All")
AUTO_REFRESH_MS = 5 * 60 * 1000


@dataclass
class TodoContext:
    """What the To-Do tab needs from the main window."""

    make_store: Callable[[], TodoStore]          # raises TodoError with a user-facing reason
    is_busy: Callable[[], bool]                  # True while a workflow uses the repository
    load_sections: Callable[[], list[str]]
    notify: Callable[[EventKind, str], None]
    handle_error: Callable[[Exception], None]
    set_todo_busy: Callable[[bool], None]


class TodoEditDialog(_Dialog):
    """Edit one task's text, assignee, due date and section."""

    def __init__(self, master: Any, item: TodoItem, people: list[str], sections: list[str],
                 on_save: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(master, "Edit task", "Edit task", f"Created by {item.by or 'unknown'} on {item.created}.")
        self.on_save = on_save
        self.text = self.entry("Task", item.text)
        self.label("Assigned to")
        self.assignee = ctk.CTkComboBox(self.body, values=[""] + people, width=460)
        self.assignee.set(item.assignee)
        self.assignee.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.due = self.entry("Due date (YYYY-MM-DD)", item.due, placeholder="optional")
        self.label("Section")
        self.section = ctk.CTkComboBox(self.body, values=[""] + sections, width=460)
        self.section.set(item.section)
        self.section.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.finish_layout("Save", self.submit)

    def submit(self) -> None:
        fields = {"text": self.text.get(), "assignee": self.assignee.get(), "due": self.due.get(),
                  "section": self.section.get()}
        if not fields["text"].strip():
            self.fail("The task text cannot be empty.")
            return
        super().close(True)
        self.on_save(fields)


class TodoPanel(ctk.CTkFrame):
    """List, filter, add, tick, edit and delete shared tasks."""

    def __init__(self, master: Any, ctx: TodoContext) -> None:
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.doc: TodoDoc | None = None
        self.me = ""
        self.people: list[str] = []
        self.sections: list[str] = []
        self.busy = False
        self._last_sync = 0.0

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        self.refresh_button = ctk.CTkButton(bar, text="⟳ Refresh", width=100, command=self.refresh)
        self.refresh_button.pack(side="left")
        self.filter = ctk.CTkSegmentedButton(bar, values=list(FILTERS), command=lambda _v: self.render())
        self.filter.set("Open")
        self.filter.pack(side="left", padx=10)
        self.status = ctk.CTkLabel(bar, text="", text_color=MUTED)
        self.status.pack(side="left", padx=6)

        captions = ctk.CTkFrame(self, fg_color="transparent")
        captions.pack(fill="x")
        for text, width, expand in (("New task", 0, True), ("Assign to", 150, False), ("Due date", 130, False),
                                    ("Section", 160, False), ("", 70, False)):
            ctk.CTkLabel(captions, text=text, width=width, anchor="w", text_color=MUTED).pack(
                side="left", fill="x", expand=expand, padx=(0 if expand else 6, 0))
        add = ctk.CTkFrame(self, fg_color="transparent")
        add.pack(fill="x", pady=(0, 6))
        self.new_text = ctk.CTkEntry(add, placeholder_text="New task, e.g. 'Update Fig. 3 with the new results'")
        self.new_text.pack(side="left", fill="x", expand=True)
        self.new_text.bind("<Return>", lambda _e: self.add())
        self.new_assignee = ctk.CTkComboBox(add, values=[""], width=150)
        self.new_assignee.set("")
        self.new_assignee.pack(side="left", padx=(6, 0))
        self.new_due = ctk.CTkEntry(add, placeholder_text="YYYY-MM-DD", width=130)
        self.new_due.pack(side="left", padx=(6, 0))
        self.new_section = ctk.CTkComboBox(add, values=[""], width=160)
        self.new_section.set("")
        self.new_section.pack(side="left", padx=(6, 0))
        self.add_button = ctk.CTkButton(add, text="Add", width=70, command=self.add)
        self.add_button.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(self, text="Assignee and section are optional. The list lives in todo.md in the paper and is "
                                "shared with everyone who syncs it.", text_color=MUTED, anchor="w").pack(fill="x")

        self.list = ctk.CTkScrollableFrame(self)
        self.list.pack(fill="both", expand=True, pady=(4, 0))
        self.list.grid_columnconfigure(1, weight=1)
        self.after(AUTO_REFRESH_MS, self._auto_refresh)

    # ------------------------------------------------------------------ #
    # Background operations
    # ------------------------------------------------------------------ #
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        self.ctx.set_todo_busy(busy)
        state = "disabled" if busy else "normal"
        for widget in (self.refresh_button, self.add_button):
            widget.configure(state=state)
        if message:
            self.status.configure(text=message)

    def _start(self, work: Callable[[TodoStore], TodoDoc], quiet: bool = False,
               done_message: str = "") -> None:
        if self.busy:
            return
        if self.ctx.is_busy():
            if not quiet:
                self.ctx.notify(EventKind.WARNING, "A workflow is using the paper - try the to-do list again when it "
                                                   "has finished.")
            return
        try:
            store = self.ctx.make_store()
        except TodoError as exc:
            self.status.configure(text=str(exc))
            if not quiet:
                self.ctx.notify(EventKind.WARNING, str(exc))
            return
        self.me = store.author
        self._set_busy(True, "Syncing…")

        def job() -> tuple[TodoDoc, list[str]]:
            doc = work(store)
            return doc, store.people()

        def ok(result: tuple[TodoDoc, list[str]]) -> None:
            self.doc, self.people = result
            self._last_sync = time.monotonic()
            self._set_busy(False, f"Synced {datetime.now():%H:%M}")
            self.new_assignee.configure(values=[""] + self.people)
            self.render()
            if done_message:
                self.ctx.notify(EventKind.SUCCESS, done_message)

        def failed(exc: Exception) -> None:
            self.render()  # undo an optimistic checkbox tick
            if quiet:  # background refresh: never pop up dialogs
                self._set_busy(False, f"Not synced: {str(exc).splitlines()[0][:100]}")
                return
            self._set_busy(False, "Failed - see the Live Log.")
            self.ctx.handle_error(exc)

        run_in_background(self, job, ok, failed)

    def refresh(self, quiet: bool = False) -> None:
        self._start(lambda store: store.refresh(), quiet=quiet)

    def _auto_refresh(self) -> None:
        try:
            if self.winfo_ismapped() or self.doc is not None:
                self.refresh(quiet=True)
        finally:
            self.after(AUTO_REFRESH_MS, self._auto_refresh)

    def _apply(self, build_operation: Callable[[str], Any], message: str) -> None:
        """Run ``build_operation(author)`` against the latest list (in the background)."""
        self._start(lambda store: store.apply(build_operation(store.author)), done_message=message)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def paper_changed(self) -> None:
        """Called when another paper is selected: show the local copy, sync when the tab is opened."""
        self.doc = None
        self.sections = []
        self.new_section.configure(values=[""])
        self._last_sync = 0.0
        self.status.configure(text="")
        try:
            store = self.ctx.make_store()
            self.me = store.author
            if store.path.exists():
                self.doc = store.read()
                self.status.configure(text="Local copy - not synced yet")
        except (TodoError, OSError):
            pass
        self.render()
        if self.winfo_ismapped():
            self.refresh(quiet=True)

    def on_show(self) -> None:
        """The To-Do tab was opened: sync if the list is older than a minute."""
        self._ensure_sections()
        if time.monotonic() - self._last_sync > 60:
            self.refresh(quiet=self.doc is not None)

    def _ensure_sections(self) -> None:
        if not self.sections:
            self.sections = self.ctx.load_sections()
            self.new_section.configure(values=[""] + self.sections)

    def prefill(self, section: str) -> None:
        """Start a new task linked to ``section`` (from a click in the PDF)."""
        self._ensure_sections()
        self.new_section.set(section)
        self.new_text.focus_set()

    def add(self) -> None:
        text, assignee = self.new_text.get(), self.new_assignee.get()
        due, section = self.new_due.get(), self.new_section.get()
        self._apply(lambda me: op_add(text, me, assignee, due, section), f"Task added: {text.strip()[:60]}")
        for entry in (self.new_text, self.new_due):
            if entry.get():  # deleting an empty entry would also remove its placeholder hint
                entry.delete(0, "end")
        self.new_assignee.set("")
        self.new_section.set("")
        self.focus_set()

    def toggle(self, item: TodoItem, done: bool) -> None:
        verb = "completed" if done else "reopened"
        self._apply(lambda me: op_update(item.id, me, done=done), f"Task {verb}: {item.text[:60]}")

    def edit(self, item: TodoItem) -> None:
        self._ensure_sections()
        TodoEditDialog(self, item, self.people, self.sections,
                       lambda fields: self._apply(lambda me: op_update(item.id, me, **fields),
                                                  f"Task updated: {fields['text'][:60]}"))

    def delete(self, item: TodoItem) -> None:
        if messagebox.askyesno("Delete task", f"Delete this task for everyone?\n\n{item.text}", parent=self):
            self._apply(lambda _me: op_delete(item.id), f"Task deleted: {item.text[:60]}")

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def visible_items(self) -> list[TodoItem]:
        items = self.doc.items if self.doc else []
        mode = self.filter.get()
        me = (self.me or "").lower()
        if mode == "Open":
            items = [i for i in items if not i.done]
        elif mode == "Mine":
            items = [i for i in items if not i.done and i.assignee.lower() == me]
        elif mode == "Overdue":
            items = [i for i in items if i.is_overdue()]
        elif mode == "Done":
            items = [i for i in items if i.done]
        return sorted(items, key=lambda i: (i.done, i.due or "9999-99-99", i.created))

    def render(self) -> None:
        for child in self.list.winfo_children():
            child.destroy()
        items = self.visible_items()
        if self.doc is None:
            ctk.CTkLabel(self.list, text="Click ⟳ Refresh to load the paper's shared to-do list.",
                         text_color=MUTED).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=8)
            return
        if not items:
            ctk.CTkLabel(self.list, text="No tasks here.", text_color=MUTED).grid(
                row=0, column=0, columnspan=4, sticky="w", padx=8, pady=8)
        today = date.today()
        for row, item in enumerate(items):
            box = ctk.CTkCheckBox(self.list, text="", width=24)
            if item.done:
                box.select()
            box.configure(command=lambda i=item, b=box: self.toggle(i, bool(b.get())))
            box.grid(row=row * 2, column=0, rowspan=2, sticky="n", padx=(6, 2), pady=(6, 0))
            ctk.CTkLabel(self.list, text=item.text, anchor="w", justify="left", wraplength=700,
                         text_color=MUTED if item.done else None,
                         font=ctk.CTkFont(overstrike=item.done)).grid(row=row * 2, column=1, sticky="w", pady=(6, 0))
            details = [f"@{item.assignee}" if item.assignee else "unassigned",
                       f"due {item.due}" + (" (overdue)" if item.is_overdue(today) else "") if item.due else "",
                       f"§ {item.section}" if item.section else "",
                       f"added by {item.by}" if item.by else "",
                       f"done by {item.done_by}" if item.done and item.done_by else ""]
            color = OVERDUE if item.is_overdue(today) else (DONE if item.done else MUTED)
            ctk.CTkLabel(self.list, text=" · ".join(d for d in details if d), anchor="w", text_color=color,
                         font=ctk.CTkFont(size=12)).grid(row=row * 2 + 1, column=1, sticky="w", pady=(0, 4))
            ctk.CTkButton(self.list, text="Edit", width=56, height=24, fg_color="transparent", border_width=1,
                          command=lambda i=item: self.edit(i)).grid(row=row * 2, column=2, rowspan=2, padx=4)
            ctk.CTkButton(self.list, text="Delete", width=64, height=24, fg_color="transparent", border_width=1,
                          command=lambda i=item: self.delete(i)).grid(row=row * 2, column=3, rowspan=2, padx=(0, 6))
        open_count = sum(not i.done for i in self.doc.items)
        overdue = sum(i.is_overdue(today) for i in self.doc.items)
        summary = f"{open_count} open" + (f", {overdue} overdue" if overdue else "")
        self.status.configure(text=f"{self.status.cget('text').split(' | ')[0]} | {summary}")
