"""End-to-end engine tests against a real local Git remote, with a fake LLM."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo

from config import AppConfig, GitSettings, LatexSettings, LLMSettings
from core.agent_engine import AgentEngine, RunOptions
from core.app_state import PaperSpec
from core.credentials import GitCredential, redact
from core.events import ApprovalGate, CancelToken, EventBus, EventKind
from core.git_manager import GitAuthError, GitManager
from core.workflows import SafeEditWorkflow


def make_config(tmp_path: Path, push_strategy: str = "feature-branch") -> AppConfig:
    config = AppConfig(
        llm=LLMSettings(),
        git=GitSettings(author_name="Agent", author_email="agent@test.org", push_strategy=push_strategy),
        latex=LatexSettings(latexmk_path=None, pdflatex_path=None),
        workspace=tmp_path / "ws",
    )
    for d in (config.workspace, config.build_dir, config.reports_dir, config.papers_dir):
        d.mkdir(parents=True, exist_ok=True)
    return config


class AutoApprover:
    """Drains the bus in a thread and answers approval requests."""

    def __init__(self, bus: EventBus, gate: ApprovalGate, approve: bool) -> None:
        self.events = []
        self._bus = bus
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(bus, gate, approve), daemon=True)
        self._thread.start()

    def _loop(self, bus, gate, approve):
        while not self._stop.is_set():
            for event in bus.drain():
                self.events.append(event)
                if event.kind in (EventKind.APPROVAL_REQUEST, EventKind.CONFIRM_PUSH):
                    gate.resolve(event.data["request_id"], approve)
            self._stop.wait(0.02)

    def stop(self):
        self._stop.set()
        self._thread.join()
        self.events.extend(self._bus.drain())


class FakeLLM:
    """Returns scripted responses shaped like BetaMessage."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.tools = []

    def create(self, system, messages, tools=None, max_tokens=None):
        self.calls.append(list(messages))  # snapshot; the engine keeps appending
        self.tools.append(tools)
        return self.responses.pop(0)


