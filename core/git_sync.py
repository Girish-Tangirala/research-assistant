"""The Sync button: fetching, counting and pushing a paper's commits.

Split out of :mod:`core.git_manager` to keep both files small; these methods are
mixed into :class:`~core.git_manager.GitManager` and use its repository, remote
settings and credential handling.
"""

from __future__ import annotations

from git import GitCommandError

from core.git_errors import GitOperationError


class RemoteSyncMixin:
    """Talking to the remote (Overleaf, GitHub): fetch, counts, two-way sync."""

    def fetch(self) -> None:
        if not self._has_remote():
            raise GitOperationError(f"No remote named {self.settings.remote_name!r}")
        try:
            with self.repo.git.custom_environment(**self._auth_env()):
                self.repo.git.fetch(self.settings.remote_name)
        except GitCommandError as exc:
            raise self._wrap("fetch", exc) from exc

    def _count(self, revision_range: str) -> int:
        try:
            return int(self.repo.git.rev_list("--count", revision_range) or 0)
        except GitCommandError:
            return 0

    def pending_commits(self, limit: int = 20) -> list[str]:
        """Subjects of commits on the working branch that the remote does not have yet.

        For a paper without a remote this is the whole history (nothing is shared yet).
        """
        if not self.exists or not self.repo.head.is_valid():
            return []
        base = self.default_branch
        try:
            if self._has_remote() and f"{self.settings.remote_name}/{base}" in [r.name for r in self.repo.refs]:
                revisions = f"{self.settings.remote_name}/{base}..{base}"
            else:
                revisions = base
            return self.repo.git.log(f"-{limit}", "--format=%s", revisions).splitlines()
        except GitCommandError:
            return []

    def counts(self) -> tuple[int, int]:
        """``(unsynced local commits, commits waiting on the remote)`` from the last fetch."""
        if not self.exists or not self.repo.head.is_valid():
            return 0, 0
        base = self.default_branch
        tracking = f"{self.settings.remote_name}/{base}"
        if not self._has_remote() or tracking not in [r.name for r in self.repo.refs]:
            return self._count(base), 0
        return self._count(f"{tracking}..{base}"), self._count(f"{base}..{tracking}")

    def _shares_history(self, base: str) -> bool:
        """Do the local branch and the remote branch have a common ancestor?"""
        try:
            return bool(self.repo.git.merge_base(base, f"{self.settings.remote_name}/{base}"))
        except GitCommandError:
            return False

    def sync_with_remote(self) -> tuple[int, int]:
        """Fetch, replay local commits on top of the remote, then push.

        Returns:
            ``(pushed, pulled)`` - commits sent and commits taken from the remote.

        Raises:
            GitOperationError: if the tree is dirty, there is no remote, or the
                rebase conflicts (the local commits are kept in that case).
        """
        if not self._has_remote():
            raise GitOperationError("This paper has no Overleaf (or Git) link yet - add one with Edit paper.")
        repo = self.ensure_repo()
        base = self.default_branch
        if self.is_dirty():
            raise GitOperationError("There are uncommitted changes in the paper folder; the app commits its "
                                    "own edits, so commit or undo the others before syncing.")
        if self.current_branch() != base:
            self.checkout(base)
        self.fetch()
        pushed, pulled = self.counts()
        if pulled:
            if pushed and not self._shares_history(base):
                raise GitOperationError(
                    f"This paper and the {self.host or 'remote'} project were started separately, so they have "
                    "nothing in common - merging them automatically would be guesswork. Nothing was sent.\n"
                    "Either link the paper to a brand-new (empty) Overleaf project, or add this paper again "
                    "from the Overleaf project link and copy your files into that folder.")
            self._log(f"{pulled} change(s) came from {self.host or 'the remote'} - replaying your commits on top")
            identity = {"GIT_COMMITTER_NAME": self.settings.author_name,
                        "GIT_COMMITTER_EMAIL": self.settings.author_email}
            try:
                with repo.git.custom_environment(**identity):
                    repo.git.rebase(f"{self.settings.remote_name}/{base}")
            except GitCommandError as exc:
                try:
                    repo.git.rebase("--abort")
                except GitCommandError:
                    pass
                raise GitOperationError(
                    "Your changes and the edits made in Overleaf touch the same lines, so they cannot be "
                    "merged automatically. Nothing was sent; open the files and resolve it, or ask a "
                    "co-author which version to keep.\n" + self.redact(str(exc.stderr or exc).strip())) from exc
        if pushed:
            self.push(base)
        return pushed, pulled
