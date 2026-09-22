"""Main-area widgets: task selector, parameter forms, live log and report viewer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import customtkinter as ctk

from core.events import EventKind
from gui.task_forms import FORMS, Form, FormContext
from gui.todo_panel import TodoContext, TodoPanel

LOG_COLORS = {
    EventKind.INFO: "#c9d1d9", EventKind.STATE: "#d2a8ff", EventKind.THOUGHT: "#8b949e",
    EventKind.LLM_TEXT: "#a5d6ff", EventKind.TOOL_CALL: "#ffa657", EventKind.TOOL_RESULT: "#7ee787",
    EventKind.WARNING: "#e3b341", EventKind.ERROR: "#f85149", EventKind.SUCCESS: "#3fb950",
    EventKind.ARTIFACT: "#79c0ff", EventKind.APPROVAL_REQUEST: "#ff7b72",
    EventKind.AUTH_REQUIRED: "#ff7b72", EventKind.FINISHED: "#d2a8ff", EventKind.CONFIRM_PUSH: "#ff7b72",
}
STREAM_KINDS = {EventKind.LLM_TEXT, EventKind.THOUGHT}
LINK_RE = re.compile(r"https?://[^\s<>|)\]\"']+")
MUTED = "#8b949e"


def open_path(path: Path) -> None:
    """Open a file or folder with the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - local file chosen by the app
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


class TaskPanel(ctk.CTkFrame):
    """Workflow selector, per-workflow parameters, run controls and output tabs."""

    def __init__(self, master: Any, task_names: list[str], run: Callable[[str, dict[str, Any]], None],
                 cancel: Callable[[], None], load_sections: Callable[[], list[str]],
                 list_bibs: Callable[[], list[str]], todo: TodoContext,
                 list_figures: Callable[[], list[Any]] = list) -> None:
        super().__init__(master, fg_color="transparent")
        self._run = run
        self._last_stream: EventKind | None = None
        self._report_path: Path | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        picker = ctk.CTkFrame(self, fg_color="transparent")
        picker.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(picker, text="Task", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(2, 8))
        self.selector = ctk.CTkOptionMenu(picker, values=task_names, command=self.select, width=260,
                                          dynamic_resizing=False)
        self.selector.pack(side="left", fill="x", expand=True)
        self.params = ctk.CTkScrollableFrame(self, height=300)
        self.params.grid(row=1, column=0, sticky="ew", pady=10)
        self.params.grid_columnconfigure(0, weight=1)
        self.context = FormContext(load_sections=load_sections, list_bibs=list_bibs, list_figures=list_figures)
        self.forms: dict[str, Form] = {name: FORMS[name](self.params, self.context) for name in task_names}

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew")
        self.run_button = ctk.CTkButton(controls, text="▶  Run", width=110, command=self._on_run)
        self.run_button.pack(side="left")
        self.cancel_button = ctk.CTkButton(controls, text="■  Cancel", width=90, state="disabled",
                                           fg_color="#6e2b2b", hover_color="#8b3535", command=cancel)
        self.cancel_button.pack(side="left", padx=8)
        ctk.CTkButton(controls, text="Clear log", width=76, fg_color="transparent", border_width=1,
                      command=lambda: self.log_box.delete("1.0", "end")).pack(side="left")
        self.state_label = ctk.CTkLabel(controls, text="State: Idle", font=ctk.CTkFont(weight="bold"))
        self.state_label.pack(side="right", padx=8)
        self.progress = ctk.CTkProgressBar(controls, mode="determinate", width=80)
        self.progress.pack(side="right", padx=8)
        self.progress.set(0)

        self.tabs = ctk.CTkTabview(self, command=self._tab_changed)
        self.tabs.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        mono = ctk.CTkFont(family="Consolas", size=13)
        self.log_box = ctk.CTkTextbox(self.tabs.add("Live Log"), font=mono, wrap="word")
        self.log_box.pack(fill="both", expand=True)
        for kind, color in LOG_COLORS.items():
            self.log_box.tag_config(kind.value, foreground=color)

        report_tab = self.tabs.add("Report")
        bar = ctk.CTkFrame(report_tab, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        self.open_report_button = ctk.CTkButton(bar, text="Open report file", width=140, state="disabled",
                                                command=lambda: self._report_path and open_path(self._report_path))
        self.open_report_button.pack(side="left")
        ctk.CTkButton(bar, text="Open reports folder", width=150, fg_color="transparent", border_width=1,
                      command=lambda: self._report_path and open_path(self._report_path.parent)).pack(
            side="left", padx=8)
        ctk.CTkLabel(bar, text="Click a link to open the paper in your browser.", text_color=MUTED).pack(side="left")
        self.report_box = ctk.CTkTextbox(report_tab, font=ctk.CTkFont(size=14), wrap="word")
        self.report_box.pack(fill="both", expand=True)
        self.report_box.tag_config("link", foreground="#58a6ff", underline=True)
        self.report_box.tag_config("heading", foreground="#d2a8ff")
        self.todo = TodoPanel(self.tabs.add("To-Do"), todo)
        self.todo.pack(fill="both", expand=True)
        self.select(task_names[0])

    def _tab_changed(self) -> None:
        if self.tabs.get() == "To-Do":
            self.todo.on_show()

    # ------------------------------------------------------------------ #
    # Parameters
    # ------------------------------------------------------------------ #
    def select(self, name: str) -> None:
        self.selector.set(name)
        for form in self.forms.values():
            form.frame.grid_forget()
        self.forms[name].frame.grid(row=0, column=0, sticky="ew")

    def set_sections(self, titles: list[str]) -> None:
        """Reset every section picker (e.g. after switching papers)."""
        self.context.refresh_sections(titles)

    def _on_run(self) -> None:
        name = self.selector.get()
        try:
            params = self.forms[name].params()
        except ValueError as exc:
            self.append(EventKind.ERROR, str(exc))
            return
        self._run(name, params)

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def set_running(self, running: bool) -> None:
        self.run_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        if running:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

    def set_state(self, text: str) -> None:
        self.state_label.configure(text=f"State: {text}")

    def append(self, kind: EventKind, message: str) -> None:
        box = self.log_box
        if kind in STREAM_KINDS:
            if self._last_stream != kind:
                box.insert("end", "\n💭 " if kind == EventKind.THOUGHT else "\n🤖 ", kind.value)
            box.insert("end", message, kind.value)
            self._last_stream = kind
        else:
            prefix = "\n" if self._last_stream else ""
            self._last_stream = None
            box.insert("end", f"{prefix}{message}\n", kind.value)
        box.see("end")

    def show_report(self, markdown: str, path: str | None) -> None:
        box = self.report_box
        box.delete("1.0", "end")
        box.insert("1.0", markdown)
        for tag in box.tag_names():
            if tag.startswith("link-"):
                box.tag_delete(tag)
        for number, line in enumerate(markdown.splitlines(), start=1):
            if line.startswith("#"):
                box.tag_add("heading", f"{number}.0", f"{number}.end")
            for i, match in enumerate(LINK_RE.finditer(line)):
                url = match.group(0).rstrip(".,;")
                start, end = f"{number}.{match.start()}", f"{number}.{match.start() + len(url)}"
                tag = f"link-{number}-{i}"
                box.tag_add("link", start, end)
                box.tag_add(tag, start, end)
                box.tag_bind(tag, "<Button-1>", lambda _e, u=url: webbrowser.open(u))
        self._report_path = Path(path) if path else None
        self.open_report_button.configure(state="normal" if path else "disabled")
        self.tabs.set("Report")
