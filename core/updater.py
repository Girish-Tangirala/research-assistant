"""Updates: find a newer release on GitHub and replace the installed app with it.

A release is published by ``scripts/release.py`` as the GitHub release ``v<version>`` of
``version.UPDATE_REPO``, with the app zip (``ResearchAssistant-windows-<version>.zip``)
attached. The installed app:

1. asks GitHub for the latest release (anonymous; the repository is public),
2. downloads the zip next to its own folder and checks it against the SHA-256 digest
   GitHub computed for the uploaded file,
3. unpacks it beside the running app (``<app>.new``),
4. starts a small script and quits; the script waits for the app to exit, swaps the
   folders (keeping the old one until the new one is in place), starts the new version
   and deletes the old folder. If a step fails, the old version is put back and started.

Settings, papers and sign-ins are not in the app folder, so they are kept.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.dependencies import DependencyError, Installer, Progress, _get, download
from core.proc import NO_WINDOW

logger = logging.getLogger("research_agent")
APP_EXE = "ResearchAssistant.exe"
ASSET_RE = re.compile(r"^ResearchAssistant-windows-[\w.\-]+\.zip$")


class UpdateError(RuntimeError):
    """An update could not be found, downloaded, checked or installed."""


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    page: str
    asset: Installer


def parse_version(text: str) -> tuple[int, ...]:
    """``"v1.10.2"`` -> ``(1, 10, 2)``; anything that is not a version -> ``()``."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    width = max(len(new), len(old))
    return bool(new) and new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def latest_release(repo: str, release: dict | None = None) -> Release:
    """The newest published release of ``repo`` and its app zip (with GitHub's SHA-256)."""
    if release is None:
        try:
            release = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=15))
        except OSError as exc:
            raise UpdateError(f"Could not reach GitHub to check for updates ({exc}).") from exc
    version = str(release.get("tag_name", "")).lstrip("v")
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        digest = str(asset.get("digest") or "")
        if ASSET_RE.match(name):
            if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                raise UpdateError(f"Release {version} has no checksum for {name} - not installing it.")
            installer = Installer("app", name, asset["browser_download_url"], digest[7:].lower(),
                                  int(asset.get("size") or 0))
            return Release(version, (release.get("body") or "").strip(), release.get("html_url", ""), installer)
    raise UpdateError(f"Release {version} has no Windows app attached.")


def check(current: str, repo: str) -> Release | None:
    """The latest release if it is newer than ``current``, else ``None``."""
    release = latest_release(repo)
    return release if is_newer(release.version, current) else None


# ---------------------------------------------------------------------- #
# Installing
# ---------------------------------------------------------------------- #
def running_app_dir() -> Path | None:
    """Folder of the packaged app; ``None`` when running from source (update with Git instead)."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def stage(release: Release, app_dir: Path, progress: Progress | None = None,
          cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Download and unpack the new version beside ``app_dir``; return the folder ready to swap in."""
    parent = app_dir.parent
    if not os.access(parent, os.W_OK):
        raise UpdateError(f"The app's folder {parent} is not writable - move the Research Assistant folder "
                          "to e.g. Documents and update again.")
    started = time.monotonic()
    logger.info("Update %s: downloading %s", release.version, release.asset.url)
    try:
        archive = download(release.asset, parent / f".{app_dir.name}-download", progress, cancelled)
    except DependencyError as exc:
        raise UpdateError(str(exc)) from exc
    logger.info("Update %s: downloaded and checked in %.1f s", release.version, time.monotonic() - started)
    staged = parent / f"{app_dir.name}.new"
    shutil.rmtree(staged, ignore_errors=True)
    unpack = parent / f".{app_dir.name}-unpack"
    shutil.rmtree(unpack, ignore_errors=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():  # never write outside the unpack folder
            target = (unpack / member).resolve()
            if not target.is_relative_to(unpack.resolve()):
                raise UpdateError(f"Unexpected file in the update: {member}")
        bundle.extractall(unpack)
    inner = next((p.parent for p in unpack.rglob(APP_EXE)), None)
    if inner is None:
        raise UpdateError(f"The update does not contain {APP_EXE}.")
    inner.rename(staged)
    shutil.rmtree(unpack, ignore_errors=True)
    shutil.rmtree(archive.parent, ignore_errors=True)
    logger.info("Update %s: unpacked to %s after %.1f s", release.version, staged, time.monotonic() - started)
    return staged


def _cmd_quote(path: Path) -> str:
    return str(path).replace("%", "%%")


def swap_script(app_dir: Path, staged: Path, pid: int, exe: str = APP_EXE, args: str = "") -> str:
    """A batch script: wait for ``pid`` to exit, swap the folders, start the new version.

    If the old folder cannot be moved (a file still in use), or the new one cannot take its
    place, the old version stays or is put back, and it is started again.
    """
    old = app_dir.with_name(f"{app_dir.name}.old")
    # /D: the new version starts in its own folder, as when it is double-clicked.
    launch = f'start "" /D "%APP%" /B "%APP%\\{exe}" {args}'.rstrip()
    # Plain labels and gotos (no ( ) blocks, no delayed expansion), so any folder name works.
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",  # the file is UTF-8: folder names like C:\Users\Jürgen stay intact
        # Never work from inside the app folder: Windows cannot move a folder that is some
        # process's current directory (a double-clicked app starts in its own folder).
        'cd /d "%~dp0"',
        f'set "APP={_cmd_quote(app_dir)}"',
        f'set "NEW={_cmd_quote(staged)}"',
        f'set "OLD={_cmd_quote(old)}"',
        ":wait",
        # Full paths: Git can put Unix tools named find/ping earlier on PATH.
        f'"%SystemRoot%\\System32\\tasklist.exe" /FI "PID eq {pid}" 2>nul'
        f' | "%SystemRoot%\\System32\\find.exe" " {pid} " >nul',
        "if errorlevel 1 goto gone",
        '"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1 >nul',
        "goto wait",
        ":gone",
        'if exist "%OLD%" rmdir /s /q "%OLD%"',
        "set /a tries=0",
        ":swap",
        'move "%APP%" "%OLD%" >nul 2>&1',
        "if not errorlevel 1 goto moved",
        "set /a tries+=1",
        "if %tries% geq 30 goto keep_old",
        '"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1 >nul',
        "goto swap",
        ":keep_old",
        launch,
        "exit /b 1",
        ":moved",
        'move "%NEW%" "%APP%" >nul 2>&1',
        "if not errorlevel 1 goto done",
        'move "%OLD%" "%APP%" >nul 2>&1',
        launch,
        "exit /b 2",
        ":done",
        launch,
        'rmdir /s /q "%OLD%"',
        "exit /b 0",
        "",
    ])


def launch_swap(app_dir: Path, staged: Path, script_dir: Path) -> None:
    """Write and start the swap script (hidden); the caller must quit the app right after."""
    script_dir.mkdir(parents=True, exist_ok=True)
    script = script_dir / "apply-update.cmd"
    script.write_text(swap_script(app_dir, staged, os.getpid()), encoding="utf-8")
    subprocess.Popen(["cmd.exe", "/c", str(script)], cwd=script_dir,  # noqa: S603 - our own script
                     creationflags=NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
