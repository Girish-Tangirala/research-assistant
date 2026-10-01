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
from core.i18n import t, translated

MUTED = "#8b949e"
ERROR = "#f85149"
OK = "#3fb950"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def real_screen_size(widget: Any) -> tuple[int, int]:
    """The screen in real pixels, which Tk here does not always know.

    On a display at 125% this Tk reports 1536x864 for a 1920x1080 screen, so
    ``-fullscreen`` sizes the window to the smaller figure and leaves a quarter
    of the screen empty. Windows itself is asked instead, and the value is passed
    to ``geometry()`` unchanged: CustomTkinter's scaling and Tk's virtualisation
    cancel out, so what goes in is what appears on the screen.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if width > 0 and height > 0:
            return width, height
    except Exception:      # not Windows, or the call is unavailable
        pass
    return widget.winfo_screenwidth(), widget.winfo_screenheight()


def window_scaling(widget: Any) -> float:
    """What CustomTkinter multiplies the size given to ``geometry()`` by.

    On a display at 125% it is 1.25, so asking for 900 produces a 1125-pixel
    window - which is how a window ends up larger (or smaller) than intended.
    Tk measures in real pixels, so sizes must be divided by this before being
    handed to ``geometry()``.
    """
    try:
        from customtkinter.windows.widgets.scaling import ScalingTracker

        return float(ScalingTracker.get_window_scaling(widget)) or 1.0
    except Exception:      # older CustomTkinter, or no scaling support
        return 1.0


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
    """Base modal dialog with a status line and a button row.

    A dialog never assumes it fits on the screen. The buttons and the status line
    are packed against the bottom *before* the body, so ``pack`` gives them their
    space first and they can never be squeezed off; the body scrolls; and the
    window is clamped to the display it opens on. A colleague's smaller screen
    once pushed Save and Cancel off the bottom of *Add paper*, with the dialog
    fixed-size so there was no way to reach them.

    **The chrome translates here, once.** ``title``, ``heading``, ``text`` and the
    primary button are passed through :func:`core.i18n.t`, so a subclass hands in
    plain English and gets a German dialog. A subclass that needs a name or a
    version in the text translates it itself and passes the finished sentence;
    translating it again is a no-op, because an unknown string falls back to
    itself. ``tests/test_i18n.py`` reads these four arguments out of every
    subclass and fails if one has no German - they were English for two releases
    because nothing looked them up at either end.
    """

    MAX_WIDTH_FRACTION = 0.95
    MAX_HEIGHT_FRACTION = 0.85
    MIN_WIDTH = 520
    MIN_HEIGHT = 220

    def __init__(self, master: Any, title: str, heading: str, text: str) -> None:
        super().__init__(master)
        self.title(t(title))
        self.resizable(False, True)      # the height can be adjusted on a short screen
        self.transient(master)
        self.status = ctk.CTkLabel(self, text="", wraplength=460, justify="left")
        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons.pack(side="bottom", fill="x", padx=20, pady=(8, 16))
        self.status.pack(side="bottom", fill="x", padx=20)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(side="top", fill="both", expand=True, padx=14, pady=(16, 0))
        self.body.grid_columnconfigure(0, weight=1)
        self._row = 0
        self.label(t(heading), font=ctk.CTkFont(size=17, weight="bold"))
        if text:
            self.label(t(text), color=MUTED)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after(150, self._grab)

    # -- sizing -------------------------------------------------------- #
    def _content_height(self) -> int:
        """Height the body's contents want, measured rather than assumed."""
        total = 0
        for child in self.body.winfo_children():
            pady = child.grid_info().get("pady", 0)
            pad = sum(pady) if isinstance(pady, (tuple, list)) else int(pady or 0) * 2
            total += child.winfo_reqheight() + pad
        return total

    def _content_width(self) -> int:
        """Width the widest child wants, plus the scrollbar and the window padding.

        A scrollable body does not pass its contents' width up the way a plain
        frame does, so asking the window for its requested width would under-size
        it and clip the entries.
        """
        widest = max((child.winfo_reqwidth() for child in self.body.winfo_children()), default=0)
        return widest + 74      # 2 x 14 outer padding, the scrollbar and its margin

    def fit_to_screen(self) -> None:
        """Size to the content, but never past the screen, and centre on the parent."""
        self.update_idletasks()
        scaling = window_scaling(self)
        screen_h, screen_w = self.winfo_screenheight(), self.winfo_screenwidth()
        chrome = self.status.winfo_reqheight() + self.buttons.winfo_reqheight() + 56
        # The screen clamp is applied last, so a minimum can never push a dialog off it.
        want_w = max(self.MIN_WIDTH, self.winfo_reqwidth(), self._content_width())
        want_h = max(self.MIN_HEIGHT, self._content_height() + chrome)
        width = min(want_w, int(screen_w * self.MAX_WIDTH_FRACTION))
        height = min(want_h, int(screen_h * self.MAX_HEIGHT_FRACTION))
        master = self.master
        try:
            x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
            y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 3)
        except Exception:                      # no usable parent geometry yet
            x, y = (screen_w - width) // 2, (screen_h - height) // 3
        x = max(0, min(x, screen_w - width))   # never off the edge of the screen
        y = max(0, min(y, screen_h - height))
        # Sizes go back in unscaled units; x and y are passed through as pixels.
        self.geometry(f"{round(width / scaling)}x{round(height / scaling)}+{x}+{y}")
        self.minsize(round(min(self.MIN_WIDTH, width) / scaling),
                     round(min(self.MIN_HEIGHT, height) / scaling))

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
            toggle = ctk.CTkCheckBox(self.body, text=t("Show"), width=60,
                                     command=lambda: widget.configure(show="" if toggle.get() else "•"))
            toggle.grid(row=self._row, column=0, sticky="w", pady=(0, 10))
            self._row += 1
        return widget

    def finish_layout(self, primary: str, on_primary: Callable[[], None]) -> None:
        # Kept as an attribute, not found again by its label: a dialog that renames this
        # button used to search for the text "Cancel", which in German is "Abbrechen",
        # so Later and Discard silently stayed "Abbrechen".
        self.cancel_button = ctk.CTkButton(self.buttons, text=t("Cancel"), width=100,
                                           fg_color="transparent", border_width=1, command=self.cancel)
        self.cancel_button.pack(side="right", padx=(8, 0))
        self.primary = ctk.CTkButton(self.buttons, text=t(primary), width=140, command=on_primary)
        self.primary.pack(side="right")
        self.bind("<Return>", lambda _e: on_primary())
        self.fit_to_screen()

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
                         + t("Paste your Anthropic API key. It is stored in the system credential vault "
                             "and reused until you sign out or it stops working."))
        self.store, self.model, self.on_done = store, model, on_done
        self.link(t("Create or copy a key at console.anthropic.com →"),
                  "https://console.anthropic.com/settings/keys")
        self.key = self.entry(t("API key"), secret=True, placeholder="sk-ant-…")
        self.finish_layout("Sign in", self.submit)
        self.after(200, self.key.focus_set)

    def submit(self) -> None:
        key = self.key.get().strip()
        self.busy(t("Verifying key…"))
        run_in_background(self, lambda: verify_claude_key(key, self.model), lambda name: self._saved(key, name),
                          lambda exc: self.fail(translated(exc)))

    def _saved(self, key: str, model_name: str) -> None:
        try:
            self.store.set_claude_key(key)
        except CredentialError as exc:
            self.fail(translated(exc))
            return
        self.status.configure(text=t("Signed in - {model} is available.", model=model_name), text_color=OK)
        self.after(600, lambda: self.close(True))

    def close(self, ok: bool) -> None:
        super().close(ok)
        self.on_done(ok)


