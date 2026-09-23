"""Persistent, non-secret application state: the paper list and UI preferences."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.credentials import host_of

URL_RE = re.compile(r"^(https://|http://|ssh://|git@)\S+$")
CREDENTIAL_URL_RE = re.compile(r"^https?://[^/@\s]+:[^/@\s]*@")
BRANCH_RE = re.compile(r"^[\w./-]+$")
APPEARANCES = ("Dark", "Light", "System")
OVERLEAF_PROJECT_RE = re.compile(
    r"^https?://(?:www\.|git\.)?overleaf\.com/(?:project/|git/)?([0-9a-f]{16,40})(?:[/?#].*)?$", re.I)
OVERLEAF_GIT_RE = re.compile(r"^https://git\.overleaf\.com/[0-9a-f]{16,40}$")


def normalize_remote_url(url: str) -> str:
    """Tidy a pasted Git URL; Overleaf project/editor links become clone URLs.

    ``https://www.overleaf.com/project/<id>`` and
    ``https://git.overleaf.com/project/<id>`` both map to
    ``https://git.overleaf.com/<id>``.
    """
    url = url.strip()
    match = OVERLEAF_PROJECT_RE.match(url)
    if match:
        return f"https://git.overleaf.com/{match.group(1).lower()}"
    return url.rstrip("/")


SHAREPOINT_MODES = ("folder", "graph")


@dataclass
class SharePointSettings:
    """Where the local-only folders are backed up (no secrets: the token is in the vault).

    Two ways to reach SharePoint:

    ``folder``
        Copy into a library the OneDrive client already syncs to a folder on this
        computer, which OneDrive then uploads. Needs nothing set up centrally.
    ``graph``
        Upload straight to the library through Microsoft Graph. Needs an Azure app
        registration (``client_id``/``tenant``), which many universities only let
        their IT department create.
    """

    mode: str = "folder"
    local_library: str = ""            # folder mode: the OneDrive-synced library folder
    client_id: str = ""                # graph mode: from the Azure app registration
    tenant: str = "organizations"
    site_url: str = ""
    library: str = ""                  # blank = the site's default 'Documents' library
    root_folder: str = "Research papers"
    folders: str = "data, supplementary"
    account: str = ""                  # display only: who signed in last

    @property
    def uses_graph(self) -> bool:
        return self.mode == "graph"

    @property
    def configured(self) -> bool:
        if self.uses_graph:
            return bool(self.client_id.strip() and self.site_url.strip())
        return bool(self.local_library.strip())

    @property
    def folder_list(self) -> list[str]:
        return [f.strip().strip("/") for f in self.folders.split(",") if f.strip().strip("/")]


def validate_sharepoint(settings: SharePointSettings) -> list[str]:
    """Human-readable problems with the SharePoint settings (empty list = OK)."""
    problems: list[str] = []
    if settings.mode not in SHAREPOINT_MODES:
        problems.append("Choose how the app should reach SharePoint.")
    elif settings.uses_graph:
        if not settings.client_id.strip():
            problems.append("Enter the application (client) ID from the Azure app registration.")
        if not settings.site_url.strip():
            problems.append("Enter the address of the SharePoint site.")
        elif not re.match(r"^(https?://)?[\w.-]+\.\w+", settings.site_url.strip()):
            problems.append("The site address should look like https://yourcompany.sharepoint.com/sites/Team.")
    elif not settings.local_library.strip():
        problems.append("Choose the folder that OneDrive syncs with the SharePoint library.")
    elif not Path(settings.local_library).expanduser().is_dir():
        problems.append(f"{settings.local_library} is not a folder on this computer.")
    if not settings.folder_list:
        problems.append("Choose at least one folder to back up.")
    if not settings.root_folder.strip():
        problems.append("Enter the folder in SharePoint the papers go into.")
    return problems


@dataclass
class PaperSpec:
    """One LaTeX paper (a Git repository) the user works on."""

    name: str
    remote_url: str = ""
    local_path: str = ""
    branch: str = ""
    read_only: str = ""  # comma-separated repo-relative glob patterns
    auto_protect_bib: bool = True  # auto-detect Zotero/Mendeley-linked .bib files

    @property
    def local_only(self) -> bool:
        """A paper that lives only on this computer (no Overleaf/Git link yet)."""
        return not self.remote_url.strip()

    @property
    def host(self) -> str:
        return host_of(self.remote_url)


def validate_paper(spec: PaperSpec, other_names: set[str]) -> list[str]:
    """Validate user input for a paper; returns a list of problems."""
    problems: list[str] = []
    if not spec.name.strip():
        problems.append("Please give the paper a name.")
    elif spec.name.strip() in other_names:
        problems.append(f"A paper named {spec.name!r} already exists.")
    if not spec.remote_url and not spec.local_path:
        problems.append("Choose a folder for the paper (a Git URL is optional).")
    if spec.remote_url:
        if not URL_RE.match(spec.remote_url):
            problems.append("Git URL must start with https://, ssh:// or git@.")
        elif CREDENTIAL_URL_RE.match(spec.remote_url):
            problems.append("Don't put credentials in the URL - sign in via the Accounts menu.")
        elif "overleaf.com" in spec.remote_url.lower() and not OVERLEAF_GIT_RE.match(spec.remote_url):
            problems.append("Overleaf URL not recognised - paste the project link "
                            "(https://www.overleaf.com/project/<id>) or the Git link from the project's Git integration.")
    if spec.local_path and Path(spec.local_path).expanduser().is_file():
        problems.append("Local path must be a folder, not a file.")
    if spec.branch and not BRANCH_RE.match(spec.branch):
        problems.append("Invalid branch name.")
    return problems


def _paper_from_json(data: dict) -> PaperSpec:
    fields = PaperSpec.__dataclass_fields__
    values = {k: (bool(v) if fields[k].type in ("bool", bool) else str(v))
              for k, v in data.items() if k in fields}
    return PaperSpec(**values)


def _sharepoint_from_json(data: object) -> SharePointSettings:
    if not isinstance(data, dict):
        return SharePointSettings()
    fields = SharePointSettings.__dataclass_fields__
    settings = SharePointSettings(**{k: str(v) for k, v in data.items() if k in fields})
    if settings.mode not in SHAREPOINT_MODES:
        settings.mode = "folder"
    return settings


def default_local_path(papers_dir: Path, name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower() or "paper"
    return str(papers_dir / slug)


@dataclass
class AppState:
    papers: list[PaperSpec] = field(default_factory=list)
    selected: str = ""
    push_after_commit: bool = False   # off: commits stay local until the Sync button is pressed
    compile_before_commit: bool = True
    web_search: bool = True
    appearance: str = "Dark"
    preview: bool = True
    confirm_push: bool = True
    show_preview: bool = True
    author_name: str = ""
    author_email: str = ""
    sharepoint: SharePointSettings = field(default_factory=SharePointSettings)

    # -- papers ------------------------------------------------------------ #
    @property
    def names(self) -> list[str]:
        return [p.name for p in self.papers]

    def get(self, name: str) -> PaperSpec | None:
        return next((p for p in self.papers if p.name == name), None)

    @property
    def current(self) -> PaperSpec | None:
        return self.get(self.selected) or (self.papers[0] if self.papers else None)

    def upsert(self, spec: PaperSpec, old_name: str | None = None) -> None:
        """Add ``spec`` or replace the paper previously called ``old_name``."""
        target = old_name or spec.name
        for idx, paper in enumerate(self.papers):
            if paper.name == target:
                self.papers[idx] = spec
                break
        else:
            self.papers.append(spec)
        self.selected = spec.name

    def remove(self, name: str) -> None:
        self.papers = [p for p in self.papers if p.name != name]
        if self.selected == name:
            self.selected = self.papers[0].name if self.papers else ""

    # -- persistence --------------------------------------------------------- #
    @classmethod
    def load(cls, path: Path) -> "AppState":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        papers = [_paper_from_json(p) for p in data.get("papers", []) if isinstance(p, dict) and p.get("name")]
        for paper in papers:
            paper.remote_url = normalize_remote_url(paper.remote_url)
        return cls(
            papers=papers,
            selected=str(data.get("selected", "")),
            push_after_commit=bool(data.get("push_after_commit", False)),
            compile_before_commit=bool(data.get("compile_before_commit", True)),
            web_search=bool(data.get("web_search", True)),
            appearance=data.get("appearance") if data.get("appearance") in APPEARANCES else "Dark",
            preview=bool(data.get("preview", True)),
            confirm_push=bool(data.get("confirm_push", True)),
            show_preview=bool(data.get("show_preview", True)),
            author_name=str(data.get("author_name", "")),
            author_email=str(data.get("author_email", "")),
            sharepoint=_sharepoint_from_json(data.get("sharepoint")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
