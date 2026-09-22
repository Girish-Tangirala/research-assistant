"""The "Edit .tex" tab: file list, saving (write + local commit), disk changes, read-only files."""

from __future__ import annotations

import time
from pathlib import Path

import customtkinter as ctk
import pytest
from git import Repo

from core.events import EventKind
from core.git_manager import GitManager
from config import GitSettings
from gui.tex_editor import EditorContext, TexEditor, editable_files


@pytest.fixture(scope="module")
def tk_root():
    # One Tk interpreter for the module: creating many in a row fails intermittently on Windows.
    window = ctk.CTk()
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture()
def root_window(tk_root):
    frame = ctk.CTkFrame(tk_root)
    yield frame
    frame.destroy()


@pytest.fixture()
def paper(tmp_path) -> Path:
    root = tmp_path / "paper"
    (root / "manuscript").mkdir(parents=True)
    (root / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\n\\input{manuscript/intro}\n"
                                   "\\end{document}\n", encoding="utf-8")
    (root / "manuscript" / "intro.tex").write_bytes(b"Hello\r\nworld\r\n")  # Windows line endings
    (root / "zotero.bib").write_text("@article{a,title={T}}\n", encoding="utf-8")
    (root / "figure.png").write_bytes(b"\x89PNG")
    repo = Repo.init(root)
    repo.git.add("-A")
    repo.git.commit("-m", "start", "--author", "T <t@x>", env={"GIT_COMMITTER_NAME": "T",
                                                                  "GIT_COMMITTER_EMAIL": "t@x"})
    return root


def make_editor(window, root: Path, messages: list) -> TexEditor:
    def commit(repo_root: Path, rel: str) -> str:
        return GitManager(repo_root, "", "", GitSettings(author_name="T", author_email="t@x")).commit(
            [rel], f"Edit {rel} in the editor")

    ctx = EditorContext(paper_root=lambda: root, read_only_reason=lambda _r, rel: "Zotero" if rel.endswith(".bib")
                        else None, save_blocked=lambda: None, commit=commit,
                        recompile=lambda: messages.append("recompile"),
                        notify=lambda kind, msg: messages.append((kind, msg)))
    editor = TexEditor(window, ctx)
    editor.paper_changed()
    return editor


def test_file_list_puts_the_main_document_first(paper):
    assert editable_files(paper) == ["main.tex", "manuscript/intro.tex", "zotero.bib"]


def test_save_writes_keeps_line_endings_and_commits(root_window, paper):
    messages: list = []
    editor = make_editor(root_window, paper, messages)
    assert editor.rel == "main.tex"
    editor.open_file("manuscript/intro.tex", line=2)
    assert editor.code.text.index("insert") == "2.0"
    editor.code.text.insert("end", "More text")
    assert editor.dirty
    editor.save(blocking=True)
    assert (paper / "manuscript" / "intro.tex").read_bytes() == b"Hello\r\nworld\r\nMore text"
    head = Repo(paper).head.commit
    assert head.message.startswith("Edit manuscript/intro.tex") and not Repo(paper).is_dirty()
    assert not editor.dirty and "recompile" in messages


def test_disk_changes_reload_unless_there_are_unsaved_edits(root_window, paper):
    editor = make_editor(root_window, paper, [])
    time.sleep(0.05)
    (paper / "main.tex").write_text("changed by a task\n", encoding="utf-8")
    editor._watch()
    assert editor.code.text.get("1.0", "end-1c") == "changed by a task\n"
    editor.code.text.insert("1.0", "mine ")
    time.sleep(0.05)
    (paper / "main.tex").write_text("changed again\n", encoding="utf-8")
    editor._watch()
    assert editor.code.text.get("1.0", "end-1c").startswith("mine ")  # unsaved edits are never replaced
    assert "Reload" in editor.status.cget("text")


def test_read_only_files_cannot_be_edited(root_window, paper):
    editor = make_editor(root_window, paper, [])
    editor.open_file("zotero.bib")
    assert str(editor.code.text.cget("state")) == "disabled"
    assert "Read-only" in editor.status.cget("text")


def test_blocked_save_keeps_the_text(root_window, paper):
    messages: list = []
    editor = make_editor(root_window, paper, messages)
    editor.ctx.save_blocked = lambda: "A task is running"
    editor.code.text.insert("1.0", "% note\n")
    editor.save(blocking=True)
    assert editor.dirty and "% note" not in (paper / "main.tex").read_text(encoding="utf-8")
    assert not any(isinstance(m, tuple) and m[0] == EventKind.WARNING for m in messages)
