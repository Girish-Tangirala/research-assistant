"""Shared to-do list: file format, operations and multi-user syncing."""

from __future__ import annotations

from datetime import date

import pytest
from git import Repo

from config import GitSettings
from core.git_manager import GitManager, GitOperationError
from core.protection import ProtectionPolicy
from core.todos import (
    TODO_FILE, TodoDoc, TodoError, TodoItem, TodoStore, op_add, op_delete, op_update,
)


def user(tmp_path, remote, name: str) -> TodoStore:
    settings = GitSettings(author_name=name, author_email=f"{name.lower()}@uni.edu", push_strategy="merge-to-default")
    git = GitManager(tmp_path / name, str(remote), settings=settings)
    return TodoStore(git, name)


# ---------------------------------------------------------------------- #
# Format
# ---------------------------------------------------------------------- #
def test_render_parse_roundtrip():
    item = TodoItem(text="Fix Fig. 3 caption", assignee="Girish", due="2026-10-01", section="Results", by="Ana")
    line = item.render()
    assert line.startswith("- [ ] Fix Fig. 3 caption — @Girish · due 2026-10-01 · § Results <!-- todo {")
    parsed = TodoItem.parse(line)
    assert parsed == item


def test_human_edits_in_overleaf_are_respected():
    item = TodoItem(text="Old text", assignee="Ana", id="abc123")
    edited = item.render().replace("- [ ]", "- [x]").replace("Old text", "New wording (v2)")
    doc = TodoDoc.parse("# To-do list\n\nSome note written by hand.\n" + edited + "\n- [ ] plain line added in Overleaf\n")
    first, second = doc.items
    assert first.id == "abc123" and first.done and first.text == "New wording (v2)" and first.assignee == "Ana"
    assert second.text == "plain line added in Overleaf" and len(second.id) == 8
    rendered = doc.render()
    assert "Some note written by hand." in rendered
    assert "<!-- todo" in rendered.splitlines()[-1]  # the plain line got an identity


def test_duplicate_ids_and_injection_are_neutralised():
    line = TodoItem(text="Task", id="same").render()
    doc = TodoDoc.parse(f"{line}\n{line}\n")
    assert len({i.id for i in doc.items}) == 2
    tricky = TodoItem(text="Close the comment --> <!-- todo {} -->")
    assert TodoItem.parse(tricky.render()).text == "Close the comment todo {}"


def test_operations_and_validation():
    doc = TodoDoc.parse("")
    assert doc.render().startswith("# To-do list")
    op_add("Write abstract", "Ana", assignee="Bo", due="2026-01-02")(doc)
    item = doc.items[0]
    assert item.by == "Ana" and item.is_overdue(date(2026, 1, 3)) and not item.is_overdue(date(2026, 1, 1))
    op_update(item.id, "Bo", done=True)(doc)
    assert item.done and item.done_by == "Bo" and not item.is_overdue(date(2027, 1, 1))
    op_update(item.id, "Bo", done=False)(doc)
    assert item.done_by == ""
    assert "delete" in op_delete(item.id)(doc)
    with pytest.raises(TodoError, match="no longer exists"):
        op_delete(item.id)(doc)
    with pytest.raises(TodoError, match="Due date"):
        op_add("x", "Ana", due="01/02/2026")
    with pytest.raises(TodoError, match="Due date"):
        op_add("x", "Ana", due="2026-02-30")
    with pytest.raises(TodoError, match="task text"):
        op_add("   ", "Ana")


def test_agent_may_not_edit_the_todo_file(tmp_path):
    (tmp_path / TODO_FILE).write_text("x")
    policy = ProtectionPolicy.build(tmp_path, "", auto_detect=True)
    assert "To-Do tab" in policy.reason(TODO_FILE)
    assert TODO_FILE not in policy.protected_files()  # enforced, but not listed as a user read-only file


# ---------------------------------------------------------------------- #
# Multi-user syncing against a shared remote
# ---------------------------------------------------------------------- #
def test_two_users_share_one_list(tmp_path, git_project):
    remote, _ = git_project
    ana, bo = user(tmp_path, remote, "Ana"), user(tmp_path, remote, "Bo")
    ana.apply(op_add("Fix Fig. 3", "Ana", assignee="Bo"))
    doc = bo.refresh()
    assert [i.text for i in doc.items] == ["Fix Fig. 3"]
    bo.apply(op_update(doc.items[0].id, "Bo", done=True))
    assert ana.refresh().items[0].done_by == "Bo"
    log = [c.summary for c in Repo(remote).iter_commits("master", max_count=2)]
    assert log == ["To-do: complete 'Fix Fig. 3'", "To-do: add 'Fix Fig. 3'"]
    assert sorted(ana.people()) == ["Ana", "Bo", "Test"]


def test_concurrent_edits_are_replayed_not_lost(tmp_path, git_project):
    remote, _ = git_project
    ana, bo = user(tmp_path, remote, "Ana"), user(tmp_path, remote, "Bo")
    ana.apply(op_add("Shared task", "Ana"))
    task_id = bo.refresh().items[0].id

    # Bo's clone is now behind: Ana adds and edits while Bo is "offline".
    original_sync = bo.git.sync
    calls = {"n": 0}

    def stale_first_sync():
        calls["n"] += 1
        if calls["n"] == 1:
            ana.apply(op_add("Ana's second task", "Ana"))  # lands on the remote after Bo pulled
            return original_sync()
        return original_sync()

    bo.git.sync = stale_first_sync
    original_sync_result = bo.apply(op_update(task_id, "Bo", assignee="Bo"))
    texts = sorted(i.text for i in original_sync_result.items)
    assert texts == ["Ana's second task", "Shared task"]
    final = ana.refresh()
    assert {i.text: i.assignee for i in final.items} == {"Shared task": "Bo", "Ana's second task": ""}


def test_push_rejection_retries_and_then_succeeds(tmp_path, git_project, monkeypatch):
    remote, seed = git_project
    ana, bo = user(tmp_path, remote, "Ana"), user(tmp_path, remote, "Bo")
    ana.refresh()
    bo.refresh()
    real_push = ana.git.push
    attempts = {"n": 0}

    def racing_push(branch):
        attempts["n"] += 1
        if attempts["n"] == 1:
            bo.apply(op_add("Bo was faster", "Bo"))  # remote moves between Ana's pull and push
        return real_push(branch)

    monkeypatch.setattr(ana.git, "push", racing_push)
    doc = ana.apply(op_add("Ana's task", "Ana"))
    assert attempts["n"] == 2
    assert sorted(i.text for i in doc.items) == ["Ana's task", "Bo was faster"]
    assert sorted(i.text for i in bo.refresh().items) == ["Ana's task", "Bo was faster"]


def test_undo_last_commit_refuses_foreign_commits(tmp_path, git_project):
    remote, _ = git_project
    git = GitManager(tmp_path / "x", str(remote))
    git.sync()
    with pytest.raises(GitOperationError, match="Refusing"):
        git.undo_last_commit("To-do: ")


def test_no_push_keeps_change_local(tmp_path, git_project):
    remote, _ = git_project
    ana = user(tmp_path, remote, "Ana")
    ana.push = False
    messages = []
    ana._log = messages.append
    ana.apply(op_add("Local only", "Ana"))
    assert "stays on this computer" in messages[0]
    assert TODO_FILE not in Repo(remote).git.ls_tree("-r", "--name-only", "master").split()
