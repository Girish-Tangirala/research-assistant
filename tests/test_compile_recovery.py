"""Overleaf-like compiling: recoverable LaTeX errors still give a PDF, and only new errors block a commit."""

from __future__ import annotations

from dataclasses import replace

import pytest
from git import Repo

import config
from core.agent_engine import AgentError
from core.compiler import LatexCompiler, new_errors
from core.events import ProposedChange
from tests.test_engine_integration import build, text_msg
from tests.test_preview import PDFLATEX, compilable_project, needs_tex, tex_settings

STRAY = r"was introduced. \textcolor{red}" + "\n" + r" \textcolor{blue}{A reviewer note}"


def test_new_errors_ignores_line_numbers_and_counts_repeats():
    before = ["main.tex:249: Argument of \\textcolor has an extra }. l.249 \\textcolor{red}"]
    after = ["main.tex:251: Argument of \\textcolor has an extra }. l.251 \\textcolor{red}",
             "main.tex:300: Undefined control sequence. l.300 \\foo",
             "main.tex:310: Argument of \\textcolor has an extra }. l.310 \\textcolor{red}"]
    assert new_errors(before, after) == after[1:]
    assert new_errors(after, before) == []


@needs_tex
def test_recoverable_error_still_produces_a_pdf(tmp_path):
    root = compilable_project(tmp_path / "paper")
    main = root / "main.tex"
    main.write_text(main.read_text().replace(r"\begin{document}", "\\usepackage{xcolor}\n\\begin{document}")
                    .replace("Protein folding is hard", "Protein folding is hard " + STRAY))
    compiler = LatexCompiler(tex_settings(), tmp_path / "build")
    for _rebuild in range(2):  # the second build rewrites the first one's PDF
        result = compiler.compile(main, root)
        assert result.success and result.pdf_path.exists() and not result.clean
    assert any("textcolor" in e for e in result.errors)
    assert "still produced the PDF" in result.summary()


LATEXMK = config._which("LATEXMK_PATH", "latexmk") if config._which("PERL_PATH", "perl") else None


@pytest.mark.skipif(LATEXMK is None or PDFLATEX is None, reason="latexmk needs Perl")
def test_latexmk_keeps_the_pdf_on_recoverable_errors_and_rebuilds(tmp_path):
    root = compilable_project(tmp_path / "paper")
    main = root / "main.tex"
    main.write_text(main.read_text().replace(r"\begin{document}", "\\usepackage{xcolor}\n\\begin{document}")
                    .replace("Protein folding is hard", "Protein folding is hard " + STRAY))
    settings = replace(tex_settings(), compiler="latexmk", latexmk_path=LATEXMK)
    compiler = LatexCompiler(settings, tmp_path / "build")
    for _rebuild in range(2):  # without -f/-g latexmk deletes the PDF, then refuses to rerun
        result = compiler.compile(main, root)
        assert result.success and result.errors, result.summary()


@needs_tex
def test_fatal_error_gives_no_pdf_even_after_an_earlier_good_build(tmp_path):
    root = compilable_project(tmp_path / "paper")
    main = root / "main.tex"
    compiler = LatexCompiler(tex_settings(), tmp_path / "build")
    assert compiler.compile(main, root).clean
    main.write_text(main.read_text().replace(r"\begin{document}", "\\begin{document}\n\\input{missing-file}"))
    result = compiler.compile(main, root)  # the stale PDF from the good build must not count
    assert not result.success and result.pdf_path is None and result.errors


def _engine_with_tex(tmp_path, remote):
    engine, approver = build(tmp_path, remote, text_msg("unused"))
    engine.options = replace(engine.options, push=False, preview=False, compile_before_commit=True)
    engine.compiler = LatexCompiler(tex_settings(), engine.config.build_dir)
    engine.tool_pull_repo()
    return engine, approver


@needs_tex
def test_commit_goes_ahead_when_errors_were_already_there(tmp_path, git_project):
    remote, _ = git_project  # this project has no natbib, so \citep is already an error
    engine, approver = _engine_with_tex(tmp_path, remote)
    try:
        root = engine.paper.root
        text = (root / "main.tex").read_text()
        change = ProposedChange(root, "main.tex", text, text.replace("Protein folding is hard", "It is hard"), "reword")
        engine.review_apply_commit([change], "Reword", topic="reword")
    finally:
        approver.stop()
    assert "It is hard" in (root / "main.tex").read_text()
    assert Repo(root).head.commit.message.startswith("Reword")
    assert any("already had" in e.message for e in approver.events)


@needs_tex
def test_commit_is_rolled_back_when_it_adds_an_error(tmp_path, git_project):
    remote, _ = git_project
    engine, approver = _engine_with_tex(tmp_path, remote)
    try:
        root = engine.paper.root
        text = (root / "main.tex").read_text()
        bad = text.replace("Protein folding is hard", "Protein folding is \\undefinedmacro hard")
        with pytest.raises(AgentError, match="adds LaTeX errors"):
            engine.review_apply_commit([ProposedChange(root, "main.tex", text, bad, "bad")], "Bad", topic="bad")
    finally:
        approver.stop()
    assert (root / "main.tex").read_text() == text
