"""PDF previews: the current paper, and the paper *with proposed changes applied*.

Proposed changes are compiled in a mirror of the repository (outside it), so the
real checkout is untouched until the reviewer approves. Changed pages are found
by comparing the text of each page with the current PDF.
"""

from __future__ import annotations

import difflib
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from config import LatexSettings
from core.compiler import CompilerNotFoundError, CompileResult, LatexCompiler, extract_errors, new_errors
from core.events import ProposedChange

KIND_CURRENT = "current"      # what is in the local repository now
KIND_PROPOSED = "proposed"    # current + changes awaiting approval
KIND_APPROVED = "approved"    # approved and compiled, not pushed yet
_SKIP_DIRS = {".git", "__pycache__"}
# PDFium is not thread-safe: every PDFium call in the app must hold this lock.
PDFIUM_LOCK = threading.RLock()


@dataclass
class PreviewResult:
    kind: str
    label: str
    success: bool
    pdf_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    changed_pages: list[int] = field(default_factory=list)  # 0-based pages that differ from the current PDF
    summary: str = ""
    added_errors: list[str] = field(default_factory=list)  # proposed only: errors the changes introduce


def page_texts(pdf_path: Path) -> list[str]:
    """Whitespace-normalised text of every page ([] if the PDF cannot be read)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover - runtime dependency
        return []
    try:
        data = pdf_path.read_bytes()
    except OSError:
        return []
    texts = []
    with PDFIUM_LOCK:
        try:
            document = pdfium.PdfDocument(data)
        except pdfium.PdfiumError:
            return []
        try:
            for index in range(len(document)):
                page = document[index]
                textpage = page.get_textpage()
                texts.append(" ".join(textpage.get_text_range().split()))
                textpage.close()
                page.close()
        finally:
            document.close()
    return texts


def image_at(pdf_path: Path, page: int, x: float, y: float) -> bool:
    """Is there an image (or an included PDF graphic) under a top-left point of ``page``?"""
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError:  # pragma: no cover - runtime dependency
        return False
    try:
        data = pdf_path.read_bytes()
    except OSError:
        return False
    kinds = [pdfium_c.FPDF_PAGEOBJ_IMAGE, pdfium_c.FPDF_PAGEOBJ_FORM]
    with PDFIUM_LOCK:
        try:
            document = pdfium.PdfDocument(data)
        except pdfium.PdfiumError:
            return False
        try:
            if not 0 <= page < len(document):
                return False
            handle = document[page]
            height = handle.get_height()
            for obj in handle.get_objects(filter=kinds, max_depth=0):
                left, bottom, right, top = obj.get_bounds()
                if left <= x <= right and bottom <= height - y <= top and (right - left) * (top - bottom) > 4:
                    return True
            return False
        finally:
            document.close()


MAX_WORDS_FOR_WORD_DIFF = 60_000


def _body_words(text: str, page: int) -> list[str]:
    """Words of a page without its page number (which moves around when text reflows)."""
    words = text.split()
    number = str(page + 1)
    if words and words[-1] == number:
        words = words[:-1]
    if words and words[0] == number:
        words = words[1:]
    return words


def changed_pages(old_pdf: Path | None, new_pdf: Path | None) -> list[int]:
    """Pages of ``new_pdf`` containing text that differs from ``old_pdf``.

    Words are compared across the whole document, so text that merely moved to
    the next page (reflow) does not mark that page as changed.
    """
    if new_pdf is None or not new_pdf.exists():
        return []
    new = page_texts(new_pdf)
    old = page_texts(old_pdf) if old_pdf is not None and old_pdf.exists() else []
    if not old:
        return []
    new_words = [(word, page) for page, text in enumerate(new) for word in _body_words(text, page)]
    old_words = [word for page, text in enumerate(old) for word in _body_words(text, page)]
    pages: set[int] = set()
    if len(new_words) + len(old_words) > MAX_WORDS_FOR_WORD_DIFF:  # very long documents: page-level diff
        matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                pages.update(range(j1, j2))
        return sorted(pages)
    matcher = difflib.SequenceMatcher(None, old_words, [w for w, _p in new_words], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            pages.update(new_words[j][1] for j in range(j1, j2))
        elif tag == "delete" and new_words:  # removed text: mark the page where it used to continue
            pages.add(new_words[min(j1, len(new_words) - 1)][1])
    if len(new) > len(old):
        pages.update(range(len(old), len(new)))
    return sorted(pages)


def mirror_tree(source: Path, target: Path) -> None:
    """Make ``target`` an up-to-date copy of ``source`` (without .git), copying only what changed."""
    target.mkdir(parents=True, exist_ok=True)
    wanted: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel_dir = Path(dirpath).relative_to(source)
        (target / rel_dir).mkdir(parents=True, exist_ok=True)
        wanted.add(target / rel_dir)
        for name in filenames:
            src, dst = Path(dirpath) / name, target / rel_dir / name
            wanted.add(dst)
            stat = src.stat()
            # copy2 keeps mtimes, so any difference means the mirror copy is stale (or was edited for a preview)
            if not dst.exists() or dst.stat().st_size != stat.st_size or dst.stat().st_mtime_ns != stat.st_mtime_ns:
                shutil.copy2(src, dst)
    for dirpath, dirnames, filenames in os.walk(target, topdown=False):
        for name in filenames:
            path = Path(dirpath) / name
            if path not in wanted:
                path.unlink()
        if Path(dirpath) not in wanted and Path(dirpath) != target:
            shutil.rmtree(dirpath, ignore_errors=True)


def source_signature(root: Path) -> tuple:
    """Cheap fingerprint of the paper's source files (for auto-recompile)."""
    newest, count = 0.0, 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            try:
                newest = max(newest, (Path(dirpath) / name).stat().st_mtime)
                count += 1
            except OSError:
                continue
    return newest, count


