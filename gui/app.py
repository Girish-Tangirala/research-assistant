"""CustomTkinter desktop dashboard for the Scientific Research Assistant Agent.

Threading model: workflows run on a daemon worker thread and communicate only
through :class:`core.events.EventBus`. The Tk main loop drains the bus every
50 ms, so widgets are only ever touched from the GUI thread. Approval requests
block the worker on :class:`core.events.ApprovalGate` until the reviewer clicks
*Approve* or *Reject* in the :class:`gui.diff_window.DiffWindow`.

Sign-in: the Claude key and Git tokens are requested in-app (at start-up and
whenever a run needs them or a service rejects them) and persisted in the OS
credential vault via :class:`core.credentials.CredentialStore`.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from config import AppConfig
from version import __version__
from core.agent_engine import AgentEngine, EngineCredentials, RunOptions, WorkflowState, with_identity
from core.app_state import AppState, PaperSpec
from core.credentials import CredentialStore
from core.dependencies import missing_tools
from core.events import AgentEvent, ApprovalGate, CancelledError, CancelToken, EventBus, EventKind
from core.git_manager import GitAuthError, GitManager, git_global_identity
from core.llm_client import LLMAuthError
from core.registry import WORKFLOWS
from core.todos import TodoError, TodoStore
from core.workflows import BaseWorkflow, SyncWorkflow
from gui.accounts import AccountsMixin
from gui.diff_window import DiffWindow
from gui.editor_mixin import EditorMixin
from gui.setup_dialog import SetupDialog
from gui.update_dialog import UpdateMixin
from gui.menubar import AppMenuBar, MenuActions
from gui.panels import TaskPanel, open_path
from gui.papers import NO_PAPER, PapersMixin
from gui.pdf_links import PdfLinkMixin
from gui.preview_pane import PreviewMixin
from gui.todo_panel import TodoContext

logger = logging.getLogger("research_agent")
MUTED = "#8b949e"
SIDEBAR_WIDTH = 172   # narrow, so the PDF gets the room
WRAP = SIDEBAR_WIDTH - 34   # labels sit inside a padded frame


class ResearchAssistantApp(AccountsMixin, PapersMixin, PreviewMixin, PdfLinkMixin, EditorMixin, UpdateMixin,
                           ctk.CTk):
    """Main application window."""

    def __init__(self, config: AppConfig, store: CredentialStore | None = None) -> None:
        super().__init__()
        self.config_ = config
        self.store = store or CredentialStore()
        self.app_state = AppState.load(config.settings_file)
        if not (self.app_state.author_name and self.app_state.author_email):
            name, email = git_global_identity()
            self.app_state.author_name = self.app_state.author_name or name
            self.app_state.author_email = self.app_state.author_email or email
        ctk.set_appearance_mode(self.app_state.appearance)
        self.bus = EventBus()
        self.cancel_token: CancelToken | None = None
        self.gate: ApprovalGate | None = None
        self.worker: threading.Thread | None = None
        self._todo_busy = False

        self.title("Scientific Research Assistant Agent")
        self.geometry("1600x900")
        self.minsize(1100, 650)
        if self.tk.call("tk", "windowingsystem") == "win32":
            self.after(0, lambda: self.state("zoomed"))  # start maximised: the PDF needs the room
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_menubar()
        todo = TodoContext(make_store=self._todo_store, is_busy=self._workflow_running,
                           load_sections=self._load_sections, notify=self.panel_log,
                           handle_error=self._todo_error, set_todo_busy=self._set_todo_busy)
        self.split = self._build_split()
        self.middle = self._build_middle(self.split)
        self.panel = TaskPanel(self.middle, list(WORKFLOWS), run=self._run_selected, cancel=self._cancel,
                               load_sections=self._load_sections, list_bibs=self._list_bibs, todo=todo,
                               list_figures=self._list_figures)
        self._attach_editor(self.middle)
        self._attach_preview()
        self._refresh_papers()
        for problem in config.validate():
            self.panel.append(EventKind.WARNING, problem)
        self.panel.append(EventKind.INFO, f"Workspace: {config.workspace}")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll_events)
        self.after(400, self._startup)

    # ------------------------------------------------------------------ #
    # Sidebar
    # ------------------------------------------------------------------ #
    def _section(self, parent: Any, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(8, 4))
        return frame

    def _build_sidebar(self) -> None:
        small = ctk.CTkFont(size=12)
        side = ctk.CTkScrollableFrame(self, width=SIDEBAR_WIDTH, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(side, text="Research Assistant", font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=10, pady=(12, 0))
        ctk.CTkLabel(side, text=f"{self.config_.llm.model} · effort {self.config_.llm.effort}",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10, pady=(0, 4))

        paper = self._section(side, "Paper")
        self.paper_menu = ctk.CTkOptionMenu(paper, values=[NO_PAPER], command=self._select_paper)
        self.paper_menu.pack(fill="x", padx=10, pady=4)
        self.paper_info = ctk.CTkLabel(paper, text="", text_color=MUTED, wraplength=WRAP, justify="left", anchor="w",
                                       font=ctk.CTkFont(size=11))
        self.paper_info.pack(fill="x", padx=10, pady=(0, 4))
        row = ctk.CTkFrame(paper, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(2, 10))
        for text, command in (("Add", self._add_paper), ("Edit", self._edit_paper), ("Remove", self._remove_paper)):
            ctk.CTkButton(row, text=text, width=10, font=small, command=command).pack(
                side="left", padx=(0, 4), expand=True, fill="x")
        self.sync_status = ctk.CTkLabel(paper, text="", text_color=MUTED, wraplength=WRAP, justify="left",
                                        anchor="w", font=ctk.CTkFont(size=11))
        self.sync_status.pack(fill="x", padx=10, pady=(0, 2))
        self.publish_button = ctk.CTkButton(paper, text="⇄  Sync with Overleaf", font=small,
                                            command=self._sync_with_overleaf)
        self.publish_button.pack(fill="x", padx=10, pady=(2, 4))
        bottom = ctk.CTkFrame(paper, fg_color="transparent")
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        self.sync_button = ctk.CTkButton(bottom, text="⟳ Refresh", width=10, font=small, fg_color="transparent",
                                         border_width=1, command=lambda: self._start(SyncWorkflow, {}))
        self.sync_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(bottom, text="Folder", width=10, font=small, fg_color="transparent", border_width=1,
                      command=self._open_paper_folder).pack(side="left", expand=True, fill="x")

    def _build_menubar(self) -> None:
        self.push_var = ctk.BooleanVar(value=self.app_state.push_after_commit)
        self.compile_var = ctk.BooleanVar(value=self.app_state.compile_before_commit)
        self.web_var = ctk.BooleanVar(value=self.app_state.web_search)
        self.appearance_var = ctk.StringVar(value=self.app_state.appearance)
        self.preview_var = ctk.BooleanVar(value=self.app_state.preview)
        self.confirm_var = ctk.BooleanVar(value=self.app_state.confirm_push)
        self.preview_visible_var = ctk.BooleanVar(value=self.app_state.show_preview)
        self.menubar = AppMenuBar(
            self,
            MenuActions(
                add_paper=self._add_paper, edit_paper=self._edit_paper, remove_paper=self._remove_paper,
                sync_paper=lambda: self._start(SyncWorkflow, {}),
                publish_paper=self._sync_with_overleaf,
                open_folder=self._open_paper_folder,
                organise_paper=self._organise_paper,
                open_reports=lambda: open_path(self.config_.reports_dir),
                open_log=self._open_log, exit_app=self._on_close,
                accounts=self._account_sections, options_changed=self._save_state,
                appearance_changed=self._set_appearance, about=self._about,
                toggle_preview=self.toggle_preview, recompile=self.recompile_preview,
                user_guide=self._open_user_guide, setup_tools=lambda: self._check_tools(None, always=True),
                check_updates=lambda: self.check_for_updates(verbose=True),
            ),
            options=[("Send to Overleaf right after each approval (off: use the Sync button)", self.push_var),
                     ("Ask before sending anything to Overleaf", self.confirm_var),
                     ("Compile before commit", self.compile_var),
                     ("Preview changes before approval", self.preview_var),
                     ("Use Claude web search", self.web_var)],
            appearance=self.appearance_var, preview_visible=self.preview_visible_var,
        )

    def _set_appearance(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        self._save_state()

    def _open_log(self) -> None:
        log = self.config_.workspace / "agent.log"
        if log.exists():
            open_path(log)
        else:
            self.panel.append(EventKind.INFO, "No log file yet.")

    def _open_user_guide(self) -> None:
        # Next to the code when run from source; inside the bundle in the packaged app.
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        guide = base / "docs" / "USER_GUIDE.md"
        if guide.exists():
            open_path(guide)
        else:
            self.panel.append(EventKind.WARNING, f"The user guide was not found at {guide}.")

    def _about(self) -> None:
        compiler = self.config_.latex
        tex = compiler.compiler if (compiler.latexmk_path or compiler.pdflatex_path) else "not found"
        messagebox.showinfo(
            "About", f"Scientific Research Assistant Agent {__version__}\n\nModel: {self.config_.llm.model} "
            f"(effort {self.config_.llm.effort})\nLaTeX: {tex}\nWorkspace: {self.config_.workspace}",
            parent=self)

    # ------------------------------------------------------------------ #
    # Start-up
    # ------------------------------------------------------------------ #
    def _startup(self) -> None:
        def after_claude() -> None:
            if not self.app_state.papers:
                self._open_paper_dialog(None)
            else:
                self._ensure_git(self.app_state.current, then=lambda: None, required=False)

        self._check_tools(lambda: self.check_for_updates(lambda: self._ensure_claude(after_claude, required=False)))

    def _check_tools(self, then: Callable[[], None] | None, always: bool = False) -> None:
        """Offer to install Git / MiKTeX when missing (Help menu: show the window anyway)."""
        missing = missing_tools()
        if not missing and not always:
            if then:
                then()
            return
        if not missing:
            messagebox.showinfo("Git and MiKTeX", "Git and MiKTeX are both installed.", parent=self)
            return
        SetupDialog(self, missing, on_done=lambda _ok: then() if then else None)

    # ------------------------------------------------------------------ #
    # Running workflows
    # ------------------------------------------------------------------ #
    def _run_selected(self, name: str, params: dict[str, Any]) -> None:
        self._start(WORKFLOWS[name], params)

    def _workflow_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _start(self, workflow_cls: type[BaseWorkflow], params: dict[str, Any]) -> None:
        if self._workflow_running():
            self.panel.append(EventKind.WARNING, "A workflow is already running.")
            return
        if self._todo_busy:
            self.panel.append(EventKind.WARNING, "The to-do list is syncing - try again in a moment.")
            return
        spec = self.app_state.current
        if spec is None:
            self.panel.append(EventKind.WARNING, "Add a paper first.")
            self._open_paper_dialog(None)
            return
        def after_claude() -> None:
            self._ensure_git(spec, lambda: self._launch(workflow_cls, params, spec))

        if workflow_cls.requires_llm(params):
            self._ensure_claude(after_claude)
        else:
            after_claude()

    def _launch(self, workflow_cls: type[BaseWorkflow], params: dict[str, Any], spec: PaperSpec) -> None:
        host, _ = self._paper_host(spec)
        credentials = self._safe(lambda: EngineCredentials(
            claude_api_key=self.store.get_claude_key(),
            git=self.store.get_git(host) if host else None,
            openalex_key=self.store.get_openalex_key(),
        ))
        if credentials is None:
            return
        self._save_state()
        self.cancel_token = CancelToken()
        self.gate = ApprovalGate(self.bus, self.cancel_token)
        config = with_identity(self.config_, self.app_state.author_name, self.app_state.author_email)
        options = RunOptions(push=self.push_var.get(), compile_before_commit=self.compile_var.get(),
                             web_search=self.web_var.get(), preview=self.preview_var.get(),
                             confirm_push=self.confirm_var.get())
        engine = AgentEngine(config, self.bus, self.cancel_token, self.gate, spec, options, credentials)
        self.panel.set_running(True)
        self.sync_button.configure(state="disabled")
        self.publish_button.configure(state="disabled")
        self.panel.append(EventKind.STATE, f"▶ {workflow_cls.name} - {spec.name}")
        self.worker = threading.Thread(target=self._worker, args=(workflow_cls, params, engine),
                                       daemon=True, name="agent-worker")
        self.worker.start()

    def _worker(self, workflow_cls: type[BaseWorkflow], params: dict[str, Any], engine: AgentEngine) -> None:
        emit = self.bus.emit
        try:
            result = workflow_cls(engine, **params).run()
            emit(EventKind.STATE, WorkflowState.DONE.value)
            emit(EventKind.SUCCESS, result.summary, artifacts=[str(p) for p in result.artifacts])
        except CancelledError:
            emit(EventKind.STATE, WorkflowState.CANCELLED.value)
            emit(EventKind.WARNING, "Workflow cancelled. No unapproved changes were written.")
        except LLMAuthError as exc:
            emit(EventKind.STATE, WorkflowState.FAILED.value)
            emit(EventKind.AUTH_REQUIRED, str(exc), service="claude")
        except GitAuthError as exc:
            emit(EventKind.STATE, WorkflowState.FAILED.value)
            emit(EventKind.AUTH_REQUIRED, str(exc), service="git", host=exc.host)
        except Exception as exc:  # noqa: BLE001 - worker boundary: report everything to the user
            emit(EventKind.STATE, WorkflowState.FAILED.value)
            emit(EventKind.ERROR, f"{type(exc).__name__}: {exc}", failed=True)
            logger.error("Workflow failed\n%s", traceback.format_exc())
        finally:
            emit(EventKind.FINISHED, "")

    def _cancel(self) -> None:
        if self.cancel_token:
            self.cancel_token.cancel()
            self.panel.append(EventKind.WARNING, "Cancellation requested - stopping after the current step…")

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def _poll_events(self) -> None:
        try:
            for event in self.bus.drain():
                self._handle_event(event)
        finally:
            self.after(50, self._poll_events)

    def _handle_event(self, event: AgentEvent) -> None:
        kind = event.kind
        if kind == EventKind.APPROVAL_REQUEST:
            self.panel.append(kind, event.message)
            request_id, gate = event.data["request_id"], self.gate
            DiffWindow(self, event.data["change"], on_decision=lambda ok: self._resolve(gate, request_id, ok))
        elif kind == EventKind.PREVIEW:
            self.handle_preview_event(event.data)
        elif kind == EventKind.CONFIRM_PUSH:
            self.panel.append(kind, event.message)
            self.confirm_push(event.data["request_id"], event.message, event.data)
        elif kind == EventKind.AUTH_REQUIRED:
            self.panel.append(EventKind.ERROR, event.message)
            reason = "Your saved credentials were rejected. Sign in again, then re-run the workflow."
            if event.data.get("service") == "claude":
                self._ensure_claude(lambda: None, required=False, reason=reason)
            else:
                self._ensure_git(self.app_state.current, lambda: None, required=False, reason=reason)
        elif kind == EventKind.ARTIFACT:
            self.panel.append(kind, event.message)
            self.panel.show_report(event.data.get("markdown", ""), event.data.get("path"))
        elif kind == EventKind.STATE:
            self.panel.set_state(event.message)
            self.panel.append(kind, f"[{event.message}]")
        elif kind == EventKind.FINISHED:
            self.panel.set_running(False)
            self.sync_button.configure(state="normal")
            self._refresh_sync_status()
        elif kind == EventKind.ERROR and event.data.get("failed"):
            # A task that stopped must not look like "nothing happened": say so where it can't be missed.
            self.panel.append(kind, event.message)
            detail = event.message.split(": ", 1)[-1]
            messagebox.showerror("The task did not finish", detail[:1500] + "\n\nAnything it had not finished was "
                                 "undone. The full details are in the Live Log (Agent tasks).", parent=self)
        else:
            self.panel.append(kind, event.message)
        if kind != EventKind.LLM_TEXT and kind != EventKind.THOUGHT and event.message:
            logger.info("[%s] %s", kind.value, event.message)

    def _resolve(self, gate: ApprovalGate | None, request_id: int, approved: bool) -> None:
        if gate is not None:
            gate.resolve(request_id, approved)
        self.panel.append(EventKind.INFO, "Change approved." if approved else "Change rejected.")

    # ------------------------------------------------------------------ #
    # Shared to-do list
    # ------------------------------------------------------------------ #
    def panel_log(self, kind: EventKind, message: str) -> None:
        self.panel.append(kind, message)

    def _set_todo_busy(self, busy: bool) -> None:
        self._todo_busy = busy
        self.sync_button.configure(state="disabled" if busy or self._workflow_running() else "normal")

    def _todo_store(self) -> TodoStore:
        """Store for the selected paper (raises TodoError with a user-facing reason)."""
        spec = self.app_state.current
        if spec is None:
            raise TodoError("Add a paper first.")
        host, _ = self._paper_host(spec)
        credential = self._safe(lambda: self.store.get_git(host)) if host else None
        if host and credential is None:
            raise TodoError(f"Sign in to {host} (Accounts menu) to use the shared to-do list.")
        config = with_identity(self.config_, self.app_state.author_name, self.app_state.author_email)
        local = spec.local_path.strip() or str(self.config_.papers_dir / spec.name)
        git = GitManager(Path(local), spec.remote_url, spec.branch, config.git, credential=credential,
                         log=lambda m: self.bus.emit(EventKind.INFO, m))
        return TodoStore(git, config.git.author_name, push=self.push_var.get(),
                         log=lambda m: self.bus.emit(EventKind.WARNING, m))

    def _todo_error(self, exc: Exception) -> None:
        if isinstance(exc, GitAuthError):
            self.bus.emit(EventKind.AUTH_REQUIRED, str(exc), service="git", host=exc.host)
        else:
            self.panel.append(EventKind.ERROR, f"To-do list: {exc}")
            logger.error("To-do operation failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _save_state(self) -> None:
        self.app_state.push_after_commit = self.push_var.get()
        self.app_state.compile_before_commit = self.compile_var.get()
        self.app_state.web_search = self.web_var.get()
        self.app_state.appearance = self.appearance_var.get()
        self.app_state.preview = self.preview_var.get()
        self.app_state.confirm_push = self.confirm_var.get()
        try:
            self.app_state.save(self.config_.settings_file)
        except OSError as exc:
            self.panel.append(EventKind.WARNING, f"Could not save settings: {exc}")

    def _on_close(self) -> None:
        if not self._editor_may_close():
            return
        self._save_state()
        if self.cancel_token:
            self.cancel_token.cancel()
        self.destroy()


def run() -> None:
    """Application entry point."""
    config = AppConfig.from_env()
    logging.basicConfig(
        filename=config.workspace / "agent.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8",
    )
    ctk.set_default_color_theme("blue")
    ResearchAssistantApp(config).mainloop()

