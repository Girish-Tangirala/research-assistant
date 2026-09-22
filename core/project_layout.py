"""The folder layout of a new local paper.

A paper is an ordinary folder on this computer with its own Git repository. It
is laid out so Overleaf can compile it unchanged (``main.tex`` in the root,
images found through ``\\graphicspath``), while the working material lives in
named folders:

===============  =========================================================
manuscript/      the text, one ``.tex`` file per section
figures/         images used in the paper
bibliography/    ``.bib`` files
code/            scripts that produce the results
notes/           working notes, drafts, meeting notes
data/            datasets - **local only**, listed in ``.gitignore``
===============  =========================================================

Everything except ``data/`` is committed, so it travels to Overleaf when the
paper is synced. ``data/`` and ``code/`` are never written by the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAIN_TEX = "main.tex"
SECTIONS = ("introduction", "method", "results", "discussion")
BIB_FILE = "bibliography/references.bib"


@dataclass(frozen=True)
class Folder:
    name: str
    purpose: str
    synced: bool = True       # sent to Overleaf
    agent_writable: bool = True


FOLDERS: tuple[Folder, ...] = (
    Folder("manuscript", "the text of the paper, one file per section"),
    Folder("figures", "images used in the paper"),
    Folder("bibliography", "BibTeX files"),
    Folder("code", "scripts that produce the results", agent_writable=False),
    Folder("notes", "working notes, drafts, meeting notes"),
    Folder("data", "datasets - kept on this computer only", synced=False, agent_writable=False),
)
LOCAL_ONLY = tuple(f.name for f in FOLDERS if not f.synced)
PROTECTED_FOLDERS = tuple(f.name for f in FOLDERS if not f.agent_writable)

GITIGNORE = """\
# Folders kept on this computer only (never sent to Overleaf)
{local_only}
# LaTeX build files
*.aux
*.bbl
*.blg
*.fdb_latexmk
*.fls
*.lof
*.log
*.lot
*.nav
*.out
*.snm
*.synctex.gz
*.toc
*.vrb

# Editors and operating systems
.DS_Store
Thumbs.db
__pycache__/
*.pyc
"""

MAIN_TEMPLATE = r"""\documentclass[11pt]{article}

\usepackage[T1]{fontenc}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{booktabs}
\usepackage{natbib}
\usepackage[hidelinks]{hyperref}

\graphicspath{{figures/}}

\title{%(title)s}
\author{%(author)s}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
Write the abstract here.
\end{abstract}

%(inputs)s

\bibliographystyle{plainnat}
\bibliography{bibliography/references}

\end{document}
"""

SECTION_TEMPLATE = "\\section{%(title)s}\n\\label{sec:%(label)s}\n\n%(hint)s\n"
SECTION_HINTS = {
    "introduction": "Write the introduction here.",
    "method": "Describe the method here.",
    "results": "Report the results here.",
    "discussion": "Discuss the results here.",
}
BIB_TEMPLATE = ("% References for this paper.\n"
                "% The app adds entries here (Add References); you can also paste your own.\n")

README_TEMPLATE = """\
# %(title)s

This folder is the whole paper: text, figures, bibliography, code and notes. It is a
Git repository, so every change is kept, and it compiles in Overleaf as it is.

| Folder | What goes in it |
|---|---|
%(rows)s

`main.tex` in this folder is the document Overleaf compiles; it pulls in the files in
`manuscript/`.

**Syncing:** `data/` stays on this computer (it is listed in `.gitignore`). Everything
else is sent to Overleaf when you press **Sync with Overleaf** in the app.
"""


def folder_rows() -> str:
    extra = {"data": " (stays on this computer)", "code": " (the assistant never edits it)"}
    return "\n".join(f"| `{f.name}/` | {f.purpose}{extra.get(f.name, '')} |" for f in FOLDERS)


def gitignore_text() -> str:
    return GITIGNORE.format(local_only="".join(f"{name}/\n" for name in LOCAL_ONLY))


def section_title(name: str) -> str:
    return name.capitalize()


def scaffold(root: Path, title: str, author: str = "") -> list[str]:
    """Create the folder structure and starter files in ``root``.

    Existing files are never overwritten.

    Returns:
        The repo-relative paths that were created (POSIX, sorted).
    """
    created: list[str] = []

    def write(rel: str, text: str) -> None:
        path = root / rel
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        created.append(rel)

    root.mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS:
        (root / folder.name).mkdir(exist_ok=True)
    inputs = "\n".join(f"\\input{{manuscript/{name}}}" for name in SECTIONS)
    write(MAIN_TEX, MAIN_TEMPLATE % {"title": title or "Untitled paper",
                                     "author": author or "Author", "inputs": inputs})
    for name in SECTIONS:
        write(f"manuscript/{name}.tex", SECTION_TEMPLATE % {
            "title": section_title(name), "label": name, "hint": SECTION_HINTS[name]})
    write(BIB_FILE, BIB_TEMPLATE)
    write("figures/.gitkeep", "")
    write(".gitignore", gitignore_text())
    write("README.md", README_TEMPLATE % {"title": title or "Untitled paper", "rows": folder_rows()})
    for folder in FOLDERS:
        if folder.name == "data":
            write("data/README.md", DATA_README)
        elif folder.name not in ("manuscript", "figures", "bibliography"):
            write(f"{folder.name}/README.md", f"# {folder.name}\n\n{folder.purpose.capitalize()}.\n")
    return sorted(created)


DATA_README = """# data

Put the datasets of this paper here (copy them in with Explorer - the **Folder** button opens this paper).

This folder stays on this computer: it is never committed, never sent to Overleaf and never
changed by the assistant.
"""
EXCLUDE_ENTRY = "/data/"


def ensure_data_folder(root: Path) -> bool:
    """Give every paper a local-only ``data/`` folder - also papers cloned from Overleaf.

    Git is told to ignore it through ``.git/info/exclude``, which (unlike ``.gitignore``)
    is private to this computer, so nothing is added to the Overleaf project.

    Only folders that already hold a paper (a Git repository) are touched, so a folder
    that is about to be cloned into stays empty.

    Returns:
        ``True`` if the folder was created now.
    """
    if not (root / ".git").is_dir():
        return False
    data = root / "data"
    created = not data.exists()
    data.mkdir(exist_ok=True)
    readme = data / "README.md"
    if not readme.exists():
        readme.write_text(DATA_README, encoding="utf-8", newline="\n")
    info = root / ".git" / "info"
    exclude = info / "exclude"
    text = exclude.read_text(encoding="utf-8", errors="replace") if exclude.exists() else ""
    if not any(line.strip() in ("data/", "/data/", "/data") for line in text.splitlines()):
        info.mkdir(parents=True, exist_ok=True)
        prefix = "" if not text or text.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{prefix}# Research Assistant: datasets stay on this computer\n{EXCLUDE_ENTRY}\n")
    return created


def looks_scaffolded(root: Path) -> bool:
    """Was this folder created with :func:`scaffold` (or does it follow the same layout)?"""
    return (root / MAIN_TEX).is_file() and (root / "manuscript").is_dir()


def present_folders(root: Path) -> list[str]:
    return [f.name for f in FOLDERS if (root / f.name).is_dir()]
