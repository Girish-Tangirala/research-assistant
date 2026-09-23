"""What OneDrive actually syncs on this computer.

The backup copies files into a folder and lets the OneDrive client upload them, so
the one thing that can silently go wrong is choosing a folder OneDrive does not
watch. OneDrive records every sync root in the registry, which is a far better
answer than guessing from the folder name:

``HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\<account>``
    ``UserFolder``                      the account's OneDrive folder
    ``ScopeIdToMountPointPathMapping``  one value per synced SharePoint library

Reading the registry is separated from deciding, so the decision can be tested
without depending on this machine's OneDrive.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.proc import NO_WINDOW

ACCOUNTS_KEY = r"Software\Microsoft\OneDrive\Accounts"


def _as_path(value: object) -> Path | None:
    """Registry paths can hold unexpanded variables (``%UserProfile%\\OneDrive``)."""
    text = os.path.expandvars(str(value or "")).strip()
    return Path(text) if text and "%" not in text else None


def sync_roots() -> list[Path]:
    """Every folder OneDrive syncs for the signed-in accounts (empty off Windows)."""
    if sys.platform != "win32":
        return []
    import winreg

    roots: list[Path] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ACCOUNTS_KEY) as accounts:
            for index in range(winreg.QueryInfoKey(accounts)[0]):
                try:
                    with winreg.OpenKey(accounts, winreg.EnumKey(accounts, index)) as account:
                        roots.extend(_account_roots(winreg, account))
                except OSError:
                    continue
    except OSError:
        return []                      # OneDrive has never run for this user
    return roots


def _account_roots(winreg, account) -> list[Path]:
    """The OneDrive folder plus every synced SharePoint library of one account."""
    found: list[Path] = []
    try:
        folder = _as_path(winreg.QueryValueEx(account, "UserFolder")[0])
        if folder:
            found.append(folder)
    except OSError:
        pass
    try:
        with winreg.OpenKey(account, "ScopeIdToMountPointPathMapping") as scopes:
            for index in range(winreg.QueryInfoKey(scopes)[1]):
                folder = _as_path(winreg.EnumValue(scopes, index)[1])
                if folder:
                    found.append(folder)
    except OSError:
        pass
    return found


def covering_root(folder: Path, roots: list[Path]) -> Path | None:
    """The sync root that contains ``folder`` (the folder itself counts), or ``None``."""
    try:
        target = Path(folder).expanduser().resolve()
    except OSError:
        return None
    for root in roots:
        try:
            resolved = Path(root).expanduser().resolve()
        except OSError:
            continue
        if target == resolved or resolved in target.parents:
            return resolved
    return None


def is_running() -> bool:
    """Is the OneDrive client running? (It uploads nothing while closed.)"""
    if sys.platform != "win32":
        return True
    try:
        proc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OneDrive.exe", "/NH"],
                              capture_output=True, text=True, timeout=15,
                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return True                    # cannot tell - do not cry wolf
    return "onedrive.exe" in proc.stdout.lower()


def folder_problem(folder: Path) -> str | None:
    """Why files copied into ``folder`` might never reach SharePoint (``None`` = fine).

    Returns a warning, never a refusal: OneDrive can be configured in ways this
    cannot see, and the user may know better.
    """
    roots = sync_roots()
    if not roots:
        return ("OneDrive does not seem to be set up on this computer, so files copied there may never "
                "reach SharePoint.")
    if covering_root(folder, roots) is None:
        listed = "\n".join(f"  • {root}" for root in dict.fromkeys(str(r) for r in roots))
        return (f"{folder}\n\nis not inside a folder OneDrive syncs, so files copied there would stay on "
                f"this computer. OneDrive syncs:\n{listed}")
    if not is_running():
        return ("OneDrive is not running, so the files will sit in the folder until you start it. "
                "They upload by themselves once it runs again.")
    return None
