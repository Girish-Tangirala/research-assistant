"""GitPython wrapper for Overleaf / GitHub LaTeX repositories.

Notes on Overleaf
-----------------
* Overleaf's Git bridge has a single branch (``main``; older clones: ``master``).
  With ``push_strategy="auto"`` an Overleaf remote therefore uses
  *merge-to-default*: the agent commits on a local feature branch (for a clean
  audit trail), rebases it if collaborators edited the project meanwhile,
  fast-forwards the default branch and pushes that. Other remotes (GitHub,
  GitLab) push the feature branch for PR review.
* A paper does not need a remote at all: the app creates a local repository and
  commits there. ``sync_with_remote`` (the Sync button) is the only operation
  that talks to Overleaf - it fetches, replays the local commits on top of the
  collaborators' edits, and pushes.
* Authentication tokens are injected per-command through ``GIT_CONFIG_*``
  environment variables (git >= 2.31) as an ``http.extraHeader``. They are never
  written into ``.git/config`` or the remote URL, and are redacted from errors.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from git import Actor, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from config import GitSettings
from core.credentials import GitCredential, git_auth_env, host_of, redact
from core.git_errors import GitAuthError, GitOperationError
from core.git_sync import RemoteSyncMixin
from core.proc import NO_WINDOW

__all__ = ["GitAuthError", "GitManager", "GitOperationError", "git_global_identity", "slugify",
           "tracked_files"]

LogFn = Callable[[str], None]


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:max_len] or "change"


class GitManager(RemoteSyncMixin):
    """High-level Git operations for one LaTeX project."""

    def __init__(
        self,
        local_path: Path,
        remote_url: str = "",
        branch: str = "",
        settings: GitSettings | None = None,
        credential: GitCredential | None = None,
        log: LogFn | None = None,
    ) -> None:
        self.local_path = Path(local_path).expanduser().resolve()
        self.remote_url = remote_url.strip()
        self.branch = branch.strip()
        self.settings = settings or GitSettings()
        self.credential = credential
        self._log = log or (lambda _msg: None)
        self._repo: Repo | None = None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @property
    def repo(self) -> Repo:
        if self._repo is None:
            try:
                self._repo = Repo(self.local_path)
            except (InvalidGitRepositoryError, NoSuchPathError) as exc:
                raise GitOperationError(f"{self.local_path} is not a Git repository") from exc
        return self._repo

    def _has_remote(self) -> bool:
        return any(r.name == self.settings.remote_name for r in self.repo.remotes)

    @property
    def exists(self) -> bool:
        return (self.local_path / ".git").exists()

    @property
    def has_remote(self) -> bool:
        """Is a remote configured (in the paper or in an existing clone)?"""
        return bool(self.remote_url) or (self.exists and self._has_remote())

    @property
    def is_overleaf(self) -> bool:
        return "overleaf.com" in self.effective_url

    @property
    def push_strategy(self) -> str:
        if self.settings.push_strategy != "auto":
            return self.settings.push_strategy
        # Local papers and Overleaf both have a single working branch; other hosts
        # get a feature branch so a pull request can be opened.
        return "feature-branch" if (self.effective_url and not self.is_overleaf) else "merge-to-default"

    @property
    def effective_url(self) -> str:
        """Configured URL, or the ``origin`` URL of an existing clone."""
        if self.remote_url:
            return self.remote_url
        if (self.local_path / ".git").exists() and self._has_remote():
            return self.repo.remotes[self.settings.remote_name].url
        return ""

    @property
    def host(self) -> str:
        return host_of(self.effective_url)

    def _auth_env(self) -> dict[str, str]:
        """Per-command environment that injects the HTTP token, if any."""
        return git_auth_env(self.credential)

    def redact(self, text: str) -> str:
        return redact(text, self.credential)

    def _wrap(self, action: str, exc: Exception) -> GitOperationError:
        detail = exc.stderr if isinstance(exc, GitCommandError) and exc.stderr else str(exc)
        detail = self.redact(str(detail).strip())
        hint = ""
        lowered = detail.lower()
        if any(s in lowered for s in ("authentication", "403", "401", "could not read username", "denied")):
            return GitAuthError(
                f"git {action} failed: {self.host or 'the Git host'} rejected the stored credentials. "
                f"Sign in to Git again.\n{detail}", self.host)
        if "non-fast-forward" in lowered or "fetch first" in lowered or "rejected" in lowered:
            hint = " (remote has new commits - pull and retry)"
        elif "conflict" in lowered:
            hint = " (resolve the merge conflict manually in the repository)"
        return GitOperationError(f"git {action} failed{hint}: {detail}")

    # ------------------------------------------------------------------ #
    # Operations
    # ------------------------------------------------------------------ #
    def init_repo(self, branch: str = "main") -> Repo:
        """Create a local repository in ``local_path`` (no remote needed)."""
        if self.exists:
            try:
                return self.repo
            except GitOperationError as exc:
                raise GitOperationError(
                    f"{self.local_path} contains a .git folder that is not a working repository. "
                    "Delete that folder (or choose another one) and try again.") from exc
        self.local_path.mkdir(parents=True, exist_ok=True)
        try:
            self._repo = Repo.init(self.local_path, initial_branch=self.branch or branch)
        except GitCommandError as exc:
            raise self._wrap("init", exc) from exc
        self._log(f"Created a local repository in {self.local_path}")
        return self._repo

    def set_remote(self, url: str) -> None:
        """Point ``origin`` at ``url`` (adding it if needed); an empty URL removes it."""
        name = self.settings.remote_name
        self.remote_url = url.strip()
        try:
            if self._has_remote():
                if not self.remote_url:
                    self.repo.delete_remote(name)
                    return
                self.repo.remotes[name].set_url(self.remote_url)
            elif self.remote_url:
                self.repo.create_remote(name, self.remote_url)
        except GitCommandError as exc:
            raise self._wrap("remote", exc) from exc

    def commit_all(self, message: str) -> str:
        """Stage everything that is not ignored and commit it."""
        actor = Actor(self.settings.author_name, self.settings.author_email)
        try:
            self.repo.git.add("-A")
            if not self.repo.index.entries and not self.repo.head.is_valid():
                raise GitOperationError("Nothing to commit")
            commit = self.repo.index.commit(message, author=actor, committer=actor)
        except GitCommandError as exc:
            raise self._wrap("commit", exc) from exc
        self._log(f"Committed {commit.hexsha[:10]}: {message.splitlines()[0]}")
        return commit.hexsha[:10]

    def ensure_repo(self) -> Repo:
        """Clone the remote if needed, otherwise open the existing repository."""
        if self.exists:
            repo = self.repo
            # A local paper that has just been given an Overleaf link needs the remote attached.
            name = self.settings.remote_name
            current = repo.remotes[name].url if self._has_remote() else ""
            if self.remote_url and current.replace("\\", "/") != self.remote_url.replace("\\", "/"):
                self._log(f"Linking this paper to {self.redact(self.remote_url)}")
                self.set_remote(self.remote_url)
            return repo
        if not self.remote_url:
            raise GitOperationError(
                f"{self.local_path} is not a Git repository and no remote URL was provided"
            )
        if self.local_path.exists() and any(self.local_path.iterdir()):
            raise GitOperationError(f"Refusing to clone into non-empty directory {self.local_path}")
        self._log(f"Cloning {self.redact(self.remote_url)} -> {self.local_path}")
        try:
            kwargs = {"branch": self.branch} if self.branch else {}
            self._repo = Repo.clone_from(self.remote_url, self.local_path, env=self._auth_env() or None, **kwargs)
        except GitCommandError as exc:
            raise self._wrap("clone", exc) from exc
        return self._repo

    @property
    def default_branch(self) -> str:
        if self.branch:
            return self.branch
        try:
            ref = self.repo.git.symbolic_ref(f"refs/remotes/{self.settings.remote_name}/HEAD")
            return ref.rsplit("/", 1)[-1]
        except GitCommandError:
            names = {h.name for h in self.repo.heads}
            return "main" if "main" in names else "master"

    def current_branch(self) -> str:
        try:
            return self.repo.active_branch.name
        except TypeError as exc:  # detached HEAD
            raise GitOperationError("Repository is in detached-HEAD state") from exc

    def is_dirty(self) -> bool:
        return self.repo.is_dirty(untracked_files=False)

    def sync(self) -> str:
        """Clone or fast-forward pull the configured branch. Returns HEAD sha.

        A local-only paper (no remote) is left exactly as it is, including
        uncommitted edits made in another editor.
        """
        repo = self.ensure_repo()
        target = self.default_branch
        if not self._has_remote():
            return repo.head.commit.hexsha[:10] if repo.head.is_valid() else ""
        if self.is_dirty():
            raise GitOperationError(
                f"{self.local_path} has uncommitted changes; commit or stash them before syncing"
            )
        try:
            if self.current_branch() != target:
                self._log(f"Checking out {target}")
                repo.git.checkout(target)
            if self._has_remote():
                self._log(f"Pulling {self.settings.remote_name}/{target}")
                with repo.git.custom_environment(**self._auth_env()):
                    repo.git.pull("--ff-only", self.settings.remote_name, target)
        except GitCommandError as exc:
            raise self._wrap("pull", exc) from exc
        return repo.head.commit.hexsha[:10]

    def create_feature_branch(self, topic: str) -> str:
        """Create and check out ``agent/<topic>-<timestamp>`` from the default branch."""
        name = f"{self.settings.feature_branch_prefix}{slugify(topic)}-{datetime.now():%Y%m%d-%H%M%S}"
        try:
            base = self.default_branch
            if self.current_branch() != base:
                self.repo.git.checkout(base)
            self.repo.git.checkout("-b", name)
        except GitCommandError as exc:
            raise self._wrap("checkout -b", exc) from exc
        self._log(f"Created branch {name}")
        return name

    def checkout(self, branch: str) -> None:
        try:
            self.repo.git.checkout(branch)
        except GitCommandError as exc:
            raise self._wrap("checkout", exc) from exc

    def commit(self, files: Iterable[str], message: str) -> str:
        """Stage ``files`` (repo-relative) and commit. Returns the short sha.

        ``git add -A`` is used so files that moved away are staged as deletions.
        """
        files = list(dict.fromkeys(files))
        if not files:
            raise GitOperationError("Nothing to commit")
        actor = Actor(self.settings.author_name, self.settings.author_email)
        try:
            self.repo.git.add("-A", "--", *files)
            if not self.repo.index.diff("HEAD"):
                raise GitOperationError("Staged files are identical to HEAD - nothing to commit")
            commit = self.repo.index.commit(message, author=actor, committer=actor)
        except GitCommandError as exc:
            raise self._wrap("commit", exc) from exc
        self._log(f"Committed {commit.hexsha[:10]}: {message.splitlines()[0]}")
        return commit.hexsha[:10]

    def push(self, branch: str) -> None:
        if not self._has_remote():
            raise GitOperationError(f"No remote named {self.settings.remote_name!r}")
        self._log(f"Pushing {branch} -> {self.settings.remote_name}")
        try:
            with self.repo.git.custom_environment(**self._auth_env()):
                self.repo.git.push("--set-upstream", self.settings.remote_name, branch)
        except GitCommandError as exc:
            raise self._wrap("push", exc) from exc

    def publish(self, feature_branch: str, push: bool = True) -> str:
        """Deliver a committed feature branch according to the push strategy.

        Returns:
            The name of the branch that was (or would be) pushed.
        """
        base = self.default_branch
        if not push:
            # Local-first: fold the commit into the working branch so the paper folder
            # is always the current version; the Sync button sends it later.
            self._integrate(feature_branch, base, pull=False)
            self._log(f"Kept on this computer on '{base}' - use Sync to send it")
            return base
        if self.push_strategy != "merge-to-default":
            self.push(feature_branch)
            return feature_branch

        for attempt in (1, 2):  # retry once if a collaborator pushes in between
            self._integrate(feature_branch, base, pull=push and self._has_remote())
            if not push:
                self._log("Push disabled - changes committed locally only")
                return base
            try:
                self.push(base)
                return base
            except GitOperationError as exc:
                if attempt == 2 or "remote has new commits" not in str(exc):
                    raise
                self._log("The remote changed while pushing - updating and retrying")
        return base

    def _integrate(self, feature_branch: str, base: str, pull: bool) -> None:
        """Bring ``base`` up to date and fast-forward it to ``feature_branch``.

        When collaborators changed the remote (e.g. edits in the Overleaf editor)
        after the agent synced, the feature branch is rebased onto the new base
        first. On conflicts the rebase is aborted and the work stays on the
        feature branch.
        """
        git = self.repo.git
        identity = {"GIT_COMMITTER_NAME": self.settings.author_name,
                    "GIT_COMMITTER_EMAIL": self.settings.author_email}
        try:
            git.checkout(base)
            if pull:
                with git.custom_environment(**self._auth_env()):
                    git.pull("--ff-only", self.settings.remote_name, base)
            try:
                git.merge_base("--is-ancestor", base, feature_branch)
            except GitCommandError:
                self._log(f"{base} has new commits from collaborators - rebasing {feature_branch} onto it")
                try:
                    with git.custom_environment(**identity):
                        git.rebase(base, feature_branch)
                except GitCommandError as exc:
                    try:
                        git.rebase("--abort")
                    finally:
                        git.checkout(base)
                    raise GitOperationError(
                        f"Your approved changes conflict with edits made on the remote since the last sync. "
                        f"They are kept on local branch '{feature_branch}'; sync the paper and run the "
                        f"workflow again.\n{self.redact(str(exc.stderr or exc).strip())}") from exc
                git.checkout(base)
            git.merge("--ff-only", feature_branch)
        except GitCommandError as exc:
            raise self._wrap("merge", exc) from exc
        self._log(f"Fast-forwarded {base} to {feature_branch}")

    def undo_last_commit(self, expected_prefix: str) -> None:
        """Drop the local HEAD commit (only if it is the app's own ``expected_prefix`` commit)."""
        head = self.repo.head.commit
        if not head.message.startswith(expected_prefix) or not head.parents:
            raise GitOperationError("Refusing to undo a commit the app did not just create.")
        try:
            self.repo.git.reset("--hard", "HEAD~1")
        except GitCommandError as exc:
            raise self._wrap("reset", exc) from exc

    def recent_authors(self, limit: int = 300) -> list[str]:
        """Distinct author names from recent history (for assignee suggestions)."""
        try:
            names = self.repo.git.log(f"-{limit}", "--format=%an").splitlines()
        except GitCommandError as exc:
            raise self._wrap("log", exc) from exc
        return sorted({n.strip() for n in names if n.strip()})

    def discard_changes(self, files: Iterable[str]) -> None:
        """Restore ``files`` to their HEAD state (used for rollback)."""
        files = list(files)
        if files:
            try:
                self.repo.git.checkout("HEAD", "--", *files)
            except GitCommandError as exc:
                raise self._wrap("checkout -- files", exc) from exc

    def abandon_branch(self, feature_branch: str) -> None:
        """Return to the default branch and delete an unused feature branch."""
        try:
            self.repo.git.checkout(self.default_branch)
            self.repo.git.branch("-D", feature_branch)
        except GitCommandError as exc:
            raise self._wrap("branch -D", exc) from exc


def tracked_files(git: "GitManager") -> list[str]:
    """Repo-relative paths Git knows about, plus files that are not ignored yet."""
    repo = git.ensure_repo()
    try:
        tracked = repo.git.ls_files().splitlines()
        untracked = list(repo.untracked_files)
    except GitCommandError as exc:
        raise git._wrap("ls-files", exc) from exc
    return sorted({f.replace("\\", "/") for f in tracked + untracked if f})


def git_global_identity() -> tuple[str, str]:
    """``(user.name, user.email)`` from the global git config (empty if unset)."""
    values = []
    for key in ("user.name", "user.email"):
        try:
            out = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True, timeout=5,
                                 creationflags=NO_WINDOW)
            values.append(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            values.append("")
    return values[0], values[1]
