"""Local-first papers: folder structure, local repository, and the Sync button."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Actor, Repo

from config import GitSettings
from core.agent_engine import AgentError, RunOptions
from core.app_state import AppState, PaperSpec, validate_paper
from core.git_manager import GitManager, GitOperationError
from core.project_layout import FOLDERS, LOCAL_ONLY, looks_scaffolded, present_folders, scaffold
from core.protection import ProtectionPolicy
from core.workflows import PublishWorkflow, SyncWorkflow
from tests.test_engine_integration import build


def local_paper(root: Path, title: str = "A local paper") -> list[str]:
    created = scaffold(root, title, "Girish")
    return created


# ---------------------------------------------------------------------- #
# Folder structure
# ---------------------------------------------------------------------- #
def test_scaffold_creates_an_overleaf_ready_project(tmp_path):
    root = tmp_path / "paper"
    created = local_paper(root)
    assert "main.tex" in created and "manuscript/introduction.tex" in created
    assert looks_scaffolded(root)
    assert present_folders(root) == [f.name for f in FOLDERS]
    main = (root / "main.tex").read_text(encoding="utf-8")
    assert r"\input{manuscript/introduction}" in main and r"\graphicspath{{figures/}}" in main
    assert r"\bibliography{bibliography/references}" in main and "A local paper" in main
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert all(f"{name}/" in ignore for name in LOCAL_ONLY) and "*.aux" in ignore
    assert "data/" in (root / "README.md").read_text(encoding="utf-8")

    (root / "main.tex").write_text("edited by the author", encoding="utf-8")
    assert scaffold(root, "Another title") == []                      # nothing is overwritten
    assert (root / "main.tex").read_text(encoding="utf-8") == "edited by the author"


def test_data_and_code_are_read_only_for_the_agent(tmp_path):
    root = tmp_path / "paper"
    local_paper(root)
    policy = ProtectionPolicy.build(root, "", auto_detect=False)
    assert policy.reason("data/experiment.csv") and policy.reason("code/train.py")
    assert policy.reason("manuscript/results.tex") is None and policy.reason("figures/plot.png") is None
    listed = policy.protected_files()
    assert not [rel for rel in listed if rel.startswith(("data/", "code/"))]  # folders, not every file


def test_local_paper_needs_no_url(tmp_path):
    spec = PaperSpec("Local", "", str(tmp_path / "paper"))
    assert validate_paper(spec, set()) == [] and spec.local_only
    assert validate_paper(PaperSpec("Nowhere"), set()) == ["Choose a folder for the paper (a Git URL is optional)."]
    assert not PaperSpec("Linked", "https://git.overleaf.com/" + "a" * 24, "x").local_only


def test_new_state_does_not_push_until_asked(tmp_path):
    path = tmp_path / "app_state.json"
    AppState(push_after_commit=True).save(path)
    assert AppState.load(path).push_after_commit is True
    assert AppState().push_after_commit is False and RunOptions().push is False
    path.write_text('{"push": true}', encoding="utf-8")   # the old "push after commit" setting
    assert AppState.load(path).push_after_commit is False


# ---------------------------------------------------------------------- #
# Local repository
# ---------------------------------------------------------------------- #
def make_local_repo(tmp_path: Path, name: str = "paper") -> GitManager:
    root = tmp_path / name
    local_paper(root)
    git = GitManager(root, settings=GitSettings(author_name="Girish", author_email="g@example.org"))
    git.init_repo()
    git.commit_all("Start the paper")
    return git


def test_local_repository_commits_without_a_remote(tmp_path):
    git = make_local_repo(tmp_path)
    assert git.exists and not git.has_remote and git.current_branch() == "main"
    tracked = git.repo.git.ls_files().splitlines()
    assert "main.tex" in tracked and "code/README.md" in tracked
    assert not [f for f in tracked if f.startswith("data/")]           # data/ never leaves the computer
    assert git.push_strategy == "merge-to-default"
    assert git.counts() == (1, 0) and git.pending_commits() == ["Start the paper"]
    assert git.sync() == git.repo.head.commit.hexsha[:10]              # no remote: nothing to pull
    (git.local_path / "notes" / "idea.md").write_text("later", encoding="utf-8")
    assert git.sync()                                                   # uncommitted work is not in the way
    with pytest.raises(GitOperationError, match="no Overleaf"):
        git.sync_with_remote()


def test_workflow_commits_locally_and_stays_on_the_working_branch(tmp_path, git_project):
    remote, _ = git_project
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None))
    engine.options = RunOptions(push=False, compile_before_commit=False, preview=False)
    try:
        SyncWorkflow(engine).run()
        from core.events import ProposedChange
        from core.paper import read_text

        main = engine.paper.root / "main.tex"
        change = ProposedChange(engine.paper.root, "main.tex", read_text(main),
                                read_text(main).replace("Protein folding is hard", "Folding proteins is hard"),
                                "Reword a sentence")
        summary = engine.review_apply_commit([change], "Reword a sentence", topic="edit")
    finally:
        approver.stop()
    assert "committed locally" in summary
    clone = Repo(tmp_path / "clone")
    assert clone.active_branch.name == "master"                         # back on the working branch
    assert "Folding proteins is hard" in (tmp_path / "clone" / "main.tex").read_text(encoding="utf-8")
    assert [h.name for h in Repo(remote).heads] == ["master"]           # nothing was pushed
    assert clone.git.rev_list("--count", "origin/master..master") == "1"


# ---------------------------------------------------------------------- #
# The Sync button
# ---------------------------------------------------------------------- #
def test_sync_sends_local_commits_and_brings_back_remote_edits(tmp_path, git_project):
    remote, seed = git_project
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None))
    engine.options = RunOptions(push=False, compile_before_commit=False, preview=False, confirm_push=True)
    try:
        SyncWorkflow(engine).run()
        git = engine.paper.git
        (git.local_path / "manuscript.txt").write_text("local work\n", encoding="utf-8")
        git.commit(["manuscript.txt"], "Add a local note")

        seed_repo = Repo(seed)                                          # a co-author edits in Overleaf
        (seed / "coauthor.txt").write_text("their edit\n", encoding="utf-8")
        seed_repo.index.add(["coauthor.txt"])
        actor = Actor("Co", "co@example.com")
        seed_repo.index.commit("Co-author edit", author=actor, committer=actor)
        seed_repo.git.push("origin", "master")

        result = PublishWorkflow(engine).run()
    finally:
        approver.stop()
    assert "1 change(s) sent" in result.summary and "1 received" in result.summary
    remote_repo = Repo(remote)
    files = remote_repo.git.ls_tree("-r", "--name-only", "master").split()
    assert {"manuscript.txt", "coauthor.txt"} <= set(files)
    assert engine.paper.git.counts() == (0, 0)
    assert (tmp_path / "clone" / "coauthor.txt").exists()


def test_linking_a_local_paper_to_an_empty_project_sends_everything(tmp_path):
    git = make_local_repo(tmp_path)
    remote = tmp_path / "overleaf.git"
    Repo.init(remote, bare=True, initial_branch="main")
    # the user pastes the link in Edit paper: the next Git operation attaches it
    linked = GitManager(git.local_path, str(remote), settings=git.settings)
    linked.ensure_repo()
    assert Path(linked.repo.remotes["origin"].url) == remote
    pushed, pulled = linked.sync_with_remote()
    assert (pushed, pulled) == (1, 0)
    assert "main.tex" in Repo(remote).git.ls_tree("-r", "--name-only", "main").split()
    assert linked.counts() == (0, 0)


def test_linking_to_a_project_that_already_has_its_own_history_is_refused(tmp_path):
    git = make_local_repo(tmp_path)
    remote = tmp_path / "overleaf.git"
    Repo.init(remote, bare=True, initial_branch="main")
    other = Repo.init(tmp_path / "their-project", initial_branch="main")
    (tmp_path / "their-project" / "main.tex").write_text("their own paper\n", encoding="utf-8")
    other.index.add(["main.tex"])
    actor = Actor("Them", "them@example.com")
    other.index.commit("Their start", author=actor, committer=actor)
    other.create_remote("origin", str(remote))
    other.git.push("origin", "main")

    linked = GitManager(git.local_path, str(remote), settings=git.settings)
    linked.ensure_repo()
    with pytest.raises(GitOperationError, match="started separately"):
        linked.sync_with_remote()
    assert git.counts()[0] == 1                       # the local work is untouched
    assert Repo(remote).git.ls_tree("-r", "--name-only", "main").split() == ["main.tex"]


def test_sync_is_a_no_op_when_nothing_changed(tmp_path, git_project):
    remote, _ = git_project
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None))
    try:
        SyncWorkflow(engine).run()
        result = PublishWorkflow(engine).run()
    finally:
        approver.stop()
    assert "Already in sync" in result.summary


def test_sync_without_a_link_explains_what_to_do(tmp_path):
    git = make_local_repo(tmp_path)
    engine, approver = build(tmp_path, "", SimpleNamespace(create=None))
    engine.paper.spec.local_path = str(git.local_path)
    engine.paper.git = git
    try:
        with pytest.raises(AgentError, match="only on this computer"):
            PublishWorkflow(engine).run()
    finally:
        approver.stop()


def test_sync_refuses_when_the_folder_has_uncommitted_edits(tmp_path, git_project):
    remote, _ = git_project
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None))
    try:
        SyncWorkflow(engine).run()
        git = engine.paper.git
        (git.local_path / "note.txt").write_text("ready to send\n", encoding="utf-8")
        git.commit(["note.txt"], "Add a note")
        (engine.paper.root / "main.tex").write_text("hand edit\n", encoding="utf-8")
        with pytest.raises(GitOperationError, match="uncommitted changes"):
            PublishWorkflow(engine).run()
    finally:
        approver.stop()
