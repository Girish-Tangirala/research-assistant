"""Persistent, in-app credentials.

Secrets are stored in the operating system's credential vault through
:mod:`keyring` (Windows Credential Manager, macOS Keychain, Secret Service on
Linux). They are entered once in the app and reused until the user signs out
or a service rejects them.

Stored items (service name ``ScientificResearchAssistant``):

* ``claude_api_key``   – Anthropic API key.
* ``git:<host>``       – JSON ``{"username", "token"}`` per Git host.
* ``git_hosts``        – JSON list of hosts with stored Git credentials.
* ``openalex_api_key`` – optional OpenAlex key (raises the daily search budget).
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from core.proc import NO_WINDOW

SERVICE = "ScientificResearchAssistant"
CLAUDE_KEY = "claude_api_key"
OPENALEX_KEY = "openalex_api_key"
GIT_HOSTS_KEY = "git_hosts"

DEFAULT_GIT_USERNAMES = {
    "git.overleaf.com": "git",
    "github.com": "x-access-token",
    "gitlab.com": "oauth2",
}
GIT_TOKEN_HELP = {
    "git.overleaf.com": "Overleaf → Account Settings → Git integration → Generate token. Username: git",
    "github.com": "GitHub → Settings → Developer settings → Fine-grained token with Contents: Read and write.",
    "gitlab.com": "GitLab → Preferences → Access tokens (read_repository + write_repository). Username: oauth2",
}


class CredentialError(RuntimeError):
    """A credential could not be stored, loaded or verified."""


class SecretBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


@dataclass(frozen=True)
class GitCredential:
    host: str
    username: str
    token: str = field(repr=False)


def host_of(url: str) -> str:
    """Hostname of an https/ssh/scp-style Git URL ('' for local paths)."""
    url = url.strip()
    scp = re.match(r"^[\w.-]+@([\w.-]+):", url)
    if scp:
        return scp.group(1).lower()
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() if parsed.scheme in {"http", "https", "ssh", "git"} else ""


def is_https(url: str) -> bool:
    return url.strip().lower().startswith(("https://", "http://"))


def mask(secret: str) -> str:
    """Show only enough of a secret to recognise it."""
    if len(secret) <= 10:
        return "•" * len(secret)
    return f"{secret[:7]}…{secret[-4:]}"


def git_auth_env(credential: GitCredential | None) -> dict[str, str]:
    """Environment that injects an HTTP Basic auth header into one git command.

    Uses ``GIT_CONFIG_*`` (git >= 2.31) so nothing is written to ``.git/config``.
    """
    if credential is None or not credential.token:
        return {}
    basic = base64.b64encode(f"{credential.username}:{credential.token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        "GIT_TERMINAL_PROMPT": "0",
    }


def redact(text: str, credential: GitCredential | None) -> str:
    """Remove URL userinfo, raw tokens and Basic-auth blobs from text."""
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text)
    if credential and credential.token:
        basic = base64.b64encode(f"{credential.username}:{credential.token}".encode()).decode()
        text = text.replace(basic, "***").replace(credential.token, "***")
    return text


class CredentialStore:
    """Typed facade over the OS credential vault."""

    def __init__(self, backend: SecretBackend | None = None) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._backend = backend

    # -- raw access ------------------------------------------------------ #
    def _get(self, key: str) -> str | None:
        try:
            return self._backend.get_password(SERVICE, key)
        except Exception as exc:  # keyring raises backend-specific errors
            raise CredentialError(f"Could not read from the credential vault: {exc}") from exc

    def _set(self, key: str, value: str) -> None:
        try:
            self._backend.set_password(SERVICE, key, value)
        except Exception as exc:
            raise CredentialError(f"Could not save to the credential vault: {exc}") from exc

    def _delete(self, key: str) -> None:
        try:
            if self._backend.get_password(SERVICE, key) is not None:
                self._backend.delete_password(SERVICE, key)
        except Exception as exc:
            raise CredentialError(f"Could not delete from the credential vault: {exc}") from exc

    # -- Claude ---------------------------------------------------------- #
    def get_claude_key(self) -> str | None:
        return self._get(CLAUDE_KEY) or None

    def set_claude_key(self, key: str) -> None:
        self._set(CLAUDE_KEY, key.strip())

    def clear_claude_key(self) -> None:
        self._delete(CLAUDE_KEY)

    # -- OpenAlex (optional) ------------------------------------------- #
    def get_openalex_key(self) -> str | None:
        return self._get(OPENALEX_KEY) or None

    def set_openalex_key(self, key: str) -> None:
        self._set(OPENALEX_KEY, key.strip())

    def clear_openalex_key(self) -> None:
        self._delete(OPENALEX_KEY)

    # -- Git --------------------------------------------------------------- #
    def git_hosts(self) -> list[str]:
        raw = self._get(GIT_HOSTS_KEY)
        try:
            return list(json.loads(raw)) if raw else []
        except ValueError:
            return []

    def get_git(self, host: str) -> GitCredential | None:
        raw = self._get(f"git:{host.lower()}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return GitCredential(host.lower(), data["username"], data["token"])
        except (ValueError, KeyError):
            return None

    def set_git(self, credential: GitCredential) -> None:
        host = credential.host.lower()
        self._set(f"git:{host}", json.dumps({"username": credential.username, "token": credential.token}))
        hosts = self.git_hosts()
        if host not in hosts:
            self._set(GIT_HOSTS_KEY, json.dumps(sorted(hosts + [host])))

    def clear_git(self, host: str) -> None:
        host = host.lower()
        self._delete(f"git:{host}")
        hosts = [h for h in self.git_hosts() if h != host]
        self._set(GIT_HOSTS_KEY, json.dumps(hosts))


# ---------------------------------------------------------------------- #
# Verification (network)
# ---------------------------------------------------------------------- #
def verify_claude_key(api_key: str, model: str, timeout: float = 30.0) -> str:
    """Check an API key by retrieving the configured model.

    Returns:
        The model's display name.

    Raises:
        CredentialError: with a user-facing explanation.
    """
    import anthropic

    if not api_key.strip():
        raise CredentialError("Please enter an API key.")
    client = anthropic.Anthropic(api_key=api_key.strip(), max_retries=1, timeout=timeout)
    try:
        info = client.models.retrieve(model)
    except anthropic.AuthenticationError as exc:
        raise CredentialError("This API key was rejected. Check that it was copied completely.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise CredentialError(f"The key is valid but lacks permission: {exc.message}") from exc
    except anthropic.NotFoundError as exc:
        raise CredentialError(f"The key works, but model {model!r} is not available to it.") from exc
    except anthropic.APIConnectionError as exc:
        raise CredentialError("Could not reach the Claude API - check your internet connection.") from exc
    except anthropic.APIStatusError as exc:
        raise CredentialError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    return info.display_name


def verify_git_access(url: str, credential: GitCredential | None, timeout: float = 45.0) -> None:
    """Run ``git ls-remote`` against ``url`` using ``credential``.

    Raises:
        CredentialError: if git is missing, the host rejects the credential,
            or the repository cannot be reached.
    """
    import os

    env = {**os.environ, **git_auth_env(credential), "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", url], env=env, capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise CredentialError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise CredentialError(f"Timed out contacting {host_of(url)}.") from exc
    if proc.returncode != 0:
        detail = redact(proc.stderr.strip(), credential)
        lowered = detail.lower()
        if any(s in lowered for s in ("authentication", "403", "401", "could not read username", "denied")):
            raise CredentialError(f"{host_of(url)} rejected these credentials.\n{detail}")
        raise CredentialError(f"Could not access the repository:\n{detail}")


def verify_openalex_key(api_key: str, timeout: float = 20.0) -> None:
    """Make one tiny OpenAlex request with ``api_key``.

    Raises:
        CredentialError: if the key is rejected or OpenAlex is unreachable.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    if not api_key.strip():
        raise CredentialError("Please enter an API key.")
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
        {"per_page": 1, "select": "id", "api_key": api_key.strip()})
    request = urllib.request.Request(url, headers={"User-Agent": "ScientificResearchAssistant/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise CredentialError("OpenAlex rejected this API key.") from exc
        raise CredentialError(f"OpenAlex returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CredentialError(f"Could not reach OpenAlex: {exc}") from exc
