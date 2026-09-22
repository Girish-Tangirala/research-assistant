"""Overleaf-specific behaviour: URL handling, compiler detection, concurrent edits."""

from __future__ import annotations

import pytest
from git import Actor, Repo

from config import GitSettings
from core.app_state import PaperSpec, normalize_remote_url, validate_paper
from core.compiler import detect_bib_tool, detect_engine
from core.git_manager import GitManager, GitOperationError

PROJECT_ID = "68af18e2086f3be729c587a0"


@pytest.mark.parametrize("pasted", [
    f"https://www.overleaf.com/project/{PROJECT_ID}",
    f"https://www.overleaf.com/project/{PROJECT_ID}/",
    f"https://git.overleaf.com/project/{PROJECT_ID}",
    f"https://git.overleaf.com/{PROJECT_ID}",
    f"  https://overleaf.com/project/{PROJECT_ID.upper()}?x=1 ",
])
def test_overleaf_links_become_clone_urls(pasted):
    url = normalize_remote_url(pasted)
    assert url == f"https://git.overleaf.com/{PROJECT_ID}"
    assert validate_paper(PaperSpec("P", url), set()) == []


def test_other_urls_are_left_alone():
    assert normalize_remote_url("https://github.com/me/paper/") == "https://github.com/me/paper"
    assert normalize_remote_url("git@github.com:me/paper.git") == "git@github.com:me/paper.git"
    problems = validate_paper(PaperSpec("P", "https://www.overleaf.com/read/abcdef"), set())
    assert any("Overleaf URL not recognised" in p for p in problems)


@pytest.mark.parametrize(("tex", "engine"), [
    (r"\usepackage{amsmath}", "pdflatex"),
    (r"\usepackage[no-math]{fontspec}", "xelatex"),
    (r"\usepackage{graphicx,polyglossia}", "xelatex"),
    (r"\usepackage{luacode}", "lualatex"),
    ("% !TEX program = xelatex\n\\documentclass{article}", "xelatex"),
    (r"% \usepackage{fontspec}", "pdflatex"),
])
def test_detect_engine(tex, engine):
    assert detect_engine(tex) == engine


@pytest.mark.parametrize(("tex", "tool"), [
    (r"\bibliography{refs}", "bibtex"),
    (r"\usepackage[style=apa]{biblatex}\addbibresource{refs.bib}", "biber"),
    (r"\usepackage[backend=bibtex]{biblatex}", "bibtex"),
    (r"\begin{thebibliography}{9}", None),
])
def test_detect_bib_tool(tex, tool):
    assert detect_bib_tool(tex) == tool


def _collaborator_edit(seed_path, filename: str, content: str) -> None:
    """Simulate a co-author editing in Overleaf (a push to the remote)."""
    seed = Repo(seed_path)
    (seed_path / filename).write_bytes(content.encode())
    seed.index.add([filename])
    actor = Actor("Co-author", "co@example.org")
    seed.index.commit(f"Edit {filename}", author=actor, committer=actor)
    seed.git.push("origin", "master")


def _agent_commit(tmp_path, remote, filename: str, content: str) -> tuple[GitManager, str]:
    git = GitManager(tmp_path / "agent", str(remote),
                     settings=GitSettings(author_name="Agent", author_email="agent@test.org",
                                          push_strategy="merge-to-default"))
    git.sync()
    branch = git.create_feature_branch("edit")
    (git.local_path / filename).write_bytes(content.encode())
    git.commit([filename], "Agent edit")
    return git, branch


def test_publish_rebases_over_collaborator_edits(tmp_path, git_project):
    remote, seed = git_project
    git, branch = _agent_commit(tmp_path, remote, "main.tex", "agent version\n")
    _collaborator_edit(seed, "refs.bib", "@misc{new, title={Added in Overleaf}}\n")

    assert git.publish(branch) == "master"
    remote_repo = Repo(remote)
    assert remote_repo.git.show("master:main.tex") == "agent version"
    assert "Added in Overleaf" in remote_repo.git.show("master:refs.bib")
    assert [c.summary for c in remote_repo.iter_commits("master", max_count=2)] == ["Agent edit", "Edit refs.bib"]


def test_conflicting_collaborator_edit_keeps_agent_branch(tmp_path, git_project):
    remote, seed = git_project
    git, branch = _agent_commit(tmp_path, remote, "main.tex", "agent version\n")
    _collaborator_edit(seed, "main.tex", "co-author version\n")

    with pytest.raises(GitOperationError, match="conflict with edits made on the remote"):
        git.publish(branch)
    assert git.current_branch() == "master" and not git.is_dirty()
    assert branch in [h.name for h in git.repo.heads]
    assert Repo(remote).git.show("master:main.tex") == "co-author version"
