"""Read-only protection for reference-manager .bib files (and user-listed files)."""

from __future__ import annotations

import pytest
from git import Actor, Repo

from core.app_state import AppState, PaperSpec
from core.events import EventKind, ProposedChange
from core.paper import ReadOnlyFileError
from core.protection import ProtectionPolicy, detect_reference_manager_bib, parse_patterns
from tests.conftest import REFS_BIB
from tests.test_engine_integration import FakeLLM, build, text_msg, tool_msg

ZOTERO_BIB = "\n".join(
    f"@article{{{key},\n  title = {{T{i}}},\n  year = {{2020}}\n}}"
    for i, key in enumerate(["smith_graph_2020", "doe_protein_2021", "li_folding_2019a",
                             "garcia-lopez_deep_2018", "kim_attention_2022"])
)


def test_detection_heuristics(tmp_path):
    cases = {
        "Zotero_Library.bib": "@misc{x, title={a}}",
        "refs.bib": REFS_BIB,
        "exported.bib": "% Exported by Better BibTeX for Zotero\n@misc{x, title={a}}",
        "library.bib": ZOTERO_BIB,
        "mendeley.bib": "@misc{x, title={a}}",
    }
    for name, content in cases.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    reasons = {name: detect_reference_manager_bib(tmp_path / name) for name in cases}
    assert "Zotero" in reasons["Zotero_Library.bib"]
    assert reasons["refs.bib"] is None  # ordinary hand-written keys
    assert "Better BibTeX" in reasons["exported.bib"]
    assert "author_title_year" in reasons["library.bib"]
    assert "Mendeley" in reasons["mendeley.bib"]


def test_policy_patterns_and_auto_detection(tmp_path):
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "zotero.bib").write_text("@misc{x, title={a}}")
    (tmp_path / "refs" / "mine.bib").write_text(REFS_BIB)
    (tmp_path / "figures.tex").write_text("x")
    policy = ProtectionPolicy.build(tmp_path, "figures.tex; chapters/*.tex", auto_detect=True)
    assert policy.reason("refs/zotero.bib").startswith("auto-detected")
    assert policy.reason("./figures.tex").startswith("listed as read-only")
    assert policy.reason("chapters/intro.tex") == "listed as read-only (chapters/*.tex)"
    assert policy.reason("refs/mine.bib") is None
    assert list(policy.protected_files()) == ["figures.tex", "refs/zotero.bib"]
    off = ProtectionPolicy.build(tmp_path, "", auto_detect=False)
    assert off.reason("refs/zotero.bib") is None and off.describe() == "No read-only files."
    assert parse_patterns(" a.bib,\nb/*.bib ;; ") == ["a.bib", "b/*.bib"]
    assert ProtectionPolicy(tmp_path, ["*.bib"]).reason("refs/mine.bib") == "listed as read-only (*.bib)"


def test_protection_settings_persist(tmp_path):
    state = AppState()
    state.upsert(PaperSpec("P", local_path="x", read_only="zotero.bib", auto_protect_bib=False))
    state.save(tmp_path / "s.json")
    loaded = AppState.load(tmp_path / "s.json").get("P")
    assert loaded.read_only == "zotero.bib" and loaded.auto_protect_bib is False
    legacy = tmp_path / "old.json"
    legacy.write_text('{"papers": [{"name": "Old", "local_path": "y"}]}')
    assert AppState.load(legacy).get("Old").auto_protect_bib is True


def _add_zotero_bib(seed_path):
    seed = Repo(seed_path)
    (seed_path / "zotero.bib").write_bytes(ZOTERO_BIB.encode())
    tex = (seed_path / "main.tex").read_text()
    (seed_path / "main.tex").write_bytes(tex.replace(r"\bibliography{refs}", r"\bibliography{refs,zotero}").encode())
    seed.index.add(["zotero.bib", "main.tex"])
    actor = Actor("Overleaf", "o@example.org")
    seed.index.commit("Import Zotero library", author=actor, committer=actor)
    seed.git.push("origin", "master")


def test_agent_cannot_edit_protected_files(tmp_path, git_project):
    remote, seed = git_project
    _add_zotero_bib(seed)
    llm = FakeLLM([
        tool_msg(("pull_repo", {})),
        tool_msg(("insert_section", {"path": "zotero.bib", "title": "X", "body": "y", "rationale": "bad"})),
        text_msg("ok"),
    ])
    engine, approver = build(tmp_path, remote, llm)
    try:
        engine.run_agent("try to edit the zotero file")
    finally:
        approver.stop()
    pull_result = llm.calls[1][-1]["content"][0]["content"]
    assert "Read-only files: zotero.bib (auto-detected" in pull_result
    assert "Never edit read-only files" in llm.calls[0][0]["content"]
    edit_result = llm.calls[2][-1]["content"][0]
    assert edit_result["is_error"] and "zotero.bib is read-only" in edit_result["content"]
    assert not engine.pending
    assert any("Read-only files" in e.message for e in approver.events if e.kind == EventKind.INFO)


def test_final_guard_blocks_workflow_built_changes(tmp_path, git_project):
    remote, seed = git_project
    _add_zotero_bib(seed)
    engine, approver = build(tmp_path, remote, FakeLLM([]))
    try:
        engine.tool_pull_repo()
        original = (engine.paper.root / "zotero.bib").read_text()
        change = ProposedChange(engine.paper.root, "zotero.bib", original, original + "\n% edit", "edit")
        with pytest.raises(ReadOnlyFileError):
            engine.review_apply_commit([change], "Edit bib", topic="bib")
    finally:
        approver.stop()
    assert not any(e.kind == EventKind.APPROVAL_REQUEST for e in approver.events)
    assert (engine.paper.root / "zotero.bib").read_text() == original
    assert [h.name for h in Repo(engine.paper.root).heads] == ["master"]
