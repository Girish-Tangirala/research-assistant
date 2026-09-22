"""Git and MiKTeX: detect them and, if missing, install them without any manual steps.

* **Git** - the official *PortableGit* of Git for Windows is unpacked into the app's own
  tools folder (``%LOCALAPPDATA%\\ResearchAssistant\\tools\\PortableGit``). No administrator
  rights, no installer, nothing changed elsewhere on the computer.
* **MiKTeX** - the official basic installer runs unattended for the current user only
  (``--unattended --private --auto-install=yes``), which also needs no administrator rights.

Both installers are the latest official releases, found at run time (GitHub's release API
for Git, miktex.org/download for MiKTeX), and each download must match the SHA-256 the
publisher lists before it is run.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from config import _which

GIT_RELEASE_API = "https://api.github.com/repos/git-for-windows/git/releases/latest"
MIKTEX_PAGE = "https://miktex.org/download"
MIKTEX_BASE = "https://miktex.org"
USER_AGENT = "ResearchAssistant-setup (+https://miktex.org, +https://gitforwindows.org)"
CHUNK = 1 << 16
MAX_PATH = 259
PORTABLE_GIT_DEPTH = 100  # longest file path inside PortableGit 2.55, relative to its folder: 86 characters
Progress = Callable[[int, int], None]  # (bytes done, bytes total or 0)


class DependencyError(RuntimeError):
    """A tool could not be found, downloaded, verified or installed."""


@dataclass(frozen=True)
class Installer:
    tool: str          # "git" or "miktex"
    file_name: str
    url: str
    sha256: str
    size: int = 0


def tools_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ResearchAssistant" / "tools"


def portable_git_dir() -> Path:
    return tools_dir() / "PortableGit"


def find_git() -> str | None:
    """git.exe: an installed Git (PATH, also installed after start) or our PortableGit."""
    found = _which("GIT_PATH", "git")
    if found:
        return found
    portable = portable_git_dir() / "cmd" / "git.exe"
    return str(portable) if portable.is_file() else None


def find_latex() -> str | None:
    return _which("PDFLATEX_PATH", "pdflatex")


def missing_tools() -> list[str]:
    """``["git", "miktex"]`` minus what is already there."""
    return [tool for tool, found in (("git", find_git()), ("miktex", find_latex())) if not found]


# ---------------------------------------------------------------------- #
# Finding the current official installers
# ---------------------------------------------------------------------- #
def _get(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URLs
        return response.read()


def git_installer(release: dict | None = None) -> Installer:
    """The PortableGit of the latest Git for Windows release, with its published SHA-256."""
    release = release if release is not None else json.loads(_get(GIT_RELEASE_API))
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "64-bit"
    pattern = re.compile(rf"^PortableGit-[\d.]+-{re.escape(arch)}\.7z\.exe$")
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if not pattern.match(name):
            continue
        digest = str(asset.get("digest") or "")
        sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
        if not sha:  # older API responses: the release notes carry a "file | sha256" table
            row = re.search(rf"{re.escape(name)}\s*\|\s*([0-9a-fA-F]{{64}})", release.get("body") or "")
            sha = row.group(1) if row else ""
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            raise DependencyError(f"No published checksum for {name} - not downloading it.")
        return Installer("git", name, asset["browser_download_url"], sha.lower(), int(asset.get("size") or 0))
    raise DependencyError(f"The latest Git for Windows release has no PortableGit for {arch}.")


def miktex_installer(page: str | None = None) -> Installer:
    """The Windows basic installer listed on miktex.org/download, with its SHA-256."""
    page = page if page is not None else _get(MIKTEX_PAGE).decode("utf-8", "replace")
    link = re.search(r"""href=['"]([^'"]*/(basic-miktex-[\d.]+-x64\.exe))['"]""", page)
    if not link:
        raise DependencyError("The MiKTeX download page has changed - install MiKTeX from "
                              f"{MIKTEX_PAGE} instead.")
    path, name = link.group(1), link.group(2)
    after_name = page[page.find(name):]
    sha = re.search(r"SHA-256:.*?([0-9a-fA-F]{64})", after_name, re.S)
    if not sha:
        raise DependencyError(f"No published checksum for {name} - not downloading it.")
    url = path if path.startswith("http") else MIKTEX_BASE + path
    return Installer("miktex", name, url, sha.group(1).lower())


# ---------------------------------------------------------------------- #
# Download, verify, install
# ---------------------------------------------------------------------- #
def download(installer: Installer, folder: Path, progress: Progress | None = None,
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Download to ``folder`` and check the SHA-256; a mismatching file is deleted, never run."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / installer.file_name
    if target.is_file() and _sha256(target) == installer.sha256:
        return target  # already downloaded earlier
    partial = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(installer.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:  # noqa: S310
        total = int(response.headers.get("Content-Length") or installer.size or 0)
        done = 0
        while chunk := response.read(CHUNK):
            if cancelled():
                out.close()
                partial.unlink(missing_ok=True)
                raise DependencyError("Download cancelled.")
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if digest.hexdigest() != installer.sha256:
        partial.unlink(missing_ok=True)
        raise DependencyError(f"{installer.file_name} does not match its published checksum - it was deleted "
                              "and not run. Try again later.")
    partial.replace(target)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def install_git(archive: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """Unpack PortableGit (a 7-Zip self-extractor: ``-o<folder> -y``); return the path of git.exe."""
    target = portable_git_dir()
    if len(str(target)) + PORTABLE_GIT_DEPTH > MAX_PATH:
        # The self-extractor stops half-way (exit 1) when a file path passes Windows' 260-character limit.
        raise DependencyError(f"The folder {target} has too long a path for Git's files.")
    shutil.rmtree(target, ignore_errors=True)  # a half-unpacked earlier attempt
    target.parent.mkdir(parents=True, exist_ok=True)
    # One command-line string: the self-extractor parses -o"<folder>" itself (paths may contain spaces).
    result = run(f'"{archive}" -o"{target}" -y', timeout=900)
    git = target / "cmd" / "git.exe"
    if result.returncode != 0 or not git.is_file():
        shutil.rmtree(target, ignore_errors=True)
        raise DependencyError(f"Unpacking Git failed (exit {result.returncode}).")
    return str(git)


def install_miktex(installer_exe: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    """Run the MiKTeX basic installer for this user only, without questions."""
    result = run([str(installer_exe), "--unattended", "--private", "--auto-install=yes"], timeout=3600)
    if result.returncode != 0:
        raise DependencyError(f"The MiKTeX installer stopped with exit code {result.returncode}.")


def download_folder() -> Path:
    return tools_dir() / "downloads"