class GitLoginDialog(_Dialog):
    """Ask for, verify and store a Git host token plus the commit identity."""

    def __init__(self, master: Any, store: CredentialStore, host: str, verify_url: str,
                 author_name: str, author_email: str,
                 on_done: Callable[[bool, str, str], None], reason: str = "") -> None:
        super().__init__(master, "Sign in to Git", t("Sign in to {host}", host=host),
                         (reason + "\n\n" if reason else "")
                         + t("The token is stored in the system credential vault and sent only to this host."))
        self.store, self.host, self.verify_url, self.on_done = store, host, verify_url, on_done
        existing = store.get_git(host)
        self.label(t(GIT_TOKEN_HELP.get(host, "Create a personal access token with read/write access to "
                                              "repositories on this host.")), color=MUTED)
        self.username = self.entry(t("Username"), existing.username if existing else DEFAULT_GIT_USERNAMES.get(host, ""))
        self.token = self.entry(t("Access token"), secret=True)
        self.name = self.entry(t("Commit author name"), author_name)
        self.email = self.entry(t("Commit author email"), author_email)
        self.finish_layout("Sign in", self.submit)
        self.after(200, self.token.focus_set)
        self._result = ("", "")

    def submit(self) -> None:
        username, token = self.username.get().strip(), self.token.get().strip()
        name, email = self.name.get().strip(), self.email.get().strip()
        if not (username and token):
            self.fail(t("Username and token are required."))
            return
        if not name or not EMAIL_RE.match(email):
            self.fail(t("Enter the name and a valid email to use for commits."))
            return
        credential = GitCredential(self.host, username, token)
        can_verify = bool(self.verify_url) and host_of(self.verify_url) == self.host
        self.busy(t("Checking repository access…") if can_verify else t("Saving…"))

        def work() -> None:
            if can_verify:
                verify_git_access(self.verify_url, credential)

        run_in_background(self, work, lambda _v: self._saved(credential, name, email),
                          lambda exc: self.fail(translated(exc)))

    def _saved(self, credential: GitCredential, name: str, email: str) -> None:
        try:
            self.store.set_git(credential)
        except CredentialError as exc:
            self.fail(translated(exc))
            return
        self._result = (name, email)
        self.status.configure(text=t("Signed in."), text_color=OK)
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
        self.link(t("Get a free key at openalex.org/settings/api →"), "https://openalex.org/settings/api")
        self.key = self.entry(t("API key"), secret=True)
        self.finish_layout("Save", self.submit)

    def submit(self) -> None:
        key = self.key.get().strip()
        self.busy(t("Verifying key…"))
        run_in_background(self, lambda: verify_openalex_key(key), lambda _v: self._saved(key),
                          lambda exc: self.fail(translated(exc)))

    def _saved(self, key: str) -> None:
        try:
            self.store.set_openalex_key(key)
        except CredentialError as exc:
            self.fail(translated(exc))
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
        self.name = self.entry(t("Paper name"), spec.name if spec else "", placeholder=t("e.g. GNN folding paper"))
        self.url = self.entry(t("Overleaf or Git URL (optional)"), spec.remote_url if spec else "",
                              placeholder="https://www.overleaf.com/project/<id>  or  https://github.com/<you>/<repo>")
        self.label(t("Local folder"))
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.path = ctk.CTkEntry(row, placeholder_text=t("blank = {folder}\\<name>", folder=papers_dir))
        self.path.pack(side="left", fill="x", expand=True)
        if spec and spec.local_path:
            self.path.insert(0, spec.local_path)
        ctk.CTkButton(row, text="…", width=32, command=self._browse).pack(side="left", padx=(4, 0))
        self.branch = self.entry(t("Branch (optional)"), spec.branch if spec else "",
                                 placeholder=t("blank = the repository's default branch (Overleaf: main)"))

        self.create = ctk.CTkCheckBox(self.body, text=t("Set up the folder structure for a new paper"),
                                      command=self._toggle_create)
        if not editing:
            self.create.select()
            self.create.grid(row=self._row, column=0, sticky="w", pady=(2, 4))
            self._row += 1
        self.title_caption = self.label(t("Title of the paper (used in main.tex)"))
        self.title_entry = ctk.CTkEntry(self.body, width=460, placeholder_text=t("blank = the paper name"))
        self.title_entry.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        folders = ", ".join(f"{f.name}/" for f in FOLDERS)
        self.layout_note = self.label(
            t("Creates {folders} and a main.tex that compiles in Overleaf. Existing files are never "
              "overwritten; data/ stays on this computer. With a link, the Overleaf project is cloned "
              "first and the structure is only added if it has no .tex files yet.", folders=folders),
                                      color=MUTED)
        self._toggle_create()

        self.label(t("Read-only files (the agent may read but never edit them)"))
        ro_row = ctk.CTkFrame(self.body, fg_color="transparent")
        ro_row.grid(row=self._row, column=0, sticky="ew", pady=(0, 4))
        self._row += 1
        self.read_only = ctk.CTkEntry(ro_row, placeholder_text=t("e.g. zotero.bib, refs/*.bib"))
        self.read_only.pack(side="left", fill="x", expand=True)
        if spec and spec.read_only:
            self.read_only.insert(0, spec.read_only)
        ctk.CTkButton(ro_row, text=t("Detect"), width=70, command=self._detect).pack(side="left", padx=(4, 0))
        self.auto_protect = ctk.CTkCheckBox(
            self.body, text=t("Also auto-protect Zotero / Mendeley / ReadCube .bib files"))
        if spec is None or spec.auto_protect_bib:
            self.auto_protect.select()
        self.auto_protect.grid(row=self._row, column=0, sticky="w", pady=(0, 4))
        self._row += 1
        self.label(t("Overleaf overwrites reference-manager .bib files when you click Refresh, so edits to "
                   "them would be lost."), color=MUTED)
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
            self.status.configure(text=t("Folder not cloned yet - save, sync the paper, then use Detect again."),
                                  text_color=MUTED)
            return
        if not found:
            self.status.configure(text=t("No reference-manager .bib files detected. Add file names manually "
                                       "if Overleaf shows a .bib as linked to Zotero/Mendeley."), text_color=MUTED)
            return
        patterns = parse_patterns(self.read_only.get())
        patterns += [f for f in found if f not in patterns]
        self.read_only.delete(0, "end")
        self.read_only.insert(0, ", ".join(patterns))
        self.status.configure(text=t("Detected: {names}",
                                     names="; ".join(f"{k} ({v})" for k, v in found.items())),
                              text_color=OK)

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
                self.fail(t("{folder} already contains a paper (main.tex). Untick the structure box to "
                            "use it as it is.", folder=folder))
                return
            layout = {"title": self.title_entry.get().strip() or spec.name}
        super().close(True)
        self.on_save(spec, self.old_name, layout)
