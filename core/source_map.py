"""What was clicked in the PDF: turn a source line into something the app can act on.

A SyncTeX hit gives a file and a line. This module finds the section around
that line (following ``\\input`` chains), the enclosing figure / table / equation
environment, the graphics a figure includes and the citation keys on the line.
It also lists the paper's figures for the "Replace a figure" form and resolves
``\\includegraphics`` names to files in the repository.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.latex_parser import CITE_RE, comment_mask, match_brace, split_sections, strip_comments

KIND_TEXT, KIND_HEADING, KIND_FIGURE, KIND_TABLE, KIND_MATH = "text", "heading", "figure", "table", "math"
KIND_PREAMBLE, KIND_BIBLIOGRAPHY, KIND_OTHER = "preamble", "bibliography", "other"
FIGURE_ENVS = {"figure", "figure*", "wrapfigure", "SCfigure"}
TABLE_ENVS = {"table", "table*", "tabular", "tabular*", "tabularx", "longtable", "wraptable"}
MATH_ENVS = {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*",
             "eqnarray", "eqnarray*", "displaymath", "flalign", "flalign*"}
GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".PDF", ".PNG", ".JPG", ".JPEG")
MAX_SECTION_LEVEL = 3  # the section pickers list \section .. \subsubsection
_ENV_RE = re.compile(r"\\(begin|end)\s*\{([^}]+)\}")
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\])?\s*\{")
_CAPTION_RE = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{")
_LABEL_RE = re.compile(r"\\label\s*\{([^}]*)\}")
_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:\s*\{[^}]*\})+)\s*\}")


@dataclass
class Graphic:
    """One ``\\includegraphics`` argument and where it sits in the file."""

    name: str
    start: int   # offset of the path argument (after "{")
    end: int     # offset of the closing "}"


@dataclass
class FigureRef:
    """A figure environment (or a bare ``\\includegraphics``) in a .tex file."""

    rel_path: str
    start_line: int
    end_line: int
    graphics: list[Graphic] = field(default_factory=list)
    caption: str = ""
    label: str = ""
    env: str = ""
    start: int = 0   # offsets of the environment in its file
    end: int = 0

    @property
    def graphic(self) -> str:
        return self.graphics[0].name if self.graphics else ""

    def display(self) -> str:
        name = self.label or self.graphic or "figure"
        more = f" (+{len(self.graphics) - 1} more)" if len(self.graphics) > 1 else ""
        return f"{name} - {self.graphic}{more} [{self.rel_path}:{self.start_line}]"


@dataclass
class ClickTarget:
    kind: str
    rel_path: str
    line: int
    section: str = ""
    figure: FigureRef | None = None
    cite_keys: list[str] = field(default_factory=list)
    snippet: str = ""

    def describe(self) -> str:
        where = f"{self.rel_path}, line {self.line}" if self.rel_path else "generated text"
        what = {KIND_FIGURE: "figure", KIND_TABLE: "table", KIND_MATH: "equation", KIND_HEADING: "heading",
                KIND_PREAMBLE: "preamble", KIND_BIBLIOGRAPHY: "bibliography"}.get(self.kind, "text")
        section = f" · section '{self.section}'" if self.section else ""
        return f"{what.capitalize()} at {where}{section}"


# ---------------------------------------------------------------------- #
# Paths
# ---------------------------------------------------------------------- #
def _key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def repo_relative(path: Path, roots: list[Path]) -> str | None:
    """``path`` relative to the first of ``roots`` containing it (POSIX), else ``None``.

    Containment is checked case-insensitively on Windows, but the result keeps the file's real
    spelling (``images/full_R.png``, not ``images/full_r.png``): it is compared with Git's file list.
    """
    target = _key(path)
    for root in roots:
        base = _key(root)
        if target.startswith(base + os.sep):
            real = Path(path).resolve()  # on Windows this also restores the on-disk capitalisation
            try:
                rel = real.relative_to(Path(root).resolve())
            except ValueError:  # e.g. differently spelled root; fall back to the given spelling
                rel = Path(os.path.relpath(os.path.abspath(str(path)), os.path.abspath(str(root))))
            return PurePosixPath(*rel.parts).as_posix()
    return None


def _offset_of_line(text: str, line: int) -> int:
    if line <= 1:
        return 0
    index = -1
    for _ in range(line - 1):
        index = text.find("\n", index + 1)
        if index < 0:
            return len(text)
    return index + 1


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------- #
# Environments, figures, sections
# ---------------------------------------------------------------------- #
def environments_at(tex: str, offset: int) -> list[tuple[str, int, int]]:
    """``(name, start, end)`` of the environments enclosing ``offset``, outermost first."""
    mask = comment_mask(tex)
    stack: list[tuple[str, int]] = []
    found: list[tuple[str, int, int]] = []
    for match in _ENV_RE.finditer(tex):
        if mask[match.start()]:
            continue
        name = match.group(2).strip()
        if match.group(1) == "begin":
            stack.append((name, match.start()))
            continue
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0] == name:
                begin = stack[depth][1]
                del stack[depth:]
                if begin <= offset <= match.end():
                    found.append((name, begin, match.end()))
                break
    return sorted(found, key=lambda env: env[1])


def _braced(tex: str, open_index: int) -> tuple[str, int]:
    try:
        close = match_brace(tex, open_index)
    except ValueError:
        return "", open_index
    return tex[open_index + 1:close], close


def _figure_from_span(tex: str, rel: str, start: int, end: int, env: str) -> FigureRef:
    body = tex[start:end]
    mask = comment_mask(body)
    graphics = []
    for match in _INCLUDEGRAPHICS_RE.finditer(body):
        if mask[match.start()]:
            continue
        name, close = _braced(body, match.end() - 1)
        if name.strip():
            graphics.append(Graphic(name.strip(), start + match.end(), start + close))
    caption = next((_braced(body, m.end() - 1)[0] for m in _CAPTION_RE.finditer(body) if not mask[m.start()]), "")
    label = next((m.group(1).strip() for m in _LABEL_RE.finditer(body) if not mask[m.start()]), "")
    return FigureRef(rel, _line_of(tex, start), _line_of(tex, end), graphics,
                     " ".join(caption.split()), label, env, start, end)


def figures_in(tex: str, rel: str) -> list[FigureRef]:
    """All figure environments of a file (in order)."""
    mask = comment_mask(tex)
    figures, stack = [], []
    for match in _ENV_RE.finditer(tex):
        if mask[match.start()]:
            continue
        name = match.group(2).strip()
        if match.group(1) == "begin" and name in FIGURE_ENVS and not stack:
            stack.append((name, match.start()))
        elif match.group(1) == "end" and stack and stack[-1][0] == name:
            env, begin = stack.pop()
            figures.append(_figure_from_span(tex, rel, begin, match.end(), env))
    return [f for f in figures if f.graphics]


def caption_span(tex: str, figure: FigureRef) -> tuple[int, int] | None:
    """Offsets of the caption text (inside the braces) of ``figure``."""
    body = tex[figure.start:figure.end]
    mask = comment_mask(body)
    for match in _CAPTION_RE.finditer(body):
        if not mask[match.start()]:
            _text, close = _braced(body, match.end() - 1)
            if close > match.end() - 1:
                return figure.start + match.end(), figure.start + close
    return None


def find_figure(tex: str, rel: str, label: str, graphic: str, line: int = 0) -> FigureRef | None:
    """Find a figure again (by label, else by graphic name nearest to ``line``)."""
    figures = figures_in(tex, rel)
    if label:
        for figure in figures:
            if figure.label == label and (not graphic or any(g.name == graphic for g in figure.graphics)):
                return _with_first(figure, graphic)
    candidates = [f for f in figures if any(g.name == graphic for g in f.graphics)]
    mask = comment_mask(tex)
    for match in _INCLUDEGRAPHICS_RE.finditer(tex):  # bare \includegraphics outside figure environments
        name, close = _braced(tex, match.end() - 1)
        inside = any(f.start <= match.start() < f.end for f in figures)
        if not mask[match.start()] and not inside and name.strip() == graphic:
            number = _line_of(tex, match.start())
            candidates.append(FigureRef(rel, number, number, [Graphic(graphic, match.end(), close)],
                                        start=match.start(), end=close + 1))
    if not candidates:
        return None
    return _with_first(min(candidates, key=lambda f: abs(f.start_line - line)), graphic)


def _with_first(figure: FigureRef, graphic: str) -> FigureRef:
    figure.graphics.sort(key=lambda g: g.name != graphic)
    return figure


def list_figures(root: Path) -> list[FigureRef]:
    """Figures with at least one ``\\includegraphics`` in every .tex file of the paper."""
    result = []
    for path in sorted(root.rglob("*.tex")):
        if ".git" in path.parts or not path.is_file():
            continue
        result += figures_in(_read(path), path.relative_to(root).as_posix())
    return result


def _deepest_section(tex: str, offset: int) -> tuple[str, bool]:
    """Title of the innermost pickable section containing ``offset``; flag if on its heading."""
    best = None
    for section in split_sections(tex):
        if section.level <= MAX_SECTION_LEVEL and section.start <= offset < section.end:
            if best is None or section.level >= best.level:
                best = section
    if best is None:
        return "", False
    return best.title, best.start <= offset < best.body_start


def _including_files(root: Path, rel: str) -> list[tuple[Path, int]]:
    """Files that ``\\input`` the file ``rel`` and the offset of that command."""
    wanted = _key(root / rel)
    hits = []
    for path in sorted(root.rglob("*.tex")):
        if ".git" in path.parts or not path.is_file():
            continue
        tex = _read(path)
        mask = comment_mask(tex)
        for match in _INPUT_RE.finditer(tex):
            name = match.group(1).strip()
            child = root / (name if name.endswith(".tex") else name + ".tex")
            if not mask[match.start()] and _key(child) == wanted:
                hits.append((path, match.start()))
    return hits


def section_at(root: Path, rel: str, offset: int, _depth: int = 0) -> tuple[str, bool]:
    """Section around ``offset`` of ``rel``, looking through the files that include it."""
    title, on_heading = _deepest_section(_read(root / rel), offset)
    if title or _depth > 5:
        return title, on_heading
    for parent, position in _including_files(root, rel):
        title, _ = section_at(root, parent.relative_to(root).as_posix(), position, _depth + 1)
        if title:
            return title, False
    return "", False


def classify(root: Path, rel: str, line: int, on_image: bool = False) -> ClickTarget:
    """Describe the source at ``rel``:``line`` (``root`` holds the compiled sources)."""
    if rel.endswith(".bbl"):
        return ClickTarget(KIND_BIBLIOGRAPHY, "", line)
    tex = _read(root / rel)
    offset = _offset_of_line(tex, line)
    line_end = tex.find("\n", offset)
    line_text = tex[offset:line_end if line_end >= 0 else len(tex)]
    snippet = " ".join(strip_comments(line_text).split())[:160]
    keys = [k.strip() for m in CITE_RE.finditer(strip_comments(line_text)) for k in m.group("keys").split(",")
            if k.strip()]
    begin_document = tex.find("\\begin{document}")
    if "\\documentclass" in tex[:offset] and 0 <= offset < begin_document:
        return ClickTarget(KIND_PREAMBLE, rel, line, snippet=snippet)
    section, on_heading = section_at(root, rel, offset)
    target = ClickTarget(KIND_TEXT, rel, line, section, cite_keys=keys, snippet=snippet)
    envs = environments_at(tex, offset)
    figure_env = next((e for e in envs if e[0] in FIGURE_ENVS), None)
    if figure_env is not None:
        target.kind = KIND_FIGURE
        target.figure = _figure_from_span(tex, rel, figure_env[1], figure_env[2], figure_env[0])
        if not target.figure.graphics:  # e.g. a TikZ picture: nothing to replace
            target.kind, target.figure = KIND_OTHER, None
    elif any(e[0] in TABLE_ENVS for e in envs):
        target.kind = KIND_TABLE
    elif any(e[0] in MATH_ENVS for e in envs):
        target.kind = KIND_MATH
    elif on_heading:
        target.kind = KIND_HEADING
    elif on_image:  # a graphic outside a figure environment: look around the line
        lines = tex.splitlines(keepends=True)
        first = max(0, line - 3)
        start = sum(len(x) for x in lines[:first])
        end = sum(len(x) for x in lines[:min(len(lines), line + 2)])
        bare = _figure_from_span(tex, rel, start, end, "")
        if bare.graphics:
            first = bare.graphics[0]
            bare.start_line = bare.end_line = _line_of(tex, first.start)
            bare.graphics, bare.caption, bare.label = [first], "", ""
            bare.start, bare.end = first.start, first.end + 1
            target.kind, target.figure = KIND_FIGURE, bare
    if target.figure is not None and len(target.figure.graphics) > 1:
        # several panels: prefer the one on the clicked line
        on_line = [g for g in target.figure.graphics if _line_of(tex, g.start) == line]
        if on_line:
            target.figure.graphics.sort(key=lambda g: g is not on_line[0])
    return target


class ClickLookupError(Exception):
    """A click could not be mapped to the paper's source (message is user-facing)."""


