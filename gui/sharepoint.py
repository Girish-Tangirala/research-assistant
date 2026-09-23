"""SharePoint backup: settings, sign-in and the 'Back up data' action.

Mixed into :class:`gui.app.ResearchAssistantApp`. The backup is one-way and only
ever runs when the user presses the button, like Sync with Overleaf.
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from core.app_state import SharePointSettings, validate_sharepoint
from core.credentials import CredentialError, CredentialStore
from core.events import EventKind
from core.onedrive import folder_problem
from core.sharepoint import (
    DeviceCode, GraphSession, SharePointAuthError, SharePointClient, SharePointError,
    poll_device_code, start_device_code,
)
from core.sharepoint_folder import LocalLibraryClient
from core.sharepoint_sync import (
    BackupResult, human_size, load_manifest, plan_backup, remote_base, run_backup,
)
from gui.dialogs import MUTED, OK, _Dialog, run_in_background
from gui.menubar import AccountSection

REGISTRATION_URL = "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"


FOLDER_MODE = "Folder synced by OneDrive"
GRAPH_MODE = "Microsoft Graph (needs an app registration)"


class SharePointSettingsDialog(_Dialog):
    """Where the backup goes, and which of the two routes reaches it."""

    def __init__(self, master: Any, settings: SharePointSettings,
                 on_save: Callable[[SharePointSettings], None]) -> None:
        super().__init__(master, "SharePoint backup", "Back up data to SharePoint",
                         "Copies the folders that never go to Overleaf (data/, supplementary/) into a "
                         "SharePoint library, keeping the same structure. Uploads only: nothing in "
                         "SharePoint is renamed or deleted.")
        self.on_save = on_save
        self.mode = ctk.CTkSegmentedButton(self.body, values=[FOLDER_MODE, GRAPH_MODE],
                                           command=lambda _v: self._toggle())
        self.mode.set(GRAPH_MODE if settings.uses_graph else FOLDER_MODE)
        self.mode.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1

        self._folder_block = self._block(lambda: self._build_folder(settings))
        self._graph_block = self._block(lambda: self._build_graph(settings))
        self.root_folder = self.entry("Folder in the library", settings.root_folder,
                                      placeholder="Research papers")
        self.folders = self.entry("Folders of each paper to back up", settings.folders,
                                  placeholder="data, supplementary")
        self.finish_layout("Save", self.submit)
        self._toggle()

    def _block(self, build: Callable[[], None]) -> list[Any]:
        """Run ``build`` and collect what it added, so the group can be shown or hidden together."""
        before = set(self.body.grid_slaves())
        build()
        return [w for w in self.body.grid_slaves() if w not in before]

    def _build_folder(self, settings: SharePointSettings) -> None:
        self.label("Sync the SharePoint library with the OneDrive app first (open the library in your "
                   "browser and press Sync), then choose the folder it created.", color=MUTED)
        self.label("Folder on this computer that OneDrive syncs with the library")
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.grid(row=self._row, column=0, sticky="ew", pady=(0, 10))
        self._row += 1
        self.local_library = ctk.CTkEntry(
            row, placeholder_text=r"C:\Users\you\Your University\Team Name - Documents")
        self.local_library.pack(side="left", fill="x", expand=True)
        if settings.local_library:
            self.local_library.insert(0, settings.local_library)
        ctk.CTkButton(row, text="…", width=32, command=self._browse).pack(side="left", padx=(4, 0))

    def _build_graph(self, settings: SharePointSettings) -> None:
        self.link("Register the app once in the Azure portal →", REGISTRATION_URL)
        self.label("Many universities only let their IT department open this portal. If it refuses you, "
                   "use the folder route instead.", color=MUTED)
        self.client_id = self.entry("Application (client) ID", settings.client_id,
                                    placeholder="00000000-0000-0000-0000-000000000000")
        self.tenant = self.entry("Directory (tenant) ID", settings.tenant,
                                 placeholder="organizations = any work account")
        self.site_url = self.entry("SharePoint site", settings.site_url,
                                   placeholder="https://yourcompany.sharepoint.com/sites/YourTeam")
        self.library = self.entry("Document library (optional)", settings.library,
                                  placeholder="blank = Documents")

    def _toggle(self) -> None:
        graph = self.mode.get() == GRAPH_MODE
        for widget in self._graph_block:
            widget.grid() if graph else widget.grid_remove()
        for widget in self._folder_block:
            widget.grid_remove() if graph else widget.grid()

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title="Choose the synced SharePoint library folder",
                                         initialdir=self.local_library.get() or str(Path.home()))
        if chosen:
            self.local_library.delete(0, "end")
            self.local_library.insert(0, chosen)

    def submit(self) -> None:
        settings = SharePointSettings(
            mode="graph" if self.mode.get() == GRAPH_MODE else "folder",
            local_library=self.local_library.get().strip(),
            client_id=self.client_id.get().strip(),
            tenant=self.tenant.get().strip() or "organizations",
            site_url=self.site_url.get().strip(),
            library=self.library.get().strip(),
            root_folder=self.root_folder.get().strip(),
            folders=self.folders.get().strip(),
        )
        problems = validate_sharepoint(settings)
        if problems:
            self.fail("\n".join(problems))
            return
        problem = None if settings.uses_graph else folder_problem(Path(settings.local_library))
        if problem and not messagebox.askyesno("Check the folder", f"{problem}\n\nUse it anyway?",
                                               parent=self):
            return
        super().close(True)
        self.on_save(settings)


class SharePointSignInDialog(_Dialog):
    """Device-code sign-in: the user types a short code in a browser."""

    def __init__(self, master: Any, store: CredentialStore, settings: SharePointSettings,
                 on_done: Callable[[str], None]) -> None:
        super().__init__(master, "Sign in to SharePoint", "Sign in to Microsoft 365",
                         "A browser page will ask for the code below. Only a sign-in token is stored, "
                         "in the system credential vault - never your password.")
        self.store, self.settings, self.on_done = store, settings, on_done
        self.cancelled = threading.Event()
        self.account = ""
        self.code_label = self.label("Asking Microsoft for a code…",
                                     font=ctk.CTkFont(size=26, weight="bold"))
        self.hint = self.label("", color=MUTED)
        self.finish_layout("Open the sign-in page", self._open_page)
        self.primary.configure(state="disabled")
        self._device: DeviceCode | None = None
        run_in_background(self, lambda: start_device_code(settings.client_id, settings.tenant),
                          self._show_code, lambda exc: self.fail(str(exc)))

    def _show_code(self, device: DeviceCode) -> None:
        self._device = device
        self.code_label.configure(text=device.user_code)
        self.hint.configure(text=f"Enter it at {device.verification_uri} and sign in with your work account.")
        self.primary.configure(state="normal")
        self.status.configure(text="Waiting for you to finish signing in…", text_color=MUTED)
        self._open_page()
        run_in_background(self, self._wait, self._signed_in, lambda exc: self.fail(str(exc)))

    def _open_page(self) -> None:
        if self._device is not None:
            webbrowser.open(self._device.verification_uri)

    def _wait(self) -> tuple[str, str]:
        """Poll until signed in, then check the site is reachable. Returns (token, account)."""
        assert self._device is not None
        token = poll_device_code(self.settings.client_id, self.settings.tenant, self._device,
                                 self.cancelled.is_set)
        client = SharePointClient(GraphSession(self.settings.client_id, self.settings.tenant, token))
        account = client.account()
        client.connect(self.settings.site_url, self.settings.library)
        return token, account

    def _signed_in(self, result: tuple[str, str]) -> None:
        token, account = result
        try:
            self.store.set_sharepoint_token(token)
        except CredentialError as exc:
            self.fail(str(exc))
            return
        self.account = account
        self.status.configure(text=f"Signed in as {account}.", text_color=OK)
        self.after(800, lambda: self.close(True))

    def cancel(self) -> None:
        self.cancelled.set()
        super().cancel()

    def close(self, ok: bool) -> None:
        self.cancelled.set()
        super().close(ok)
        self.on_done(self.account if ok else "")


class BackupProgressWindow(ctk.CTkToplevel):
    """Progress while files are copied or uploaded, with a working Cancel.

    The backup runs on a worker thread, which only writes plain values into ``self.state``;
    the window polls them, so no widget is ever touched off the GUI thread.
    """

    def __init__(self, master: Any, paper: str, files: int, total_bytes: int, handing_off: bool) -> None:
        super().__init__(master)
        self.title("Backing up to SharePoint")
        self.resizable(False, False)
        self.transient(master)
        self.cancelled = threading.Event()
        self.progress_state: dict[str, Any] = {"sent": 0, "total": max(total_bytes, 1), "file": "", "index": 0}
        self._files = files
        self._done = False

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(body, text=f"Backing up '{paper}'", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").pack(fill="x")
        self.counts = ctk.CTkLabel(body, text=f"{files} file(s), {human_size(total_bytes)}",
                                   text_color=MUTED, anchor="w")
        self.counts.pack(fill="x", pady=(2, 8))
        self.bar = ctk.CTkProgressBar(body, width=430, mode="determinate")
        self.bar.set(0)
        self.bar.pack(fill="x")
        self.current = ctk.CTkLabel(body, text="Starting…", text_color=MUTED, anchor="w", wraplength=430,
                                    justify="left", font=ctk.CTkFont(size=11))
        self.current.pack(fill="x", pady=(6, 0))
        if handing_off:
            ctk.CTkLabel(body, text="OneDrive uploads them to SharePoint afterwards; watch the tick marks "
                                    "in Explorer.", text_color=MUTED, anchor="w", wraplength=430,
                         justify="left", font=ctk.CTkFont(size=11)).pack(fill="x", pady=(6, 0))
        self.button = ctk.CTkButton(body, text="Cancel", width=110, fg_color="transparent", border_width=1,
                                    command=self._stop)
        self.button.pack(anchor="e", pady=(12, 0))
        self.protocol("WM_DELETE_WINDOW", self._stop)
        self.after(150, self._grab)
        self.after(100, self._poll)

    def _grab(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            self.after(150, self._grab)

    def _stop(self) -> None:
        if self._done:
            self.destroy()
            return
        self.cancelled.set()
        self.button.configure(state="disabled")
        self.current.configure(text="Stopping after the current file…")

    def _poll(self) -> None:
        if self._done:
            return
        sent, total = self.progress_state["sent"], self.progress_state["total"]
        self.bar.set(min(sent / total, 1.0))
        if self.progress_state["file"]:
            self.counts.configure(text=f"File {self.progress_state['index']} of {self._files} · "
                                       f"{human_size(sent)} of {human_size(total)}")
            self.current.configure(text=self.progress_state["file"])
        self.after(100, self._poll)

    def finish(self) -> None:
        self._done = True
        self.destroy()


class SharePointMixin:
    """The SharePoint entries of the Accounts menu and the backup action."""

    _sharepoint_busy = False

    # -- configuration and sign-in -------------------------------------- #
    def _sharepoint_settings(self) -> None:
        def saved(settings: SharePointSettings) -> None:
            changed_site = (settings.site_url, settings.client_id, settings.tenant) != (
                self.app_state.sharepoint.site_url, self.app_state.sharepoint.client_id,
                self.app_state.sharepoint.tenant)
            settings.account = "" if changed_site else self.app_state.sharepoint.account
            self.app_state.sharepoint = settings
            self._save_state()
            where = settings.site_url if settings.uses_graph else settings.local_library
            self.panel.append(EventKind.SUCCESS, f"SharePoint backup set up: {where} → "
                                                 f"{settings.root_folder}/<paper>/")
            if settings.uses_graph and (not self._safe(self.store.get_sharepoint_token) or changed_site):
                self._sharepoint_sign_in()

        SharePointSettingsDialog(self, self.app_state.sharepoint, saved)

    def _sharepoint_sign_in(self) -> None:
        settings = self.app_state.sharepoint
        if not settings.uses_graph:
            self.panel.append(EventKind.INFO, "No sign-in needed: OneDrive uploads the synced folder. "
                                              "Sign in to OneDrive itself if it is not syncing.")
            return
        if not settings.configured:
            self._sharepoint_settings()
            return

        def done(account: str) -> None:
            if account:
                self.app_state.sharepoint.account = account
                self._save_state()
                self.panel.append(EventKind.SUCCESS, f"Signed in to SharePoint as {account}.")

        SharePointSignInDialog(self, self.store, settings, done)

    def _sharepoint_sign_out(self) -> None:
        self._safe(self.store.clear_sharepoint_token)
        self.app_state.sharepoint.account = ""
        self._save_state()
        self.panel.append(EventKind.INFO, "Signed out of SharePoint. Files already uploaded stay there.")

    def _sharepoint_section(self) -> AccountSection:
        settings = self.app_state.sharepoint
        signed_in = bool(self._safe(self.store.get_sharepoint_token))
        if not settings.configured:
            status = "SharePoint backup: not set up (optional)"
        elif not settings.uses_graph:
            status = f"SharePoint: via OneDrive folder {Path(settings.local_library).name}"
        elif signed_in:
            status = f"SharePoint: signed in{f' as {settings.account}' if settings.account else ''}"
        else:
            status = "SharePoint: set up, not signed in"
        return AccountSection(status, [
            ("Change settings…" if settings.configured else "Set up…", self._sharepoint_settings, True),
            ("Sign in…", self._sharepoint_sign_in, settings.configured and settings.uses_graph),
            ("Sign out", self._sharepoint_sign_out, signed_in)])

    # -- the backup ------------------------------------------------------ #
    def _sharepoint_client(self) -> Any:
        """The Graph client or the synced-folder one - both answer index/ensure_folder/upload."""
        settings = self.app_state.sharepoint
        if not settings.uses_graph:
            client = LocalLibraryClient(Path(settings.local_library))
            client.check()
            return client
        token = self.store.get_sharepoint_token()
        if not token:
            raise SharePointAuthError("Not signed in to SharePoint.")
        session = GraphSession(settings.client_id, settings.tenant, token,
                               on_refresh=self.store.set_sharepoint_token)
        client = SharePointClient(session)
        client.connect(settings.site_url, settings.library)
        return client

    def _backup_to_sharepoint(self) -> None:
        """Look at what changed, show it, and upload once the user agrees."""
        spec = self.app_state.current
        root = self._paper_root()
        settings = self.app_state.sharepoint
        if spec is None or root is None:
            self.panel.append(EventKind.WARNING, "Add a paper first.")
            return
        if self._sharepoint_busy:
            self.panel.append(EventKind.WARNING, "A SharePoint backup is already running.")
            return
        if not settings.configured:
            self.panel.append(EventKind.INFO, "Set up the SharePoint backup first (Accounts menu).")
            self._sharepoint_settings()
            return
        if settings.uses_graph and not self._safe(self.store.get_sharepoint_token):
            self._sharepoint_sign_in()
            return
        base = remote_base(settings.root_folder, spec.name)
        self._sharepoint_busy = True
        self.panel.append(EventKind.INFO, f"Checking what has changed in {', '.join(settings.folder_list)}…")

        def work() -> tuple[SharePointClient, Any]:
            client = self._sharepoint_client()
            remote = client.index(base)
            plan = plan_backup(root, settings.folder_list, base,
                               remote, load_manifest(self.config_.workspace, spec.name))
            return client, plan

        run_in_background(self, work, lambda result: self._confirm_backup(*result, base, spec.name),
                          self._sharepoint_failed)

    def _confirm_backup(self, client: Any, plan: Any, base: str, paper: str) -> None:
        settings = self.app_state.sharepoint
        for skipped in plan.skipped:
            self.panel.append(EventKind.WARNING, f"Not uploaded - {skipped.relative}: {skipped.reason}")
        if plan.empty:
            self._sharepoint_busy = False
            self.panel.append(EventKind.SUCCESS, f"SharePoint is already up to date "
                                                 f"({plan.unchanged} file(s) in {base}).")
            return
        new = sum(1 for u in plan.uploads if u.new)
        where = settings.site_url if settings.uses_graph else settings.local_library
        warning = None if settings.uses_graph else folder_problem(Path(settings.local_library))
        handover = ("" if settings.uses_graph else
                    "\n\nOneDrive uploads them to SharePoint from there; its icons show the progress.")
        if warning:
            handover = f"\n\n⚠ {warning}"
            self.panel.append(EventKind.WARNING, warning)
        detail = (f"{len(plan.uploads)} file(s), {human_size(plan.total_bytes)}\n"
                  f"{new} new · {len(plan.uploads) - new} changed · {plan.unchanged} already there\n\n"
                  f"To: {where}\n     {base}/")
        if not messagebox.askyesno("Back up to SharePoint",
                                   f"Copy the {', '.join(settings.folder_list)} folder(s) of "
                                   f"'{paper}'?\n\n{detail}\n\nNothing in SharePoint is deleted or "
                                   f"renamed.{handover}", parent=self):
            self._sharepoint_busy = False
            self.panel.append(EventKind.INFO, "SharePoint backup cancelled - nothing was uploaded.")
            return
        self._run_backup(client, plan, base, paper)

    def _run_backup(self, client: Any, plan: Any, base: str, paper: str) -> None:
        self.panel.append(EventKind.STATE, f"▶ Backing up {paper} to SharePoint")
        window = BackupProgressWindow(self, paper, len(plan.uploads), plan.total_bytes,
                                      handing_off=not self.app_state.sharepoint.uses_graph)

        def on_file(upload: Any, index: int, total: int) -> None:
            window.progress_state["file"], window.progress_state["index"] = upload.relative, index
            self.bus.emit(EventKind.INFO, f"[{index}/{total}] {upload.relative} ({human_size(upload.size)})")

        def on_bytes(sent: int, total: int) -> None:
            window.progress_state["sent"], window.progress_state["total"] = sent, max(total, 1)

        def work() -> BackupResult:
            return run_backup(client, plan, base, self.config_.workspace, paper,
                              on_file=on_file, on_bytes=on_bytes, cancelled=window.cancelled.is_set)

        def done(result: BackupResult) -> None:
            window.finish()
            self._backup_done(result, base, client.web_url)

        def failed(exc: Exception) -> None:
            window.finish()
            self._sharepoint_failed(exc)

        run_in_background(self, work, done, failed)

    def _backup_done(self, result: BackupResult, base: str, web_url: str) -> None:
        self._sharepoint_busy = False
        if result.cancelled:
            self.panel.append(EventKind.WARNING, f"Backup stopped. {result.uploaded} file(s) were already "
                                                 "sent and are not sent again next time.")
        for failure in result.failed:
            self.panel.append(EventKind.ERROR, f"Failed - {failure.relative}: {failure.reason}")
        summary = (f"Uploaded {result.uploaded} file(s), {human_size(result.bytes_sent)} to {base}/ · "
                   f"{result.unchanged} already up to date")
        if result.failed:
            summary += f" · {len(result.failed)} failed"
        self.panel.append(EventKind.ERROR if result.failed else EventKind.SUCCESS, summary)
        if result.uploaded and web_url:
            self.panel.append(EventKind.INFO, f"In SharePoint: {web_url}" if self.app_state.sharepoint.uses_graph
                              else f"Copied into {web_url} - OneDrive uploads them from there.")

    def _sharepoint_failed(self, exc: Exception) -> None:
        self._sharepoint_busy = False
        if isinstance(exc, SharePointAuthError):
            self.panel.append(EventKind.ERROR, str(exc))
            self._sharepoint_sign_in()
        elif isinstance(exc, SharePointError):
            self.panel.append(EventKind.ERROR, f"SharePoint: {exc}")
        else:
            self.panel.append(EventKind.ERROR, f"SharePoint backup failed: {type(exc).__name__}: {exc}")
