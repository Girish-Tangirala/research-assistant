"""Summarising a paper you already have: reading PDFs, and where the facts came from."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from core.literature import ScholarlySearch
from core.literature_summary import NO_DOI, run_summary, split_identifiers
from core.pdf_text import MIN_USEFUL_CHARS, PdfTextError, read_pdf
from core.workflows import LiteratureReviewWorkflow
from tests.test_engine_integration import build, text_msg

WORK = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1038/s41586-021-03819-2",
        "title": "Highly accurate protein structure prediction", "publication_year": 2021,
        "authorships": [{"author": {"display_name": "John Jumper"}}],
        "primary_location": {"source": {"display_name": "Nature"}},
        "abstract_inverted_index": {"Proteins": [0], "are": [1], "essential": [2]},
        "cited_by_count": 20000, "type": "article"}


class SingleWorkHTTP:
    """OpenAlex answering a one-work lookup; anything else is a miss."""

    def __init__(self, known: bool = True) -> None:
        self.known = known
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if urlparse(url).hostname == "api.openalex.org" and self.known:
            return json.dumps(WORK).encode()
        raise OSError("not found")


# ---------------------------------------------------------------------- #
# Making a real PDF without needing LaTeX
# ---------------------------------------------------------------------- #
def make_pdf(path: Path, lines: list[str]) -> Path:
    """A minimal one-page PDF with a real text layer."""
    shown = "\n".join(f"({line.replace('(', '').replace(')', '')}) Tj 0 -16 Td" for line in lines)
    stream = f"BT /F1 11 Tf 40 760 Td\n{shown}\nET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))
    return path


def paper_pdf(path: Path, doi: str = "", extra: int = 40) -> Path:
    lines = ["Equivariant Graph Networks for Protein Design",
             "Ada Mueller and Bo Li, NeurIPS 2024"]
    if doi:
        lines.append(f"https://doi.org/{doi}")
    lines += [f"Section {i}: we report an accuracy of {80 + i} percent on the held-out set."
              for i in range(extra)]
    return make_pdf(path, lines)


# ---------------------------------------------------------------------- #
# Reading PDFs
# ---------------------------------------------------------------------- #
def test_reads_the_text_of_a_pdf(tmp_path):
    result = read_pdf(paper_pdf(tmp_path / "paper.pdf"))
    assert result.pages == 1
    assert "Equivariant Graph Networks" in result.text
    assert "accuracy of 80 percent" in result.text
    assert not result.truncated


def test_finds_a_doi_printed_in_the_paper(tmp_path):
    with_doi = read_pdf(paper_pdf(tmp_path / "a.pdf", doi="10.1000/gnn.2024.7"))
    assert with_doi.doi() == "10.1000/gnn.2024.7"
    assert read_pdf(paper_pdf(tmp_path / "b.pdf")).doi() == ""


def test_a_pdf_with_no_text_layer_says_so(tmp_path):
    empty = make_pdf(tmp_path / "scan.pdf", ["x"])
    with pytest.raises(PdfTextError, match="almost no text"):
        read_pdf(empty)


def test_unreadable_files_explain_themselves(tmp_path):
    with pytest.raises(PdfTextError, match="is not a file"):
        read_pdf(tmp_path / "missing.pdf")
    (tmp_path / "notes.txt").write_bytes(b"hello")
    with pytest.raises(PdfTextError, match="only PDF files"):
        read_pdf(tmp_path / "notes.txt")


def test_a_long_pdf_is_truncated_and_says_so(tmp_path, monkeypatch):
    import core.pdf_text as pdf_text

    monkeypatch.setattr(pdf_text, "MAX_CHARS", MIN_USEFUL_CHARS + 50)
    result = read_pdf(paper_pdf(tmp_path / "long.pdf", extra=200))
    assert result.truncated and len(result.text) <= MIN_USEFUL_CHARS + 50


def test_identifier_list_drops_blanks_and_duplicates():
    assert split_identifiers(" 10.1/a \n\n10.1/A\n 10.2/b \n") == ["10.1/a", "10.2/b"]


# ---------------------------------------------------------------------- #
# Summarising, and where the facts came from
# ---------------------------------------------------------------------- #
def run(tmp_path, remote, params, http=None, answer="**What it does** - a model."):
    seen: list[str] = []

    def responder(system, messages, tools=None, max_tokens=None):
        seen.append(messages[0]["content"])
        return text_msg(answer)

    search = ScholarlySearch(fetch=http or SingleWorkHTTP())
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=responder), literature=search)
    try:
        result = LiteratureReviewWorkflow(engine, mode="summarise", **params).run()
    finally:
        approver.stop()
    return result, seen, Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_a_link_is_resolved_and_summarised(tmp_path, git_project):
    remote, _ = git_project
    result, prompts, report = run(tmp_path, remote, {"identifiers": "10.1038/s41586-021-03819-2"})

    assert result.success
    assert "Proteins are essential" in prompts[0]          # the abstract was given to Claude
    assert "Highly accurate protein structure prediction" in report
    assert "https://doi.org/10.1038/s41586-021-03819-2" in report
    assert "| openalex |" in report.lower()
    assert "nothing in your paper was changed" in report.lower()


def test_a_pdf_is_summarised_from_its_own_text(tmp_path, git_project):
    remote, _ = git_project
    pdf = paper_pdf(tmp_path / "mine.pdf")
    result, prompts, report = run(tmp_path, remote, {"files": [str(pdf)]})

    assert "accuracy of 80 percent" in prompts[0]           # the file's text, not an abstract
    assert "mine.pdf" in report and NO_DOI in report
    assert "Summarised from your file only" in report
    assert result.success


def test_a_doi_printed_in_a_pdf_is_confirmed_not_assumed(tmp_path, git_project):
    remote, _ = git_project
    pdf = paper_pdf(tmp_path / "withdoi.pdf", doi="10.1038/s41586-021-03819-2")
    _, _, report = run(tmp_path, remote, {"files": [str(pdf)]})

    assert "was confirmed by openalex" in report.lower()
    assert "Highly accurate protein structure prediction" in report   # the index's title, not the file name


def test_an_unconfirmable_doi_in_a_pdf_is_not_quoted(tmp_path, git_project):
    remote, _ = git_project
    pdf = paper_pdf(tmp_path / "bad.pdf", doi="10.9999/nope")
    _, _, report = run(tmp_path, remote, {"files": [str(pdf)]}, http=SingleWorkHTTP(known=False))

    assert "could not be confirmed" in report
    assert "Summarised from your file only" in report
    # the unconfirmed DOI must not appear as if it were a verified link
    assert "https://doi.org/10.9999/nope" not in report


def test_a_paper_that_cannot_be_read_is_reported_not_silently_dropped(tmp_path, git_project):
    remote, _ = git_project
    good = paper_pdf(tmp_path / "good.pdf")
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf at all")
    _, _, report = run(tmp_path, remote, {"files": [str(good), str(tmp_path / "broken.pdf")]})

    assert "Could not be read:" in report and "broken.pdf" in report
    assert "good.pdf" in report


def test_nothing_readable_fails_with_the_reasons(tmp_path, git_project):
    from core.agent_engine import AgentError

    remote, _ = git_project
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    with pytest.raises(AgentError, match="None of the papers could be read"):
        run(tmp_path, remote, {"files": [str(tmp_path / "broken.pdf")]})


def test_it_refuses_an_empty_request_and_an_oversized_one(tmp_path, git_project):
    from core.agent_engine import AgentError
    from core.literature_summary import MAX_PAPERS

    remote, _ = git_project
    with pytest.raises(AgentError, match="Choose a PDF or enter"):
        run(tmp_path, remote, {})
    many = "\n".join(f"10.1/{n}" for n in range(MAX_PAPERS + 1))
    with pytest.raises(AgentError, match="at most"):
        run(tmp_path, remote, {"identifiers": many})


def test_the_summary_never_touches_the_paper(tmp_path, git_project):
    from git import Repo

    remote, _ = git_project
    before = Repo(remote).head.commit.hexsha
    run(tmp_path, remote, {"identifiers": "10.1038/s41586-021-03819-2"})
    assert Repo(remote).head.commit.hexsha == before
    assert [h.name for h in Repo(remote).heads] == ["master"]
