"""LaTeX / BibTeX parsing helpers.

These are dependency-free, character-level parsers. They handle the things that
trip up naive regexes in real Overleaf projects: escaped ``\\%``, nested braces
in section titles and BibTeX values, ``\\input`` trees, starred sectioning
commands, and multi-key ``\\cite{a,b}`` commands with optional arguments.

Character offsets returned by :func:`split_sections` refer to the *original*
text, so edits can be spliced back without touching anything else in the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SECTION_LEVELS: dict[str, int] = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
}

_SECTION_RE = re.compile(
    r"\\(?P<cmd>part|chapter|section|subsection|subsubsection|paragraph)"
    r"(?P<star>\*)?\s*(?:\[[^\]]*\])?\s*\{"
)
_TERMINATOR_RE = re.compile(
    r"\\(?:end\{document\}|bibliography\{|bibliographystyle\{|printbibliography\b|appendix\b"
    r"|begin\{thebibliography\})"
)
CITE_RE = re.compile(
    r"\\(?P<cmd>[a-zA-Z]*cite[a-zA-Z]*|nocite)\*?\s*"
    r"(?:\[[^\]]*\]\s*){0,2}\{(?P<keys>[^}]*)\}"
)
_BIB_CMD_RE = re.compile(r"\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


# ---------------------------------------------------------------------- #
# Low-level helpers
# ---------------------------------------------------------------------- #
def comment_mask(tex: str) -> list[bool]:
    """Return a per-character mask that is True inside ``%`` comments."""
    mask = [False] * len(tex)
    i, n = 0, len(tex)
    while i < n:
        ch = tex[i]
        if ch == "\\":
            i += 2  # skip escaped char, including \%
            continue
        if ch == "%":
            j = tex.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                mask[k] = True
            i = j
            continue
        i += 1
    return mask


def strip_comments(tex: str) -> str:
    """Remove ``%`` comments while keeping escaped ``\\%`` and line structure."""
    mask = comment_mask(tex)
    return "".join(ch for ch, is_comment in zip(tex, mask) if not is_comment)


def match_brace(text: str, open_index: int) -> int:
    """Return the index of the ``}`` matching the ``{`` at ``open_index``.

    Raises:
        ValueError: if ``text[open_index]`` is not ``{`` or braces are unbalanced.
    """
    if open_index >= len(text) or text[open_index] != "{":
        raise ValueError(f"No opening brace at index {open_index}")
    depth = 0
    i = open_index
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"Unbalanced braces starting at index {open_index}")


def line_of(text: str, index: int) -> int:
    """1-based line number of a character offset."""
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------------- #
# Sections
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class Section:
    """A sectioning unit located in a .tex string.

    ``start``/``end`` delimit the whole unit including its header and nested
    subsections; ``body_start`` is the first character after the header.
    """

    command: str
    level: int
    title: str
    start: int
    body_start: int
    end: int
    starred: bool = False

    def body(self, tex: str) -> str:
        return tex[self.body_start : self.end]

    def full(self, tex: str) -> str:
        return tex[self.start : self.end]


def split_sections(tex: str) -> list[Section]:
    """Locate all sectioning commands (ignoring commented-out ones)."""
    mask = comment_mask(tex)
    headers: list[tuple[str, int, str, int, int, bool]] = []
    for match in _SECTION_RE.finditer(tex):
        if mask[match.start()]:
            continue
        open_idx = match.end() - 1
        try:
            close_idx = match_brace(tex, open_idx)
        except ValueError:
            continue
        cmd = match.group("cmd")
        title = " ".join(tex[open_idx + 1 : close_idx].split())
        headers.append(
            (cmd, match.start(), title, close_idx + 1, SECTION_LEVELS[cmd], bool(match.group("star")))
        )

    terminators = [m.start() for m in _TERMINATOR_RE.finditer(tex) if not mask[m.start()]]
    sections: list[Section] = []
    for idx, (cmd, start, title, body_start, level, starred) in enumerate(headers):
        end = len(tex)
        for later in headers[idx + 1 :]:
            if later[4] <= level:
                end = later[1]
                break
        for term in terminators:
            if body_start <= term < end:
                end = term
                break
        sections.append(Section(cmd, level, title, start, body_start, end, starred))
    return sections


def _normalise_title(title: str) -> str:
    title = re.sub(r"\\[a-zA-Z]+\s*", "", title)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def find_section(tex: str, title: str) -> Section | None:
    """Find a section by (case/format-insensitive) title; exact match preferred."""
    wanted = _normalise_title(title)
    sections = split_sections(tex)
    for section in sections:
        if _normalise_title(section.title) == wanted:
            return section
    for section in sections:
        if wanted and wanted in _normalise_title(section.title):
            return section
    return None


def replace_span(tex: str, start: int, end: int, replacement: str) -> str:
    """Return ``tex`` with ``tex[start:end]`` replaced."""
    return tex[:start] + replacement + tex[end:]


def replace_section_body(tex: str, section: Section, new_body: str) -> str:
    """Replace a section's body, preserving its header and trailing spacing."""
    body = section.body(tex)
    trailing = body[len(body.rstrip()) :] or "\n\n"
    return replace_span(tex, section.body_start, section.end, "\n" + new_body.strip("\n") + trailing)


def insert_section(
    tex: str,
    title: str,
    body: str,
    after_titles: tuple[str, ...] = ("introduction",),
    label: str | None = None,
) -> str:
    """Insert a new top-level ``\\section`` into a document.

    Placement priority: after the first section matching ``after_titles``;
    otherwise before the bibliography / ``\\end{document}``; otherwise append.
    """
    label_line = f"\\label{{{label}}}\n" if label else ""
    block = f"\\section{{{title}}}\n{label_line}{body.strip()}\n\n"
    for anchor in after_titles:
        section = find_section(tex, anchor)
        if section is not None:
            insert_at = section.end
            prefix = "" if tex[:insert_at].endswith("\n\n") else "\n"
            return tex[:insert_at] + prefix + block + tex[insert_at:]
    mask = comment_mask(tex)
    for match in _TERMINATOR_RE.finditer(tex):
        if not mask[match.start()]:
            return tex[: match.start()] + block + tex[match.start() :]
    return tex.rstrip() + "\n\n" + block


# ---------------------------------------------------------------------- #
# Project structure
# ---------------------------------------------------------------------- #
def _tex_body(path: Path) -> str | None:
    try:
        return strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def find_main_tex(root: Path) -> Path | None:
    """Locate the root document LaTeX is run on.

    That is the file with ``\\documentclass`` - or a top-level file that only ``\\input``s the
    real document (``\\input{manuscript/paper}``, as left by File ▸ Organise), because LaTeX
    and Overleaf must run in the top folder for the paper's relative paths to work.
    """
    preferred = [root / "main.tex", root / "paper.tex", root / "manuscript.tex"]
    top_level = preferred + sorted(root.glob("*.tex"))
    for path in top_level:
        body = _tex_body(path) if path.is_file() else None
        if body and "\\documentclass" in body:
            return path
    for path in top_level:  # a pointer at the top that pulls in the real document
        body = _tex_body(path) if path.is_file() else None
        for target in _INPUT_RE.findall(body or ""):
            inner = root / (target.strip() if target.strip().endswith(".tex") else target.strip() + ".tex")
            inner_body = _tex_body(inner) if inner.is_file() else None
            if inner_body and "\\documentclass" in inner_body:
                return path
    for path in sorted(root.rglob("*.tex")):
        if ".git" in path.parts or not path.is_file():
            continue
        body = _tex_body(path)
        if body and "\\documentclass" in body:
            return path
    return None


def list_tex_files(root: Path) -> list[str]:
    """All .tex/.bib files under ``root`` as POSIX relative paths."""
    files = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.suffix in {".tex", ".bib"} and ".git" not in p.parts and p.is_file()
    ]
    return sorted(files)



def list_section_titles(root: Path, max_level: int = 3) -> list[str]:
    """Unique section titles (main file first, then other .tex files)."""
    main = find_main_tex(root)
    files = ([main] if main else []) + sorted(
        p for p in root.rglob("*.tex") if p != main and ".git" not in p.parts)
    titles: list[str] = []
    for tex_file in files:
        for section in split_sections(tex_file.read_text(encoding="utf-8", errors="replace")):
            if section.level <= max_level and section.title not in titles:
                titles.append(section.title)
    return titles

def _resolve_tex_path(name: str, base: Path) -> Path:
    path = (base / name.strip()).resolve()
    return path if path.suffix else path.with_suffix(".tex")


def flatten_inputs(tex_path: Path, root: Path, _seen: set[Path] | None = None) -> str:
    """Return document text with ``\\input``/``\\include`` expanded recursively.

    Missing files are replaced by a ``% [missing: ...]`` marker instead of
    raising, and include cycles are broken.
    """
    seen = _seen if _seen is not None else set()
    tex_path = tex_path.resolve()
    if tex_path in seen:
        return f"% [cyclic include skipped: {tex_path.name}]"
    seen.add(tex_path)
    tex = tex_path.read_text(encoding="utf-8", errors="replace")
    mask = comment_mask(tex)
    out: list[str] = []
    last = 0
    for match in _INPUT_RE.finditer(tex):
        if mask[match.start()]:
            continue
        out.append(tex[last : match.start()])
        child = _resolve_tex_path(match.group(1), root)
        if root.resolve() not in child.parents and child != root.resolve():
            out.append(f"% [include outside project skipped: {match.group(1)}]")
        elif child.is_file():
            out.append(flatten_inputs(child, root, seen))
        else:
            out.append(f"% [missing: {match.group(1)}]")
        last = match.end()
    out.append(tex[last:])
    return "".join(out)


def find_bib_files(tex: str, root: Path) -> list[Path]:
    """Resolve ``\\bibliography{}`` / ``\\addbibresource{}`` targets.

    Falls back to every .bib file in the project when none are declared.
    """
    mask = comment_mask(tex)
    paths: list[Path] = []
    for match in _BIB_CMD_RE.finditer(tex):
        if mask[match.start()]:
            continue
        for name in match.group(1).split(","):
            name = name.strip()
            if not name:
                continue
            path = root / (name if name.endswith(".bib") else f"{name}.bib")
            if path not in paths:
                paths.append(path)
    if not paths:
        paths = sorted(p for p in root.rglob("*.bib") if ".git" not in p.parts)
    return paths


# ---------------------------------------------------------------------- #
# Citations
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class Citation:
    key: str
    command: str
    line: int


def extract_citations(tex: str) -> list[Citation]:
    """Return every citation key used in ``tex`` (commented-out ones ignored)."""
    mask = comment_mask(tex)
    citations: list[Citation] = []
    for match in CITE_RE.finditer(tex):
        if mask[match.start()]:
            continue
        line = line_of(tex, match.start())
        for key in match.group("keys").split(","):
            key = key.strip()
            if key and key != "*":
                citations.append(Citation(key=key, command=match.group("cmd"), line=line))
    return citations


# ---------------------------------------------------------------------- #
# BibTeX
# ---------------------------------------------------------------------- #
@dataclass
class BibEntry:
    """A parsed BibTeX entry. Field names are lower-cased."""

    entry_type: str
    key: str
    fields: dict[str, str] = field(default_factory=dict)
    raw: str = ""
    source: str = ""
    line: int = 0

    def get(self, name: str, default: str = "") -> str:
        return self.fields.get(name.lower(), default)


_ENTRY_START_RE = re.compile(r"@\s*([a-zA-Z]+)\s*([{(])")
_FIELD_RE = re.compile(r"\s*([A-Za-z][\w:.\-]*)\s*=\s*")
_BARE_VALUE_RE = re.compile(r"[^\s,#})]+")
_SKIP_TYPES = {"comment", "preamble", "string"}


def _match_paren(text: str, open_index: int) -> int:
    """Index of the ``)`` closing a ``@type( ... )`` entry (braces respected)."""
    depth = 0
    for i in range(open_index + 1, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ")" and depth == 0:
            return i
    raise ValueError(f"Unterminated entry at index {open_index}")


def _read_value(text: str, i: int) -> tuple[str, int]:
    """Read one BibTeX field value (with ``#`` concatenation) starting at ``i``."""
    parts: list[str] = []
    n = len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] == "{":
            end = match_brace(text, i)
            parts.append(text[i + 1 : end])
            i = end + 1
        elif text[i] == '"':
            j = i + 1
            depth = 0
            while j < n and not (text[j] == '"' and depth == 0 and text[j - 1] != "\\"):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            parts.append(text[i + 1 : j])
            i = j + 1
        else:
            match = _BARE_VALUE_RE.match(text, i)
            if not match:
                break
            parts.append(match.group(0))
            i = match.end()
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "#":
            i += 1
            continue
        break
    return " ".join("".join(parts).split()), i


def parse_bib(text: str, source: str = "") -> list[BibEntry]:
    """Parse BibTeX source into entries. Malformed entries are skipped."""
    entries: list[BibEntry] = []
    pos = 0
    while True:
        match = _ENTRY_START_RE.search(text, pos)
        if not match:
            break
        entry_type = match.group(1).lower()
        open_idx = match.end() - 1
        try:
            if match.group(2) == "{":
                close_idx = match_brace(text, open_idx)
            else:
                close_idx = _match_paren(text, open_idx)
        except ValueError:
            pos = match.end()
            continue
        body = text[open_idx + 1 : close_idx]
        pos = close_idx + 1
        if entry_type in _SKIP_TYPES:
            continue
        key, _, rest = body.partition(",")
        entry = BibEntry(
            entry_type=entry_type,
            key=key.strip(),
            raw=text[match.start() : close_idx + 1],
            source=source,
            line=line_of(text, match.start()),
        )
        i = 0
        while i < len(rest):
            field_match = _FIELD_RE.match(rest, i)
            if not field_match:
                next_comma = rest.find(",", i)
                if next_comma == -1:
                    break
                i = next_comma + 1
                continue
            try:
                value, i = _read_value(rest, field_match.end())
            except ValueError:
                break
            entry.fields[field_match.group(1).lower()] = value
            comma = rest.find(",", i)
            if comma == -1:
                break
            i = comma + 1
        if entry.key:
            entries.append(entry)
    return entries


def load_bib_files(paths: list[Path], root: Path) -> list[BibEntry]:
    """Parse every existing .bib file in ``paths``."""
    entries: list[BibEntry] = []
    for path in paths:
        if path.is_file():
            rel = path.relative_to(root).as_posix() if root in path.parents else str(path)
            entries.extend(parse_bib(path.read_text(encoding="utf-8", errors="replace"), rel))
    return entries
