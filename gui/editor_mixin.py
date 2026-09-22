"""Main-window glue for the middle area: "Agent tasks" and the "Edit .tex" source editor.

Mixed into :class:`gui.app.ResearchAssistantApp`. The editor saves straight to the
paper folder and commits each save locally, so the Sync button and the agent (which
refuse uncommitted changes) keep working; nothing is sent until Sync.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.agent_engine import with_identity
from core.app_state import PaperSpec
from core.events import EventKind
from core.git_manager import GitManager, GitOperationError
from core.project_layout import PROTECTED_FOLDERS
from core.protection import ProtectionPolicy
from gui.tex_editor import EditorContext, TexEditor

AGENT_MODE = "🤖  Agent tasks"
EDITOR_MODE = "✎  Edit .tex"


class EditorMixin:
    """Needs ``self.app_state``, ``self.config_``, ``self.panel``, ``self._paper_root()`` and friends."""

    def _build_middle(self, parent: Any) -> ctk.CTkFrame:
        middle = ctk.CTkFrame(parent, fg_color="transparent")
        self.mode_switch = ctk.CTkSegmentedButton(middle, values=[AGENT_MODE, EDITOR_MODE],
                                                  command=self.show_mode)
        self.mode_switch.pack(fill="x", pady=(0, 8))
        self._editor_paper: Path | None = None
        return middle

    def _attach_editor(self, middle: ctk.CTkFrame) -> None:
        self.editor = TexEditor(middle, EditorContext(
            paper_root=self._paper_root, read_only_reason=self._editor_read_only,
            save_blocked=self._editor_save_blocked, commit=self._editor_commit,
            recompile=lambda: self.recompile_preview(quiet=True), notify=self.panel.append))
        self.show_mode(AGENT_MODE)

    def show_mode(self, mode: str) -> None:
        """Show Agent tasks or the editor; the PDF click switch follows unless it is Off."""
        self.mode_switch.set(mode)
        preview = getattr(self, "preview", None)  # the preview pane is built after this column
        if preview is not None and preview.mode != "off":
            preview.set_click_mode("source" if mode == EDITOR_MODE else "agent")
        if mode == EDITOR_MODE:
            self.panel.pack_forget()
            self.editor.pack(fill="both", expand=True)
            if self.editor.rel is None:
                self.editor.paper_changed()
            self.editor.code.apply_theme()
        else:
            self.editor.pack_forget()
            self.panel.pack(fill="both", expand=True)

    def sync_middle_to_click_mode(self, click_mode: str) -> None:
        if click_mode == "source":
            self.show_mode(EDITOR_MODE)
        elif click_mode == "agent":
            self.show_mode(AGENT_MODE)

    def editor_paper_changed(self) -> None:
        """Called on every paper refresh; only reloads when the paper (or its folder) really changed."""
        root = self._paper_root()
        exists = root is not None and root.is_dir()
        key = root if exists else None
        if key != self._editor_paper or (exists and self.editor.rel is None):
            self._editor_paper = key
            self.editor.paper_changed()
        else:
            self.editor.refresh_files()

    def open_in_editor(self, rel_path: str, line: int | None, note: str = "") -> None:
        self.show_mode(EDITOR_MODE)
        self.editor.open_file(rel_path, line)
        if note:
            self.editor.status.configure(text=note)

    def open_error_location(self, location: str, line: int) -> None:
        """A click on a LaTeX error: map the log's file path to the paper and open that line."""
        root = self._paper_root()
        if root is None:
            return
        path = Path(location)
        mirror = self._preview_builder().base / "src" / root.name  # proposals compile in a mirror
        rel = None
        for base in (root, mirror):
            try:
                rel = (path if path.is_absolute() else base / path).resolve().relative_to(base.resolve()).as_posix()
                break
            except ValueError:
                continue
        if rel and (root / rel).is_file():
            self.open_in_editor(rel, line)
        else:
            self.panel.append(EventKind.WARNING, f"{location} is not a file of this paper.")

    # ------------------------------------------------------------------ #
    def _spec_for(self, root: Path) -> PaperSpec | None:
        """The paper whose folder is ``root`` (the editor may still show the previous paper)."""
        for spec in self.app_state.papers:
            local = spec.local_path.strip() or str(self.config_.papers_dir / spec.name)
            if Path(local).expanduser().resolve() == root.resolve():
                return spec
        return None

    def _editor_read_only(self, root: Path, rel: str) -> str | None:
        spec = self._spec_for(root)
        if spec is None:
            return None
        if rel.split("/", 1)[0] in PROTECTED_FOLDERS:
            return None  # data/ and code/ are off limits for the agent, not for you
        return ProtectionPolicy.build(root, spec.read_only, spec.auto_protect_bib).reason(rel)

    def _editor_save_blocked(self) -> str | None:
        if self._workflow_running() or self._todo_busy:
            return "A task is running - save when it has finished (your text is kept)."
        return None

    def _editor_commit(self, root: Path, rel: str) -> str:
        spec = self._spec_for(root)
        if spec is None:
            raise GitOperationError("the paper was removed from the list")
        config = with_identity(self.config_, self.app_state.author_name, self.app_state.author_email)
        git = GitManager(root, spec.remote_url, spec.branch, config.git)
        sha = git.commit([rel], f"Edit {rel} in the editor")
        where = "Sync sends it to Overleaf" if spec.remote_url else "on this computer"
        return f"committed locally ({sha}) - {where}"

    def _editor_may_close(self) -> bool:
        if not self.editor.has_unsaved():
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", f"Save your changes to {self.editor.rel} before "
                                           "closing?", parent=self)
        if answer:
            self.editor.save(recompile=False, blocking=True)
        return answer is not None
