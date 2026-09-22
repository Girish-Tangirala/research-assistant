"""Organise an existing paper into the standard folders.

Files that are already in the repository are sorted into ``manuscript/``,
``figures/``, ``bibliography/``, ``code/``, ``notes/`` and ``data/`` (see
:mod:`core.project_layout`), and every ``\\input``, ``\\includegraphics``,
``\\bibliography`` and ``\\addbibresource`` that points at a moved file is
rewritten. Nothing is moved that LaTeX needs in place: the root document, class
and style files, and read-only (reference-manager) files stay where they are.

The result is a plan; the workflow turns it into one move change plus one diff
per rewritten ``.tex`` file, so the author approves it like any other edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.latex_parser import comment_mask
from core.project_layout import FOLDERS

# Extension -> target folder.
TEX_EXTS = {".tex"}
FIGURE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".tif", ".tiff", ".gif", ".bmp", ".svg", ".webp"}
BIB_EXTS = {".bib"}
CODE_EXTS = {".py", ".ipynb", ".m", ".r", ".jl", ".c", ".cpp", ".h", ".hpp", ".sh", ".ps1", ".sql"}
DATA_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".mat", ".h5", ".hdf5", ".npy", ".npz", ".dat", ".parquet"}
NOTE_EXTS = {".md", ".txt", ".rst", ".docx", ".odt"}
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
    kept: list[tuple[str, str]] = field(default_factory=list)           # (rel_path, why)
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.moves and not self.rewrites


def _category(rel: str, name: str, suffix: str, referenced_images: set[str]) -> str | None:
    """Target folder for a file, or ``None`` to leave it where it is."""
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
    if suffix in FIGURE_EXTS:
        # A stray PDF at the root is usually a compiled document, not a figure.
        in_figure_folder = PurePosixPath(rel).parts[0].lower() in ALIASES["figures"] if "/" in rel else False
        return "figures" if (rel in referenced_images or in_figure_folder) else None
    if suffix in NOTE_EXTS:
        return "notes"
    return None


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
    for rel in sorted(files):
        path = PurePosixPath(rel)
        if rel == main_rel:
            plan.kept.append((rel, "the root document stays where LaTeX expects it"))
            continue
        reason = is_protected(rel)
        if reason:
            plan.kept.append((rel, reason))
            continue
        folder = _category(rel, path.name, path.suffix.lower(), images)
        if folder is None:
            continue
        if path.parts[0] == folder:            # already in the right place
            continue
        target = _target_path(rel, folder, taken)
        if target != rel:
            plan.moves.append((rel, target))

    mapping = dict(plan.moves)
    if not mapping:
        return plan
    main_source = tex_by_file.get(main_rel, "")
    for rel, text in tex_by_file.items():
        new_text = _rewrite(text, mapping, root, main_rel, main_source)
        if new_text != text:
            plan.rewrites[mapping.get(rel, rel)] = new_text
    moved_data = [t for _s, t in plan.moves if t.startswith("data/")]
    if moved_data:
        plan.warnings.append(
            f"{len(moved_data)} data file(s) move into data/. They were already part of the project, so they "
            "stay in it (and in Overleaf); delete them there if you want them only on this computer.")
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
    if plan.kept:
        lines += ["", "**Left where they are**", "", "| File | Why |", "|---|---|"]
        lines += [f"| `{rel}` | {why} |" for rel, why in plan.kept]
    for warning in plan.warnings:
        lines += ["", f"> {warning}"]
    return "\n".join(lines) + "\n"
