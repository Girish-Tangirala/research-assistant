"""Click-to-edit: SyncTeX lookups, source classification and replacing figures."""

from __future__ import annotations

import gzip
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Actor, Repo

from core.agent_engine import AgentError
from core.asset_workflows import AddFiguresWorkflow
from core.events import ProposedChange
from core.paper import AppliedChanges, ChangeConflictError, ReadOnlyFileError, apply_changes
from core.source_map import (
    KIND_FIGURE, KIND_HEADING, KIND_MATH, KIND_PREAMBLE, KIND_TABLE, KIND_TEXT, ClickLookupError, caption_span,
    classify, find_figure, figures_in, list_figures, repo_relative, resolve_graphic, target_for_click,
)
from core.synctex import SyncTexData, locate
from tests.test_asset_workflows import make_image
from tests.test_engine_integration import build, text_msg
from tests.test_preview import needs_tex, tex_settings

SYNCTEX = """SyncTeX Version:1
Input:1:/p/main.tex
Input:2:/p/intro.tex
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
!100
{1
[1,20:0,50000000:40000000,50000000,0
(2,5:6553600,6553600:13107200,655360,0
x2,5:6553600,6553600
x2,3:6900000,6553600
x2,4:9830400,6553600
k2,4:19660800,6553600:1000
)
(1,9:6553600,13107200:6553600,3276800,0
g1,9:13107200,13107200
)
]
}1
Postamble:
"""

PAPER = r"""\documentclass{article}
\usepackage{graphicx}
\graphicspath{{img/}}
\begin{document}
\section{Introduction}
Intro text \cite{a,b} here.
\subsection{Scope}
Scope text.
\begin{equation}
  E = mc^2
\end{equation}
\begin{figure}[h]
  \centering
  \includegraphics[width=0.4\linewidth]{plot}
  \includegraphics[width=0.4\linewidth]{figures/other.png}
  \caption{Two \emph{plots}.}
  \label{fig:plots}
\end{figure}
\begin{table}[h]
  \begin{tabular}{cc} 1 & 2 \\ \end{tabular}
\end{table}
\section{Method}
\input{sections/method}
\includegraphics{figures/other.png}
\end{document}
"""


def paper_tree(root: Path) -> Path:
    (root / "sections").mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(PAPER, encoding="utf-8")
    (root / "sections" / "method.tex").write_text("Method text.\n", encoding="utf-8")
    make_image(root / "img" / "plot.png")
    make_image(root / "figures" / "other.png")
    return root


# ---------------------------------------------------------------------- #
# SyncTeX reader
# ---------------------------------------------------------------------- #
def test_synctex_reader_picks_the_line_under_the_pointer(tmp_path):
    data = SyncTexData.parse(SYNCTEX)
    assert data.lookup(0, 120, 95) == ("/p/intro.tex", 3)       # first word of the line
    assert data.lookup(0, 100, 95) == ("/p/intro.tex", 3)       # not 5, where the paragraph ended
    assert data.lookup(0, 160, 95) == ("/p/intro.tex", 4)       # after the second character record
    assert data.lookup(0, 150, 170) == ("/p/main.tex", 9)       # inside the image box
    assert data.lookup(0, 140, 104) == ("/p/intro.tex", 3)      # just below the line: still that line
    assert data.lookup(0, 150, 130) == ("/p/main.tex", 20)      # empty space: the enclosing box
    assert data.lookup(1, 150, 130) is None

    pdf = tmp_path / "out" / "main.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF")
    assert locate(pdf, 0, 120, 95, tmp_path, None) is None     # no SyncTeX data
    with gzip.open(pdf.with_suffix(".synctex.gz"), "wt", encoding="utf-8") as handle:
        handle.write(SYNCTEX.replace("/p/intro.tex", "intro.tex"))
    found = locate(pdf, 0, 120, 95, tmp_path, None)
    assert found.path == tmp_path / "intro.tex" and found.line == 3


def test_repo_relative(tmp_path):
    root, mirror = tmp_path / "repo", tmp_path / "mirror" / "repo"
    assert repo_relative(mirror / "sections" / "a.tex", [mirror, root]) == "sections/a.tex"
    assert repo_relative(root / "main.tex", [mirror, root]) == "main.tex"
    assert repo_relative(tmp_path / "texmf" / "article.cls", [mirror, root]) is None


# ---------------------------------------------------------------------- #
# Classification
# ---------------------------------------------------------------------- #
def line_of(text: str, needle: str) -> int:
    return text[:text.index(needle)].count("\n") + 1


