"""The selected paper: repository paths, safe path resolution and write protection."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.app_state import PaperSpec
from core.events import ProposedChange
from core.git_manager import GitManager
from core.latex_parser import find_main_tex
from core.protection import ProtectionPolicy, read_only_message


class ToolError(RuntimeError):
    """Recoverable tool failure - reported back to the model with is_error."""


class ReadOnlyFileError(ToolError):
    """An edit targeted a protected file (e.g. a Zotero-linked .bib)."""


class PaperHandle:
    """The selected paper plus its Git manager and read-only policy."""

    def __init__(self, spec: PaperSpec, git: GitManager) -> None:
        self.spec = spec
        self.git = git
        self._protection: ProtectionPolicy | None = None

    @property
    def root(self) -> Path:
        return self.git.local_path

    @property
    def protection(self) -> ProtectionPolicy:
        """Read-only policy, computed lazily from the current checkout."""
        if self._protection is None:
            self._protection = ProtectionPolicy.build(self.root, self.spec.read_only, self.spec.auto_protect_bib)
        return self._protection

    def refresh_protection(self) -> None:
        """Forget the cached policy (call after pulling new files)."""
        self._protection = None

    def main_tex(self) -> Path:
        main = find_main_tex(self.root)
        if main is None:
            raise ToolError(f"No main .tex file (with \\documentclass) in {self.root}")
        return main

    def resolve(self, rel_path: str | None, for_write: bool = False) -> Path:
        """Resolve a repo-relative path, refusing anything outside the repo.

        Raises:
            ToolError: for paths outside the repository or inside ``.git``.
            ReadOnlyFileError: if ``for_write`` and the file is protected.
        """
        path = self.main_tex() if not rel_path else (self.root / rel_path).resolve()
        if path != self.root and self.root not in path.parents:
            raise ToolError(f"Path escapes the repository: {rel_path}")
        if ".git" in path.relative_to(self.root).parts:
            raise ToolError("Access to .git is not allowed")
        if for_write:
            self.ensure_writable(self.rel(path))
        return path

    def ensure_writable(self, rel_path: str) -> None:
        reason = self.protection.reason(rel_path)
        if reason:
            raise ReadOnlyFileError(read_only_message(rel_path, reason))

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text_preserving_eol(path: Path, content: str) -> None:
    """Write ``content`` keeping the file's existing line-ending convention."""
    eol = "\n"
    if path.exists() and b"\r\n" in path.read_bytes()[:65536]:
        eol = "\r\n"
    with path.open("w", encoding="utf-8", newline=eol) as handle:
        handle.write(content)


class ChangeConflictError(ToolError):
    """A file changed on disk after the change was prepared."""


@dataclass
class AppliedChanges:
    """Files written by :func:`apply_changes`, so they can be committed or reverted."""

    root: Path
    written: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)  # repo-relative paths that did not exist before
    moved: list[tuple[str, str]] = field(default_factory=list)  # (from, to) pairs already moved


def apply_changes(changes: list[ProposedChange], applied: AppliedChanges) -> None:
    """Write approved changes to disk (copying binary assets), recording progress in ``applied``.

    Raises:
        ChangeConflictError: if a target changed since the change was prepared.
    """
    for change in changes:
        if change.moves:
            _move_files(change, applied)
            continue
        target = change.abs_path
        existed = target.exists()
        if change.source_file is not None:
            if existed and not change.replaces:
                raise ChangeConflictError(f"{change.rel_path} already exists - choose another name.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(change.source_file, target)
        else:
            current = read_text(target) if existed else ""
            if current != change.original:
                raise ChangeConflictError(f"{change.rel_path} changed on disk since it was read - aborting.")
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text_preserving_eol(target, change.proposed)
        if not existed:
            applied.created.append(change.rel_path)
        applied.written.append(change.rel_path)


def _move_files(change: ProposedChange, applied: AppliedChanges) -> None:
    """Move files to their new folders, recording each one so it can be undone."""
    for source_rel, target_rel in change.moves:
        source, target = applied.root / source_rel, applied.root / target_rel
        if source_rel == target_rel:
            continue
        if not source.is_file():
            raise ChangeConflictError(f"{source_rel} is no longer there - sync the paper and try again.")
        if target.exists():
            raise ChangeConflictError(f"{target_rel} already exists - aborting.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        applied.moved.append((source_rel, target_rel))
        applied.written += [source_rel, target_rel]
    _remove_empty_folders(applied.root, [applied.root / s for s, _t in change.moves])


def _remove_empty_folders(root: Path, paths: list[Path]) -> None:
    """Delete the folders of ``paths`` (deepest first, up to ``root``) that are now empty."""
    folders = {parent for path in paths for parent in path.parents}
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        if folder != root and root in folder.parents:
            try:
                folder.rmdir()  # only succeeds when the folder is empty
            except OSError:
                pass


def revert_changes(git: GitManager, applied: AppliedChanges) -> None:
    """Undo :func:`apply_changes`: delete new files, move files back, restore tracked files."""
    # New files go first: one of them may sit exactly where a moved file has to return
    # (organising writes a new top-level main.tex where the old one was moved away from).
    for rel in applied.created:
        (applied.root / rel).unlink(missing_ok=True)
    for source_rel, target_rel in reversed(applied.moved):
        source, target = applied.root / source_rel, applied.root / target_rel
        if target.is_file() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(source))
    # Folders the change created and that are empty again (figures/, code/ ...) go too.
    _remove_empty_folders(applied.root, [applied.root / t for _s, t in applied.moved]
                          + [applied.root / rel for rel in applied.created])
    moved_paths = {rel for pair in applied.moved for rel in pair}
    git.discard_changes([w for w in applied.written if w not in applied.created and w not in moved_paths])
    applied.written.clear()
    applied.created.clear()
    applied.moved.clear()
