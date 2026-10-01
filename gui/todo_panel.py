"""The shared To-Do tab: one list for every paper, backed by its own repository.

Each task may name the paper it belongs to, so the list still says what belongs
where without being tied to one manuscript. See :mod:`core.global_todos`.
"""

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
from core.i18n import Choices, t, translated

MUTED, OVERDUE, DONE = "#8b949e", "#f85149", "#3fb950"
FILTERS = ("Open", "Mine", "Overdue", "Done", "All")
ALL_PAPERS = "All papers"
NO_PAPER = "(no paper)"
# The list has a repository to itself, so refreshing is one small fetch: often enough
# to feel live without hammering the server.
AUTO_REFRESH_MS = 45 * 1000
FOCUS_REFRESH_SECONDS = 20      # coming back to the window re-checks, but not on every click


@dataclass
class TodoContext:
    """What the To-Do tab needs from the main window."""

    make_store: Callable[[], TodoStore]          # raises TodoError with a user-facing reason
    load_sections: Callable[[], list[str]]
    notify: Callable[[EventKind, str], None]
    handle_error: Callable[[Exception], None]
    paper_names: Callable[[], list[str]] = list  # every paper in the app, for tagging and filtering
    current_paper: Callable[[], str] = str       # the selected paper, used as the default tag


