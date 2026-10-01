"""Reading the text out of a PDF, for summarising a paper you already have.

The text is extracted here rather than sending the file to Claude, which keeps a
summary to a few thousand tokens instead of tens of thousands. The cost is that
figures are not seen and tables arrive flattened - and that a scanned PDF with no
text layer yields nothing, which :func:`read_pdf` reports rather than hiding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_CHARS = 60_000        # about 15k tokens: a long paper, without an alarming bill
MAX_FILE_MB = 50
MIN_USEFUL_CHARS = 400    # less than this and the PDF is almost certainly scanned images
# A DOI as it appears in a paper's header or footer.
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
TRAILING_PUNCTUATION = ".,;:)]}>"


class PdfTextError(ValueError):
    """A PDF cannot be read (missing, too large, or no text layer)."""


@dataclass
class PdfText:
    """What was read out of one PDF."""

    path: Path
    text: str
    pages: int
    truncated: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    def doi(self) -> str:
        """The first DOI printed in the first few pages, lower-cased, or ``""``.

        Only used to *look up* verified metadata - never to assert a DOI the
        search tools did not confirm.
        """
        match = DOI_RE.search(self.text[:8000])
        return match.group(0).rstrip(TRAILING_PUNCTUATION).lower() if match else ""


def read_pdf(path: Path) -> PdfText:
    """Extract the text of ``path``.

    Raises:
        PdfTextError: with a plain reason the user can act on.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfTextError(f"{path} is not a file.")
    if path.suffix.lower() != ".pdf":
        raise PdfTextError(f"{path.name}: only PDF files can be summarised from your computer.")
    size_mb = path.stat().st_size / 1_000_000
    if size_mb > MAX_FILE_MB:
        raise PdfTextError(f"{path.name} is {size_mb:.0f} MB - too large to read (limit {MAX_FILE_MB} MB).")

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:      # pragma: no cover - pypdfium2 is in requirements.txt
        raise PdfTextError("Reading PDFs needs the pypdfium2 package.") from exc

    parts: list[str] = []
    total = 0
    try:
        document = pdfium.PdfDocument(str(path))
        pages = len(document)
        for page in document:
            page_text = page.get_textpage().get_text_range() or ""
            parts.append(page_text)
            total += len(page_text)
            if total >= MAX_CHARS:
                break
    except PdfTextError:
        raise
    except Exception as exc:        # noqa: BLE001 - PDFium raises its own types
        raise PdfTextError(f"{path.name} could not be read: {exc}") from exc

    text = _tidy("\n".join(parts))
    if len(text) < MIN_USEFUL_CHARS:
        raise PdfTextError(
            f"{path.name} has almost no text to read ({len(text)} characters). It is probably a scan of "
            "the printed pages; a PDF with real text is needed, or use the paper's DOI instead.")
    return PdfText(path=path, text=text[:MAX_CHARS], pages=pages, truncated=total > MAX_CHARS)


def _tidy(text: str) -> str:
    """Join the hyphenated line breaks and collapse the runs of blank lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # "experi-\nment" -> "experiment"
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
