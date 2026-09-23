"""Plan and run the one-way backup of a paper's local-only folders to SharePoint.

The SharePoint library ends up with the same structure as the app::

    <root folder>/<paper name>/data/...
    <root folder>/<paper name>/supplementary/...

Nothing is downloaded, renamed or deleted in SharePoint: a file that disappears
here stays there, which is what makes this safe to run at any time.

What counts as "needs uploading" is decided against a small manifest of what this
computer sent last time (local modification times compared with local modification
times, so a clock difference with the server cannot cause endless re-uploads) plus
the listing of what is actually in the library.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.sharepoint import RemoteFile, SharePointAuthError, SharePointClient, SharePointError, path_problem

IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".gitkeep"}
IGNORED_DIRS = {".git", "__pycache__", ".ipynb_checkpoints", ".venv"}


@dataclass(frozen=True)
class Upload:
    """One file that will be sent."""

    local: Path
    remote_path: str
    relative: str        # path shown to the user, e.g. ``data/runs/a.csv``
    size: int
    new: bool


@dataclass(frozen=True)
class Skipped:
    """A file that cannot be sent, and why."""

    relative: str
    reason: str


@dataclass
class BackupPlan:
    uploads: list[Upload] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    unchanged: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(u.size for u in self.uploads)

    @property
    def empty(self) -> bool:
        return not self.uploads


@dataclass
class BackupResult:
    uploaded: int = 0
    bytes_sent: int = 0
    unchanged: int = 0
    skipped: list[Skipped] = field(default_factory=list)
    failed: list[Skipped] = field(default_factory=list)
    cancelled: bool = False


def remote_base(root_folder: str, paper_name: str) -> str:
    """Where this paper's folders live in the library."""
    parts = [p.strip() for p in f"{root_folder.strip('/ ')}/{paper_name.strip()}".split("/") if p.strip()]
    return "/".join(parts)


def _manifest_path(workspace: Path, paper_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in paper_name).strip() or "paper"
    return workspace / "sharepoint" / f"{safe}.json"


def load_manifest(workspace: Path, paper_name: str) -> dict[str, list[int]]:
    """``{relative path: [size, mtime_ns]}`` of what this computer uploaded before."""
    try:
        data = json.loads(_manifest_path(workspace, paper_name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}
    return {str(k): [int(v[0]), int(v[1])] for k, v in files.items()
            if isinstance(v, list) and len(v) == 2}


def save_manifest(workspace: Path, paper_name: str, files: dict[str, list[int]]) -> None:
    path = _manifest_path(workspace, paper_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"files": files}, indent=1), encoding="utf-8")
    except OSError:
        pass  # a lost manifest only costs one extra upload pass


def local_files(root: Path, folders: list[str]) -> list[tuple[Path, str]]:
    """Every file in the chosen folders as ``(path, relative posix path)``, sorted."""
    found: list[tuple[Path, str]] = []
    for folder in folders:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            parts = relative.split("/")
            if any(p.lower() in IGNORED_DIRS for p in parts[:-1]) or parts[-1].lower() in IGNORED_NAMES:
                continue
            found.append((path, relative))
    return sorted(found, key=lambda item: item[1])


def plan_backup(root: Path, folders: list[str], base: str, remote: dict[str, RemoteFile],
                manifest: dict[str, list[int]]) -> BackupPlan:
    """Decide what to send, comparing the folders with the library and the manifest."""
    plan = BackupPlan()
    for path, relative in local_files(root, folders):
        problem = path_problem(f"{base}/{relative}")
        if problem:
            plan.skipped.append(Skipped(relative, problem))
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            plan.skipped.append(Skipped(relative, f"could not be read ({exc.strerror or exc})"))
            continue
        there = remote.get(relative)
        sent_before = manifest.get(relative)
        changed_here = sent_before is None or sent_before != [stat.st_size, stat.st_mtime_ns]
        if there is not None and not changed_here and there.size == stat.st_size:
            plan.unchanged += 1
            continue
        plan.uploads.append(Upload(path, f"{base}/{relative}", relative, stat.st_size, there is None))
    return plan


def run_backup(client: SharePointClient, plan: BackupPlan, base: str, workspace: Path, paper_name: str,
               on_file: Callable[[Upload, int, int], None] | None = None,
               on_bytes: Callable[[int, int], None] | None = None,
               cancelled: Callable[[], bool] = lambda: False) -> BackupResult:
    """Send everything in ``plan``. A file that fails is reported; the rest still go.

    ``on_file`` is called as each file starts; ``on_bytes`` reports ``(sent, total)``
    across the whole run, so a single large file still moves the progress bar.

    Raises:
        SharePointAuthError: if the sign-in stops working (nothing more is attempted).
    """
    result = BackupResult(unchanged=plan.unchanged, skipped=list(plan.skipped))
    manifest = load_manifest(workspace, paper_name)
    created: set[str] = set()
    total_bytes, done_bytes = plan.total_bytes, 0
    for index, upload in enumerate(plan.uploads, start=1):
        if cancelled():
            result.cancelled = True
            break
        if on_file:
            on_file(upload, index, len(plan.uploads))
        parent = upload.remote_path.rsplit("/", 1)[0]
        sent_so_far = done_bytes
        try:
            if parent not in created:
                client.ensure_folder(parent)
                created.add(parent)
            client.upload(upload.local, upload.remote_path,
                          progress=(lambda sent, _size: on_bytes(sent_so_far + sent, total_bytes))
                          if on_bytes else None)
        except SharePointAuthError:
            save_manifest(workspace, paper_name, manifest)
            raise
        except (SharePointError, OSError) as exc:
            result.failed.append(Skipped(upload.relative, str(exc)))
            done_bytes += upload.size      # a rejected file must not stall the progress bar
            if on_bytes:
                on_bytes(done_bytes, total_bytes)
            continue
        try:
            stat = upload.local.stat()
            manifest[upload.relative] = [stat.st_size, stat.st_mtime_ns]
        except OSError:
            manifest.pop(upload.relative, None)
        result.uploaded += 1
        result.bytes_sent += upload.size
        done_bytes += upload.size
        if on_bytes:
            on_bytes(done_bytes, total_bytes)
    save_manifest(workspace, paper_name, manifest)
    return result


def human_size(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
