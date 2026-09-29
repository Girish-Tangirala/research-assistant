"""The shared to-do list: one repository for every paper, and the migration into it."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Actor, Repo

from config import GitSettings
from core.app_state import AppState, TodoRepoSettings, validate_todo_repo
from core.git_manager import GitManager
from core.global_todos import (
    FOLDER, clone_path, migrate_paper_lists, open_store, read_paper_items,
)
from core.todos import TODO_FILE, TodoError, TodoItem, TodoStore, op_add
from tests.test_todos import user


def bare(tmp_path: Path, name: str) -> Path:
    """A remote with one commit on master, the way a real repository starts."""
    remote = tmp_path / f"{name}.git"
    Repo.init(remote, bare=True, initial_branch="master")
    seed = tmp_path / f"{name}-seed"
    repo = Repo.init(seed, initial_branch="master")
    (seed / "README.md").write_bytes(b"# " + name.encode() + b"\n")
    repo.index.add(["README.md"])
    actor = Actor("Test", "test@example.com")
    repo.index.commit("Initial", author=actor, committer=actor)
    repo.create_remote("origin", str(remote))
    repo.git.push("origin", "master")
    return remote


def paper_with_list(tmp_path: Path, remote: Path, name: str, lines: list[str]) -> GitManager:
    """A paper repository whose todo.md already holds ``lines``."""
    settings = GitSettings(author_name="Girish", author_email="g@uni.edu", push_strategy="merge-to-default")
    git = GitManager(tmp_path / name, str(remote), settings=settings)
    git.sync()
    (git.local_path / "main.tex").write_bytes(b"\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n")
    (git.local_path / TODO_FILE).write_bytes(("# To-do list\n\n" + "\n".join(lines) + "\n").encode())
    git.commit(["main.tex", TODO_FILE], "Start the paper")
    return git


# ---------------------------------------------------------------------- #
# Settings
# ---------------------------------------------------------------------- #
def test_settings_round_trip_and_validation(tmp_path):
    state = AppState()
    assert not state.todo_repo.configured
    state.todo_repo = TodoRepoSettings(url="https://github.com/me/research-todo.git", branch="main")
    path = tmp_path / "state.json"
    state.save(path)
    assert AppState.load(path).todo_repo == state.todo_repo

    assert validate_todo_repo(TodoRepoSettings()) == []
    assert "must start with" in validate_todo_repo(TodoRepoSettings(url="github.com/me/x"))[0]
    assert "Remove the user name" in validate_todo_repo(
        TodoRepoSettings(url="https://me:tok@github.com/me/x.git"))[0]
    assert "not a valid branch" in validate_todo_repo(
        TodoRepoSettings(url="https://github.com/me/x.git", branch="bad branch"))[0]


def test_store_explains_what_is_missing(tmp_path):
    with pytest.raises(TodoError, match="not set up yet"):
        open_store(tmp_path, TodoRepoSettings(), "Girish")
    with pytest.raises(TodoError, match="Sign in to github.com"):
        open_store(tmp_path, TodoRepoSettings(url="https://github.com/me/x.git"), "Girish")


def test_the_list_lives_beside_the_papers_not_inside_one(tmp_path):
    assert clone_path(tmp_path) == tmp_path / FOLDER
    assert FOLDER != "papers"


def test_the_background_refresh_does_not_fill_the_log(tmp_path):
    """Refreshing every 45 seconds must not print 'Pulling origin/main' every time."""
    from core.global_todos import _quiet

    seen: list[str] = []
    quiet = _quiet(seen.append)
    for message in ("Pulling origin/main", "Checking out main", "Cloning https://host/x -> C:\\ws\\todo",
                    "Someone else changed the list at the same time - retrying."):
        quiet(message)
    assert seen == ["Cloning https://host/x -> C:\\ws\\todo",
                    "Someone else changed the list at the same time - retrying."]
    assert _quiet(None) is None


# ---------------------------------------------------------------------- #
# One list, many papers
# ---------------------------------------------------------------------- #
def test_one_list_is_shared_by_two_people_and_tags_papers(tmp_path):
    remote = bare(tmp_path, "todo")
    girish, ana = user(tmp_path, remote, "Girish"), user(tmp_path, remote, "Ana")
    girish.apply(op_add("Fix Fig. 3", "Girish", paper="Paper 1", section="Results"))
    girish.apply(op_add("Book the conference room", "Girish"))          # belongs to no paper
    ana.apply(op_add("Re-run the 6-model benchmark", "Ana", paper="Paper 3"))

    items = {i.text: i for i in girish.refresh().items}
    assert set(items) == {"Fix Fig. 3", "Book the conference room", "Re-run the 6-model benchmark"}
    assert items["Fix Fig. 3"].paper == "Paper 1"
    assert items["Fix Fig. 3"].section == "Results"
    assert items["Book the conference room"].paper == ""
    assert items["Re-run the 6-model benchmark"].paper == "Paper 3"


def test_the_paper_label_survives_a_hand_edit_in_the_browser(tmp_path):
    remote = bare(tmp_path, "todo")
    store = user(tmp_path, remote, "Girish")
    store.apply(op_add("Fix Fig. 3", "Girish", paper="Paper 1"))
    line = next(ln for ln in store.path.read_text(encoding="utf-8").splitlines() if "Fix Fig." in ln)
    assert " in Paper 1 " in line                      # the label is visible, not only in the comment
    store.path.write_bytes(line.replace("Fix Fig. 3", "Fix Figure 3 caption").encode() + b"\n")
    item = store.read().items[0]
    assert item.text == "Fix Figure 3 caption" and item.paper == "Paper 1"


# ---------------------------------------------------------------------- #
# Migration
# ---------------------------------------------------------------------- #
def test_migration_moves_tasks_in_and_removes_todo_from_the_papers(tmp_path):
    shared = user(tmp_path, bare(tmp_path, "todo"), "Girish")
    one = paper_with_list(tmp_path, bare(tmp_path, "p1"), "Paper 1", [
        TodoItem(text="Fix Fig. 3", id="aaa11111", assignee="Ana", due="2026-10-01").render(),
        TodoItem(text="Write the conclusion", id="bbb22222").render()])
    three = paper_with_list(tmp_path, bare(tmp_path, "p3"), "Paper 3", [
        TodoItem(text="Add multirow package", id="ccc33333", done=True).render()])

    report = migrate_paper_lists(shared, [("Paper 1", one), ("Paper 3", three)])

    assert report.imported == 3 and report.skipped == 0
    assert report.papers_cleared == ["Paper 1", "Paper 3"] and report.problems == []
    items = {i.id: i for i in shared.refresh().items}
    assert items["aaa11111"].paper == "Paper 1" and items["aaa11111"].assignee == "Ana"
    assert items["aaa11111"].due == "2026-10-01"          # nothing about a task is invented or lost
    assert items["bbb22222"].paper == "Paper 1"
    assert items["ccc33333"].paper == "Paper 3" and items["ccc33333"].done
    for git in (one, three):
        assert not (git.local_path / TODO_FILE).exists()


def test_migration_commits_the_removal_locally_and_leaves_pushing_to_sync(tmp_path):
    remote = bare(tmp_path, "p1")
    shared = user(tmp_path, bare(tmp_path, "todo"), "Girish")
    paper = paper_with_list(tmp_path, remote, "Paper 1", [TodoItem(text="A task", id="aaa11111").render()])
    paper.push(paper.default_branch)                      # the paper starts in sync with "Overleaf"

    migrate_paper_lists(shared, [("Paper 1", paper)])

    assert TODO_FILE in Repo(remote).git.ls_tree("-r", "--name-only", paper.default_branch).split()
    assert not Repo(paper.local_path).is_dirty(untracked_files=True)     # committed, not left dirty
    head = Repo(paper.local_path).head.commit.message
    assert "shared to-do repository" in head


def test_running_the_migration_twice_does_not_duplicate_anything(tmp_path):
    shared = user(tmp_path, bare(tmp_path, "todo"), "Girish")
    paper = paper_with_list(tmp_path, bare(tmp_path, "p1"), "Paper 1",
                            [TodoItem(text="Fix Fig. 3", id="aaa11111").render()])

    first = migrate_paper_lists(shared, [("Paper 1", paper)])
    second = migrate_paper_lists(shared, [("Paper 1", paper)])

    assert first.imported == 1 and second.imported == 0
    assert [i.text for i in shared.refresh().items] == ["Fix Fig. 3"]
    assert not second.papers_cleared and second.problems == []


def test_migration_reports_a_paper_it_could_not_read(tmp_path):
    shared = user(tmp_path, bare(tmp_path, "todo"), "Girish")
    missing = GitManager(tmp_path / "gone", "", settings=GitSettings(author_name="G", author_email="g@u.edu"))
    report = migrate_paper_lists(shared, [("Ghost paper", missing)])
    assert report.imported == 0 and report.papers_cleared == []
    assert "There were no tasks to move." in report.as_text()


def test_reading_a_paper_list_tags_every_task_with_the_paper(tmp_path):
    root = tmp_path / "paper"
    root.mkdir()
    (root / TODO_FILE).write_bytes((TodoItem(text="Untagged", id="aaa11111").render() + "\n"
                                    + TodoItem(text="Already tagged", id="bbb22222",
                                               paper="Paper 9").render() + "\n").encode())
    items = {i.text: i for i in read_paper_items(root, "Paper 1")}
    assert items["Untagged"].paper == "Paper 1"
    assert items["Already tagged"].paper == "Paper 9"      # an existing label is never overwritten
    assert read_paper_items(tmp_path / "nothing-here", "Paper 1") == []
