"""Organise an existing paper into the standard folders.

Files that are already in the repository are sorted into ``manuscript/``,
``figures/``, ``bibliography/``, ``code/``, ``notes/``, ``data/`` and
``supplementary/`` (see :mod:`core.project_layout`; the last two stay on this
computer), and every ``\\input``, ``\\includegraphics``,
``\\bibliography`` and ``\\addbibresource`` that points at a moved file is
rewritten. Class and style files and read-only (reference-manager) files stay where
they are. A paper written as a single .tex file moves into ``manuscript/`` and a one-line
pointer stays on top, and every paper gets a ``code/`` folder.

The result is a plan; the workflow turns it into one move change plus one diff
per rewritten ``.tex`` file, so the author approves it like any other edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.latex_parser import comment_mask, strip_comments
from core.project_layout import FOLDERS, LOCAL_ONLY

# Extension -> target folder.
TEX_EXTS = {".tex"}
FIGURE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".tif", ".tiff", ".gif", ".bmp", ".svg", ".webp"}
BIB_EXTS = {".bib"}
CODE_EXTS = {".py", ".ipynb", ".m", ".r", ".jl", ".c", ".cpp", ".h", ".hpp", ".sh", ".ps1", ".sql"}
DATA_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".mat", ".h5", ".hdf5", ".npy", ".npz", ".dat", ".parquet"}
NOTE_EXTS = {".md", ".txt", ".rst", ".docx", ".odt"}
# Big extras that belong to the work but not into the PDF; kept on this computer only.
SUPPLEMENTARY_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".wav", ".mp3", ".zip", ".7z",
                      ".tar", ".gz", ".rar"}
# Never moved: LaTeX looks for these next to the root document, or they are the app's own files.
KEEP_AT_ROOT_EXTS = {".cls", ".sty", ".bst", ".clo", ".ist", ".bbl", ".cfg"}
KEEP_AT_ROOT_NAMES = {"readme.md", "todo.md", "license", "license.md", "license.txt", "makefile",
                      ".gitignore", ".gitattributes", ".latexmkrc", "latexmkrc", ".texcount"}
# First path component that just says "this is where the X live"; dropped when moving.
ALIASES = {
    "manuscript": {"sections", "section", "chapters", "chapter", "tex", "text", "manuscript", "src", "source",
                   "paper", "content"},
    "figures": {"figures", "figure", "figs", "fig", "images", "image", "img", "graphics", "pictures", "plots",
                "pics"},
    "bibliography": {"bib", "bibliography", "refs", "references", "bibtex"},
    "code": {"code", "scripts", "script", "src", "analysis", "matlab", "python"},
    "data": {"data", "datasets", "dataset", "raw", "results"},
    "notes": {"notes", "note", "docs", "doc", "admin"},
    "supplementary": {"supplementary", "supplement", "extra", "extras", "media", "videos", "video"},
}
FOLDER_NAMES = {f.name for f in FOLDERS}
_PATH_COMMANDS = re.compile(
    r"\\(?P<cmd>input|include|subfile|includegraphics|bibliography|addbibresource|graphicspath)"
    r"\*?\s*(?:\[[^\]]*\])?\s*\{(?P<arg>[^{}]*)\}")
_MULTI_ARG = {"bibliography"}          # \bibliography{a,b}
_NO_EXTENSION = {"input", "include", "subfile", "bibliography"}


@dataclass
class ReorgPlan:
    """What organising this paper would do."""

    moves: list[tuple[str, str]] = field(default_factory=list)           # (from, to)
    rewrites: dict[str, str] = field(default_factory=dict)              # tex rel_path -> new content
    created: dict[str, str] = field(default_factory=dict)               # new rel_path -> content
    kept: list[tuple[str, str]] = field(default_factory=list)           # (rel_path, why)
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.moves and not self.rewrites and not self.created


POINTER = """% The paper itself is in {target}.tex. This file only loads it, so that LaTeX and Overleaf
% compile in this folder, where figures/ and bibliography/ are. Keep it here; edit the manuscript file.
\\input{{{target}}}
"""
CODE_README = """# code

