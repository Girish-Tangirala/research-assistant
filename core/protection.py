"""Read-only file protection (e.g. Zotero/Mendeley-linked .bib files).

Overleaf's reference-manager integrations create ``.bib`` files that Overleaf
overwrites on every *Refresh*, so edits pushed through Git would silently be
lost. Nothing in the cloned file marks it as linked, so protection combines:

* explicit per-paper patterns (``refs/zotero.bib``, ``*.bib`` …), and
* auto-detection of files that look reference-manager generated (file name or
  header mentions a manager, or citation keys follow Zotero's
  ``author_title_year`` scheme).

The agent may read protected files but never stage or write them.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.project_layout import PROTECTED_FOLDERS

# Most specific first: Better BibTeX headers also mention Zotero.
MANAGER_NAMES = {"better bibtex": "Zotero (Better BibTeX)", "zotero": "Zotero", "mendeley": "Mendeley",
                 "readcube": "ReadCube", "jabref": "JabRef", "paperpile": "Paperpile"}
ZOTERO_KEY_RE = re.compile(r"^[a-z]+(?:-[a-z]+)?_[a-z0-9]+_\d{4}[a-z]?$")
ENTRY_KEY_RE = re.compile(r"@\s*(?!comment|preamble|string)[a-zA-Z]+\s*[{(]\s*([^,\s]+)\s*,", re.I)
MIN_ENTRIES_FOR_KEY_HEURISTIC = 5
SHARED_TODO_FILE = "todo.md"  # maintained by core.todos, never by the agent
FOLDER_REASONS = {name: f"the {name}/ folder is yours - the assistant only writes the manuscript"
                  for name in PROTECTED_FOLDERS}


def parse_patterns(text: str) -> list[str]:
    """Split a comma/newline separated pattern list."""
    return [p.strip().replace("\\", "/") for p in re.split(r"[,\n;]", text or "") if p.strip()]


def detect_reference_manager_bib(path: Path) -> str | None:
    """Return why ``path`` looks reference-manager generated, or ``None``."""
    lowered_name = path.name.lower()
    for hint, manager in MANAGER_NAMES.items():
        if hint.replace(" ", "") in lowered_name:
            return f"file name suggests {manager}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    head = text[:4096].lower()
    for hint, manager in MANAGER_NAMES.items():
        if hint in head:
            return f"file header mentions {manager}"
    keys = ENTRY_KEY_RE.findall(text)
    if len(keys) >= MIN_ENTRIES_FOR_KEY_HEURISTIC:
        zotero_like = sum(bool(ZOTERO_KEY_RE.match(k)) for k in keys)
        if zotero_like / len(keys) >= 0.8:
            return "citation keys follow Zotero's author_title_year pattern"
    return None


def detect_reference_manager_bibs(root: Path) -> dict[str, str]:
    """Map repo-relative .bib paths to detection reasons."""
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*.bib")):
        if ".git" in path.parts or not path.is_file():
            continue
        reason = detect_reference_manager_bib(path)
        if reason:
            found[path.relative_to(root).as_posix()] = reason
    return found


@dataclass
class ProtectionPolicy:
    """Decides which repo-relative files the agent must not modify."""

    root: Path
    patterns: list[str] = field(default_factory=list)
    auto_detect: bool = True
    detected: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, root: Path, patterns: str, auto_detect: bool) -> "ProtectionPolicy":
        detected = detect_reference_manager_bibs(root) if auto_detect else {}
        return cls(root=root, patterns=parse_patterns(patterns), auto_detect=auto_detect, detected=detected)

    def reason(self, rel_path: str) -> str | None:
        """Why ``rel_path`` is read-only, or ``None`` if it may be edited."""
        rel = rel_path.replace("\\", "/").removeprefix("./")
        if rel == SHARED_TODO_FILE:
            return "shared to-do list - change it in the app's To-Do tab"
        top = rel.split("/", 1)[0]
        if "/" in rel and top in FOLDER_REASONS:
            return FOLDER_REASONS[top]
        for pattern in self.patterns:
            if fnmatch.fnmatch(rel, pattern) or ("/" not in pattern and fnmatch.fnmatch(Path(rel).name, pattern)):
                return f"listed as read-only ({pattern})"
        if rel in self.detected:
            return f"auto-detected: {self.detected[rel]}"
        return None

    def protected_files(self) -> dict[str, str]:
        """All existing files currently protected, with reasons."""
        result = dict((k, f"auto-detected: {v}") for k, v in self.detected.items())
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if ".git" in path.parts or not path.is_file():
                    continue
                rel = path.relative_to(self.root).as_posix()
                reason = self.reason(rel)
                # whole folders and the to-do list are enforced but not listed file by file
                if reason and rel not in result and rel != SHARED_TODO_FILE \
                        and rel.split("/", 1)[0] not in FOLDER_REASONS:
                    result[rel] = reason
        return dict(sorted(result.items()))

    def describe(self) -> str:
        files = self.protected_files()
        if not files:
            return "No read-only files."
        return "Read-only files: " + "; ".join(f"{k} ({v})" for k, v in files.items())


def read_only_message(rel_path: str, reason: str) -> str:
    message = f"{rel_path} is read-only - {reason}."
    if rel_path.lower().endswith(".bib"):
        message += (" Reference-manager .bib files are overwritten when Overleaf refreshes them: change the "
                    "reference in Zotero/Mendeley, then click Refresh on the file in Overleaf.")
    return message
