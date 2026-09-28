"""Parameter form for the "Results Figures & Tables" task.

Kept out of :mod:`gui.task_forms` so both files stay under the 500-line limit.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from core.results_data import SUFFIXES
from core.results_workflow import KIND_CHOICES, ResultsFigureWorkflow
from gui.task_forms import FileList, Form

RESULT_TYPES = [("Result files", " ".join(f"*{s}" for s in SUFFIXES)), ("All files", "*.*")]


class ResultsFileList(FileList):
    """File list that also accepts a whole folder of results."""

    empty_text = "Nothing chosen - click 'Add files…' for single files, or 'Add folder…' for a whole run."

    def __init__(self, master: Any) -> None:
        super().__init__(master, "Choose result files", RESULT_TYPES, height=80)
        ctk.CTkButton(self, text="Add folder…", width=110, fg_color="transparent", border_width=1,
                      command=self.add_folder).grid(row=3, column=1, padx=(6, 0), pady=2)

    def add_folder(self) -> None:
        name = filedialog.askdirectory(parent=self, title="Choose a folder of results")
        if name and Path(name) not in self.files:
            self.files.append(Path(name))
            self._render()


class ResultsForm(Form):
    workflow = ResultsFigureWorkflow

    def build(self) -> None:
        self.label("Result files or a folder (CSV, Excel, JSON history, classification report, "
                   "confusion matrix)")
        self.files = ResultsFileList(self.frame)
        self._place(self.files)
        self.label("Files are only read. Nothing is written to data/ or supplementary/, and the raw files "
                   "never\nleave your computer - only the numbers that end up in the figure do.", muted=True)
        self.label("What to draw")
        self.kind = ctk.CTkOptionMenu(self.frame, values=list(KIND_CHOICES), width=260)
        self.kind.set(list(KIND_CHOICES)[0])
        self._place(self.kind, sticky="w")
        self.section_picker("section", "Place it at the end of section")
        self.textbox("caption", "Caption (optional - Claude drafts one from the numbers and the section)",
                     height=45)
        self.entry("x_label", "X axis label (optional)", width=260)
        self.entry("y_label", "Y axis label (optional)", width=260)
        self.entry("decimals", "Decimal places", "3", width=80)
        self.entry("width", "Chart width", r"0.85\linewidth", width=160)
        self.checkbox("reference_sentence", "Add a sentence that refers to it (Figure~\\ref{…})", checked=True)
        self.label("Charts are written as pgfplots/booktabs code, so you see every number in the approval "
                   "window\nand can edit it later in Overleaf. Nothing changes until you approve.", muted=True)

    def params(self) -> dict[str, Any]:
        if not self.files.files:
            raise ValueError("Choose at least one results file or a folder.")
        decimals = self.number("decimals", 0, 6)
        return {"files": [str(p) for p in self.files.files],
                "section_title": self.value("section"),
                "kind": KIND_CHOICES[self.kind.get()],
                "caption": self.value("caption"),
                "x_label": self.value("x_label"), "y_label": self.value("y_label"),
                "decimals": 3 if decimals is None else decimals,
                "width": self.value("width") or r"0.85\linewidth",
                "reference_sentence": self.value("reference_sentence")}
