"""Add Figures / Add References: helpers and end-to-end runs against a local remote."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

import pytest
from git import Repo
from PIL import Image

from core.asset_workflows import AddFiguresWorkflow, AddReferencesWorkflow
from core.figures import (
    FigureError, check_image, convert_to_png, ensure_graphicx, graphics_dir, include_path,
    insert_at_section_end, unique_label, unique_rel_path,
)
from core.literature import ScholarlySearch
from core.references import classify, declare_bib_file, split_identifiers
from tests.conftest import MAIN_TEX
from tests.test_engine_integration import build, text_msg
from tests.test_literature import CROSSREF_RESULT, OPENALEX_RESULTS


def make_image(path: Path, fmt: str = "PNG", size=(64, 40)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path, fmt)
    return path


# ---------------------------------------------------------------------- #
# Figure helpers
# ---------------------------------------------------------------------- #
def test_check_image_and_conversion(tmp_path):
    png = make_image(tmp_path / "a.png")
    assert check_image(png) == []
    tif = make_image(tmp_path / "scan.tif", "TIFF")
    assert "converted to PNG" in check_image(tif)[0]
    converted = convert_to_png(tif, tmp_path / "work")
    assert converted.suffix == ".png" and Image.open(converted).size == (64, 40)
    (tmp_path / "plot.svg").write_text("<svg/>")
    with pytest.raises(FigureError, match="Export it as PDF"):
        check_image(tmp_path / "plot.svg")
    with pytest.raises(FigureError, match="not found"):
        check_image(tmp_path / "missing.png")


def test_destination_and_labels(tmp_path):
    assert graphics_dir(tmp_path, r"\graphicspath{{./img/}{other/}}") == "img"
    (tmp_path / "Figures").mkdir()
    assert graphics_dir(tmp_path, "") == "Figures"
    (tmp_path / "Figures" / "loss.png").write_bytes(b"x")
    taken: set[str] = set()
    assert unique_rel_path(tmp_path, "Figures", "loss", ".png", taken) == "Figures/loss-2.png"
    assert unique_rel_path(tmp_path, "Figures", "loss", ".png", taken) == "Figures/loss-3.png"
    assert unique_label("loss", [r"\label{fig:loss}"], set()) == "fig:loss-2"
    assert include_path("figures/a.png", "main.tex") == "figures/a.png"
    assert include_path("paper/figures/a.png", "paper/main.tex") == "figures/a.png"
    assert include_path("figures/a.png", "paper/main.tex") == "../figures/a.png"


def test_graphicx_and_insertion():
    assert ensure_graphicx(r"\documentclass{article}\usepackage{graphicx}") is None
    added = ensure_graphicx(MAIN_TEX)
    assert added.index(r"\usepackage{graphicx}") > added.index(r"\usepackage{amsmath}")
    assert added.index(r"\usepackage{graphicx}") < added.index(r"\begin{document}")
    new = insert_at_section_end(MAIN_TEX, "Introduction", "FIGURE")
    assert new.index("FIGURE") < new.index(r"\subsection{Contributions}")
    assert new.index("FIGURE") > new.index(r"\end{equation}")


# ---------------------------------------------------------------------- #
# Reference helpers
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(("text", "kind", "value"), [
    ("10.1038/S41586-021-03819-2", "doi", "10.1038/s41586-021-03819-2"),
    ("https://doi.org/10.1000/xyz.1", "doi", "10.1000/xyz.1"),
    ("arXiv:2401.01234v2", "arxiv", "2401.01234"),
    ("https://arxiv.org/abs/1710.10903", "arxiv", "1710.10903"),
    ("W2741809807", "openalex", "W2741809807"),
    ("https://example.com/paper", "url", "https://example.com/paper"),
    ("Attention Is All You Need", "title", "Attention Is All You Need"),
])
def test_classify(text, kind, value):
    assert classify(text) == (kind, value)


def test_split_and_declare_bib():
    assert split_identifiers("a\n\n- b\na\n") == ["a", "b"]
    assert r"\bibliography{refs,references}" in declare_bib_file(MAIN_TEX, "references.bib")
    assert declare_bib_file(MAIN_TEX, "refs.bib") is None
    biblatex = "\\documentclass{article}\n\\usepackage{biblatex}\n\\addbibresource{a.bib}\n\\begin{document}\n\\end{document}\n"
    assert "\\addbibresource{a.bib}\n\\addbibresource{new.bib}\n" in declare_bib_file(biblatex, "new.bib")
    plain = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
    assert "\\bibliographystyle{plain}\n\\bibliography{new}\n\n\\end{document}" in declare_bib_file(plain, "new.bib")


# ---------------------------------------------------------------------- #
# End-to-end
# ---------------------------------------------------------------------- #
def test_add_figures_end_to_end(tmp_path, git_project):
    remote, _ = git_project
    first = make_image(tmp_path / "Downloads" / "Loss Curve.png")
    second = make_image(tmp_path / "Desktop" / "results" / "confusion.jpg", "JPEG")
    seen_content = []

    def responder(system, messages, tools=None, max_tokens=None):
        content = messages[0]["content"]
        seen_content.append(content)
        label = "fig:loss-curve" if "Loss Curve.png" in content[-1]["text"] else "fig:confusion"
        return text_msg(f"<caption>Training loss over 100 epochs.</caption>"
                        f"<sentence>Figure~\\ref{{{label}}} shows the result.</sentence>")

    engine, approver = build(tmp_path, remote, SimpleNamespace(create=responder))
    try:
        result = AddFiguresWorkflow(engine, files=[str(first), str(second)], section_title="Method").run()
    finally:
        approver.stop()

    assert seen_content[0][0]["type"] == "image"  # Claude saw the picture
    remote_repo = Repo(remote)
    feature = next(h.name for h in remote_repo.heads if h.name.startswith("agent/"))
    files = remote_repo.git.ls_tree("-r", "--name-only", feature).split()
    assert {"figures/loss-curve.png", "figures/confusion.jpg"} <= set(files)
    tex = remote_repo.git.show(f"{feature}:main.tex")
    assert r"\usepackage{graphicx}" in tex
    assert r"\includegraphics[width=0.8\linewidth]{figures/loss-curve.png}" in tex
    assert r"Figure~\ref{fig:confusion} shows the result." in tex
    assert tex.index(r"\label{fig:loss-curve}") < tex.index(r"\bibliographystyle")
    assert "figures" in result.summary or "pushed" in result.summary


def test_rejecting_image_drops_the_tex_change(tmp_path, git_project):
    remote, _ = git_project
    image = make_image(tmp_path / "pic.png")
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None), approve=False)
    try:
        AddFiguresWorkflow(engine, files=[str(image)], section_title="Method", caption="A picture.",
                           draft_captions=False, reference_sentence=False).run()
    finally:
        approver.stop()
    clone = Repo(tmp_path / "clone")
    assert not clone.is_dirty(untracked_files=True)
    assert [h.name for h in Repo(remote).heads] == ["master"]


class ReferenceHTTP:
    """Canned OpenAlex/Crossref responses for single-work and search lookups."""

    def __call__(self, url: str) -> bytes:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if parsed.hostname == "api.openalex.org" and "/works/doi:" in path:
            doi = path.split("doi:", 1)[1]
            for item in OPENALEX_RESULTS["results"]:
                if item["doi"].lower().endswith(doi):
                    return json.dumps(item).encode()
            raise AssertionError(url)
        if parsed.hostname == "api.openalex.org":
            return json.dumps(OPENALEX_RESULTS).encode()
        if parsed.hostname == "api.crossref.org":
            return json.dumps(CROSSREF_RESULT).encode()
        raise AssertionError(url)


def test_add_references_end_to_end(tmp_path, git_project):
    remote, _ = git_project
    extra_bib = tmp_path / "Documents" / "exported.bib"
    extra_bib.parent.mkdir(parents=True)
    extra_bib.write_text("@book{knuth1984, title={The TeXbook}, author={Knuth, Donald}, year={1984}}\n"
                         "@article{kipf2017, title={Semi-Supervised Classification with Graph Convolutional "
                         "Networks}, year={2017}}\n")
    identifiers = "\n".join([
        "10.1000/gnn.2024.7",                                           # new, via OpenAlex
        "https://doi.org/10.1038/s41586-021-03819-2",                    # already cited as jumper2021
        "Equivariant Graph Networks for Protein Design and Folding",     # same paper as the DOI (dedup)
        "A title that does not exist anywhere",                          # unresolved
    ])
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None),
                             literature=ScholarlySearch(fetch=ReferenceHTTP()))
    try:
        result = AddReferencesWorkflow(engine, identifiers=identifiers, bib_files=[str(extra_bib)],
                                       cite_section="Method", write_sentence=False).run()
    finally:
        approver.stop()

    report = result.artifacts[0].read_text(encoding="utf-8")
    assert "`muller2024equivariant`" in report
    assert "→ `jumper2021`" in report and "→ `kipf2017`" in report
    assert "A title that does not exist anywhere" in report
    remote_repo = Repo(remote)
    feature = next(h.name for h in remote_repo.heads if h.name.startswith("agent/"))
    bib = remote_repo.git.show(f"{feature}:refs.bib")
    assert bib.count("@article{muller2024equivariant,") == 1 and "@book{knuth1984" in bib
    assert "doi = {10.1000/gnn.2024.7}" in bib
    tex = remote_repo.git.show(f"{feature}:main.tex")
    assert r"\cite{muller2024equivariant,knuth1984}" in tex


def test_add_references_creates_new_bib_when_existing_is_read_only(tmp_path, git_project):
    remote, _ = git_project
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None),
                             literature=ScholarlySearch(fetch=ReferenceHTTP()))
    engine.paper.spec.read_only = "refs.bib"
    try:
        AddReferencesWorkflow(engine, identifiers="10.1000/gnn.2024.7").run()
    finally:
        approver.stop()
    remote_repo = Repo(remote)
    feature = next(h.name for h in remote_repo.heads if h.name.startswith("agent/"))
    assert "muller2024equivariant" in remote_repo.git.show(f"{feature}:references.bib")
    assert r"\bibliography{refs,references}" in remote_repo.git.show(f"{feature}:main.tex")
    assert remote_repo.git.show(f"{feature}:refs.bib") == remote_repo.git.show("master:refs.bib")
