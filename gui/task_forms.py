"""Parameter forms, one per workflow tab."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from core.asset_workflows import AddFiguresWorkflow, AddReferencesWorkflow
from core.source_map import FigureRef
from core.workflows import CitationAuditWorkflow, CustomAgentWorkflow, LiteratureReviewWorkflow, SafeEditWorkflow

MUTED = "#8b949e"
PICKED = "#58a6ff"
IMAGE_TYPES = [("Images", "*.png *.jpg *.jpeg *.pdf *.tif *.tiff *.bmp *.gif *.webp"), ("All files", "*.*")]
BIB_TYPES = [("BibTeX", "*.bib"), ("All files", "*.*")]


@dataclass
class FormContext:
    """Callbacks and shared widgets provided by the main window."""

    load_sections: Callable[[], list[str]]
    list_bibs: Callable[[], list[str]]
    list_figures: Callable[[], list[FigureRef]] = list
    section_combos: list[tuple[ctk.CTkComboBox, bool]] = field(default_factory=list)  # (combo, optional)
    bib_combos: list[ctk.CTkComboBox] = field(default_factory=list)

    def refresh_sections(self, titles: list[str] | None = None) -> None:
        titles = self.load_sections() if titles is None else titles
        for combo, optional in self.section_combos:
            current = combo.get()
            combo.configure(values=([""] if optional else []) + titles)
            if current not in titles:
                combo.set("" if optional or not titles else titles[0])

    def refresh_bibs(self) -> None:
        values = [""] + self.list_bibs()
        for combo in self.bib_combos:
            combo.configure(values=values)


class FileList(ctk.CTkFrame):
    """A list of local files collected from any number of folders."""

    def __init__(self, master: Any, title: str, filetypes: list[tuple[str, str]], height: int = 90) -> None:
        super().__init__(master, fg_color="transparent")
        self.files: list[Path] = []
        self.filetypes, self.title = filetypes, title
        self.grid_columnconfigure(0, weight=1)
        self.box = ctk.CTkTextbox(self, height=height, state="disabled")
        self.box.grid(row=0, column=0, rowspan=3, sticky="ew")
        ctk.CTkButton(self, text="Add files…", width=110, command=self.add).grid(row=0, column=1, padx=(6, 0), pady=2)
        ctk.CTkButton(self, text="Remove last", width=110, fg_color="transparent", border_width=1,
                      command=self.remove_last).grid(row=1, column=1, padx=(6, 0), pady=2)
        ctk.CTkButton(self, text="Clear", width=110, fg_color="transparent", border_width=1,
                      command=self.clear).grid(row=2, column=1, padx=(6, 0), pady=2)
        self._render()

    def add(self) -> None:
        chosen = filedialog.askopenfilenames(parent=self, title=self.title, filetypes=self.filetypes)
        for name in chosen:
            path = Path(name)
            if path not in self.files:
                self.files.append(path)
        self._render()

    def remove_last(self) -> None:
        if self.files:
            self.files.pop()
        self._render()

    def clear(self) -> None:
        self.files.clear()
        self._render()

    def _render(self) -> None:
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        text = "\n".join(str(p) for p in self.files) or "No files chosen - click 'Add files…' (repeat for other folders)."
        self.box.insert("1.0", text)
        self.box.configure(state="disabled")


class Form:
    """Base class: builds widgets into ``frame`` and returns workflow params."""

    workflow: type = object

    def __init__(self, parent: Any, ctx: FormContext) -> None:
        self.ctx = ctx
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.grid_columnconfigure(0, weight=1)
        self.inputs: dict[str, Any] = {}
        self._row = 0
        self._group: list[Any] | None = None  # widgets placed while building a switchable group
        self.build()

    # -- widget helpers ------------------------------------------------ #
    def _place(self, widget: Any, pady: tuple[int, int] = (2, 6), sticky: str = "ew") -> Any:
        widget.grid(row=self._row, column=0, sticky=sticky, padx=10, pady=pady)
        self._row += 1
        if self._group is not None:
            self._group.append(widget)
        return widget

    def note(self) -> ctk.CTkLabel:
        """A highlighted line that says what was picked in the PDF (hidden until used)."""
        label = ctk.CTkLabel(self.frame, text="", text_color=PICKED, anchor="w", justify="left")
        self._place(label, pady=(4, 0), sticky="w")
        label.grid_remove()
        return label

    @staticmethod
    def show_note(label: ctk.CTkLabel, text: str) -> None:
        label.configure(text=text)
        if text:
            label.grid()
        else:
            label.grid_remove()

    @staticmethod
    def set_entry(widget: ctk.CTkEntry, text: str) -> None:
        widget.delete(0, "end")
        if text:
            widget.insert(0, text)

    def label(self, text: str, muted: bool = False) -> None:
        self._place(ctk.CTkLabel(self.frame, text=text, justify="left", anchor="w",
                                 text_color=MUTED if muted else None), pady=(8 if not muted else 0, 0), sticky="w")

    def entry(self, key: str, label: str, default: str = "", placeholder: str = "", width: int | None = None) -> None:
        self.label(label)
        widget = ctk.CTkEntry(self.frame, placeholder_text=placeholder, **({"width": width} if width else {}))
        if default:
            widget.insert(0, default)
        self.inputs[key] = self._place(widget, sticky="w" if width else "ew")

    def textbox(self, key: str, label: str, default: str = "", height: int = 70) -> None:
        self.label(label)
        widget = ctk.CTkTextbox(self.frame, height=height)
        widget.insert("1.0", default)
        self.inputs[key] = self._place(widget)

    def checkbox(self, key: str, text: str, checked: bool) -> None:
        widget = ctk.CTkCheckBox(self.frame, text=text)
        if checked:
            widget.select()
        self.inputs[key] = self._place(widget, sticky="w")

    def section_picker(self, key: str, label: str, optional: bool = False) -> None:
        self.label(label)
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        combo = ctk.CTkComboBox(row, values=[], width=200)
        combo.set("")
        combo.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Load sections", width=120,
                      command=lambda: self.ctx.refresh_sections()).pack(side="left", padx=(6, 0))
        self.ctx.section_combos.append((combo, optional))
        self.inputs[key] = combo
        self._place(row)

    def value(self, key: str) -> Any:
        widget = self.inputs[key]
        if isinstance(widget, ctk.CTkTextbox):
            return widget.get("1.0", "end").strip()
        if isinstance(widget, ctk.CTkCheckBox):
            return bool(widget.get())
        return widget.get().strip()

    def number(self, key: str, low: int, high: int) -> int | None:
        raw = self.value(key)
        if not raw:
            return None
        if not raw.isdigit() or not low <= int(raw) <= high:
            raise ValueError(f"'{raw}' is not a valid value ({low}-{high}).")
        return int(raw)

    def build(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def params(self) -> dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError


class LiteratureForm(Form):
    workflow = LiteratureReviewWorkflow

    def build(self) -> None:
        self.entry("topic", "Topic", placeholder="Blank = derived from the selected paper's title and abstract")
        self.textbox("focus", "Focus (optional) - sub-questions, methods, exclusions", height=55)
        self.entry("max_papers", "Approx. number of papers", "20", width=120)
        self.entry("year_from", "Published from (year, optional)", placeholder="e.g. 2018", width=120)
        self.label("Searches OpenAlex, Crossref and arXiv (plus Claude web search if enabled). Read-only: "
                   "writes a review with a link for every paper,\na verification table and a .bib of new "
                   "candidates.", muted=True)

    def params(self) -> dict[str, Any]:
        return {"topic": self.value("topic"), "focus": self.value("focus"),
                "max_papers": self.number("max_papers", 3, 60) or 20,
                "year_from": self.number("year_from", 1900, datetime.now().year)}


class ReferencesForm(Form):
    workflow = AddReferencesWorkflow

    def build(self) -> None:
        self.textbox("identifiers", "DOIs, arXiv IDs / links or paper titles - one per line", height=80)
        self.label("…and/or import entries from .bib files on your computer")
        self.files = FileList(self.frame, "Choose .bib files", BIB_TYPES, height=50)
        self._place(self.files)
        self.label("Add to .bib file (blank = first editable .bib of the paper, or a new references.bib)")
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        combo = ctk.CTkComboBox(row, values=[""], width=200)
        combo.set("")
        combo.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="List .bib files", width=120, command=self.ctx.refresh_bibs).pack(side="left", padx=(6, 0))
        self.ctx.bib_combos.append(combo)
        self.inputs["target_bib"] = combo
        self._place(row)
        self.section_picker("cite_section", "Cite them in section (optional)", optional=True)
        self.checkbox("write_sentence", "Let Claude write a sentence citing them there (otherwise a plain \\cite{} "
                                        "is added)", checked=True)
        self.label("Metadata comes from OpenAlex / Crossref / arXiv or your file - never invented. Duplicates are "
                   "skipped; read-only (Zotero) .bib files are never edited.", muted=True)

    def focus(self, section: str) -> None:
        self.inputs["cite_section"].set(section)

    def params(self) -> dict[str, Any]:
        return {"identifiers": self.value("identifiers"), "bib_files": [str(p) for p in self.files.files],
                "target_bib": self.value("target_bib"), "cite_section": self.value("cite_section"),
                "write_sentence": self.value("write_sentence")}


class EditForm(Form):
    workflow = SafeEditWorkflow

    def build(self) -> None:
        self.picked = self.note()
        self.section_picker("section", "Section")
        self.entry("edit_path", "File (optional)", placeholder="Repo-relative path; blank = search all .tex files")
        self.textbox("instructions", "Editing instructions",
                     "Improve clarity, flow and concision. Keep all technical content.")

    def focus(self, section: str, path: str, note: str) -> None:
        """Pre-fill from a click in the PDF."""
        self.inputs["section"].set(section)
        self.set_entry(self.inputs["edit_path"], path)
        self.show_note(self.picked, note)

    def params(self) -> dict[str, Any]:
        return {"section_title": self.value("section"), "path": self.value("edit_path") or None,
                "instructions": self.value("instructions")}


class FiguresForm(Form):
    workflow = AddFiguresWorkflow
    MODES = ("Add new figures", "Replace a figure")

    def build(self) -> None:
        self.mode = ctk.CTkSegmentedButton(self.frame, values=list(self.MODES), command=self.set_mode)
        self._place(self.mode, sticky="w")
        self.picked = self.note()

        self._group = self.add_widgets = []
        self.label("Images from anywhere on your computer (PNG, JPG, PDF; TIFF/BMP/GIF/WebP are converted)")
        self.files = FileList(self.frame, "Choose images", IMAGE_TYPES)
        self._place(self.files)
        self.section_picker("section", "Place the figures at the end of section")
        self.textbox("caption", "Caption (optional, used when adding a single image)", height=45)
        self.entry("width", "Width", r"0.8\linewidth", width=160)
        self.checkbox("draft_captions", "Let Claude draft captions by looking at each image", checked=True)
        self.checkbox("reference_sentence", "Add a sentence that refers to each figure (Figure~\\ref{…})", checked=True)
        self.label("Images are copied into the paper's figures folder only after you approve them.", muted=True)

        self._group = self.replace_widgets = []
        self.figures: dict[str, FigureRef] = {}
        self.label("Figure to replace (or click a figure in the PDF preview)")
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.figure_combo = ctk.CTkComboBox(row, values=[], width=200, command=self._figure_chosen)
        self.figure_combo.set("")
        self.figure_combo.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="List figures", width=120, command=self.refresh_figures).pack(side="left", padx=(6, 0))
        self._place(row)
        self.figure_info = ctk.CTkLabel(self.frame, text="", text_color=MUTED, anchor="w", justify="left",
                                        wraplength=640)
        self._place(self.figure_info, pady=(0, 4), sticky="w")
        self.label("New image")
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.new_image = ctk.CTkEntry(row, placeholder_text="Choose the new image file")
        self.new_image.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Choose image…", width=120, command=self._choose_image).pack(side="left", padx=(6, 0))
        self._place(row)
        self.textbox("new_caption", "New caption (optional - blank keeps the current caption)", height=45)
        self.checkbox("update_caption", "Let Claude update the caption for the new image", checked=False)
        self.label("Same file type: the image file is replaced in place (no LaTeX change). Otherwise the new file "
                   "is added\nand the figure points to it. Nothing changes until you approve.", muted=True)
        self._group = None
        self.set_mode(self.MODES[0])

    # -- modes ---------------------------------------------------------- #
    @property
    def replacing(self) -> bool:
        return self.mode.get() == self.MODES[1]

    def set_mode(self, mode: str) -> None:
        self.mode.set(mode)
        shown, hidden = ((self.replace_widgets, self.add_widgets) if mode == self.MODES[1]
                         else (self.add_widgets, self.replace_widgets))
        for widget in hidden:
            widget.grid_remove()
        for widget in shown:
            widget.grid()
        self.show_note(self.picked, "")

    def refresh_figures(self, keep: FigureRef | None = None) -> None:
        refs = self.ctx.list_figures()
        if keep is not None and not any(self._same(keep, r) for r in refs):
            refs.insert(0, keep)
        self.figures = {ref.display(): ref for ref in refs}
        self.figure_combo.configure(values=list(self.figures))
        if self.figure_combo.get() not in self.figures:
            self.figure_combo.set("")
            self.figure_info.configure(text="" if refs else "No figures with \\includegraphics were found.")

    @staticmethod
    def _same(a: FigureRef, b: FigureRef) -> bool:
        return (a.rel_path, a.start_line, a.graphic) == (b.rel_path, b.start_line, b.graphic)

    def _figure_chosen(self, choice: str) -> None:
        ref = self.figures.get(choice)
        if ref is None:
            self.figure_info.configure(text="")
            return
        caption = ref.caption if len(ref.caption) < 220 else ref.caption[:217] + "…"
        self.figure_info.configure(text=f"Image: {ref.graphic}   ·   {ref.rel_path}, line {ref.start_line}\n"
                                        f"Caption: {caption or '(none)'}")

    def _choose_image(self) -> None:
        name = filedialog.askopenfilename(parent=self.frame, title="Choose the new image", filetypes=IMAGE_TYPES)
        if name:
            self.set_entry(self.new_image, name)

    def focus_replace(self, ref: FigureRef, note: str) -> None:
        """Switch to Replace mode with ``ref`` selected (from a click in the PDF)."""
        self.set_mode(self.MODES[1])
        self.refresh_figures(keep=ref)
        key = next((k for k, value in self.figures.items() if self._same(value, ref)), ref.display())
        self.figures[key] = ref  # the clicked version (its graphic comes first)
        self.figure_combo.set(key)
        self._figure_chosen(key)
        self.show_note(self.picked, note)

    def focus_add(self, section: str, note: str) -> None:
        self.set_mode(self.MODES[0])
        self.inputs["section"].set(section)
        self.show_note(self.picked, note)

    def params(self) -> dict[str, Any]:
        if self.replacing:
            ref = self.figures.get(self.figure_combo.get())
            if ref is None:
                raise ValueError("Choose the figure to replace (click it in the PDF or use 'List figures').")
            image = self.new_image.get().strip()
            if not image:
                raise ValueError("Choose the new image file.")
            return {"mode": "replace", "files": [image], "replace_tex": ref.rel_path,
                    "replace_graphic": ref.graphic, "replace_label": ref.label, "replace_line": ref.start_line,
                    "caption": self.value("new_caption"), "draft_captions": self.value("update_caption")}
        return {"files": [str(p) for p in self.files.files], "section_title": self.value("section"),
                "caption": self.value("caption"), "width": self.value("width") or r"0.8\linewidth",
                "draft_captions": self.value("draft_captions"),
                "reference_sentence": self.value("reference_sentence")}


class AuditForm(Form):
    workflow = CitationAuditWorkflow

    def build(self) -> None:
        self.label("Read-only check of the selected paper: missing or duplicate citation keys, missing or "
                   "malformed DOIs,\nmissing required fields and unused entries. DOIs are never invented. "
                   "No Claude sign-in needed.", muted=True)

    def params(self) -> dict[str, Any]:
        return {}


class CustomForm(Form):
    workflow = CustomAgentWorkflow

    def build(self) -> None:
        self.textbox("goal", "Describe the task (the agent can read, search literature, edit, audit, compile and "
                             "commit - every edit needs your approval)",
                     "Read the paper and suggest a clearer abstract; stage the edit.", height=110)

    def params(self) -> dict[str, Any]:
        return {"goal": self.value("goal")}


FORMS: dict[str, type[Form]] = {form.workflow.name: form for form in (
    LiteratureForm, ReferencesForm, EditForm, FiguresForm, AuditForm, CustomForm)}