Scripts and programs that produce the paper's results (Python, C/C++, MATLAB, R, ...), so that
co-authors and reviewers can see how every number and figure was made.
"""


def _pdf_pages(path: Path) -> int:
    """Number of pages of a PDF (0 if it cannot be read)."""
    try:
        import pypdfium2 as pdfium

        from core.preview import PDFIUM_LOCK

        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(path.read_bytes())
            try:
                return len(document)
            finally:
                document.close()
    except Exception:  # noqa: BLE001 - an unreadable PDF is simply not treated as a document
        return 0


def _category(rel: str, name: str, suffix: str, referenced_images: set[str], root: Path | None = None) -> str | None:
    """Target folder for a file, or ``None`` to leave it where it is.

    Every image goes to ``figures/``, used by the paper or not. A PDF is a figure when the
    paper includes it or it has one page; a longer PDF (a manual, a compiled copy of the
    paper) is a document and goes to ``notes/``.
    """
    if name.lower() in KEEP_AT_ROOT_NAMES or suffix in KEEP_AT_ROOT_EXTS:
        return None
    if suffix in TEX_EXTS:
        return "manuscript"
    if suffix in BIB_EXTS:
        return "bibliography"
    if suffix in CODE_EXTS:
        return "code"
    if suffix in DATA_EXTS:
        return "data"
    if suffix in SUPPLEMENTARY_EXTS:
        return "supplementary"
    if suffix == ".pdf" and rel not in referenced_images:
        return "notes" if root is not None and _pdf_pages(root / rel) > 1 else "figures"
    if suffix in FIGURE_EXTS:
        return "figures"
    if suffix in NOTE_EXTS:
        return "notes"
    return None


def unsorted_files(root: Path, main_rel: str) -> list[str]:
    """Top-level files that organising would move (for the sidebar's "not organised" hint)."""
    if not root.is_dir():
        return []
    return [p.name for p in sorted(root.iterdir())
            if p.is_file() and p.name != main_rel and not p.name.startswith(".")
            and _category(p.name, p.name, p.suffix.lower(), set(), None) is not None]


def _target_path(rel: str, folder: str, taken: set[str]) -> str:
    """Where ``rel`` goes inside ``folder``, keeping any meaningful sub-folders."""
    parts = list(PurePosixPath(rel).parts)
    while len(parts) > 1 and parts[0].lower() in ALIASES[folder] | FOLDER_NAMES:
        parts.pop(0)
    candidate = str(PurePosixPath(folder, *parts))
    stem, suffix = PurePosixPath(candidate).stem, PurePosixPath(candidate).suffix
    parent = str(PurePosixPath(candidate).parent)
    number = 2
    while candidate in taken:
        candidate = str(PurePosixPath(parent, f"{stem}-{number}{suffix}"))
        number += 1
    taken.add(candidate)
    return candidate


def referenced_graphics(tex_by_file: dict[str, str], root: Path, main_rel: str) -> set[str]:
    """Repo-relative image files that some ``\\includegraphics`` points at."""
    from core.source_map import resolve_graphic

    main_source = tex_by_file.get(main_rel, "")
    found: set[str] = set()
    for text in tex_by_file.values():
        mask = comment_mask(text)
        for match in _PATH_COMMANDS.finditer(text):
            if mask[match.start()] or match.group("cmd") != "includegraphics":
                continue
            resolved = resolve_graphic(root, main_rel, main_source, match.group("arg").strip())
            if resolved:
                found.add(resolved)
    return found


def _rewrite(text: str, mapping: dict[str, str], root: Path, main_rel: str, main_source: str) -> str:
    """Point every path command at the new location of the file it refers to."""
    from core.source_map import resolve_graphic

    mask = comment_mask(text)
    out, last = [], 0
    for match in _PATH_COMMANDS.finditer(text):
        cmd, arg = match.group("cmd"), match.group("arg")
        if mask[match.start()] or cmd == "graphicspath":
            continue
        pieces = [p.strip() for p in arg.split(",")] if cmd in _MULTI_ARG else [arg.strip()]
        new_pieces = []
        for piece in pieces:
            if cmd == "includegraphics":
                current = resolve_graphic(root, main_rel, main_source, piece)
            else:
                name = piece if PurePosixPath(piece).suffix else piece + (".bib" if "bib" in cmd else ".tex")
                current = name.lstrip("./")
            target = mapping.get(current or "")
            if target and cmd in _NO_EXTENSION:
                target = str(PurePosixPath(target).with_suffix(""))
            elif target and cmd == "includegraphics" and not PurePosixPath(piece).suffix:
                target = str(PurePosixPath(target).with_suffix(""))
            new_pieces.append(target or piece)
        replacement = ", ".join(new_pieces) if cmd in _MULTI_ARG else new_pieces[0]
        if replacement != arg:
            start = match.start("arg")
            out.append(text[last:start])
            out.append(replacement)
            last = match.end("arg")
    out.append(text[last:])
    return "".join(out)


def plan_reorganisation(root: Path, files: list[str], main_rel: str, is_protected) -> ReorgPlan:
    """Work out the moves and the LaTeX rewrites for a paper that already exists.

    Args:
        root: the paper folder.
        files: repo-relative paths to consider (tracked files, ``.git`` excluded).
        main_rel: the root document; it stays where it is.
        is_protected: ``callable(rel) -> str | None`` giving the reason a file is read-only.
    """
    plan = ReorgPlan()
    tex_by_file = {rel: (root / rel).read_text(encoding="utf-8", errors="replace")
                   for rel in files if rel.endswith(".tex") and (root / rel).is_file()}
    images = referenced_graphics(tex_by_file, root, main_rel)
    taken = set(files)
    # A paper written as one .tex file: its text goes to manuscript/ and a one-line pointer stays on
    # top (LaTeX and Overleaf must still run in the top folder). A main file that already assembles
    # other .tex files (main.tex + sections) is left as it is.
    single_file = ("/" not in main_rel and [f for f in files if f.endswith(".tex")] == [main_rel]
                   and "\\documentclass" in strip_comments(tex_by_file.get(main_rel, "")))
    for rel in sorted(files):
        path = PurePosixPath(rel)
        if rel == main_rel:
            if single_file and not is_protected(rel):
                target = _target_path(rel, "manuscript", taken)
                plan.moves.append((rel, target))
                plan.created[rel] = POINTER.format(target=str(PurePosixPath(target).with_suffix("")))
            else:
                plan.kept.append((rel, "the root document stays where LaTeX expects it"))
            continue
        reason = is_protected(rel)
        if reason:
            plan.kept.append((rel, reason))
            continue
        folder = _category(rel, path.name, path.suffix.lower(), images, root)
        if folder is None:
            if path.suffix.lower() in KEEP_AT_ROOT_EXTS:
                plan.kept.append((rel, "LaTeX and Overleaf only find class/style files next to the root document"))
            elif "/" not in rel and path.name.lower() not in KEEP_AT_ROOT_NAMES:
                plan.kept.append((rel, "unknown kind of file - move it by hand if it belongs in a folder"))
            continue
        if path.parts[0] == folder:            # already in the right place
            continue
        target = _target_path(rel, folder, taken)
        if target != rel:
            plan.moves.append((rel, target))

    code_folder = root / "code"
    has_code = (any(f.startswith("code/") for f in files) or any(t.startswith("code/") for _s, t in plan.moves)
                or (code_folder.is_dir() and any(code_folder.iterdir())))
    if not has_code:  # always give the paper a code/ folder (Git keeps no empty folders, hence the README)
        plan.created["code/README.md"] = CODE_README
    mapping = dict(plan.moves)
    if not mapping:
        return plan
    main_source = tex_by_file.get(main_rel, "")
    for rel, text in tex_by_file.items():
        new_text = _rewrite(text, mapping, root, main_rel, main_source)
        if new_text != text:
            plan.rewrites[mapping.get(rel, rel)] = new_text
    for folder in LOCAL_ONLY:
        moved = [t for _s, t in plan.moves if t.startswith(f"{folder}/")]
        if moved:
            plan.warnings.append(
                f"{len(moved)} file(s) move into {folder}/, which is kept on this computer. They were already "
                "part of the project, so they stay in it (and in Overleaf); delete them there if you want them "
                "only on this computer.")
    return plan


def plan_to_markdown(plan: ReorgPlan, name: str) -> str:
    """The plan as a report the author can read before approving."""
    lines = [f"# Organising '{name}' into folders", ""]
    if plan.empty:
        return "\n".join(lines + ["This paper is already organised - nothing to move."]) + "\n"
    lines += [f"{len(plan.moves)} file(s) move and {len(plan.rewrites)} LaTeX file(s) get updated paths.", "",
              "| File | Moves to |", "|---|---|"]
    lines += [f"| `{old}` | `{new}` |" for old, new in plan.moves]
    if plan.rewrites:
        lines += ["", "**Paths rewritten in:** " + ", ".join(f"`{rel}`" for rel in sorted(plan.rewrites))]
    if plan.created:
        why = {"code/README.md": "creates the code/ folder for the scripts that produce the results"}
        lines += ["", "**New files**", "", "| File | Why |", "|---|---|"]
        lines += [f"| `{rel}` | {why.get(rel, 'one-line main file that loads the manuscript, so LaTeX runs here')} |"
                  for rel in plan.created]
    if plan.kept:
        lines += ["", "**Left where they are**", "", "| File | Why |", "|---|---|"]
        lines += [f"| `{rel}` | {why} |" for rel, why in plan.kept]
    for warning in plan.warnings:
        lines += ["", f"> {warning}"]
    return "\n".join(lines) + "\n"