def test_classify_kinds_and_sections(tmp_path):
    root = paper_tree(tmp_path / "paper")
    assert classify(root, "main.tex", 2).kind == KIND_PREAMBLE
    text = classify(root, "main.tex", line_of(PAPER, "Intro text"))
    assert (text.kind, text.section, text.cite_keys) == (KIND_TEXT, "Introduction", ["a", "b"])
    assert classify(root, "main.tex", line_of(PAPER, "\\section{Method}")).kind == KIND_HEADING
    assert classify(root, "main.tex", line_of(PAPER, "Scope text")).section == "Scope"
    assert classify(root, "main.tex", line_of(PAPER, "E = mc")).kind == KIND_MATH
    assert classify(root, "main.tex", line_of(PAPER, "1 & 2")).kind == KIND_TABLE

    figure = classify(root, "main.tex", line_of(PAPER, "\\caption"))
    assert figure.kind == KIND_FIGURE and figure.section == "Scope"
    assert (figure.figure.label, figure.figure.caption) == ("fig:plots", r"Two \emph{plots}.")
    assert [g.name for g in figure.figure.graphics] == ["plot", "figures/other.png"]
    second = classify(root, "main.tex", line_of(PAPER, "{figures/other.png}"))
    assert second.figure.graphic == "figures/other.png"

    included = classify(root, "sections/method.tex", 1)
    assert (included.kind, included.section) == (KIND_TEXT, "Method")
    bare_line = line_of(PAPER, "\\includegraphics{figures/other.png}")
    assert classify(root, "main.tex", bare_line).kind == KIND_TEXT
    bare = classify(root, "main.tex", bare_line, on_image=True)
    assert bare.kind == KIND_FIGURE and bare.figure.graphic == "figures/other.png" and bare.figure.label == ""


def test_figures_lookup_and_graphics_resolution(tmp_path):
    root = paper_tree(tmp_path / "paper")
    figures = figures_in(PAPER, "main.tex")
    assert len(figures) == 1 and len(list_figures(root)) == 1
    span = caption_span(PAPER, figures[0])
    assert PAPER[span[0]:span[1]] == r"Two \emph{plots}."
    again = find_figure(PAPER, "main.tex", "fig:plots", "figures/other.png")
    assert again.graphic == "figures/other.png"
    bare = find_figure(PAPER, "main.tex", "", "figures/other.png", line=30)
    assert bare.env == "" and bare.start_line == line_of(PAPER, "\\includegraphics{figures/other.png}")
    assert find_figure(PAPER, "main.tex", "", "missing") is None
    assert resolve_graphic(root, "main.tex", PAPER, "plot") == "img/plot.png"          # via \graphicspath
    assert resolve_graphic(root, "main.tex", PAPER, "figures/other.png") == "figures/other.png"
    assert resolve_graphic(root, "main.tex", PAPER, "nothing") is None


@needs_tex
def test_click_on_compiled_pdf(tmp_path):
    import pypdfium2 as pdfium

    from core.compiler import LatexCompiler

    root = paper_tree(tmp_path / "paper")
    result = LatexCompiler(tex_settings(), tmp_path / "build").compile(root / "main.tex", root)
    assert result.success, result.summary()
    document = pdfium.PdfDocument(str(result.pdf_path))
    page = document[0]
    height = page.get_height()
    image = next(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]))
    left, bottom, right, top = image.get_bounds()
    textpage = page.get_textpage()
    searcher = textpage.search("Intro text")
    index, _count = searcher.get_next()
    char = textpage.get_charbox(index)
    document.close()

    mirror = tmp_path / "unused-mirror"
    hit = target_for_click(result.pdf_path, 0, (left + right) / 2, height - (bottom + top) / 2, root, root, None)
    assert hit.kind == KIND_FIGURE and hit.figure.label == "fig:plots"
    text = target_for_click(result.pdf_path, 0, char[0] + 2, height - (char[1] + char[3]) / 2, mirror, root, None)
    assert (text.rel_path, text.section) == ("main.tex", "Introduction")

    result.pdf_path.with_suffix(".synctex.gz").unlink()
    with pytest.raises(ClickLookupError, match="Recompile"):
        target_for_click(result.pdf_path, 0, 100, 100, root, root, None)


# ---------------------------------------------------------------------- #
# Replacing figures
# ---------------------------------------------------------------------- #
@pytest.fixture
def figure_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    Repo.init(remote, bare=True, initial_branch="master")
    seed = paper_tree(tmp_path / "seed")
    repo = Repo.init(seed, initial_branch="master")
    repo.git.add(A=True)
    actor = Actor("Test", "test@example.com")
    repo.index.commit("Initial", author=actor, committer=actor)
    repo.create_remote("origin", str(remote))
    repo.git.push("origin", "master")
    return remote


