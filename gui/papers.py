"""The paper list: choosing, adding, editing and setting up a paper folder.

Split out of :mod:`gui.app`; mixed into the main window. A paper is a folder on
this computer with its own Git repository. New papers get the standard folder
structure (see :mod:`core.project_layout`) and an Overleaf link is optional -
commits stay local until the Sync button is pressed.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

from core.agent_engine import with_identity
from core.app_state import PaperSpec
from core.credentials import host_of, is_https
from core.events import EventKind
from core.git_manager import GitManager, GitOperationError
from core.latex_parser import find_main_tex, list_section_titles
from core.project_layout import FOLDERS, ensure_local_folders, present_folders, scaffold
from core.reorganize import unsorted_files
from core.workflows import OrganizeWorkflow, PublishWorkflow
from core.protection import ProtectionPolicy
from gui.dialogs import PaperDialog, run_in_background
from gui.panels import open_path
from core.i18n import t

NO_PAPER = "— add a paper —"


class PapersMixin:
    """Paper dropdown, add/edit/remove dialogs, folder setup and sync status."""

    def _paper_host(self, spec: PaperSpec | None) -> tuple[str, str]:
        """Return ``(host, url)`` for the paper, reading an existing clone's origin if needed."""
        if spec is None:
            return "", ""
        url = spec.remote_url
        if not url and spec.local_path:
            try:
                url = GitManager(spec.local_path).effective_url
            except GitOperationError:
                url = ""
        return (host_of(url), url) if is_https(url) else ("", url)

    def _refresh_papers(self) -> None:
        names = self.app_state.names
        current = self.app_state.current
        self.paper_menu.configure(values=names or [NO_PAPER])
        self.paper_menu.set(current.name if current else NO_PAPER)
        if current:
            self.app_state.selected = current.name
            root = Path(current.local_path).expanduser()
            for name in ensure_local_folders(root):  # data/ and supplementary/ are created for every paper
                self.panel.append(EventKind.INFO,
                                  t("Created {folder} - it stays on this computer and is never sent to "
                                    "Overleaf.", folder=root / name))
            where = current.remote_url or t("on this computer only")
            policy = ProtectionPolicy.build(root, current.read_only, current.auto_protect_bib)
            locked = policy.protected_files()
            folders = present_folders(root)
            lines = [where, str(root)]
            if folders:
                lines.append(t("Folders: {names}", names=", ".join(f"{name}/" for name in folders)))
            if locked:
                lines.append(t("Read-only: {files}", files=", ".join(locked)))
            unsorted = self._unsorted_files(root)
            if unsorted:
                lines.append(t("{count} file(s) not in folders yet - File ▸ Organise paper into folders…",
                               count=len(unsorted)))
            self.paper_info.configure(text="\n".join(lines))
        else:
            self.paper_info.configure(text=t("Create a new paper folder, or add the Overleaf/GitHub repository "
                                           "of one you already have."))
        self._refresh_sync_status()
        self.panel.set_sections([])
        self.todo.paper_changed()
        self.preview_paper_changed()
        self.editor_paper_changed()

    def _select_paper(self, name: str) -> None:
        if name == NO_PAPER:
            return
        self.app_state.selected = name
        self._save_state()
        self._refresh_papers()
        self._ensure_git(self.app_state.current, then=lambda: None, required=False)

    def _add_paper(self) -> None:
        self._open_paper_dialog(None)

    def _edit_paper(self) -> None:
        if self.app_state.current:
            self._open_paper_dialog(self.app_state.current)

    def _open_paper_dialog(self, spec: PaperSpec | None) -> None:
        others = set(self.app_state.names) - ({spec.name} if spec else set())

        def saved(new: PaperSpec, old_name: str | None, layout: dict | None) -> None:
            self.app_state.upsert(new, old_name)
            self._save_state()
            self._refresh_papers()
            self.panel.append(EventKind.SUCCESS, t("Paper '{name}' saved.", name=new.name))
            if old_name is None and new.remote_url:
                # Clone first, so the local folder shares Overleaf's history and Sync can merge.
                title = layout["title"] if layout is not None else None
                self._ensure_git(new, then=lambda: self._clone_new_paper(new, title), required=False)
                return
            if layout is not None:
                self._create_paper_folder(new, layout["title"])
            if new.remote_url:
                self._ensure_git(new, then=lambda: None, required=False)

        PaperDialog(self, spec, others, self.config_.papers_dir, saved)

    def _remove_paper(self) -> None:
        spec = self.app_state.current
        if spec and messagebox.askyesno(
                t("Remove paper"),
                t("Remove '{name}' from the list?\n\nFiles on disk are not deleted.", name=spec.name),
                parent=self):
            self.app_state.remove(spec.name)
            self._save_state()
            self._refresh_papers()

    def _open_paper_folder(self) -> None:
        root = self._paper_root()
        if root is None:
            self.panel.append(EventKind.WARNING, t("Add a paper first."))
        elif root.is_dir():
            open_path(root)
        else:
            self.panel.append(EventKind.WARNING, t("{folder} does not exist yet - refresh or sync the paper first.", folder=root))

    def _sync_with_overleaf(self) -> None:
        """The Sync button: offer to add a link first if the paper is local only."""
        spec = self.app_state.current
        if spec is None:
            self.panel.append(EventKind.WARNING, t("Add a paper first."))
            return
        if spec.local_only:
            self.panel.append(EventKind.INFO,
                              t("'{name}' is only on this computer - nothing is sent anywhere until you "
                                "link it to an Overleaf project.", name=spec.name))
            if messagebox.askyesno(t("No Overleaf link yet"),
                                   t("'{name}' is saved on this computer only.\n\nAdd its Overleaf "
                                     "project link now? You can also keep working locally and link it "
                                     "later.", name=spec.name), parent=self):
                self._edit_paper()
            return
        self._start(PublishWorkflow, {})

    def _organise_paper(self) -> None:
        """Offer to move an existing paper's files into the standard folders."""
        spec = self.app_state.current
        root = self._paper_root()
        if spec is None or root is None or not root.is_dir():
            self.panel.append(EventKind.WARNING, t("Add and sync a paper first."))
            return
        folders = ", ".join(f"{f.name}/" for f in FOLDERS)
        where = "Overleaf" if not spec.local_only else "this computer"
        if messagebox.askyesno(
                t("Organise into folders"),
                t("Sort the files of '{name}' into {folders}?\n\nThe app shows you every move and "
                  "every changed \\input / \\includegraphics path, and compiles the result, before "
                  "anything is written. Nothing moves until you approve.\n\nIt becomes one commit on "
                  "{where}.", name=spec.name, folders=folders, where=where), parent=self):
            self._start(OrganizeWorkflow, {})

    def _sync_label(self, spec: PaperSpec | None) -> str:
        host = host_of(spec.remote_url) if spec else ""
        where = "Overleaf" if (not host or "overleaf" in host) else host
        return t("⇄  Sync with {where}", where=where)

    def _refresh_sync_status(self) -> None:
        """Show how many commits are waiting to go to Overleaf (counted in the background)."""
        spec = self.app_state.current
        self.publish_button.configure(state="normal" if spec else "disabled", text=self._sync_label(spec))
        self.backup_button.configure(state="normal" if spec else "disabled")
        if spec is None:
            self.sync_status.configure(text="")
            return
        root = Path(spec.local_path).expanduser()
        if not (root / ".git").exists():
            self.sync_status.configure(text=t("Not set up yet - press Refresh to clone or create the folder."))
            return
        self.sync_status.configure(text=t("Checking…"))

        def count() -> tuple[bool, int, int]:
            git = GitManager(root, spec.remote_url, spec.branch, self.config_.git)
            ahead, behind = git.counts()
            return git.has_remote, ahead, behind

        def show(result: tuple[bool, int, int]) -> None:
            linked, ahead, behind = result
            if not linked:
                text = (t("Only on this computer")
                        + (t(" · {n} change(s) saved", n=ahead) if ahead else "")
                        + t(" · add an Overleaf link with Edit paper to share it"))
            elif ahead or behind:
                parts = ([t("{n} change(s) to send", n=ahead)] if ahead else []) + \
                        ([t("{n} waiting from Overleaf", n=behind)] if behind else [])
                text = " · ".join(parts) + t(" (as of the last sync)")
            else:
                text = t("In sync with Overleaf as of the last sync")
            self.sync_status.configure(text=text)

        run_in_background(self, count, show, lambda exc: self.sync_status.configure(text=""))

    def _create_paper_folder(self, spec: PaperSpec, title: str) -> None:
        """Create the folder structure and a local repository for a brand-new paper."""
        root = Path(spec.local_path).expanduser()
        config = with_identity(self.config_, self.app_state.author_name, self.app_state.author_email)
        self.panel.append(EventKind.INFO, t("Setting up {folder}…", folder=root))

        def work() -> list[str]:
            created = scaffold(root, title, config.git.author_name)
            git = GitManager(root, spec.remote_url, spec.branch, config.git, log=lambda m: None)
            git.init_repo()
            if spec.remote_url:
                git.set_remote(spec.remote_url)
            if created:
                git.commit_all("Start the paper (folders created by Research Assistant Agent)")
            return created

        def done(created: list[str]) -> None:
            self.panel.append(EventKind.SUCCESS, f"Created {len(created)} file(s) in {root}: "
                                                 + ", ".join(created[:8]) + (" …" if len(created) > 8 else ""))
            self._refresh_papers()
            self.recompile_preview(quiet=True)

        run_in_background(self, work, done, lambda exc: self.panel.append(
            EventKind.ERROR, t("Could not set up the paper folder: {problem}", problem=exc)))

    def _clone_new_paper(self, spec: PaperSpec, title: str | None) -> None:
        """Clone a newly added linked paper; add the folder structure only if the project has no .tex yet."""
        root = Path(spec.local_path).expanduser()
        host, _ = self._paper_host(spec)
        credential = self._safe(lambda: self.store.get_git(host)) if host else None
        config = with_identity(self.config_, self.app_state.author_name, self.app_state.author_email)
        self.panel.append(EventKind.INFO, t("Cloning {url} into {folder}…", url=spec.remote_url, folder=root))

        def work() -> tuple[list[str], bool]:
            git = GitManager(root, spec.remote_url, spec.branch, config.git, credential=credential,
                             log=lambda m: self.bus.emit(EventKind.INFO, m))
            git.ensure_repo()
            has_tex = any(".git" not in p.parts for p in root.rglob("*.tex"))
            if title is None or has_tex:
                return [], has_tex
            created = scaffold(root, title, config.git.author_name)
            if created:
                git.commit_all("Start the paper (folders created by Research Assistant Agent)")
            return created, has_tex

        def done(result: tuple[list[str], bool]) -> None:
            created, has_tex = result
            self.panel.append(EventKind.SUCCESS, t("Cloned '{name}' into {folder}.", name=spec.name, folder=root))
            if created:
                self.panel.append(EventKind.SUCCESS,
                                  t("The Overleaf project was empty, so the folder structure was added "
                                    "({count} file(s)). Press Sync to send it.", count=len(created)))
            elif title is not None and has_tex:
                self.panel.append(EventKind.INFO, t("The Overleaf project already has a paper, so its files were "
                                                  "left as they are."))
            if self._unsorted_files(root):
                self.panel.append(EventKind.INFO, t("To sort its files into folders, use "
                                                  "File ▸ Organise paper into folders…"))
            self._refresh_papers()
            self.recompile_preview(quiet=True)

        run_in_background(self, work, done, lambda exc: self.panel.append(
            EventKind.ERROR, t("Could not clone the paper: {problem}", problem=exc)))

    @staticmethod
    def _unsorted_files(root: Path) -> list[str]:
        """Top-level files that File ▸ Organise paper into folders would still move."""
        main = find_main_tex(root) if root.is_dir() else None
        return unsorted_files(root, main.name if main is not None and main.parent == root else "")

    def _load_sections(self) -> list[str]:
        spec = self.app_state.current
        if spec is None:
            self.panel.append(EventKind.ERROR, t("Add a paper first."))
            return []
        root = Path(spec.local_path).expanduser()
        if not root.is_dir():
            self.panel.append(EventKind.WARNING, t("The paper is not cloned yet - click 'Sync paper' first."))
            return []
        titles = list_section_titles(root)
        self.panel.append(EventKind.INFO, t("Loaded {count} section titles.", count=len(titles)))
        return titles

    def _list_bibs(self) -> list[str]:
        """Editable .bib files of the selected paper (read-only ones are left out)."""
        spec = self.app_state.current
        root = Path(spec.local_path).expanduser() if spec else None
        if root is None or not root.is_dir():
            self.panel.append(EventKind.WARNING, t("The paper is not cloned yet - click 'Sync paper' first."))
            return []
        policy = ProtectionPolicy.build(root, spec.read_only, spec.auto_protect_bib)
        bibs = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.bib") if ".git" not in p.parts)
        editable = [b for b in bibs if policy.reason(b) is None]
        if len(editable) < len(bibs):
            self.panel.append(EventKind.INFO,
                              t("Read-only .bib files not listed: {files}",
                                files=", ".join(b for b in bibs if b not in editable)))
        return editable
