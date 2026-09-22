"""The Overleaf-style PDF preview pane and its controller.

* :class:`PreviewPane` - viewer, status badge, Recompile / auto-recompile,
  zoom, page counter, "next change" navigation, click-to-edit status and
  compile errors.
* :class:`PushConfirmDialog` - "Push to Overleaf / Discard" after approval.
* :class:`PreviewMixin` - main-window glue: split layout, background
  recompiles, preview events, auto-recompile polling.
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from typing import Any

import customtkinter as ctk

from core.events import EventKind
from core.latex_parser import find_main_tex
from core.preview import KIND_APPROVED, KIND_CURRENT, KIND_PROPOSED, PreviewBuilder, PreviewResult, source_signature
from gui.dialogs import _Dialog
from gui.panels import open_path

MUTED = "#8b949e"
BADGES = {
    KIND_CURRENT: ("#3fb950", "Current version (your local copy)"),
    KIND_PROPOSED: ("#f0883e", "PREVIEW - proposed changes, not approved yet"),
    KIND_APPROVED: ("#58a6ff", "Approved changes - not pushed yet"),
}
AUTO_POLL_MS = 2000
MIDDLE_MIN = 460        # px the task forms / editor need
PREVIEW_SHARE = 0.62   # the PDF gets this share of the width at start
ERROR_LOCATION_RE = re.compile(r"^(.+?\.(?:tex|bib|sty|cls|bbl)):(\d+): ")
CLICK_MODES = {"Agent task": "agent", "Edit .tex": "source", "Off": "off"}  # same order as the middle column
CLICK_HINTS = {
    "source": "Click opens the .tex line in the editor; right-click for more.",
    "agent": "Click text to edit its section with the agent, a figure to replace it; right-click for more.",
    "off": "Clicking is off - right-click still opens the menu.",
}


class PreviewPane(ctk.CTkFrame):
    """PDF preview with status, navigation and compile errors."""

    def __init__(self, master: Any, recompile: Callable[[], None], on_click: Callable[..., None] | None = None,
                 click_mode: str = "agent", on_mode: Callable[[str], None] | None = None,
                 on_error_click: Callable[[str, int], None] | None = None) -> None:
        super().__init__(master, corner_radius=0)
        from gui.pdf_view import PdfViewer

        self.recompile_cb = recompile
        self.result: PreviewResult | None = None
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(head, text="PDF preview", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Open PDF", width=90, fg_color="transparent", border_width=1,
                      command=self._open_external).pack(side="right")
        self.badge = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", justify="left", wraplength=560)
        self.badge.pack(fill="x", padx=10, pady=(2, 0))
        self.badge.bind("<Configure>", lambda e: self.badge.configure(wraplength=max(200, e.width - 10)))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=4)
        self.recompile_button = ctk.CTkButton(bar, text="⟳ Recompile", width=100, command=recompile)
        self.recompile_button.pack(side="left")
        self.auto = ctk.CTkCheckBox(bar, text="Auto-recompile", width=60)
        self.auto.pack(side="left", padx=(8, 0))
        self.next_change = ctk.CTkButton(bar, text="Next change ▸", width=110, state="disabled",
                                         fg_color="#9e5a1c", hover_color="#b86a23", command=self._goto_next_change)
        self.next_change.pack(side="left", padx=8)
        ctk.CTkButton(bar, text="⤢", width=30, command=lambda: self.viewer.set_zoom(None)).pack(side="right")
        ctk.CTkButton(bar, text="+", width=30, command=lambda: self.viewer.zoom_in()).pack(side="right", padx=2)
        ctk.CTkButton(bar, text="−", width=30, command=lambda: self.viewer.zoom_out()).pack(side="right", padx=2)
        self.page_label = ctk.CTkLabel(bar, text="", width=70, text_color=MUTED)
        self.page_label.pack(side="right", padx=4)

        links = ctk.CTkFrame(self, fg_color="transparent")
        links.pack(fill="x", padx=10)
        ctk.CTkLabel(links, text="Click in PDF:").pack(side="left")
        self.click_mode = ctk.CTkSegmentedButton(links, values=list(CLICK_MODES), command=self._mode_clicked)
        self.click_mode.pack(side="left", padx=(6, 0))
        self._on_mode = on_mode
        self.source_label = ctk.CTkLabel(links, text="", text_color=MUTED, anchor="w")
        self.source_label.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.viewer = PdfViewer(self, on_page_change=self._page_changed, on_click=on_click)
        self.viewer.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self.set_click_mode(click_mode)
        self.errors = ctk.CTkTextbox(self, height=110, font=ctk.CTkFont(family="Consolas", size=12),
                                     text_color="#f85149", cursor="hand2")
        self._on_error_click = on_error_click
        self.errors.bind("<Button-1>", self._error_clicked)

    # ------------------------------------------------------------------ #
    @property
    def mode(self) -> str:
        """``agent`` (fill a task form), ``source`` (open the .tex line) or ``off``."""
        return CLICK_MODES.get(self.click_mode.get(), "agent")

    def set_click_mode(self, mode: str) -> None:
        label = next((k for k, v in CLICK_MODES.items() if v == mode), "Agent task")
        self.click_mode.set(label)
        self.viewer.clickable = mode != "off"
        self.set_source_status(CLICK_HINTS[CLICK_MODES[label]])

    def _mode_clicked(self, label: str) -> None:
        self.set_click_mode(CLICK_MODES[label])
        if self._on_mode:
            self._on_mode(CLICK_MODES[label])

    def _error_clicked(self, event: Any) -> None:
        """Open the ``file:line:`` of the clicked error in the editor."""
        index = self.errors._textbox.index(f"@{event.x},{event.y}")
        line_text = self.errors.get(f"{index} linestart", f"{index} lineend")
        match = ERROR_LOCATION_RE.match(line_text)
        if match and self._on_error_click:
            self._on_error_click(match.group(1), int(match.group(2)))

    def set_source_status(self, text: str, error: bool = False) -> None:
        self.source_label.configure(text=text, text_color="#e3b341" if error else MUTED)

    def set_busy(self, busy: bool) -> None:
        self.recompile_button.configure(state="disabled" if busy else "normal")

    def set_compiling(self, label: str) -> None:
        self.badge.configure(text=f"⏳ {label}", text_color=MUTED)

    def show(self, result: PreviewResult) -> None:
        previous = self.result
        self.result = result
        color, text = BADGES.get(result.kind, (MUTED, result.label))
        if result.kind == KIND_CURRENT and "pushed" in result.label.lower():
            text = "Pushed - this is the version your collaborators now have"
        if result.kind == KIND_PROPOSED:
            text = result.label.upper() if result.success else text
        if not result.success:
            color, text = "#f85149", f"Compile failed ({result.label.lower()}) - showing the last good PDF"
        changed = len(result.changed_pages)
        if changed and result.success:
            text += f" · {changed} changed page{'s' if changed != 1 else ''}"
        if result.success and result.errors:
            count = len(result.errors)
            color = "#d29922"
            text += f" · {count} LaTeX error{'s' if count != 1 else ''} (PDF still produced, as in Overleaf)"
        self.badge.configure(text=text, text_color=color)
        self.errors.pack_forget()
        if result.errors:
            self.errors.delete("1.0", "end")
            self.errors.insert("1.0", "\n".join(result.errors[:30]))
            self.errors.pack(fill="x", padx=10, pady=(0, 10))
        self.next_change.configure(state="normal" if changed and result.success else "disabled")
        if result.success and result.pdf_path and result.pdf_path.exists():
            same_document = previous is not None and previous.pdf_path == result.pdf_path
            self.viewer.load(result.pdf_path, set(result.changed_pages),
                             keep_position=same_document or result.kind == KIND_CURRENT)
            if changed and result.kind in (KIND_PROPOSED, KIND_APPROVED):
                self.viewer.jump_to(result.changed_pages[0])
        elif self.viewer.data is None:
            self.viewer.message("No PDF could be produced - see the errors below.")

    def show_cached(self, pdf: Path) -> None:
        self.result = PreviewResult(KIND_CURRENT, "Last compiled version", True, pdf)
        self.badge.configure(text="Last compiled version - click Recompile to refresh", text_color=MUTED)
        self.viewer.load(pdf, keep_position=False)

    def clear(self, text: str) -> None:
        self.result = None
        self.badge.configure(text="", text_color=MUTED)
        self.errors.pack_forget()
        self.next_change.configure(state="disabled")
        self.viewer.data = None
        self.viewer.sizes = []
        self.viewer.message(text)

    def _goto_next_change(self) -> None:
        if not self.result or not self.result.changed_pages:
            return
        current = self.viewer.current_page()
        pages = self.result.changed_pages
        self.viewer.jump_to(next((p for p in pages if p > current), pages[0]))

    def _page_changed(self, page: int, total: int) -> None:
        self.page_label.configure(text=f"{page} / {total}" if total else "")

    def _open_external(self) -> None:
        if self.result and self.result.pdf_path and self.result.pdf_path.exists():
            open_path(self.result.pdf_path)


class PushConfirmDialog(_Dialog):
    """Final check before approved changes leave the computer."""

    DEFAULT_DETAIL = ("The approved changes are committed locally and compiled - check the PDF preview. "
                      "Push sends them to your collaborators; Discard throws them away.")

    def __init__(self, master: Any, message: str, files: list[str], on_decision: Callable[[bool], None],
                 detail: str = "", button: str = "Push", cancel: str = "Discard") -> None:
        super().__init__(master, "Send changes?", message, detail or self.DEFAULT_DETAIL)
        self.on_decision = on_decision
        listed = ", ".join(files[:12]) + (" …" if len(files) > 12 else "")
        self.label(listed, color=MUTED)
        self.finish_layout(button, lambda: self.close(True))
        self.primary.configure(fg_color="#1f6f3a", hover_color="#27894a")
        for child in self.buttons.winfo_children():
            if isinstance(child, ctk.CTkButton) and child.cget("text") == "Cancel":
                child.configure(text=cancel)
        self._decided = False

    def _grab(self) -> None:  # stay non-modal so the preview can be scrolled
        self.lift()

    def close(self, ok: bool) -> None:
        if self._decided:
            return
        self._decided = True
        self.destroy()
        self.on_decision(ok)


class PreviewMixin:
    """Main-window glue for the preview pane (mixed into ResearchAssistantApp)."""

    def _build_split(self) -> tk.PanedWindow:
        mode = ctk.get_appearance_mode()
        colors = ctk.ThemeManager.theme["CTk"]["fg_color"]
        background = colors[1] if mode == "Dark" else colors[0]
        split = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bd=0, bg=background, sashrelief="flat")
        split.grid(row=0, column=1, sticky="nsew")
        self._preview_busy = False
        self._last_signature: tuple | None = None
        return split

    def _attach_preview(self) -> None:
        self.preview = PreviewPane(self.split, recompile=self.recompile_preview, on_click=self.pdf_clicked,
                                   on_mode=self._click_mode_changed,
                                   on_error_click=self.open_error_location)
        self.split.add(self.middle, minsize=MIDDLE_MIN, stretch="always", padx=6, pady=6)
        if self.app_state.show_preview:
            self.split.add(self.preview, minsize=360, stretch="always")
            self.after(200, self._place_sash)
        self.after(AUTO_POLL_MS, self._auto_recompile_tick)

    def _place_sash(self) -> None:
        """Give the PDF most of the width (the task/editor side keeps what it needs)."""
        self.update_idletasks()
        width = self.split.winfo_width()
        if width > 1:
            self.split.sash_place(0, max(MIDDLE_MIN, int(width * (1 - PREVIEW_SHARE))), 0)

    def _click_mode_changed(self, mode: str) -> None:
        """The PDF click switch moves the middle column along (Off leaves it as it is)."""
        self.sync_middle_to_click_mode(mode)

    def toggle_preview(self) -> None:
        shown = str(self.preview) in [str(pane) for pane in self.split.panes()]
        if shown:
            self.split.forget(self.preview)
        else:
            self.split.add(self.preview, minsize=360, stretch="always")
            self.after(50, self._place_sash)
        self.app_state.show_preview = not shown
        self.preview_visible_var.set(not shown)
        self._save_state()

    def _preview_builder(self) -> PreviewBuilder:
        return PreviewBuilder(self.config_.latex, self.config_.build_dir)

    def _paper_root(self) -> Path | None:
        spec = self.app_state.current
        if spec is None:
            return None
        return Path(spec.local_path.strip() or self.config_.papers_dir / spec.name).expanduser()

    def preview_paper_changed(self) -> None:
        root = self._paper_root()
        main = find_main_tex(root) if root and root.is_dir() else None
        self._last_signature = None
        if main is None:
            self.preview.clear("Sync the paper, then click Recompile to see the PDF.")
            return
        cached = self._preview_builder().current_pdf(root, main.relative_to(root).as_posix())
        if cached.exists():
            self.preview.show_cached(cached)
        else:
            self.preview.clear("Click Recompile to build the PDF of this paper.")

    def recompile_preview(self, quiet: bool = False) -> None:
        """Compile the paper as it is on disk, in the background."""
        root = self._paper_root()
        builder = self._preview_builder()
        if self._preview_busy:
            return
        if self._workflow_running() or self._todo_busy:
            if not quiet:
                self.panel.append(EventKind.WARNING, "The paper is busy - recompile when the current task is done.")
            return
        if not builder.available:
            self.preview.clear("No LaTeX compiler found - install MiKTeX or TeX Live to see the PDF.")
            return
        main = find_main_tex(root) if root and root.is_dir() else None
        if main is None:
            if not quiet:
                self.panel.append(EventKind.WARNING, "The paper is not cloned yet - click 'Sync paper' first.")
            return
        self._preview_busy = True
        self.preview.set_busy(True)
        self.preview.set_compiling("Compiling current version…")
        self._last_signature = source_signature(root)
        main_rel = main.relative_to(root).as_posix()

        def work() -> None:
            try:
                self.bus.emit(EventKind.PREVIEW, "", result=builder.current(root, main_rel), done=True)
            except Exception as exc:  # noqa: BLE001 - reported in the log
                self.bus.emit(EventKind.ERROR, f"Preview compile failed: {exc}")
                self.bus.emit(EventKind.PREVIEW, "", done=True)

        threading.Thread(target=work, daemon=True, name="preview-compile").start()

    def _auto_recompile_tick(self) -> None:
        try:
            root = self._paper_root()
            if (self.preview.auto.get() and root and root.is_dir() and not self._preview_busy
                    and not self._workflow_running() and not self._todo_busy
                    and source_signature(root) != self._last_signature):
                self.recompile_preview(quiet=True)
        finally:
            self.after(AUTO_POLL_MS, self._auto_recompile_tick)

    def handle_preview_event(self, data: dict[str, Any]) -> None:
        if "click" in data or "click_error" in data:
            self.handle_click_event(data)
            return
        if data.get("done"):
            self._preview_busy = False
            self.preview.set_busy(False)
        if "compiling" in data:
            self.preview.set_compiling(data["compiling"])
        if data.get("result") is not None:
            self.preview.show(data["result"])
            if data["result"].kind == KIND_CURRENT:
                root = self._paper_root()
                self._last_signature = source_signature(root) if root and root.is_dir() else None

    def confirm_push(self, request_id: int, message: str, data: dict[str, Any]) -> None:
        gate, files = self.gate, data.get("files", [])
        syncing = bool(data.get("detail"))  # the Sync button: commits already exist locally

        def decided(ok: bool) -> None:
            if gate is not None:
                gate.resolve(request_id, ok)
            if syncing:
                self.panel.append(EventKind.INFO, "Syncing…" if ok else "Sync cancelled.")
            else:
                self.panel.append(EventKind.INFO, "Pushing…" if ok else "Discarding the approved changes…")

        PushConfirmDialog(self, message, files, decided, detail=data.get("detail", ""),
                          button="Sync now" if syncing else "Push",
                          cancel="Not now" if syncing else "Discard")
