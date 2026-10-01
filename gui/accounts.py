"""Sign-in handling for the main window (Claude, Git hosts, OpenAlex)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.app_state import PaperSpec
from core.credentials import CredentialError, host_of, mask
from core.events import EventKind
from gui.dialogs import ClaudeLoginDialog, GitLoginDialog, OpenAlexKeyDialog
from gui.menubar import AccountSection
from core.i18n import t, translated


class AccountsMixin:
    """Mixed into :class:`gui.app.ResearchAssistantApp` (uses its store, panel and state)."""

    def _safe(self, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except CredentialError as exc:
            self.panel.append(EventKind.ERROR, translated(exc))
            return default

    def _account_sections(self) -> list[AccountSection]:
        """Current sign-in state for the Accounts menu."""
        key = self._safe(self.store.get_claude_key)
        sections = [AccountSection(
            t("Claude: signed in ({key})", key=mask(key)) if key else t("Claude: not signed in"),
            [(t("Change API key…") if key else t("Sign in…"), self._login_claude, True),
             (t("Sign out"), self._logout_claude, bool(key))])]

        host, _ = self._paper_host(self.app_state.current)
        cred = self._safe(lambda: self.store.get_git(host)) if host else None
        if host:
            status = t("Git ({host}): signed in as {user}", host=host, user=cred.username) if cred \
                else t("Git ({host}): not signed in", host=host)
        else:
            status = t("Git: no sign-in needed (local or SSH)") if self.app_state.current \
                else t("Git: add a paper first")
        sections.append(AccountSection(status, [
            (t("Change token…") if cred else t("Sign in…"), self._login_git, bool(host)),
            (t("Sign out"), self._logout_git, bool(cred))]))
        sections += self._todo_host_section(host)

        oa = self._safe(self.store.get_openalex_key)
        sections.append(AccountSection(
            t("OpenAlex key: set") if oa else t("OpenAlex key: not set (optional)"),
            [(t("Change key…") if oa else t("Add key…"), self._login_openalex, True),
             (t("Remove key"), self._logout_openalex, bool(oa))]))
        sections.append(self._sharepoint_section())
        return sections

    def _todo_host_section(self, paper_host: str) -> list[AccountSection]:
        """Sign-in for the shared to-do repository, when it is on another host than the paper.

        Without this there is no way to sign in to, say, github.com while every
        paper is on Overleaf.
        """
        settings = self.app_state.todo_repo
        host = host_of(settings.url) if settings.configured else ""
        if not host or host == paper_host:
            return []
        cred = self._safe(lambda: self.store.get_git(host))
        status = (t("Shared to-do list ({host}): signed in as {user}", host=host, user=cred.username)
                  if cred else t("Shared to-do list ({host}): not signed in", host=host))
        return [AccountSection(status, [
            (t("Change token…") if cred else t("Sign in…"), self._login_todo_git, True),
            (t("Sign out"), self._logout_todo_git, bool(cred))])]

    def _login_todo_git(self) -> None:
        settings = self.app_state.todo_repo
        host = host_of(settings.url)

        def done(ok: bool, name: str, email: str) -> None:
            if ok:
                self.app_state.author_name, self.app_state.author_email = name, email
                self._save_state()
                self.todo.refresh()

        GitLoginDialog(self, self.store, host, settings.url, self.app_state.author_name,
                       self.app_state.author_email, done,
                       reason="This token is used only for the shared to-do list.")

    def _logout_todo_git(self) -> None:
        host = host_of(self.app_state.todo_repo.url)
        if host:
            self._safe(lambda: self.store.clear_git(host))
            self.panel.append(EventKind.INFO, t("Signed out of {host}.", host=host))

    def _ensure_claude(self, then: Callable[[], None], required: bool = True, reason: str = "") -> None:
        if not reason and self._safe(self.store.get_claude_key):
            then()
            return

        def done(ok: bool) -> None:
            if ok or not required:
                then()
            else:
                self.panel.append(EventKind.WARNING, t("Claude sign-in is required for this workflow."))

        ClaudeLoginDialog(self, self.store, self.config_.llm.model, done, reason=reason)

    def _ensure_git(self, spec: PaperSpec | None, then: Callable[[], None], required: bool = True,
                    reason: str = "") -> None:
        host, url = self._paper_host(spec)
        if not host or (not reason and self._safe(lambda: self.store.get_git(host))):
            then()
            return

        def done(ok: bool, name: str, email: str) -> None:
            if ok:
                self.app_state.author_name, self.app_state.author_email = name, email
                self._save_state()
            if ok or not required:
                then()
            else:
                self.panel.append(EventKind.WARNING, t("Sign in to {host} to sync this paper.", host=host))

        GitLoginDialog(self, self.store, host, url, self.app_state.author_name, self.app_state.author_email,
                       done, reason=reason)

    def _login_claude(self) -> None:
        ClaudeLoginDialog(self, self.store, self.config_.llm.model, lambda _ok: None)

    def _logout_claude(self) -> None:
        self._safe(self.store.clear_claude_key)
        self.panel.append(EventKind.INFO, t("Signed out of Claude."))

    def _login_git(self) -> None:
        self._ensure_git(self.app_state.current, then=lambda: None, required=False, reason="Update your Git credentials.")

    def _logout_git(self) -> None:
        host, _ = self._paper_host(self.app_state.current)
        if host:
            self._safe(lambda: self.store.clear_git(host))
            self.panel.append(EventKind.INFO, t("Signed out of {host}.", host=host))

    def _login_openalex(self) -> None:
        OpenAlexKeyDialog(self, self.store, lambda _ok: None)

    def _logout_openalex(self) -> None:
        self._safe(self.store.clear_openalex_key)
        self.panel.append(EventKind.INFO, t("OpenAlex key removed."))