def text_msg(text):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def tool_msg(*calls):
    blocks = [SimpleNamespace(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(calls)]
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


def build(tmp_path, remote, llm, approve=True, push_strategy="feature-branch", web_search=False, literature=None):
    config = make_config(tmp_path, push_strategy)
    bus, cancel = EventBus(), CancelToken()
    gate = ApprovalGate(bus, cancel)
    spec = PaperSpec("Test paper", str(remote), str(tmp_path / "clone"))
    engine = AgentEngine(config, bus, cancel, gate, spec, RunOptions(push=True, web_search=web_search),
                         llm=llm, literature=literature)
    return engine, AutoApprover(bus, gate, approve)


def test_safe_edit_workflow_commits_and_pushes_feature_branch(tmp_path, git_project):
    remote, _ = git_project

    def responder(system, messages, tools=None, max_tokens=None):
        prompt = messages[0]["content"]
        text = prompt.split("<text>\n", 1)[1].rsplit("\n</text>", 1)[0]
        edited = text.replace("Protein folding is hard", "Protein structure prediction is challenging")
        return text_msg(f"<edited>\n{edited}\n</edited>\n<changes>- reworded</changes>")

    engine, approver = build(tmp_path, remote, SimpleNamespace(create=responder))
    try:
        result = SafeEditWorkflow(engine, section_title="Introduction").run()
    finally:
        approver.stop()
    assert "pushed" in result.summary
    remote_repo = Repo(remote)
    feature = next(h.name for h in remote_repo.heads if h.name.startswith("agent/"))
    content = remote_repo.git.show(f"{feature}:main.tex")
    assert "Protein structure prediction is challenging" in content
    assert "\\frac{1}{N}\\sum_{i=1}^{N}" in content
    assert remote_repo.git.show("master:main.tex").count("Protein folding is hard") == 1


def test_rejected_change_writes_nothing(tmp_path, git_project):
    remote, _ = git_project
    llm = FakeLLM([
        tool_msg(("pull_repo", {})),
        tool_msg(("edit_section", {"section_title": "Method",
                                   "new_body": "Details follow.\n\\input{sections/method}\n",
                                   "rationale": "add lead-in sentence"})),
        tool_msg(("commit_and_push", {"message": "Tweak"})),
        text_msg("done"),
    ])
    engine, approver = build(tmp_path, remote, llm, approve=False)
    try:
        assert engine.run_agent("tweak method") == "done"
    finally:
        approver.stop()
    assert any(e.kind == EventKind.APPROVAL_REQUEST for e in approver.events)
    assert not Repo(tmp_path / "clone").is_dirty()
    assert [h.name for h in Repo(remote).heads] == ["master"]


def test_agent_gets_integrity_errors_back(tmp_path, git_project):
    remote, _ = git_project
    llm = FakeLLM([
        tool_msg(("pull_repo", {})),
        tool_msg(("edit_section", {"section_title": "Introduction",
                                   "new_body": "All math removed.", "rationale": "bad"})),
        text_msg("gave up"),
    ])
    engine, approver = build(tmp_path, remote, llm)
    try:
        engine.run_agent("break it")
    finally:
        approver.stop()
    last_results = llm.calls[-1][-1]["content"]
    assert last_results[0]["is_error"] is True
    assert "Citations removed" in last_results[0]["content"]
    assert not engine.pending


def test_web_search_tool_is_offered_only_when_enabled(tmp_path, git_project):
    remote, _ = git_project
    for enabled in (True, False):
        llm = FakeLLM([text_msg("ok")])
        engine, approver = build(tmp_path / str(enabled), remote, llm, web_search=enabled)
        approver.stop()
        engine.run_agent("hello")
        names = [t.get("name") for t in llm.tools[0]]
        assert ("web_search" in names) is enabled
        assert "search_papers" in names


def test_path_traversal_blocked(tmp_path, git_project):
    remote, _ = git_project
    engine, approver = build(tmp_path, remote, FakeLLM([]))
    try:
        engine.tool_pull_repo()
        output, is_error = engine.execute_tool("read_tex_file", {"path": "../../etc/passwd"})
    finally:
        approver.stop()
    assert is_error and "escapes" in output


def test_merge_to_default_strategy_pushes_master(tmp_path, git_project):
    remote, _ = git_project
    config = make_config(tmp_path, "merge-to-default")
    git = GitManager(tmp_path / "clone2", str(remote), settings=config.git)
    git.sync()
    branch = git.create_feature_branch("fix typo")
    (git.local_path / "main.tex").write_bytes(b"changed\n")
    git.commit(["main.tex"], "Fix typo")
    assert git.publish(branch) == "master"
    assert Repo(remote).git.show("master:main.tex") == "changed"


def test_auth_failure_raises_git_auth_error(tmp_path):
    git = GitManager(tmp_path / "x", "https://github.com/x/y.git",
                     credential=GitCredential("github.com", "u", "tok"))
    from git import GitCommandError

    error = git._wrap("push", GitCommandError(["git", "push"], 128, stderr="fatal: Authentication failed for tok"))
    assert isinstance(error, GitAuthError) and error.host == "github.com"
    assert "tok" not in str(error)


def test_token_redaction():
    text = "fatal: https://git:s3cr3t@git.overleaf.com/abc Authorization: Basic Z2l0OnMzY3IzdA=="
    redacted = redact(text, GitCredential("git.overleaf.com", "git", "s3cr3t"))
    assert "s3cr3t" not in redacted and "Z2l0OnMzY3IzdA==" not in redacted


def test_dirty_repo_refuses_sync(tmp_path, git_project):
    remote, _ = git_project
    git = GitManager(tmp_path / "clone3", str(remote), settings=GitSettings())
    git.sync()
    (git.local_path / "main.tex").write_text("dirty", encoding="utf-8")
    with pytest.raises(Exception, match="uncommitted"):
        git.sync()
