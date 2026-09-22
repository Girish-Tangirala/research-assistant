"""Updates from GitHub releases: version checks, staging the new version, swapping the folders."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from core import updater
from core.dependencies import Installer
from tests.test_dependencies import file_server  # noqa: F401 - fixture

SHA = "ab" * 32


def release_json(tag="v1.2.0", name="ResearchAssistant-windows-1.2.0.zip", digest=f"sha256:{SHA}"):
    return {"tag_name": tag, "body": "What's new", "html_url": "https://github.com/o/r/releases/tag/" + tag,
            "assets": [{"name": "ResearchAssistant-source-1.2.0.zip", "digest": f"sha256:{SHA}",
                        "browser_download_url": "https://x/source.zip"},
                       {"name": name, "digest": digest, "size": 10, "browser_download_url": "https://x/app.zip"}]}


def test_versions_compare_numerically():
    assert updater.is_newer("1.10.0", "1.9.3") and updater.is_newer("v2", "1.99")
    assert not updater.is_newer("1.0", "1.0.0") and not updater.is_newer("1.0.0", "1.0.1")
    assert not updater.is_newer("latest", "1.0.0")


def test_latest_release_picks_the_app_zip_and_needs_githubs_checksum():
    release = updater.latest_release("o/r", release_json())
    assert release.version == "1.2.0" and release.asset.url == "https://x/app.zip" and release.asset.sha256 == SHA
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.latest_release("o/r", release_json(digest=None))
    with pytest.raises(updater.UpdateError, match="no Windows app"):
        updater.latest_release("o/r", release_json(name="something-else.zip"))


def make_app(folder: Path, marker: str) -> None:
    folder.mkdir(parents=True)
    # Stand-in for the app: a copy of cmd.exe, which runs from any folder.
    shutil.copy2(Path(r"C:\Windows\System32\cmd.exe"), folder / "ResearchAssistant.exe")
    (folder / "_internal").mkdir()
    (folder / "_internal" / "version.txt").write_text(marker, encoding="utf-8")


def test_stage_unpacks_the_new_version_beside_the_app(tmp_path, file_server):  # noqa: F811
    served, base = file_server
    new = tmp_path / "build" / "ResearchAssistant"
    make_app(new, "new")
    archive = served / "ResearchAssistant-windows-1.2.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in new.rglob("*"):
            bundle.write(path, Path("ResearchAssistant") / path.relative_to(new))
    asset = Installer("app", archive.name, f"{base}/{archive.name}", hashlib.sha256(archive.read_bytes()).hexdigest())
    app = tmp_path / "apps" / "ResearchAssistant"
    make_app(app, "old")
    staged = updater.stage(updater.Release("1.2.0", "", "", asset), app)
    assert staged == app.with_name("ResearchAssistant.new")
    assert (staged / "_internal" / "version.txt").read_text(encoding="utf-8") == "new"
    assert sorted(p.name for p in app.parent.iterdir()) == ["ResearchAssistant", "ResearchAssistant.new"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch script")
def test_swap_script_replaces_the_app_after_it_exits(tmp_path):
    base = tmp_path / "Müller & Co! 100%"  # characters that break naive batch scripts
    app, staged = base / "ResearchAssistant", base / "ResearchAssistant.new"
    make_app(app, "old")
    make_app(staged, "new")
    (app / "papers-are-not-here.txt").write_text("the old folder goes away", encoding="utf-8")
    script = tmp_path / "apply-update.cmd"
    # PID 999999 is not running, so the script goes straight on; the new "app" records that it started.
    script.write_text(updater.swap_script(app, staged, 999_999, args='/c "echo yes> started.txt"'),
                      encoding="utf-8")
    result = subprocess.run(["cmd.exe", "/c", str(script)], cwd=base, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (app / "_internal" / "version.txt").read_text(encoding="utf-8") == "new"
    assert not staged.exists() and not app.with_name("ResearchAssistant.old").exists()
    assert not (app / "papers-are-not-here.txt").exists()
    for _ in range(50):  # "start /B" returns at once; give the new app a moment
        if (base / "started.txt").exists():
            break
        time.sleep(0.1)
    assert (base / "started.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch script")
def test_swap_script_keeps_the_old_version_if_the_new_one_is_missing(tmp_path):
    app, staged = tmp_path / "ResearchAssistant", tmp_path / "ResearchAssistant.new"
    make_app(app, "old")  # no staged folder: the second move fails
    script = tmp_path / "apply-update.cmd"
    script.write_text(updater.swap_script(app, staged, 999_999, args="/c exit"), encoding="utf-8")
    result = subprocess.run(["cmd.exe", "/c", str(script)], capture_output=True, timeout=120)
    assert result.returncode == 2
    assert (app / "_internal" / "version.txt").read_text(encoding="utf-8") == "old"  # put back


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch script")
def test_swap_script_waits_until_the_running_app_has_quit(tmp_path):
    app, staged = tmp_path / "ResearchAssistant", tmp_path / "ResearchAssistant.new"
    make_app(app, "old")
    make_app(staged, "new")
    running = subprocess.Popen(["ping", "-n", "4", "127.0.0.1"], stdout=subprocess.DEVNULL)  # "the app", ~3 s
    script = tmp_path / "apply-update.cmd"
    script.write_text(updater.swap_script(app, staged, running.pid, args="/c exit"), encoding="utf-8")
    started = time.time()
    result = subprocess.run(["cmd.exe", "/c", str(script)], capture_output=True, timeout=120)
    assert result.returncode == 0 and running.poll() is not None
    assert time.time() - started > 2  # it waited for the process instead of swapping under it
    assert (app / "_internal" / "version.txt").read_text(encoding="utf-8") == "new"