def target_for_click(pdf: Path, page: int, x: float, y: float, source_root: Path, repo_root: Path,
                     tool: str | None) -> ClickTarget:
    """Map a click on ``pdf`` to a :class:`ClickTarget`.

    ``source_root`` is the folder that was compiled (the repository, or the
    preview mirror for proposed changes); the returned path is relative to it,
    which is the same relative path as in the repository.

    Raises:
        ClickLookupError: with an explanation when nothing usable was found.
    """
    from core.preview import image_at
    from core.synctex import locate, synctex_file

    if synctex_file(pdf) is None:
        raise ClickLookupError("This PDF was built before click-to-edit existed - click Recompile once.")
    location = locate(pdf, page, x, y, source_root, tool)
    if location is None:
        raise ClickLookupError("Nothing to edit there - click on text or a figure.")
    if location.path.suffix.lower() == ".bbl":
        return ClickTarget(KIND_BIBLIOGRAPHY, "", location.line)
    for root in (source_root, repo_root):
        rel = repo_relative(location.path, [root])
        if rel is not None and (root / rel).is_file():
            return classify(root, rel, location.line, on_image=image_at(pdf, page, x, y))
    raise ClickLookupError(f"That text comes from {location.path.name}, which is not part of the paper "
                           "(e.g. a package or class file).")


# ---------------------------------------------------------------------- #
# Graphics files
# ---------------------------------------------------------------------- #
def graphics_paths(main_source: str) -> list[str]:
    match = _GRAPHICSPATH_RE.search(strip_comments(main_source))
    if not match:
        return []
    return [p.strip() for p in re.findall(r"\{([^}]*)\}", match.group(1)) if p.strip()]


def resolve_graphic(root: Path, main_rel: str, main_source: str, name: str) -> str | None:
    """Repo-relative file an ``\\includegraphics{name}`` refers to (``None`` if not found)."""
    main_dir = (root / main_rel).parent
    folders = [main_dir] + [main_dir / p for p in graphics_paths(main_source)]
    has_ext = PurePosixPath(name).suffix.lower() in {e.lower() for e in GRAPHIC_EXTS}
    for folder in folders:
        base = folder / name
        candidates = [base] if has_ext else [base.with_name(base.name + ext) for ext in GRAPHIC_EXTS]
        for candidate in candidates:
            if candidate.is_file():
                rel = repo_relative(candidate, [root])
                if rel is not None:
                    return rel
    return None
