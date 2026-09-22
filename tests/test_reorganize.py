"""Organising an existing paper into the standard folders."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Actor, Repo

from core.app_state import PaperSpec
from core.project_layout import looks_scaffolded
from core.protection import ProtectionPolicy
from core.reorganize import plan_reorganisation, plan_to_markdown
from core.workflows import OrganizeWorkflow
from tests.test_asset_workflows import make_image
from core.preview import page_texts
from tests.test_engine_integration import build
from tests.test_preview import needs_tex, tex_settings

OLD_MAIN = r"""\documentclass{article}
\usepackage{graphicx}
\graphicspath{{figs/}}
\begin{document}
\section{Introduction}
See Figure~\ref{fig:loss} and \cite{knuth1984}.
\begin{figure}
  \includegraphics[width=0.5\linewidth]{loss}
  \includegraphics[width=0.5\linewidth]{figs/setup.jpg}
  \caption{Results.}
  \label{fig:loss}
\end{figure}
\input{sections/method}
\include{appendix}
\bibliographystyle{plain}
\bibliography{refs,zotero}
\end{document}
"""


def old_paper(root: Path) -> Path:
    """A paper laid out the way people write them before using the app."""
    (root / "sections").mkdir(parents=True, exist_ok=True)
    (root / "figs").mkdir(exist_ok=True)
    (root / "main.tex").write_text(OLD_MAIN, encoding="utf-8")
    (root / "sections" / "method.tex").write_text("\\section{Method}\nWe use \\includegraphics{figs/setup.jpg}.\n",
                                                  encoding="utf-8")
    (root / "appendix.tex").write_text("\\section{Appendix}\nExtra.\n", encoding="utf-8")
    (root / "refs.bib").write_text("@book{knuth1984, title={The TeXbook}, year={1984}}\n", encoding="utf-8")
    (root / "zotero.bib").write_text("% Zotero export\n@article{a_b_2020, title={X}}\n", encoding="utf-8")
    (root / "analysis.py").write_text("print('train')\n", encoding="utf-8")
    (root / "measurements.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "meeting.md").write_text("Notes from the meeting\n", encoding="utf-8")
    (root / "ieee.cls").write_text("% a class file\n", encoding="utf-8")
    make_image(root / "figs" / "loss.png")
    make_image(root / "figs" / "setup.jpg", "JPEG")
    make_image(root / "unused-photo.png")
    return root


def files_of(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.parts)


def test_plan_sorts_files_and_leaves_latex_essentials_alone(tmp_path):
    root = old_paper(tmp_path / "paper")
    policy = ProtectionPolicy.build(root, "", auto_detect=True)
    plan = plan_reorganisation(root, files_of(root), "main.tex", policy.reason)
    moves = dict(plan.moves)
    assert moves == {
        "sections/method.tex": "manuscript/method.tex",
        "appendix.tex": "manuscript/appendix.tex",
        "refs.bib": "bibliography/refs.bib",
        "analysis.py": "code/analysis.py",
        "measurements.csv": "data/measurements.csv",
        "meeting.md": "notes/meeting.md",
        "figs/loss.png": "figures/loss.png",
        "figs/setup.jpg": "figures/setup.jpg",
    }
    kept = dict(plan.kept)
    assert "main.tex" in kept and "zotero.bib" in kept          # root document and the Zotero file stay
    assert "ieee.cls" not in moves and "unused-photo.png" not in moves
    assert any("data file(s) move into data/" in w for w in plan.warnings)

    report = plan_to_markdown(plan, "Test paper")
    assert "`sections/method.tex` | `manuscript/method.tex`" in report and "zotero.bib" in report


def test_plan_rewrites_every_path_that_moved(tmp_path):
    root = old_paper(tmp_path / "paper")
    policy = ProtectionPolicy.build(root, "", auto_detect=True)
    plan = plan_reorganisation(root, files_of(root), "main.tex", policy.reason)
    main = plan.rewrites["main.tex"]
    assert r"\input{manuscript/method}" in main and r"\include{manuscript/appendix}" in main
    assert r"\bibliography{bibliography/refs, zotero}" in main   # the Zotero file did not move
    assert r"\includegraphics[width=0.5\linewidth]{figures/loss}" in main      # extension-less stays so
    assert r"\includegraphics[width=0.5\linewidth]{figures/setup.jpg}" in main
    assert r"\graphicspath{{figs/}}" in main                     # left alone: paths are now explicit
    assert r"\includegraphics{figures/setup.jpg}" in plan.rewrites["manuscript/method.tex"]


def test_plan_is_empty_for_a_paper_that_is_already_organised(tmp_path):
    from core.project_layout import scaffold

    root = tmp_path / "paper"
    scaffold(root, "Organised")
    policy = ProtectionPolicy.build(root, "", auto_detect=False)
    plan = plan_reorganisation(root, files_of(root), "main.tex", policy.reason)
    assert plan.empty and "already organised" in plan_to_markdown(plan, "Organised")


@pytest.fixture
def old_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    Repo.init(remote, bare=True, initial_branch="master")
    seed = old_paper(tmp_path / "seed")
    repo = Repo.init(seed, initial_branch="master")
    repo.git.add(A=True)
    actor = Actor("Test", "test@example.com")
    repo.index.commit("Initial", author=actor, committer=actor)
    repo.create_remote("origin", str(remote))
    repo.git.push("origin", "master")
    return remote


def test_organise_workflow_moves_files_and_commits_once(tmp_path, old_remote):
    engine, approver = build(tmp_path, old_remote, SimpleNamespace(create=None))
    engine.options = replace(engine.options, push=False)      # local-first, like the app
    try:
        result = OrganizeWorkflow(engine).run()
    finally:
        approver.stop()
    clone = tmp_path / "clone"
    assert "committed locally" in result.summary
    assert files_of(clone) == sorted([
        "bibliography/refs.bib", "code/analysis.py", "data/measurements.csv", "figures/loss.png",
        "figures/setup.jpg", "ieee.cls", "main.tex", "manuscript/appendix.tex", "manuscript/method.tex",
        "notes/meeting.md", "unused-photo.png", "zotero.bib",
    ])
    assert looks_scaffolded(clone)
    main = (clone / "main.tex").read_text(encoding="utf-8")
    assert r"\input{manuscript/method}" in main and "figures/loss" in main
    repo = Repo(clone)
    assert repo.active_branch.name == "master" and not repo.is_dirty(untracked_files=True)
    head = repo.head.commit
    assert head.message.startswith("Organise 8 file(s) into folders")
    changed = repo.git.show("--name-status", "--format=", "HEAD")
    assert changed.count("R") >= 6 or changed.count("D") >= 6      # recorded as moves (or delete + add)
    assert [h.name for h in Repo(old_remote).heads] == ["master"]  # local-first: nothing pushed


def test_rejecting_the_moves_leaves_the_paper_untouched(tmp_path, old_remote):
    engine, approver = build(tmp_path, old_remote, SimpleNamespace(create=None), approve=False)
    try:
        OrganizeWorkflow(engine).run()
    finally:
        approver.stop()
    clone = tmp_path / "clone"
    assert "sections/method.tex" in files_of(clone) and "manuscript/method.tex" not in files_of(clone)
    assert not Repo(clone).is_dirty(untracked_files=True)


def test_organising_is_refused_for_read_only_files(tmp_path, old_remote):
    engine, approver = build(tmp_path, old_remote, SimpleNamespace(create=None))
    engine.paper.spec = PaperSpec(engine.paper.spec.name, engine.paper.spec.remote_url,
                                  engine.paper.spec.local_path, read_only="analysis.py")
    try:
        OrganizeWorkflow(engine).run()
    finally:
        approver.stop()
    assert "code/analysis.py" not in files_of(tmp_path / "clone")
    assert "analysis.py" in files_of(tmp_path / "clone")


@needs_tex
def test_the_paper_still_compiles_after_being_organised(tmp_path):
    """The real check: LaTeX finds every moved file through the rewritten paths."""
    from core.compiler import LatexCompiler

    root = old_paper(tmp_path / "paper")
    (root / "ieee.cls").unlink()                       # use the stock article class
    before = LatexCompiler(tex_settings(), tmp_path / "build-before").compile(root / "main.tex", root)
    assert before.success, before.summary()

    policy = ProtectionPolicy.build(root, "", auto_detect=True)
    plan = plan_reorganisation(root, files_of(root), "main.tex", policy.reason)
    for source, target in plan.moves:                  # apply the plan as the workflow would
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        (root / source).replace(root / target)
    for rel, text in plan.rewrites.items():
        (root / rel).write_text(text, encoding="utf-8")

    after = LatexCompiler(tex_settings(), tmp_path / "build-after").compile(root / "main.tex", root)
    assert after.success, after.summary()
    assert page_texts(after.pdf_path) == page_texts(before.pdf_path)   # same document, new folders