def run_replace(tmp_path, remote, image, llm=None, **params):
    engine, approver = build(tmp_path, remote, llm or SimpleNamespace(create=None))
    try:
        AddFiguresWorkflow(engine, mode="replace", files=[str(image)], replace_tex="main.tex",
                           replace_line=14, **params).run()
    finally:
        approver.stop()
    remote_repo = Repo(remote)
    return remote_repo, next(h.name for h in remote_repo.heads if h.name.startswith("agent/"))


def test_replace_same_type_overwrites_file_in_place(tmp_path, figure_remote):
    new = make_image(tmp_path / "Downloads" / "better plot.png", size=(90, 60))
    repo, branch = run_replace(tmp_path, figure_remote, new, replace_graphic="plot", replace_label="fig:plots")
    changed = repo.git.diff("--name-only", "master", branch).split()
    assert changed == ["img/plot.png"]
    assert repo.git.show(f"{branch}:main.tex") == repo.git.show("master:main.tex")


def test_replace_other_type_repoints_figure_and_sets_caption(tmp_path, figure_remote):
    new = make_image(tmp_path / "scan.jpg", "JPEG")
    repo, branch = run_replace(tmp_path, figure_remote, new, replace_graphic="figures/other.png",
                               replace_label="fig:plots", caption="An updated \\emph{scan}.")
    assert sorted(repo.git.diff("--name-only", "master", branch).split()) == ["figures/other.jpg", "main.tex"]
    tex = repo.git.show(f"{branch}:main.tex")
    assert r"\includegraphics[width=0.4\linewidth]{figures/other.jpg}" in tex
    assert r"\includegraphics[width=0.4\linewidth]{plot}" in tex
    assert r"\caption{An updated \emph{scan}.}" in tex
    assert r"\includegraphics{figures/other.png}" in tex   # the bare graphic elsewhere is untouched


def test_replace_with_claude_caption(tmp_path, figure_remote):
    new = make_image(tmp_path / "new.png")
    seen = []

    def responder(system, messages, tools=None, max_tokens=None):
        seen.append(messages[0]["content"])
        return text_msg("<caption>New plots of the \\emph{updated} run.</caption>")

    repo, branch = run_replace(tmp_path, figure_remote, new, llm=SimpleNamespace(create=responder),
                               replace_graphic="plot", replace_label="fig:plots", draft_captions=True)
    assert seen[0][0]["type"] == "image" and "Two \\emph{plots}." in seen[0][1]["text"]
    assert r"\caption{New plots of the \emph{updated} run.}" in repo.git.show(f"{branch}:main.tex")
    assert AddFiguresWorkflow.requires_llm({"mode": "replace", "draft_captions": True})
    assert not AddFiguresWorkflow.requires_llm({"mode": "replace", "draft_captions": True, "caption": "x"})


def test_replace_respects_read_only_and_missing_figures(tmp_path, figure_remote):
    new = make_image(tmp_path / "new.png")
    engine, approver = build(tmp_path, figure_remote, SimpleNamespace(create=None))
    engine.paper.spec.read_only = "img/*"
    try:
        with pytest.raises(ReadOnlyFileError):
            AddFiguresWorkflow(engine, mode="replace", files=[str(new)], replace_tex="main.tex",
                               replace_graphic="plot", replace_label="fig:plots").run()
        with pytest.raises(AgentError, match="not found"):
            AddFiguresWorkflow(engine, mode="replace", files=[str(new)], replace_tex="main.tex",
                               replace_graphic="gone", replace_label="fig:gone").run()
    finally:
        approver.stop()
    assert [h.name for h in Repo(figure_remote).heads] == ["master"]


def test_apply_changes_only_overwrites_when_replacing(tmp_path):
    (tmp_path / "a.png").write_bytes(b"old")
    source = tmp_path / "new.png"
    source.write_bytes(b"new")
    with pytest.raises(ChangeConflictError):
        apply_changes([ProposedChange(tmp_path, "a.png", "", "", "add", source_file=source)],
                      AppliedChanges(tmp_path))
    applied = AppliedChanges(tmp_path)
    change = ProposedChange(tmp_path, "a.png", "", "", "replace", source_file=source, replaces=True)
    apply_changes([change], applied)
    assert (tmp_path / "a.png").read_bytes() == b"new" and applied.created == []
    assert change.unified_diff().startswith("Replace a.png")
