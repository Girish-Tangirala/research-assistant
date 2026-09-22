"""Modal dialogs: Claude / Git / OpenAlex sign-in and paper add/edit.

Network verification runs on a background thread; results are marshalled back
to the Tk thread with ``after`` polling so widgets are never touched off-thread.
"""

from __future__ import annotations

import re
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from core.app_state import PaperSpec, default_local_path, normalize_remote_url, validate_paper
from core.project_layout import FOLDERS, looks_scaffolded
from core.protection import detect_reference_manager_bibs, parse_patterns
from core.credentials import (
    DEFAULT_GIT_USERNAMES, GIT_TOKEN_HELP, CredentialError, CredentialStore, GitCredential,
    host_of, verify_claude_key, verify_git_access, verify_openalex_key,
)

MUTED = "#8b949e"
ERROR = "#f85149"
OK = "#3fb950"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def run_in_background(widget: Any, fn: Callable[[], Any], on_success: Callable[[Any], None],
                      on_error: Callable[[Exception], None]) -> None:
    """Run ``fn`` off the UI thread and deliver the outcome on the UI thread."""
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - delivered to the UI
            outcome["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    def poll() -> None:
        if thread.is_alive():
            widget.after(100, poll)
        elif "error" in outcome:
            on_error(outcome["error"])
        else:
            on_success(outcome.get("value"))

    widget.after(100, poll)


class _Dialog(ctk.CTkToplevel):
    """Base modal dialog with a status line and a button row."""

    def __init__(self, master: Any, title: str, heading: str, text: str) -> None:
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=16)
        self.body.grid_columnconfigure(0, weight=1)
        self._row = 0
        self.label(heading, font=ctk.CTkFont(size=17, weight="bold"))
        if text:
            self.label(text, color=MUTED)
        self.status = ctk.CTkLabel(self, text="", wraplength=460, justify="left")
        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after(150, self._grab)

    def _grab(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:  # window not viewable yet
            self.after(150, self._grab)

    def label(self, text: str, color: str | None = None, **kwargs: Any) -> ctk.CTkLabel:
        widget = ctk.CTkLabel(self.body, text=text, wraplength=460, justify="left", anchor="w",
                              text_color=color, **kwargs)
        widget.grid(row=self._row, column=0, sticky="ew", pady=(0, 6))
        self._row += 1
        return widget

    def link(self, text: str, url: str) -> None:
        widget = self.label(text, color="#58a6ff", cursor="hand2")
        widget.bind("<Button-1>", lambda _e: webbrowser.open(url))

    def entry(self, caption: str, value: str = "", secret: bool = False, placeholder: str = "") -> ctk.CTkEntry:
        self.label(caption)
        widget = ctk.CTkEntry(self.body, width=460, placeholder_text=placeholder, show="•" if secret else "")
        if value:
            widget.insert(0, value)
        widget.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        if secret:
            toggle = ctk.CTkCheckBox(self.body, text="Show", width=60,
                                     command=lambda: widget.configure(show="" if toggle.get() else "•"))
            toggle.grid(row=self._row, column=0, sticky="w", pady=(0, 10))
            self._row += 1
        return widget

    def finish_layout(self, primary: str, on_primary: Callable[[], None]) -> None:
        self.status.pack(fill="x", padx=20)
        self.buttons.pack(fill="x", padx=20, pady=(8, 16))
        ctk.CTkButton(self.buttons, text="Cancel", width=100, fg_color="transparent", border_width=1,
                      command=self.cancel).pack(side="right", padx=(8, 0))
        self.primary = ctk.CTkButton(self.buttons, text=primary, width=140, command=on_primary)
        self.primary.pack(side="right")
        self.bind("<Return>", lambda _e: on_primary())

    def busy(self, message: str) -> None:
        self.primary.configure(state="disabled")
        self.status.configure(text=message, text_color=MUTED)

    def fail(self, message: str) -> None:
        self.primary.configure(state="normal")
        self.status.configure(text=message, text_color=ERROR)

    def cancel(self) -> None:
        self.close(False)

    def close(self, ok: bool) -> None:  # overridden to notify callers
        try:
            self.grab_release()
        finally:
            self.destroy()


class ClaudeLoginDialog(_Dialog):
    """Ask for, verify and store the Anthropic API key."""

    def __init__(self, master: Any, store: CredentialStore, model: str,
                 on_done: Callable[[bool], None], reason: str = "") -> None:
        super().__init__(master, "Sign in to Claude", "Sign in to Claude",
                         (reason + "\n\n" if reason else "")
                         + "Paste your Anthropic API key. It is stored in the system credential vault "
                           "and reused until you sign out or it stops working.")
        self.store, self.model, self.on_done = store, model, on_done
        self.link("Create or copy a key at console.anthropic.com →", "https://console.anthropic.com/settings/keys")
        self.key = self.entry("API key", secret=True, placeholder="sk-ant-…")
        self.finish_layout("Sign in", self.submit)
        self.after(200, self.key.focus_set)

    def submit(self) -> None:
        key = self.key.get().strip()
        self.busy("Verifying key…")
        run_in_background(self, lambda: verify_claude_key(key, self.model), lambda name: self._saved(key, name),
                          lambda exc: self.fail(str(exc)))

    def _saved(self, key: str, model_name: str) -> None:
        try:
            self.store.set_claude_key(key)
        except CredentialError as exc:
            self.fail(str(exc))
            return
        self.status.configure(text=f"Signed in - {model_name} is available.", text_color=OK)
        self.after(600, lambda: self.close(True))

    def close(self, ok: bool) -> None:
        super().close(ok)
        self.on_done(ok)


class GitLoginDialog(_Dialog):
    """Ask for, verify and store a Git host token plus the commit identity."""

    def __init__(self, master: Any, store: CredentialStore, host: str, verify_url: str,
                 author_name: str, author_email: str,
                 on_done: Callable[[bool, str, str], None], reason: str = "") -> None:
        super().__init__(master, "Sign in to Git", f"Sign in to {host}",
                         (reason + "\n\n" if reason else "")
                         + "The token is stored in the system credential vault and sent only to this host.")
        self.store, self.host, self.verify_url, self.on_done = store, host, verify_url, on_done
        existing = store.get_git(host)
        self.label(GIT_TOKEN_HELP.get(host, "Create a personal access token with read/write access to "
                                            "repositories on this host."), color=MUTED)
        self.username = self.entry("Username", existing.username if existing else DEFAULT_GIT_USERNAMES.get(host, ""))
        self.token = self.entry("Access token", secret=True)
        self.name = self.entry("Commit author name", author_name)
        self.email = self.entry("Commit author email", author_email)
        self.finish_layout("Sign in", self.submit)
        self.after(200, self.token.focus_set)
        self._result = ("", "")

    def submit(self) -> None:
        username, token = self.username.get().strip(), self.token.get().strip()
        name, email = self.name.get().strip(), self.email.get().strip()
        if not (username and token):
            self.fail("Username and token are required.")
            return
        if not name or not EMAIL_RE.match(email):
            self.fail("Enter the name and a valid email to use for commits.")
            return
        credential = GitCredential(self.host, username, token)
        can_verify = bool(self.verify_url) and host_of(self.verify_url) == self.host
        self.busy("Checking repository access…" if can_verify else "Saving…")

        def work() -> None:
            if can_verify:
                verify_git_access(self.verify_url, credential)

        run_in_background(self, work, lambda _v: self._saved(credential, name, email),
                          lambda exc: self.fail(str(exc)))

    def _saved(self, credential: GitCredential, name: str, email: str) -> None:
        try:
            self.store.set_git(credential)
        except CredentialError as exc:
            self.fail(str(exc))
            return
        self._result = (name, email)
        self.status.configure(text="Signed in.", text_color=OK)
        self.after(500, lambda: self.close(True))

    def close(self, ok: bool) -> None:
        super().close(ok)
        self.on_done(ok, *self._result)


class OpenAlexKeyDialog(_Dialog):
    """Optional OpenAlex API key (raises the free daily search budget 10×)."""

    def __init__(self, master: Any, store: CredentialStore, on_done: Callable[[bool], None]) -> None:
        super().__init__(master, "OpenAlex API key", "OpenAlex API key (optional)",
                         "Literature search works without a key, but a free key raises the daily "
                         "OpenAlex budget 10×.")
        self.store, self.on_done = store, on_done
        self.link("Get a free key at openalex.org/settings/api →", "https://openalex.org/settings/api")
        self.key = self.entry("API key", secret=True)
        self.finish_layout("Save", self.submit)

    def submit(self) -> None:
        key = self.key.get().strip()
        self.busy("Verifying key…")
        run_in_background(self, lambda: verify_openalex_key(key), lambda _v: self._saved(key),
                          lambda exc: self.fail(str(exc)))

    def _saved(self, key: str) -> None:
        try:
            self.store.set_openalex_key(key)
        except CredentialError as exc:
            self.fail(str(exc))
            return
        self.close(True)

    def close(self, ok: bool) -> None:
        super().close(ok)
        self.on_done(ok)


class PaperDialog(_Dialog):
    """Add or edit a paper (Git repository)."""

    def __init__(self, master: Any, spec: PaperSpec | None, other_names: set[str], papers_dir: Path,
                 on_save: Callable[[PaperSpec, str | None, dict | None], None]) -> None:
        editing = spec is not None
        super().__init__(master, "Edit paper" if editing else "Add paper",
                         "Edit paper" if editing else "Add a paper",
                         "The paper lives in a folder on this computer. An Overleaf (or GitHub) link is "
                         "optional - you can add it later and send your work with the Sync button.")
        self.old_name = spec.name if spec else None
        self.editing = editing
        self.other_names, self.papers_dir, self.on_save = other_names, papers_dir, on_save
        self.name = self.entry("Paper name", spec.name if spec else "", placeholder="e.g. GNN folding paper")
        self.url = self.entry("Overleaf or Git URL (optional)", spec.remote_url if spec else "",
                              placeholder="https://www.overleaf.com/project/<id>  or  https://github.com/<you>/<repo>")
        self.label("Local folder")
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.path = ctk.CTkEntry(row, placeholder_text=f"blank = {papers_dir}\\<name>")
        self.path.pack(side="left", fill="x", expand=True)
        if spec and spec.local_path:
            self.path.insert(0, spec.local_path)
        ctk.CTkButton(row, text="…", width=32, command=self._browse).pack(side="left", padx=(4, 0))
        self.branch = self.entry("Branch (optional)", spec.branch if spec else "",
                                 placeholder="blank = the repository's default branch (Overleaf: main)")

        self.create = ctk.CTkCheckBox(self.body, text="Set up the folder structure for a new paper",
                                      command=self._toggle_create)
        if not editing:
            self.create.select()
            self.create.grid(row=self._row, column=0, sticky="w", pady=(2, 4))
            self._row += 1
        self.title_caption = self.label("Title of the paper (used in main.tex)")
        self.title_entry = ctk.CTkEntry(self.body, width=460, placeholder_text="blank = the paper name")
        self.title_entry.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        folders = ", ".join(f"{f.name}/" for f in FOLDERS)
        self.layout_note = self.label(f"Creates {folders} and a main.tex that compiles in Overleaf. "
                                      "Existing files are never overwritten; data/ stays on this computer. "
                                      "With a link, the Overleaf project is cloned first and the structure is "
                                      "only added if it has no .tex files yet.",
                                      color=MUTED)
        self._toggle_create()

        self.label("Read-only files (the agent may read but never edit them)")
        ro_row = ctk.CTkFrame(self.body, fg_color="transparent")
        ro_row.grid(row=self._row, column=0, sticky="ew", pady=(0, 4))
        self._row += 1
        self.read_only = ctk.CTkEntry(ro_row, placeholder_text="e.g. zotero.bib, refs/*.bib")
        self.read_only.pack(side="left", fill="x", expand=True)
        if spec and spec.read_only:
            self.read_only.insert(0, spec.read_only)
        ctk.CTkButton(ro_row, text="Detect", width=70, command=self._detect).pack(side="left", padx=(4, 0))
        self.auto_protect = ctk.CTkCheckBox(
            self.body, text="Also auto-protect Zotero / Mendeley / ReadCube .bib files")
        if spec is None or spec.auto_protect_bib:
            self.auto_protect.select()
        self.auto_protect.grid(row=self._row, column=0, sticky="w", pady=(0, 4))
        self._row += 1
        self.label("Overleaf overwrites reference-manager .bib files when you click Refresh, so edits to "
                   "them would be lost.", color=MUTED)
        self.finish_layout("Save", self.submit)

    def _toggle_create(self) -> None:
        """Show the title field only when a new paper folder will be created."""
        creating = bool(self.create.get()) and not self.editing
        for widget in (self.title_caption, self.title_entry, self.layout_note):
            widget.grid() if creating else widget.grid_remove()

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self, initialdir=self.path.get() or str(Path.home()))
        if chosen:
            self.path.delete(0, "end")
            self.path.insert(0, chosen)

    def _detect(self) -> None:
        folder = Path(self.path.get().strip() or default_local_path(self.papers_dir, self.name.get() or "paper"))
        found = detect_reference_manager_bibs(folder.expanduser())
        if not folder.expanduser().is_dir():
            self.status.configure(text="Folder not cloned yet - save, sync the paper, then use Detect again.",
                                  text_color=MUTED)
            return
        if not found:
            self.status.configure(text="No reference-manager .bib files detected. Add file names manually "
                                       "if Overleaf shows a .bib as linked to Zotero/Mendeley.", text_color=MUTED)
            return
        patterns = parse_patterns(self.read_only.get())
        patterns += [f for f in found if f not in patterns]
        self.read_only.delete(0, "end")
        self.read_only.insert(0, ", ".join(patterns))
        self.status.configure(text="Detected: " + "; ".join(f"{k} ({v})" for k, v in found.items()), text_color=OK)

    def submit(self) -> None:
        name = self.name.get().strip()
        # A paper always has a folder; blank means "inside the app's workspace".
        path = self.path.get().strip() or (default_local_path(self.papers_dir, name) if name else "")
        spec = PaperSpec(name, normalize_remote_url(self.url.get()), path, self.branch.get().strip(),
                         read_only=", ".join(parse_patterns(self.read_only.get())),
                         auto_protect_bib=bool(self.auto_protect.get()))
        problems = validate_paper(spec, self.other_names)
        if problems:
            self.fail("\n".join(problems))
            return
        layout = None
        if bool(self.create.get()) and not self.editing:
            folder = Path(spec.local_path).expanduser()
            if looks_scaffolded(folder):
                self.fail(f"{folder} already contains a paper (main.tex). Untick the structure box to use it "
                          "as it is.")
                return
            layout = {"title": self.title_entry.get().strip() or spec.name}
        super().close(True)
        self.on_save(spec, self.old_name, layout)
