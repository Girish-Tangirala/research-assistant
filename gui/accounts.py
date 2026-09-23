"""Sign-in handling for the main window (Claude, Git hosts, OpenAlex)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.app_state import PaperSpec
from core.credentials import CredentialError, mask
from core.events import EventKind
from gui.dialogs import ClaudeLoginDialog, GitLoginDialog, OpenAlexKeyDialog
from gui.menubar import AccountSection


class AccountsMixin:
    """Mixed into :class:`gui.app.ResearchAssistantApp` (uses its store, panel and state)."""

    def _safe(self, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except CredentialError as exc:
            self.panel.append(EventKind.ERROR, str(exc))
            return default

    def _account_sections(self) -> list[AccountSection]:
        """Current sign-in state for the Accounts menu."""
        key = self._safe(self.store.get_claude_key)
        sections = [AccountSection(
            f"Claude: signed in ({mask(key)})" if key else "Claude: not signed in",
            [("Change API key…" if key else "Sign in…", self._login_claude, True),
             ("Sign out", self._logout_claude, bool(key))])]

        host, _ = self._paper_host(self.app_state.current)
        cred = self._safe(lambda: self.store.get_git(host)) if host else None
        if host:
            status = f"Git ({host}): signed in as {cred.username}" if cred else f"Git ({host}): not signed in"
        else:
            status = "Git: no sign-in needed (local or SSH)" if self.app_state.current else "Git: add a paper first"
        sections.append(AccountSection(status, [
            ("Change token…" if cred else "Sign in…", self._login_git, bool(host)),
            ("Sign out", self._logout_git, bool(cred))]))

        oa = self._safe(self.store.get_openalex_key)
        sections.append(AccountSection(
            "OpenAlex key: set" if oa else "OpenAlex key: not set (optional)",
            [("Change key…" if oa else "Add key…", self._login_openalex, True),
             ("Remove key", self._logout_openalex, bool(oa))]))
        sections.append(self._sharepoint_section())
        return sections

    def _ensure_claude(self, then: Callable[[], None], required: bool = True, reason: str = "") -> None:
        if not reason and self._safe(self.store.get_claude_key):
            then()
            return

        def done(ok: bool) -> None:
            if ok or not required:
                then()
            else:
                self.panel.append(EventKind.WARNING, "Claude sign-in is required for this workflow.")

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
                self.panel.append(EventKind.WARNING, f"Sign in to {host} to sync this paper.")

        GitLoginDialog(self, self.store, host, url, self.app_state.author_name, self.app_state.author_email,
                       done, reason=reason)

    def _login_claude(self) -> None:
        ClaudeLoginDialog(self, self.store, self.config_.llm.model, lambda _ok: None)

    def _logout_claude(self) -> None:
        self._safe(self.store.clear_claude_key)
        self.panel.append(EventKind.INFO, "Signed out of Claude.")

    def _login_git(self) -> None:
        self._ensure_git(self.app_state.current, then=lambda: None, required=False, reason="Update your Git credentials.")

    def _logout_git(self) -> None:
        host, _ = self._paper_host(self.app_state.current)
        if host:
            self._safe(lambda: self.store.clear_git(host))
            self.panel.append(EventKind.INFO, f"Signed out of {host}.")

    def _login_openalex(self) -> None:
        OpenAlexKeyDialog(self, self.store, lambda _ok: None)

    def _logout_openalex(self) -> None:
        self._safe(self.store.clear_openalex_key)
        self.panel.append(EventKind.INFO, "OpenAlex key removed.")
