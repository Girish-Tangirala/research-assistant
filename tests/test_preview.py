"""PDF previews: mirroring, change detection, proposed-change builds and push confirmation."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo

import config
from config import LatexSettings
from core.events import ApprovalGate, CancelToken, EventBus, EventKind, ProposedChange
from core.preview import PreviewBuilder, changed_pages, mirror_tree, source_signature
from core.workflows import SafeEditWorkflow
from tests.conftest import _write_project
from tests.test_engine_integration import build, text_msg

PDFLATEX = config._which("PDFLATEX_PATH", "pdflatex")
needs_tex = pytest.mark.skipif(PDFLATEX is None, reason="no LaTeX installation")


def tex_settings() -> LatexSettings:
    return LatexSettings(compiler="pdflatex", pdflatex_path=PDFLATEX,
                         bibtex_path=config._which("BIBTEX_PATH", "bibtex"), timeout_s=600)


def compilable_project(root: Path) -> Path:
    _write_project(root)
    main = root / "main.tex"
    main.write_text(main.read_text().replace("{amsmath}", "{amsmath}\n\\usepackage{natbib}"))
    return root


def test_mirror_tree_tracks_source_and_undoes_preview_edits(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "HEAD").write_text("ref")
    (src / "sub").mkdir()
    (src / "main.tex").write_text("original")
    (src / "sub" / "a.tex").write_text("a")
    mirror_tree(src, dst)
    assert (dst / "main.tex").read_text() == "original" and not (dst / ".git").exists()

    (dst / "main.tex").write_text("proposed edit!")      # a preview wrote here
    (dst / "figures").mkdir()
    (dst / "figures" / "new.png").write_bytes(b"x")       # a proposed new file
    (src / "sub" / "a.tex").unlink()
    mirror_tree(src, dst)
    assert (dst / "main.tex").read_text() == "original"
    assert not (dst / "figures").exists() and not (dst / "sub" / "a.tex").exists()


def test_source_signature_changes_on_edit(tmp_path):
    (tmp_path / "main.tex").write_text("x")
    before = source_signature(tmp_path)
    time.sleep(0.05)
    (tmp_path / "main.tex").write_text("y")
    os.utime(tmp_path / "main.tex", (time.time() + 5, time.time() + 5))
    assert source_signature(tmp_path) != before


def test_gate_ask_is_generic():
    bus, gate = EventBus(), ApprovalGate(EventBus(), CancelToken())
    gate._bus = bus
    answer = {}
    thread = threading.Thread(target=lambda: answer.setdefault("v", gate.ask(EventKind.CONFIRM_PUSH, "Push?", x=1)))
    thread.start()
    for _ in range(100):
        events = bus.drain()
        if events:
            break
        time.sleep(0.02)
    assert events[0].kind == EventKind.CONFIRM_PUSH and events[0].data["x"] == 1
    gate.resolve(events[0].data["request_id"], False)
    thread.join(5)
    assert answer["v"] is False


@needs_tex
def test_proposed_preview_marks_changed_pages_and_leaves_repo_untouched(tmp_path):
    root = compilable_project(tmp_path / "paper")
    builder = PreviewBuilder(tex_settings(), tmp_path / "build")
    current = builder.current(root, "main.tex")
    assert current.success and current.pdf_path.exists() and builder.current_is_fresh(root, "main.tex")

    original = (root / "main.tex").read_text()
    long_text = "\n\n".join(["A new paragraph of text that fills the page. " * 12] * 12)
    proposed_tex = original.replace(r"\section{Method}", long_text + "\n\\section{Method}")
    change = ProposedChange(root, "main.tex", original, proposed_tex, "longer intro")
    result = builder.proposed(root, "main.tex", [change])
    assert result.success and result.kind == "proposed"
    assert result.pdf_path != current.pdf_path
    assert result.changed_pages and result.changed_pages[0] == 0
    assert (root / "main.tex").read_text() == original  # real checkout untouched
    assert changed_pages(current.pdf_path, current.pdf_path) == []


@needs_tex
def test_reflow_does_not_mark_later_pages(tmp_path):
    root = compilable_project(tmp_path / "paper")
    main = root / "main.tex"
    filler = "\n\n".join(["Graph neural networks have been applied widely. " * 10] * 10)
    main.write_text(main.read_text().replace(r"\section{Method}", filler + "\n\\section{Method}"))
    builder = PreviewBuilder(tex_settings(), tmp_path / "build")
    original = main.read_text()
    edit = original.replace("Protein folding is hard", "Protein folding is a famously hard problem to solve")
    result = builder.proposed(root, "main.tex", [ProposedChange(root, "main.tex", original, edit, "reword")])
    assert result.success and result.changed_pages == [0]


@needs_tex
def test_broken_proposal_reports_the_errors_it_adds(tmp_path):
    root = compilable_project(tmp_path / "paper")
    builder = PreviewBuilder(tex_settings(), tmp_path / "build")
    original = (root / "main.tex").read_text()
    broken = ProposedChange(root, "main.tex", original, original.replace(r"\end{itemize}", ""), "broken")
    result = builder.proposed(root, "main.tex", [broken])
    assert result.errors and result.added_errors   # LaTeX recovers (PDF produced), but the new error is flagged


def test_declining_push_discards_the_commit(tmp_path, git_project):
    remote, _ = git_project

    def responder(system, messages, tools=None, max_tokens=None):
        text = messages[0]["content"].split("<text>\n", 1)[1].rsplit("\n</text>", 1)[0]
        return text_msg(f"<edited>\n{text.replace('Protein folding is hard', 'It is hard')}\n</edited>")

    engine, approver = build(tmp_path, remote, SimpleNamespace(create=responder))
    engine.options = replace(engine.options, confirm_push=True)
    approver.stop()
    bus, gate = engine.bus, engine.gate
    stop = threading.Event()
    seen = []

    def answer():  # approve the change, decline the push
        while not stop.is_set():
            for event in bus.drain():
                seen.append(event.kind)
                if event.kind == EventKind.APPROVAL_REQUEST:
                    gate.resolve(event.data["request_id"], True)
                elif event.kind == EventKind.CONFIRM_PUSH:
                    gate.resolve(event.data["request_id"], False)
            stop.wait(0.02)

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    try:
        result = SafeEditWorkflow(engine, section_title="Introduction").run()
    finally:
        stop.set()
        thread.join()
    assert "discarded" in result.summary.lower()
    assert EventKind.CONFIRM_PUSH in seen
    clone = Repo(tmp_path / "clone")
    assert clone.active_branch.name == "master" and not clone.is_dirty(untracked_files=True)
    assert [h.name for h in clone.heads] == ["master"]
    assert [h.name for h in Repo(remote).heads] == ["master"]
    assert "Protein folding is hard" in (tmp_path / "clone" / "main.tex").read_text()
