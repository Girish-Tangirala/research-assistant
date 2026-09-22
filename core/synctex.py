"""SyncTeX reverse search: a position in the PDF -> source file and line.

The app compiles with ``-synctex=1``, which writes ``<name>.synctex.gz`` next
to the PDF. Lookups use a small built-in reader of that file and fall back to
the ``synctex`` program of the TeX distribution. Positions are PDF points
measured from the top-left corner of the page (the viewer's coordinates).
SyncTeX is line-precise only: it tells which source line produced the text,
not which character.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from config import LatexSettings
from core.proc import NO_WINDOW

_SP_TO_BP = 72.0 / 72.27 / 65536.0
_BOX_KINDS = "(h[v"
_POINT_KINDS = "xg$"
_RECORD_RE = re.compile(r"^([\[(hvxkg$])(\d+),(-?\d+):(-?\d+),(-?\d+)(?::(-?\d+)(?:,(-?\d+),(-?\d+))?)?")
_TOLERANCE_BP = 1.5
_NEAR_BP = 8.0            # clicks this close to a line of text still count as that line


@dataclass(frozen=True)
class SourceLocation:
    path: Path
    line: int


def synctex_file(pdf: Path) -> Path | None:
    """The SyncTeX data written next to ``pdf`` (``None`` if it was compiled without it)."""
    for candidate in (pdf.with_suffix(".synctex.gz"), pdf.with_suffix(".synctex")):
        if candidate.is_file():
            return candidate
    return None


def find_synctex_tool(settings: LatexSettings) -> str | None:
    """``synctex`` from the same TeX distribution as the compiler, else from PATH."""
    for known in (settings.pdflatex_path, settings.latexmk_path):
        if known:
            base = Path(known)
            sibling = base.with_name("synctex" + base.suffix)
            if sibling.is_file():
                return str(sibling)
    return shutil.which("synctex")


def _resolve(raw: str, base: Path) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        path = base / path
    return Path(os.path.normpath(path))


def query_tool(tool: str, pdf: Path, page: int, x: float, y: float, base: Path,
               timeout: float = 15) -> SourceLocation | None:
    """Ask the ``synctex`` program; ``page`` is 0-based. ``None`` if nothing was found."""
    try:
        proc = subprocess.run([tool, "edit", "-o", f"{page + 1}:{x:.2f}:{y:.2f}:{pdf}"], cwd=pdf.parent,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    source, line = None, None
    for row in proc.stdout.splitlines():
        if row.startswith("Input:") and source is None:
            source = row[len("Input:"):]
        elif row.startswith("Line:") and line is None:
            try:
                line = int(row[len("Line:"):])
            except ValueError:
                return None
    if not source or not line or line < 1:
        return None
    return SourceLocation(_resolve(source, base), line)


@dataclass(frozen=True)
class _Record:
    kind: str
    tag: int
    line: int
    x: float
    y: float
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0

    def contains(self, x: float, y: float) -> bool:
        return (self.x - _TOLERANCE_BP <= x <= self.x + self.width + _TOLERANCE_BP
                and self.y - self.height - _TOLERANCE_BP <= y <= self.y + self.depth + _TOLERANCE_BP)

    def distance(self, x: float, y: float) -> float:
        dx = max(self.x - x, 0.0, x - (self.x + self.width))
        dy = max(self.y - self.height - y, 0.0, y - (self.y + self.depth))
        return (dx * dx + dy * dy) ** 0.5


class SyncTexData:
    """Parsed ``.synctex(.gz)`` file: input files and the boxes on every page."""

    def __init__(self, inputs: dict[int, str], pages: dict[int, list[_Record]]) -> None:
        self.inputs = inputs
        self.pages = pages

    @classmethod
    def load(cls, path: Path) -> SyncTexData:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            return cls.parse(handle.read())

    @classmethod
    def parse(cls, text: str) -> SyncTexData:
        inputs: dict[int, str] = {}
        pages: dict[int, list[_Record]] = {}
        unit, magnification, x_offset, y_offset = 1.0, 1000.0, 0.0, 0.0
        header = {"Unit:": "unit", "Magnification:": "mag", "X Offset:": "x", "Y Offset:": "y"}
        current: list[_Record] | None = None
        for row in text.splitlines():
            if current is None:
                if row.startswith("Input:"):
                    tag, _, name = row[len("Input:"):].partition(":")
                    if tag.isdigit():
                        inputs[int(tag)] = name
                    continue
                key = next((k for k in header if row.startswith(k)), None)
                if key:
                    try:
                        value = float(row[len(key):])
                    except ValueError:
                        continue
                    if header[key] == "unit":
                        unit = value
                    elif header[key] == "mag":
                        magnification = value or 1000.0
                    elif header[key] == "x":
                        x_offset = value
                    else:
                        y_offset = value
                    continue
            if row.startswith("{") and row[1:].isdigit():
                current = pages.setdefault(int(row[1:]), [])
                continue
            if row.startswith("}") and row[1:].isdigit():
                current = None
                continue
            if current is None:
                continue
            match = _RECORD_RE.match(row)
            if not match:
                continue
            factor = unit * magnification / 1000.0 * _SP_TO_BP
            kind, tag, line, x, y, w, h, d = match.groups()
            current.append(_Record(kind, int(tag), int(line), (int(x) + x_offset) * factor,
                                   (int(y) + y_offset) * factor, int(w or 0) * factor,
                                   int(h or 0) * factor, int(d or 0) * factor))
        return cls(inputs, pages)

    def lookup(self, page: int, x: float, y: float) -> tuple[str, int] | None:
        """``(input name, line)`` for a 0-based page and a top-left point in PDF points."""
        records = [r for r in self.pages.get(page + 1, []) if r.line > 0 and r.tag in self.inputs]
        boxes = [r for r in records if r.kind in _BOX_KINDS and r.width > 0]
        lines = [b for b in boxes if b.kind in "(h"]  # horizontal boxes: text lines, images
        if not boxes:
            return None

        def smallest(candidates: list[_Record]) -> _Record:
            return min(candidates, key=lambda b: (b.width * (b.height + b.depth), b.kind != "h"))

        containing = [b for b in lines if b.contains(x, y)]
        nearest = min(lines, key=lambda b: b.distance(x, y), default=None)
        if containing:
            box = smallest(containing)
        elif nearest is not None and nearest.distance(x, y) <= _NEAR_BP:
            box = nearest
        else:  # empty space inside a float or the page: the enclosing vertical box
            outer = [b for b in boxes if b.contains(x, y)]
            if not outer:
                return None
            box = smallest(outer)
        # characters/glue on the box's baseline; kerns mark where something *ended*, so skip them
        points = [r for r in records if r.kind in _POINT_KINDS and abs(r.y - box.y) < 0.01
                  and box.x <= r.x < box.x + box.width]
        # a paragraph's line box carries the line where the paragraph *ended*; its words know better
        words = [p for p in points if (p.tag, p.line) != (box.tag, box.line)]
        points = words or points
        before = [p for p in points if p.x <= x]
        best = max(before, key=lambda p: p.x) if before else (min(points, key=lambda p: p.x) if points else box)
        return self.inputs[best.tag], best.line


_CACHE: dict[str, tuple[int, SyncTexData]] = {}
_CACHE_LOCK = threading.Lock()


def _parsed(path: Path) -> SyncTexData:
    stamp = path.stat().st_mtime_ns
    with _CACHE_LOCK:
        cached = _CACHE.get(str(path))
        if cached and cached[0] == stamp:
            return cached[1]
    data = SyncTexData.load(path)
    with _CACHE_LOCK:
        _CACHE.clear()  # only the PDF on screen matters
        _CACHE[str(path)] = (stamp, data)
    return data


def locate(pdf: Path, page: int, x: float, y: float, base: Path, tool: str | None) -> SourceLocation | None:
    """Source line for a point of ``pdf`` (0-based ``page``); relative inputs resolve against ``base``.

    Uses the built-in reader (it picks the line under the pointer more consistently
    than ``synctex edit`` does around floats) and the ``synctex`` program only when
    the data file cannot be read.
    """
    data_file = synctex_file(pdf)
    if data_file is None:
        return None
    try:
        hit = _parsed(data_file).lookup(page, x, y)
    except (OSError, EOFError, ValueError):  # unreadable here: let the synctex program try
        return query_tool(tool, pdf, page, x, y, base) if tool else None
    # an empty spot stays empty (``synctex edit`` would jump to some far-away line)
    return SourceLocation(_resolve(hit[0], base), hit[1]) if hit else None
