"""Installing Git / MiKTeX on first start, and the local-only data/ folder of every paper."""

from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo

from core import dependencies as deps
from core.project_layout import ensure_local_folders

SHA = "5aa8a20f6e9abb2c755f0e73c91c687701a46b309ad84a0ca6509380fa4ae290"


def test_git_installer_uses_the_published_digest_or_the_release_notes():
    asset = {"name": "PortableGit-2.55.0.5-64-bit.7z.exe", "size": 5, "digest": f"sha256:{SHA}",
             "browser_download_url": "https://github.com/x/PortableGit-2.55.0.5-64-bit.7z.exe"}
    other = {"name": "Git-2.55.0.5-64-bit.exe", "browser_download_url": "https://x/other.exe"}
    found = deps.git_installer({"assets": [other, asset]})
    assert found.file_name == asset["name"] and found.sha256 == SHA and found.url.endswith(".7z.exe")
    no_digest = {**asset, "digest": None}
    body = f"| File | SHA-256 |\n| {asset['name']} | {SHA.upper()} |"
    assert deps.git_installer({"assets": [no_digest], "body": body}).sha256 == SHA
    with pytest.raises(deps.DependencyError, match="checksum"):
        deps.git_installer({"assets": [no_digest], "body": ""})


def test_miktex_installer_is_read_from_the_download_page():
    page = """<div>basic-miktex-25.12-x64.exe</div><div>SHA-256:</div>
              <div>14b42dd9f4b4a7813a8bfd69c8f99316c2888cc4ee26f631f397e163d85d6c62</div>
              <a href='/download/ctan/systems/win32/miktex/setup/windows-x64/basic-miktex-25.12-x64.exe'>Download</a>
              <div>SHA-256:</div><div>0571e90f6d94353089b4f189fd82a532f9fe559a388c7e7f1102b14b3c1ae27d</div>"""
    found = deps.miktex_installer(page)
    assert found.file_name == "basic-miktex-25.12-x64.exe"
    assert found.sha256 == "14b42dd9f4b4a7813a8bfd69c8f99316c2888cc4ee26f631f397e163d85d6c62"
    assert found.url == "https://miktex.org/download/ctan/systems/win32/miktex/setup/windows-x64/basic-miktex-25.12-x64.exe"
    with pytest.raises(deps.DependencyError, match="changed"):
        deps.miktex_installer("<html>nothing here</html>")


@pytest.fixture()
def file_server(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(served), **kw)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield served, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_download_checks_the_checksum_and_never_keeps_a_bad_file(tmp_path, file_server):
    served, base = file_server
    payload = b"installer bytes" * 1000
    (served / "setup.exe").write_bytes(payload)
    good = deps.Installer("git", "setup.exe", f"{base}/setup.exe", hashlib.sha256(payload).hexdigest())
    seen = []
    path = deps.download(good, tmp_path / "dl", progress=lambda done, total: seen.append((done, total)))
    assert path.read_bytes() == payload and seen[-1] == (len(payload), len(payload))
    bad = deps.Installer("git", "evil.exe", f"{base}/setup.exe", "0" * 64)
    with pytest.raises(deps.DependencyError, match="checksum"):
        deps.download(bad, tmp_path / "dl")
    assert not list((tmp_path / "dl").glob("evil.exe*"))


def test_install_git_unpacks_into_the_tools_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local app data"))  # a path with spaces
    commands = []

    def fake_run(command, timeout):
        commands.append(command)
        git = deps.portable_git_dir() / "cmd" / "git.exe"
        git.parent.mkdir(parents=True)
        git.write_bytes(b"")
        return SimpleNamespace(returncode=0)

    git = deps.install_git(Path("C:/downloads/PortableGit.7z.exe"), run=fake_run)
    assert git.endswith("git.exe") and "local app data" in git
    assert commands[0].endswith(f'-o"{deps.portable_git_dir()}" -y')
    monkeypatch.setattr(deps, "_which", lambda *_a: None)
    assert deps.find_git() == git  # used when no installed Git is found


def test_install_miktex_runs_unattended_for_this_user_only():
    calls = []
    deps.install_miktex(Path("basic-miktex.exe"), run=lambda cmd, timeout: calls.append(cmd) or
                        SimpleNamespace(returncode=0))
    assert calls[0][1:] == ["--unattended", "--private", "--auto-install=yes"]
    with pytest.raises(deps.DependencyError, match="exit code 1"):
        deps.install_miktex(Path("x.exe"), run=lambda cmd, timeout: SimpleNamespace(returncode=1))


def test_every_paper_gets_local_only_data_and_supplementary_folders(tmp_path):
    empty = tmp_path / "about-to-be-cloned"
    empty.mkdir()
    assert not ensure_local_folders(empty) and not any(empty.iterdir())  # never block a clone
    root = tmp_path / "paper"
    repo = Repo.init(root)
    (root / "main.tex").write_text("x", encoding="utf-8")
    repo.git.add("-A")
    repo.git.commit("-m", "start", "--author", "T <t@x>", env={"GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x"})
    assert ensure_local_folders(root) == ["data", "supplementary"]
    assert (root / "data" / "README.md").is_file() and (root / "supplementary" / "README.md").is_file()
    (root / "data" / "measurements.csv").write_text("1,2", encoding="utf-8")
    (root / "supplementary" / "demo.mp4").write_bytes(b"0" * 100)   # large extras stay here
    assert not repo.is_dirty(untracked_files=True)  # invisible to Git: never committed or synced
    assert not (root / ".gitignore").exists()        # nothing added to the Overleaf project
    assert not ensure_local_folders(root)            # idempotent
    exclude = (root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.count("/data/") == 1 and exclude.count("/supplementary/") == 1


def test_install_git_refuses_a_too_long_folder_and_cleans_up_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / ("x" * 170)))
    with pytest.raises(deps.DependencyError, match="too long"):
        deps.install_git(Path("PortableGit.7z.exe"), run=lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "short"))

    def half_unpacked(command, timeout):  # what the self-extractor leaves behind when it fails
        (deps.portable_git_dir() / "usr").mkdir(parents=True)
        return SimpleNamespace(returncode=1)

    with pytest.raises(deps.DependencyError, match="exit 1"):
        deps.install_git(Path("PortableGit.7z.exe"), run=half_unpacked)
    assert not deps.portable_git_dir().exists()  # "Try again" starts from a clean folder
