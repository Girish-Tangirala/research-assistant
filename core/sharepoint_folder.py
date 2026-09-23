"""Back up into a SharePoint library that the OneDrive client syncs to this computer.

Needs nothing set up centrally: the files are copied into the synced folder and the
OneDrive client uploads them. The structure, the change detection and the name rules
are the same as the Graph route, because :mod:`core.sharepoint_sync` only ever calls
``index``, ``ensure_folder`` and ``upload`` - which is all this class provides.

The catch, and why the Graph route still exists: the app hands off to OneDrive and
cannot confirm that a file reached SharePoint. OneDrive's own icons do that.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from core.sharepoint import RemoteFile, SharePointError

PARTIAL_SUFFIX = ".part-researchassistant"


class LocalLibraryClient:
    """The synced library folder, addressed exactly like a Graph drive."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()
        self.drive_name = self.root.name
        self.web_url = str(self.root)

    def check(self) -> None:
        """Fail early with something the user can act on."""
        if not self.root.exists():
            raise SharePointError(
                f"{self.root} does not exist. Open OneDrive, make sure the SharePoint library is synced "
                "to this computer, then pick that folder again.")
        if not self.root.is_dir():
            raise SharePointError(f"{self.root} is a file, not a folder.")
        if not os.access(self.root, os.W_OK):
            raise SharePointError(f"{self.root} cannot be written to. Check your access to the library.")

    def _resolve(self, path: str) -> Path:
        """``a/b`` → the real path, refusing anything that escapes the library folder."""
        target = (self.root / path.strip("/")).resolve()
        root = self.root.resolve()
        if target != root and root not in target.parents:
            raise SharePointError(f"{path!r} is outside the library folder.")
        return target

    def index(self, path: str) -> dict[str, RemoteFile]:
        """Every file at or below ``path``, keyed by path relative to it."""
        base = self._resolve(path)
        if not base.is_dir():
            return {}
        found: dict[str, RemoteFile] = {}
        for item in base.rglob("*"):
            if not item.is_file() or item.name.endswith(PARTIAL_SUFFIX):
                continue
            try:
                stat = item.stat()
            except OSError:
                continue          # a cloud-only placeholder being rehydrated; next run sees it
            found[item.relative_to(base).as_posix()] = RemoteFile(
                item.relative_to(base).as_posix(), stat.st_size,
                datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))
        return found

    def ensure_folder(self, path: str) -> None:
        try:
            self._resolve(path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SharePointError(f"Could not create {path!r} in the library folder: {exc}") from exc

    def upload(self, local: Path, remote_path: str,
               progress: Callable[[int, int], None] | None = None) -> None:
        """Copy the file in, via a temporary name so OneDrive never uploads half of it."""
        target = self._resolve(remote_path)
        partial = target.with_name(target.name + PARTIAL_SUFFIX)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, partial)
            os.replace(partial, target)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise SharePointError(f"Could not copy {local.name} into the library folder: {exc}") from exc
        if progress:
            size = local.stat().st_size
            progress(size, size)