class PreviewBuilder:
    """Compiles previews into ``<build_dir>/_preview`` (never inside the repository)."""

    _locks: dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, settings: LatexSettings, build_dir: Path) -> None:
        self.settings = settings
        self.base = build_dir / "_preview"
        with self._locks_guard:
            self._lock = self._locks.setdefault(str(self.base).lower(), threading.Lock())

    @property
    def available(self) -> bool:
        return bool(self.settings.latexmk_path or self.settings.pdflatex_path)

    def current_pdf(self, root: Path, main_rel: str) -> Path:
        return self.base / "current" / root.name / f"{Path(main_rel).stem}.pdf"

    def _compile(self, build_root: Path, main_tex: Path, project_root: Path) -> CompileResult:
        try:
            return LatexCompiler(self.settings, build_root).compile(main_tex, project_root)
        except CompilerNotFoundError as exc:
            return CompileResult(False, None, -1, [str(exc)])

    def current_errors(self, root: Path, main_rel: str) -> list[str]:
        """LaTeX errors of the last compile of the current version (read back from its log)."""
        log = self.current_pdf(root, main_rel).with_suffix(".log")
        return extract_errors(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else []

    def _signature_file(self, root: Path) -> Path:
        return self.base / "current" / f"{root.name}.signature"

    def current_is_fresh(self, root: Path, main_rel: str) -> bool:
        sig = self._signature_file(root)
        return (self.current_pdf(root, main_rel).exists() and sig.exists()
                and sig.read_text(encoding="utf-8") == repr(source_signature(root)))

    def current(self, root: Path, main_rel: str) -> PreviewResult:
        """Compile the repository as it is on disk."""
        with self._lock:
            signature = repr(source_signature(root))
            result = self._compile(self.base / "current", root / main_rel, root)
            if result.success:
                self._signature_file(root).write_text(signature, encoding="utf-8")
        return PreviewResult(KIND_CURRENT, "Current version", result.success, result.pdf_path,
                             result.errors, summary=result.summary())

    def proposed(self, root: Path, main_rel: str, changes: list[ProposedChange]) -> PreviewResult:
        """Compile a mirror of the repository with ``changes`` applied."""
        if not self.current_is_fresh(root, main_rel):
            self.current(root, main_rel)  # baseline for changed-page detection
        with self._lock:
            src = self.base / "src" / root.name
            mirror_tree(root, src)
            for change in changes:
                if change.moves:
                    for source_rel, target_rel in change.moves:
                        source, target = src / source_rel, src / target_rel
                        if source.is_file() and source_rel != target_rel:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(source), str(target))
                    continue
                target = src / change.rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                if change.source_file is not None:
                    shutil.copy2(change.source_file, target)
                else:
                    target.write_text(change.proposed, encoding="utf-8")
            result = self._compile(self.base / "proposed", src / main_rel, src)
        pages = changed_pages(self.current_pdf(root, main_rel), result.pdf_path) if result.success else []
        label = f"Preview of {len(changes)} proposed change(s) - not approved yet"
        added = new_errors(self.current_errors(root, main_rel), result.errors)
        return PreviewResult(KIND_PROPOSED, label, result.success, result.pdf_path,
                             result.errors, pages, result.summary(), added)

    def approved(self, compile_result: CompileResult, root: Path, main_rel: str) -> PreviewResult:
        """Describe the compile check run on the real checkout after approval."""
        pages = changed_pages(self.current_pdf(root, main_rel), compile_result.pdf_path)
        return PreviewResult(KIND_APPROVED, "Approved changes - compiled, not pushed yet", compile_result.success,
                             compile_result.pdf_path, compile_result.errors, pages, compile_result.summary())

