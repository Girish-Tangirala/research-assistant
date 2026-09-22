"""Click-to-edit for the PDF preview (mixed into the main window).

A click on the PDF is mapped to the source with SyncTeX in the background. In the
"Edit .tex" click mode it opens that line in the source editor; in "Agent task" mode:

* text / heading / equation / table -> "Edit Text" with that section selected,
* an image -> "Add Figures" in *Replace a figure* mode with that figure selected,
* the bibliography -> "Add References".

A right-click opens a menu with every action that fits the spot.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Any

from core.asset_workflows import AddFiguresWorkflow, AddReferencesWorkflow
from core.events import EventKind
from core.latex_parser import list_section_titles
from core.preview import KIND_PROPOSED
from core.source_map import (
    KIND_BIBLIOGRAPHY, KIND_FIGURE, KIND_MATH, KIND_PREAMBLE, KIND_TABLE, ClickLookupError, ClickTarget,
    FigureRef, list_figures, target_for_click,
)
from core.synctex import find_synctex_tool
from core.workflows import CitationAuditWorkflow, SafeEditWorkflow
from gui.editor_mixin import AGENT_MODE
from gui.panels import open_path

EDIT_TAB = SafeEditWorkflow.name
FIGURES_TAB = AddFiguresWorkflow.name
REFERENCES_TAB = AddReferencesWorkflow.name
AUDIT_TAB = CitationAuditWorkflow.name
KIND_NOTES = {
    KIND_MATH: "The equation itself is protected - instructions can still ask to reword the text around it.",
    KIND_TABLE: "Table cells are edited like text; the table structure is protected.",
}


class PdfLinkMixin:
    """Needs ``self.preview``, ``self.panel``, ``self.bus`` and ``self._paper_root()``."""

    def _list_figures(self) -> list[FigureRef]:
        root = self._paper_root()
        if root is None or not root.is_dir():
            self.panel.append(EventKind.WARNING, "The paper is not cloned yet - click 'Sync paper' first.")
            return []
        figures = list_figures(root)
        self.panel.append(EventKind.INFO, f"Found {len(figures)} figure(s).")
        return figures

    # ------------------------------------------------------------------ #
    # Click -> source (background)
    # ------------------------------------------------------------------ #
    def pdf_clicked(self, page: int, x: float, y: float, x_root: int, y_root: int, context_menu: bool) -> None:
        result, repo = self.preview.result, self._paper_root()
        if result is None or result.pdf_path is None or repo is None:
            return
        pdf = result.pdf_path
        source_root = repo
        if result.kind == KIND_PROPOSED:  # compiled from the preview mirror of the repository
            source_root = self._preview_builder().base / "src" / repo.name
        tool = find_synctex_tool(self.config_.latex)
        self.preview.set_source_status("Looking up the source…")

        def work() -> None:
            try:
                target = target_for_click(pdf, page, x, y, source_root, repo, tool)
            except ClickLookupError as exc:
                self.bus.emit(EventKind.PREVIEW, "", click_error=str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - shown in the status line
                self.bus.emit(EventKind.PREVIEW, "", click_error=f"Could not map the click: {exc}")
                return
            self.bus.emit(EventKind.PREVIEW, "", click=target, menu=(x_root, y_root) if context_menu else None)

        threading.Thread(target=work, daemon=True, name="pdf-click").start()

    def handle_click_event(self, data: dict[str, Any]) -> None:
        if "click_error" in data:
            self.preview.set_source_status(data["click_error"], error=True)
            return
        target: ClickTarget = data["click"]
        self.preview.set_source_status(target.describe())
        if data.get("menu"):
            self._click_menu(target, *data["menu"])
        elif self.preview.mode == "source":
            self.edit_source_at(target)
        else:
            self._default_action(target)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def _note(self, target: ClickTarget) -> str:
        text = f"Picked in the PDF: {target.rel_path}, line {target.line}"
        if target.snippet:
            snippet = target.snippet if len(target.snippet) <= 90 else target.snippet[:87] + "…"
            text += f'  -  "{snippet}"'
        extra = KIND_NOTES.get(target.kind)
        return f"{text}\n{extra}" if extra else text

    def _busy_hint(self) -> None:
        if self._workflow_running():
            self.panel.append(EventKind.INFO, "A task is running - the form is filled in; run it when the task "
                                              "has finished.")

    def _default_action(self, target: ClickTarget) -> None:
        self.show_mode(AGENT_MODE)
        if target.kind == KIND_FIGURE and target.figure is not None:
            self.replace_figure_at(target)
        elif target.kind == KIND_BIBLIOGRAPHY:
            self.panel.select(REFERENCES_TAB)
            self.panel.append(EventKind.INFO, "Bibliography clicked - add references here, or run the "
                                              "Citation & BibTeX Audit.")
        elif target.kind == KIND_PREAMBLE:
            self.panel.append(EventKind.INFO, f"That comes from the preamble ({target.rel_path}, line "
                                              f"{target.line}) - it is not part of a section.")
        elif not target.section:
            self.panel.append(EventKind.WARNING, f"{target.rel_path}, line {target.line} is not inside a section "
                                                 "- use a Custom Agent Task for text outside sections.")
        else:
            self.edit_section_at(target)

    def edit_source_at(self, target: ClickTarget) -> None:
        """Open the clicked source line in the .tex editor."""
        if not target.rel_path:
            self.preview.set_source_status("No source line found for that spot.", error=True)
            return
        note = ""
        if self.preview.result and self.preview.result.kind == KIND_PROPOSED:
            note = "This PDF shows proposed changes - the line number is from the proposal, not your file."
        self.open_in_editor(target.rel_path, target.line, note)

    def edit_section_at(self, target: ClickTarget) -> None:
        self.show_mode(AGENT_MODE)
        self.panel.select(EDIT_TAB)
        self.panel.set_sections(self.panel_sections())
        self.panel.forms[EDIT_TAB].focus(target.section, target.rel_path, self._note(target))
        self._busy_hint()

    def replace_figure_at(self, target: ClickTarget) -> None:
        self.show_mode(AGENT_MODE)
        self.panel.select(FIGURES_TAB)
        figure = target.figure
        note = f"Picked in the PDF: {figure.graphic} ({target.rel_path}, line {figure.start_line})"
        if len(figure.graphics) > 1:
            note += f" - this figure has {len(figure.graphics)} images; the clicked one is selected."
        if target.kind == KIND_FIGURE and self.preview.result and self.preview.result.kind == KIND_PROPOSED:
            note += "\nThis PDF shows proposed changes - the figure is replaced in the current version."
        self.panel.forms[FIGURES_TAB].focus_replace(figure, note)
        self._busy_hint()

    def add_figure_at(self, target: ClickTarget) -> None:
        self.show_mode(AGENT_MODE)
        self.panel.select(FIGURES_TAB)
        self.panel.set_sections(self.panel_sections())
        self.panel.forms[FIGURES_TAB].focus_add(target.section, f"New figures go at the end of '{target.section}'.")

    def add_references_at(self, target: ClickTarget) -> None:
        self.show_mode(AGENT_MODE)
        self.panel.select(REFERENCES_TAB)
        self.panel.set_sections(self.panel_sections())
        self.panel.forms[REFERENCES_TAB].focus(target.section)

    def todo_at(self, target: ClickTarget) -> None:
        self.show_mode(AGENT_MODE)
        self.panel.tabs.set("To-Do")
        self.panel.todo.on_show()
        self.panel.todo.prefill(target.section)

    def panel_sections(self) -> list[str]:
        root = self._paper_root()
        return list_section_titles(root) if root is not None and root.is_dir() else []

    def _click_menu(self, target: ClickTarget, x_root: int, y_root: int) -> None:
        menu = tk.Menu(self, tearoff=False)
        section = target.section
        if target.rel_path:
            menu.add_command(label=f"Edit in the .tex editor ({target.rel_path}, line {target.line})",
                             command=lambda: self.edit_source_at(target))
            menu.add_separator()
        if target.kind == KIND_FIGURE and target.figure is not None:
            menu.add_command(label=f"Replace this figure ({target.figure.graphic})",
                             command=lambda: self.replace_figure_at(target))
        if section:
            menu.add_command(label=f"Edit section '{section}'", command=lambda: self.edit_section_at(target))
            menu.add_command(label=f"Add a figure to '{section}'", command=lambda: self.add_figure_at(target))
            menu.add_command(label=f"Add references to '{section}'", command=lambda: self.add_references_at(target))
            menu.add_command(label=f"New to-do for '{section}'", command=lambda: self.todo_at(target))
        if target.cite_keys or target.kind == KIND_BIBLIOGRAPHY:
            keys = ", ".join(target.cite_keys[:3])
            menu.add_command(label=f"Check citations{f' ({keys})' if keys else ''}",
                             command=lambda: (self.show_mode(AGENT_MODE), self.panel.select(AUDIT_TAB)))
        if target.rel_path:
            if menu.index("end") is not None:
                menu.add_separator()
            menu.add_command(label=f"Open {target.rel_path} in another program",
                             command=lambda: self._open_source(target))
            menu.add_command(label="Copy source location",
                             command=lambda: self._copy(f"{target.rel_path}:{target.line}"))
        if menu.index("end") is None:
            menu.add_command(label="Nothing to do here", state="disabled")
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _open_source(self, target: ClickTarget) -> None:
        root = self._paper_root()
        path = root / target.rel_path if root else None
        if path is not None and path.is_file():
            open_path(Path(path))

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.panel.append(EventKind.INFO, f"Copied: {text}")
