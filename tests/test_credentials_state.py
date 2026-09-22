from pathlib import Path

import pytest

from core.app_state import AppState, PaperSpec, default_local_path, validate_paper
from core.credentials import (
    CredentialError, CredentialStore, GitCredential, git_auth_env, host_of, is_https, mask,
)


class MemoryBackend:
    def __init__(self):
        self.data = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        del self.data[(service, username)]


class BrokenBackend(MemoryBackend):
    def get_password(self, service, username):
        raise RuntimeError("vault locked")


def test_claude_key_roundtrip():
    store = CredentialStore(MemoryBackend())
    assert store.get_claude_key() is None
    store.set_claude_key("  sk-ant-abc123456789  ")
    assert store.get_claude_key() == "sk-ant-abc123456789"
    store.clear_claude_key()
    store.clear_claude_key()  # idempotent
    assert store.get_claude_key() is None


def test_git_credentials_per_host():
    store = CredentialStore(MemoryBackend())
    store.set_git(GitCredential("GitHub.com", "x-access-token", "ghp_1"))
    store.set_git(GitCredential("git.overleaf.com", "git", "olp_2"))
    assert store.git_hosts() == ["git.overleaf.com", "github.com"]
    assert store.get_git("github.com").token == "ghp_1"
    assert "olp_2" not in repr(store.get_git("git.overleaf.com"))
    store.clear_git("github.com")
    assert store.get_git("github.com") is None
    assert store.git_hosts() == ["git.overleaf.com"]


def test_vault_errors_are_wrapped():
    with pytest.raises(CredentialError, match="vault locked"):
        CredentialStore(BrokenBackend()).get_claude_key()


@pytest.mark.parametrize(("url", "host"), [
    ("https://git.overleaf.com/abc123", "git.overleaf.com"),
    ("https://github.com/me/paper.git", "github.com"),
    ("git@github.com:me/paper.git", "github.com"),
    ("ssh://git@gitlab.com/me/paper.git", "gitlab.com"),
    ("C:/papers/local", ""),
    ("", ""),
])
def test_host_of(url, host):
    assert host_of(url) == host


def test_helpers():
    assert is_https("https://x") and not is_https("git@x:y")
    assert mask("sk-ant-api03-abcdefgh1234") == "sk-ant-…1234"
    env = git_auth_env(GitCredential("h", "git", "tok"))
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader" and "tok" not in env["GIT_CONFIG_VALUE_0"]
    assert git_auth_env(None) == {}


def test_validate_paper():
    assert validate_paper(PaperSpec("P", "https://git.overleaf.com/68af18e2086f3be729c587a0"), set()) == []
    problems = validate_paper(PaperSpec("P", "https://u:pw@github.com/x"), {"P"})
    assert any("already exists" in p for p in problems)
    assert any("credentials" in p for p in problems)
    assert validate_paper(PaperSpec("Q"), set()) == ["Choose a folder for the paper (a Git URL is optional)."]
    assert any("branch" in p for p in validate_paper(PaperSpec("Q", local_path="x", branch="a b"), set()))


def test_app_state_persistence(tmp_path: Path):
    path = tmp_path / "state.json"
    state = AppState.load(path)  # missing file -> defaults
    assert state.papers == [] and state.current is None
    state.upsert(PaperSpec("A", "https://github.com/a/b", default_local_path(tmp_path, "My Paper!")))
    state.upsert(PaperSpec("B", local_path="x"))
    state.upsert(PaperSpec("B2", local_path="y"), old_name="B")  # rename
    state.web_search = False
    state.save(path)
    loaded = AppState.load(path)
    assert loaded.names == ["A", "B2"] and loaded.selected == "B2"
    assert loaded.get("A").local_path.endswith("my-paper") and loaded.web_search is False
    loaded.remove("B2")
    assert loaded.current.name == "A"
    path.write_text("{not json")
    assert AppState.load(path).papers == []
