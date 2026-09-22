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
        "unused-photo.png": "figures/unused-photo.png",           # every image is sorted, used or not
    }
    kept = dict(plan.kept)
    assert "main.tex" in kept and "zotero.bib" in kept          # root document and the Zotero file stay
    assert "ieee.cls" in kept and "ieee.cls" not in moves        # LaTeX needs it next to main.tex
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
        "figures/setup.jpg", "figures/unused-photo.png", "ieee.cls", "main.tex", "manuscript/appendix.tex",
        "manuscript/method.tex", "notes/meeting.md", "zotero.bib",
    ])
    assert looks_scaffolded(clone)
    main = (clone / "main.tex").read_text(encoding="utf-8")
    assert r"\input{manuscript/method}" in main and "figures/loss" in main
    repo = Repo(clone)
    assert repo.active_branch.name == "master" and not repo.is_dirty(untracked_files=True)
    head = repo.head.commit
    assert head.message.startswith("Organise 9 file(s) into folders")
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


def test_capitalised_image_names_are_rewritten_too(tmp_path):
    """Paper 1 had images/full_R.png: paths were matched in lower case, so the rewrite missed them."""
    root = tmp_path / "paper"
    (root / "images").mkdir(parents=True)
    make_image(root / "images" / "full_R.png")
    make_image(root / "SetUp.png")
    (root / "main.tex").write_text(r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
\includegraphics[width=\linewidth, angle = 90]{images/full_R.png}
\includegraphics{SetUp.png}
\end{document}
""", encoding="utf-8")
    plan = plan_reorganisation(root, files_of(root), "main.tex", lambda rel: None)
    assert dict(plan.moves) == {"images/full_R.png": "figures/full_R.png", "SetUp.png": "figures/SetUp.png"}
    main = plan.rewrites["main.tex"]
    assert "{figures/full_R.png}" in main and "{figures/SetUp.png}" in main


def test_undoing_moves_removes_the_folders_they_created(tmp_path):
    from core.events import ProposedChange
    from core.paper import AppliedChanges, apply_changes, revert_changes

    root = tmp_path / "paper"
    (root / "images").mkdir(parents=True)
    make_image(root / "images" / "a.png")
    (root / "data").mkdir()
    (root / "data" / "README.md").write_text("keep", encoding="utf-8")
    change = ProposedChange(root, "(moves)", "", "", "move", moves=[("images/a.png", "figures/deep/a.png")])
    applied = AppliedChanges(root)
    apply_changes([change], applied)
    assert (root / "figures" / "deep" / "a.png").is_file()
    revert_changes(SimpleNamespace(discard_changes=lambda files: None), applied)
    assert (root / "images" / "a.png").is_file()
    assert not (root / "figures").exists()          # created by the move, empty again -> gone
    assert (root / "data" / "README.md").is_file()  # unrelated folders untouched


def test_every_file_kind_gets_its_folder_and_emptied_folders_go(tmp_path):
    from PIL import Image

    from core.events import ProposedChange
    from core.paper import AppliedChanges, apply_changes
    from core.reorganize import unsorted_files

    root = tmp_path / "paper"
    (root / "images").mkdir(parents=True)
    (root / "main.tex").write_text("\\documentclass{article}\\begin{document}Hi\\end{document}\n", encoding="utf-8")
    (root / "IEEEtran.cls").write_text("% class\n", encoding="utf-8")
    make_image(root / "images" / "unused.png")
    make_image(root / "Plot.png")
    page = Image.new("RGB", (60, 80), "white")
    page.save(root / "manual.pdf", "PDF", save_all=True, append_images=[page.copy()])   # 2 pages: a document
    page.save(root / "diagram.pdf", "PDF")                                              # 1 page: a figure
    assert sorted(unsorted_files(root, "main.tex")) == ["Plot.png", "diagram.pdf", "manual.pdf"]
    plan = plan_reorganisation(root, files_of(root), "main.tex", lambda rel: None)
    assert dict(plan.moves) == {"images/unused.png": "figures/unused.png", "Plot.png": "figures/Plot.png",
                                "manual.pdf": "notes/manual.pdf", "diagram.pdf": "figures/diagram.pdf"}
    apply_changes([ProposedChange(root, "(moves)", "", "", "move", moves=plan.moves)], AppliedChanges(root))
    assert not (root / "images").exists()             # emptied by the move -> removed
    assert unsorted_files(root, "main.tex") == []     # only main.tex and the class file are left on top
    assert sorted(p.name for p in root.iterdir()) == ["IEEEtran.cls", "figures", "main.tex", "notes"]