class TodoEditDialog(_Dialog):
    """Edit one task's text, assignee, due date, paper and section."""

    def __init__(self, master: Any, item: TodoItem, people: list[str], sections: list[str],
                 papers: list[str], on_save: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(master, "Edit task", "Edit task",
                         t("Created by {who} on {when}.", who=item.by or t("unknown"), when=item.created))
        self.on_save = on_save
        self.text = self.entry(t("Task"), item.text)
        self.label(t("Assigned to"))
        self.assignee = ctk.CTkComboBox(self.body, values=[""] + people, width=460)
        self.assignee.set(item.assignee)
        self.assignee.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.due = self.entry(t("Due date (YYYY-MM-DD)"), item.due, placeholder=t("optional"))
        self.label(t("Paper"))
        self.paper = ctk.CTkComboBox(self.body, values=[""] + papers, width=460)
        self.paper.set(item.paper)
        self.paper.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.label(t("Section"))
        self.section = ctk.CTkComboBox(self.body, values=[""] + sections, width=460)
        self.section.set(item.section)
        self.section.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.finish_layout("Save", self.submit)

    def submit(self) -> None:
        fields = {"text": self.text.get(), "assignee": self.assignee.get(), "due": self.due.get(),
                  "paper": self.paper.get(), "section": self.section.get()}
        if not fields["text"].strip():
            self.fail(t("The task text cannot be empty."))
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
        self.refresh_button = ctk.CTkButton(bar, text=t("⟳ Refresh"), width=100, command=self.refresh)
        self.refresh_button.pack(side="left")
        # Shown translated, compared as English - visible_items() switches on these.
        self.filters = Choices(list(FILTERS))
        self.filter = ctk.CTkSegmentedButton(bar, values=self.filters.labels,
                                             command=lambda _v: self.render())
        self.filter.set(self.filters.label("Open"))
        self.filter.pack(side="left", padx=10)
        self.paper_filter = ctk.CTkComboBox(bar, values=[t(ALL_PAPERS)], width=150,
                                            command=lambda _v: self.render())
        self.paper_filter.set(t(ALL_PAPERS))
        self.paper_filter.pack(side="left", fill="x", expand=True)
        # Its own line: beside the filters it was pushed off the edge of the narrow column.
        self.status = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status.pack(fill="x", pady=(0, 4))

        # Two rows on a grid: the middle column is narrow, and one row of six fixed-width
        # widgets ran off the edge, hiding Section and the Add button.
        ctk.CTkLabel(self, text=t("New task"), anchor="w", text_color=MUTED).pack(fill="x")
        add = ctk.CTkFrame(self, fg_color="transparent")
        add.pack(fill="x")
        add.grid_columnconfigure(0, weight=1)
        self.new_text = ctk.CTkEntry(add, placeholder_text=t("New task, e.g. 'Update Fig. 3 with the new results'"))
        self.new_text.grid(row=0, column=0, sticky="ew")
        self.new_text.bind("<Return>", lambda _e: self.add())
        self.add_button = ctk.CTkButton(add, text=t("Add"), width=70, command=self.add)
        self.add_button.grid(row=0, column=1, padx=(6, 0))

        fields = ctk.CTkFrame(self, fg_color="transparent")
        fields.pack(fill="x", pady=(4, 6))
        self.new_assignee = ctk.CTkComboBox(fields, values=[""])
        self.new_assignee.set("")
        self.new_due = ctk.CTkEntry(fields, placeholder_text=t("YYYY-MM-DD"))
        self.new_paper = ctk.CTkComboBox(fields, values=[t(NO_PAPER)])
        self.new_paper.set(t(NO_PAPER))
        self.new_section = ctk.CTkComboBox(fields, values=[""])
        self.new_section.set("")
        for column, (caption, widget) in enumerate((("Assign to", self.new_assignee), ("Due date", self.new_due),
                                                    ("Paper", self.new_paper), ("Section", self.new_section))):
            fields.grid_columnconfigure(column, weight=1, uniform="todo")
            ctk.CTkLabel(fields, text=caption, anchor="w", text_color=MUTED).grid(
                row=0, column=column, sticky="w", padx=(0 if column == 0 else 6, 0))
            widget.grid(row=1, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))
        ctk.CTkLabel(self, text=t("One list for all your papers. Everything except the task text is optional; "
                                "naming a paper is\njust a label, so tasks that belong to no paper are fine too."),
                     text_color=MUTED, anchor="w", justify="left").pack(fill="x")

        self.list = ctk.CTkScrollableFrame(self)
        self.list.pack(fill="both", expand=True, pady=(4, 0))
        self.list.grid_columnconfigure(1, weight=1)
        self.after(AUTO_REFRESH_MS, self._auto_refresh)
        self.winfo_toplevel().bind("<FocusIn>", self._window_focused, add="+")

    def _window_focused(self, _event: Any) -> None:
        """Back from Overleaf or a colleague's message: pick up their changes."""
        if self.winfo_ismapped() and time.monotonic() - self._last_sync > FOCUS_REFRESH_SECONDS:
            self.refresh(quiet=True)

    # ------------------------------------------------------------------ #
    # Background operations
    # ------------------------------------------------------------------ #
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.refresh_button, self.add_button):
            widget.configure(state=state)
        if message:
            self.status.configure(text=message)

    def _start(self, work: Callable[[TodoStore], TodoDoc], quiet: bool = False,
               done_message: str = "") -> None:
        if self.busy:
            return
        # The list has its own repository, so a running workflow never blocks it.
        try:
            store = self.ctx.make_store()
        except TodoError as exc:
            self.status.configure(text=translated(exc))
            if not quiet:
                self.ctx.notify(EventKind.WARNING, translated(exc))
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
                self._set_busy(False, t("Not synced: {problem}",
                                        problem=translated(exc).splitlines()[0][:100]))
                return
            self._set_busy(False, t("Failed - see the Live Log."))
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
        """Another paper was selected: the list stays, only its paper labels follow."""
        self.sections = []
        self.new_section.configure(values=[""])
        self._refresh_paper_choices()
        if self.doc is None:
            self._load_local_copy()
        self.render()

    def _refresh_paper_choices(self) -> None:
        papers = self.ctx.paper_names()
        # The sentinels are shown translated; paper names are the user's own text.
        self.paper_filter.configure(values=[t(ALL_PAPERS)] + papers)
        if self.paper_filter.get() not in [t(ALL_PAPERS)] + papers:
            self.paper_filter.set(t(ALL_PAPERS))
        self.new_paper.configure(values=[t(NO_PAPER)] + papers)
        current = self.ctx.current_paper()
        if current in papers:            # new tasks default to the paper you are working on
            self.new_paper.set(current)
        elif self.new_paper.get() not in [t(NO_PAPER)] + papers:
            self.new_paper.set(t(NO_PAPER))

    def _load_local_copy(self) -> None:
        """Show the last synced copy straight away, before the network answers."""
        try:
            store = self.ctx.make_store()
            self.me = store.author
            if store.path.exists():
                self.doc = store.read()
                self.status.configure(text=t("Local copy - not synced yet"))
        except (TodoError, OSError):
            pass

    def on_show(self) -> None:
        """The To-Do tab was opened: sync if the list is older than a minute."""
        self._ensure_sections()
        self._refresh_paper_choices()
        if self.doc is None:
            self._load_local_copy()
            self.render()
        if time.monotonic() - self._last_sync > 60:
            self.refresh(quiet=self.doc is not None)

    def _ensure_sections(self) -> None:
        if not self.sections:
            self.sections = self.ctx.load_sections()
            self.new_section.configure(values=[""] + self.sections)

    def prefill(self, section: str) -> None:
        """Start a new task linked to ``section`` (from a click in the PDF)."""
        self.on_show()
        self._refresh_paper_choices()     # the click came from a paper, so tag the task with it
        self.new_section.set(section)
        self.new_text.focus_set()

    def add(self) -> None:
        text, assignee = self.new_text.get(), self.new_assignee.get()
        due, section = self.new_due.get(), self.new_section.get()
        paper = "" if self.new_paper.get() == t(NO_PAPER) else self.new_paper.get()
        self._apply(lambda me: op_add(text, me, assignee, due, section, paper), f"Task added: {text.strip()[:60]}")
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
        TodoEditDialog(self, item, self.people, self.sections, self.ctx.paper_names(),
                       lambda fields: self._apply(lambda me: op_update(item.id, me, **fields),
                                                  f"Task updated: {fields['text'][:60]}"))

    def delete(self, item: TodoItem) -> None:
        if messagebox.askyesno(t("Delete task"), t("Delete this task for everyone?\n\n{task}", task=item.text), parent=self):
            self._apply(lambda _me: op_delete(item.id), f"Task deleted: {item.text[:60]}")

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def visible_items(self) -> list[TodoItem]:
        items = self.doc.items if self.doc else []
        mode = self.filters.value(self.filter.get())      # the widgets show the translations
        me = (self.me or "").lower()
        paper = self.paper_filter.get()
        if paper == t(NO_PAPER):
            items = [i for i in items if not i.paper]
        elif paper != t(ALL_PAPERS):
            items = [i for i in items if i.paper == paper]
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
            ctk.CTkLabel(self.list, text=t("Click ⟳ Refresh to load the shared to-do list."),
                         text_color=MUTED).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=8)
            return
        if not items:
            ctk.CTkLabel(self.list, text=t("No tasks here."), text_color=MUTED).grid(
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
                       f"in {item.paper}" if item.paper else "",
                       f"§ {item.section}" if item.section else "",
                       f"added by {item.by}" if item.by else "",
                       f"done by {item.done_by}" if item.done and item.done_by else ""]
            color = OVERDUE if item.is_overdue(today) else (DONE if item.done else MUTED)
            ctk.CTkLabel(self.list, text=" · ".join(d for d in details if d), anchor="w", text_color=color,
                         font=ctk.CTkFont(size=12)).grid(row=row * 2 + 1, column=1, sticky="w", pady=(0, 4))
            ctk.CTkButton(self.list, text=t("Edit"), width=56, height=24, fg_color="transparent", border_width=1,
                          command=lambda i=item: self.edit(i)).grid(row=row * 2, column=2, rowspan=2, padx=4)
            ctk.CTkButton(self.list, text=t("Delete"), width=64, height=24, fg_color="transparent", border_width=1,
                          command=lambda i=item: self.delete(i)).grid(row=row * 2, column=3, rowspan=2, padx=(0, 6))
        open_count = sum(not i.done for i in self.doc.items)
        overdue = sum(i.is_overdue(today) for i in self.doc.items)
        summary = f"{open_count} open" + (f", {overdue} overdue" if overdue else "")
        self.status.configure(text=f"{self.status.cget('text').split(' | ')[0]} | {summary}")
