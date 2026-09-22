"""Agent engine: tool implementations, the ReAct loop and the change pipeline.

The engine works on exactly one paper (a Git repository) and owns everything
with side effects:

* **Tools** exposed to Claude via JSON schemas - repository/LaTeX tools
  (``pull_repo``, ``read_tex_file``, ``edit_section``, ``validate_bib``,
  ``compile_pdf``, ``commit_and_push`` ...) and literature tools
  (``search_papers``, ``get_paper_details``), plus Claude's server-side
  ``web_search`` when enabled.
* **ReAct loop** (:meth:`AgentEngine.run_agent`) - a cancellable, logged tool-use loop.
* **Change pipeline** (:meth:`AgentEngine.review_apply_commit`) - the state machine
  ``PREVIEWING → AWAITING_APPROVAL → APPLYING → COMPILING → COMMITTING →
  CONFIRMING → PUBLISHING`` with rollback when compilation or Git fails. No file
  is written without approval and nothing is pushed without confirmation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from config import AppConfig
from core.app_state import PaperSpec
from core.citation_audit import run_audit
from core.compiler import CompilerNotFoundError, LatexCompiler, new_errors
from core.credentials import GitCredential
from core.events import ApprovalGate, CancelToken, EventBus, EventKind, ProposedChange
from core.git_manager import GitAuthError, GitManager, GitOperationError
from core.latex_parser import flatten_inputs as flatten_tex_inputs
from core.latex_parser import (
    find_bib_files, find_section, insert_section,
    list_tex_files, load_bib_files, replace_section_body, split_sections,
)
from core.latex_safety import validate_edit, validate_fragment
from core.paper import AppliedChanges, PaperHandle, ToolError, apply_changes, read_text, revert_changes
from core.literature import LiteratureError, ScholarlySearch
from core.llm_client import LLMClient, text_of
from core.preview import PreviewBuilder
from core.prompts import AGENT_SYSTEM_PROMPT
from core.tool_schemas import TOOL_SCHEMAS

MAX_TOOL_OUTPUT_CHARS = 300_000
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


class WorkflowState(str, Enum):
    IDLE = "Idle"
    SYNCING = "Syncing repository"
    ANALYZING = "Analyzing"
    SEARCHING = "Searching literature"
    DRAFTING = "Drafting"
    VALIDATING = "Validating"
    PREVIEWING = "Compiling preview"
    AWAITING_APPROVAL = "Awaiting approval"
    APPLYING = "Applying changes"
    COMPILING = "Compiling PDF"
    COMMITTING = "Committing"
    CONFIRMING = "Waiting for push confirmation"
    PUBLISHING = "Pushing"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class AgentError(RuntimeError):
    """Unrecoverable engine failure."""


@dataclass
class RunOptions:
    push: bool = False          # off: commit locally; the Sync button sends it to Overleaf
    compile_before_commit: bool = True
    web_search: bool = True
    preview: bool = True        # compile a PDF preview of proposed changes before approval
    confirm_push: bool = True   # ask before pushing approved, compiled changes


@dataclass
class EngineCredentials:
    """Secrets resolved by the GUI from the credential store for one run."""

    claude_api_key: str | None = None
    git: GitCredential | None = None
    openalex_key: str | None = None


class AgentEngine:
    """Executes tools, the ReAct loop and the approval/commit pipeline for one paper."""

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        cancel: CancelToken,
        gate: ApprovalGate,
        paper: PaperSpec,
        options: RunOptions | None = None,
        credentials: EngineCredentials | None = None,
        llm: LLMClient | None = None,
        literature: ScholarlySearch | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.cancel = cancel
        self.gate = gate
        self.options = options or RunOptions()
        self.credentials = credentials or EngineCredentials()
        self.compiler = LatexCompiler(config.latex, config.build_dir)
        self.preview = PreviewBuilder(config.latex, config.build_dir)
        self._approved_preview = None
        local = paper.local_path.strip() or str(config.papers_dir / paper.name)
        git = GitManager(Path(local), paper.remote_url, paper.branch, config.git,
                         credential=self.credentials.git, log=self.log)
        self.paper = PaperHandle(paper, git)
        self._llm = llm
        self._literature = literature
        self.pending: dict[str, ProposedChange] = {}
        self.state = WorkflowState.IDLE

    # ------------------------------------------------------------------ #
    # Infrastructure
    # ------------------------------------------------------------------ #
    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(
                self.config.llm, api_key=self.credentials.claude_api_key,
                on_text=lambda t: self.bus.emit(EventKind.LLM_TEXT, t),
                on_thinking=lambda t: self.bus.emit(EventKind.THOUGHT, t),
            )
        return self._llm

    @property
    def literature(self) -> ScholarlySearch:
        if self._literature is None:
            self._literature = ScholarlySearch(mailto=self.config.git.author_email,
                                               openalex_key=self.credentials.openalex_key or "")
        return self._literature

    def log(self, message: str, kind: EventKind = EventKind.INFO, **data: Any) -> None:
        self.bus.emit(kind, message, **data)

    def set_state(self, state: WorkflowState) -> None:
        self.cancel.raise_if_cancelled()
        self.state = state
        self.bus.emit(EventKind.STATE, state.value, state=state.name)

    def current_content(self, path: Path) -> str:
        """File content including any staged-but-unapplied edits."""
        staged = self.pending.get(self.paper.rel(path))
        if staged is not None:
            return staged.proposed
        if not path.is_file():
            raise ToolError(f"File not found: {self.paper.rel(path)}")
        return read_text(path)

    def stage_change(self, path: Path, proposed: str, description: str) -> ProposedChange:
        rel = self.paper.rel(path)
        self.paper.ensure_writable(rel)
        existing = self.pending.get(rel)
        if existing is not None:
            existing.proposed = proposed
            existing.description += f"; {description}"
            return existing
        change = ProposedChange(self.paper.root, rel, read_text(path), proposed, description)
        self.pending[rel] = change
        return change

    def refresh_protection(self) -> None:
        """Re-evaluate read-only files after a sync and tell the user about them."""
        self.paper.refresh_protection()
        if self.paper.protection.protected_files():
            self.log(self.paper.protection.describe(), EventKind.INFO)

    def bib_entries(self):
        tex = flatten_tex_inputs(self.paper.main_tex(), self.paper.root)
        return load_bib_files(find_bib_files(tex, self.paper.root), self.paper.root)

    # ------------------------------------------------------------------ #
    # Repository / LaTeX tools
    # ------------------------------------------------------------------ #
    def tool_pull_repo(self) -> str:
        sha = self.paper.git.sync()
        self.refresh_protection()
        return (f"Repository at {self.paper.root} is up to date (HEAD {sha}). "
                f"{self.paper.protection.describe()}")

    def tool_list_project_files(self) -> str:
        files = list_tex_files(self.paper.root)
        return json.dumps({"main_file": self.paper.rel(self.paper.main_tex()), "files": files}, indent=1)

    def tool_read_tex_file(self, path: str | None = None, flatten_inputs: bool = False, start_line: int = 1) -> str:
        target = self.paper.resolve(path)
        text = flatten_tex_inputs(target, self.paper.root) if flatten_inputs else self.current_content(target)
        lines = text.splitlines()
        start = max(1, start_line)
        chunk = "\n".join(lines[start - 1 :])
        if len(chunk) > MAX_TOOL_OUTPUT_CHARS:
            chunk = chunk[:MAX_TOOL_OUTPUT_CHARS]
            shown = chunk.count("\n") + start
            chunk += f"\n[TRUNCATED at line {shown} of {len(lines)} - call again with start_line={shown + 1}]"
        return f"# {self.paper.rel(target)} (lines {start}-{len(lines)})\n{chunk}"

    def tool_list_sections(self, path: str | None = None) -> str:
        target = self.paper.resolve(path)
        tex = self.current_content(target)
        rows = [{"level": s.command, "title": s.title,
                 "lines": [tex.count("\n", 0, s.start) + 1, tex.count("\n", 0, s.end) + 1]}
                for s in split_sections(tex)]
        return json.dumps({"file": self.paper.rel(target), "sections": rows}, indent=1)

    def tool_edit_section(self, section_title: str, new_body: str, rationale: str, path: str | None = None) -> str:
        target = self.paper.resolve(path, for_write=True)
        tex = self.current_content(target)
        section = find_section(tex, section_title)
        if section is None:
            raise ToolError(f"Section {section_title!r} not found in {self.paper.rel(target)}")
        report = validate_edit(section.body(tex), new_body)
        if not report.ok:
            raise ToolError("Edit rejected by LaTeX integrity check:\n- " + "\n- ".join(report.errors))
        self.stage_change(target, replace_section_body(tex, section, new_body),
                          f"Edit '{section.title}': {rationale}")
        warn = f" Warnings: {report.warnings}" if report.warnings else ""
        return f"Staged edit of section '{section.title}' in {self.paper.rel(target)}.{warn}"

    def tool_insert_section(self, title: str, body: str, rationale: str,
                            path: str | None = None, after_section: str = "Introduction") -> str:
        target = self.paper.resolve(path, for_write=True)
        tex = self.current_content(target)
        if find_section(tex, title) is not None:
            raise ToolError(f"Section {title!r} already exists - use edit_section instead")
        report = validate_fragment(body, {e.key for e in self.bib_entries()})
        if not report.ok:
            raise ToolError("Section rejected by LaTeX integrity check:\n- " + "\n- ".join(report.errors))
        new_tex = insert_section(tex, title, body, after_titles=(after_section,) if after_section else ())
        self.stage_change(target, new_tex, f"Insert section '{title}': {rationale}")
        return f"Staged new section '{title}' in {self.paper.rel(target)}."

    def tool_validate_bib(self) -> str:
        return json.dumps(run_audit(self.paper.root).to_dict(), indent=1)

    def tool_compile_pdf(self) -> str:
        try:
            result = self.compiler.compile(self.paper.main_tex(), self.paper.root)
        except CompilerNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        if not result.success:
            raise ToolError(result.summary())
        return result.summary()

    def tool_commit_and_push(self, message: str) -> str:
        if not self.pending:
            raise ToolError("No staged changes.")
        return self.review_apply_commit(list(self.pending.values()), message, topic=message)

    # ------------------------------------------------------------------ #
    # Literature tools
    # ------------------------------------------------------------------ #
    def tool_search_papers(self, query: str, source: str = "openalex", limit: int = 10,
                           year_from: int | None = None, year_to: int | None = None) -> str:
        records = self.literature.search(query, limit, year_from, year_to, source)
        if not records:
            return f"No results from {source} for {query!r}. Try broader or different keywords."
        return json.dumps([r.to_tool_dict() for r in records], indent=1, ensure_ascii=False)

    def tool_get_paper_details(self, identifier: str) -> str:
        record = self.literature.details(identifier)
        return json.dumps(record.to_tool_dict(max_abstract=6000), indent=1, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # Tool dispatch and ReAct loop
    # ------------------------------------------------------------------ #
    def execute_tool(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Run a tool by name; returns ``(output, is_error)``.

        Authentication failures are re-raised so the run stops and the GUI can
        ask the user to sign in again.
        """
        method = getattr(self, f"tool_{name}", None)
        if method is None or name not in {s["name"] for s in TOOL_SCHEMAS}:
            return f"Unknown tool: {name}", True
        preview = {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v) for k, v in args.items()}
        self.log(f"→ {name}({preview})", EventKind.TOOL_CALL)
        try:
            output = method(**args)
        except GitAuthError:
            raise
        except TypeError as exc:
            output, is_error = f"Invalid arguments for {name}: {exc}", True
        except (ToolError, GitOperationError, LiteratureError, FileNotFoundError, OSError, ValueError) as exc:
            output, is_error = str(exc), True
        else:
            is_error = False
        shown = output if len(output) < 600 else output[:600] + f"… ({len(output)} chars)"
        self.log(f"← {name}: {shown}", EventKind.ERROR if is_error else EventKind.TOOL_RESULT)
        return output, is_error

    def _record_server_results(self, content: list[Any]) -> None:
        for block in content:
            if block.type == "server_tool_use":
                self.log(f"→ {block.name}({getattr(block, 'input', {})})", EventKind.TOOL_CALL)
            elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                urls = [r.url for r in block.content if getattr(r, "url", None)]
                self.literature.seen_urls.update(urls)
                self.log(f"← web_search: {len(urls)} results", EventKind.TOOL_RESULT)

    def run_agent(self, goal: str, tool_names: set[str] | None = None,
                  system: str = AGENT_SYSTEM_PROMPT, max_steps: int | None = None) -> str:
        """Run a Claude tool-use loop until the model stops calling tools."""
        tools: list[dict[str, Any]] = [s for s in TOOL_SCHEMAS if tool_names is None or s["name"] in tool_names]
        if self.options.web_search:
            tools.append(WEB_SEARCH_TOOL)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"Paper: {self.paper.spec.name} (repository: {self.paper.root})\n"
                                        f"{self.paper.protection.describe()} Never edit read-only files.\n\n"
                                        f"Task:\n{goal}"}
        ]
        limit = max_steps or self.config.llm.max_agent_steps
        for step in range(1, limit + 1):
            self.cancel.raise_if_cancelled()
            self.log(f"Agent step {step}/{limit}", EventKind.STATE, state=self.state.name)
            response = self.llm.create(system, messages, tools=tools)
            messages.append({"role": "assistant", "content": response.content})
            self._record_server_results(response.content)
            if response.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "max_tokens" and not tool_uses:
                raise AgentError("Model output was truncated (max_tokens). Increase AGENT_MAX_TOKENS.")
            if not tool_uses:
                return text_of(response)
            results = []
            for block in tool_uses:
                self.cancel.raise_if_cancelled()
                output, is_error = self.execute_tool(block.name, dict(block.input))
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        raise AgentError(f"Agent did not finish within {limit} steps (AGENT_MAX_STEPS).")

    # ------------------------------------------------------------------ #
    # Change pipeline (human-in-the-loop state machine)
    # ------------------------------------------------------------------ #
    def _compile_check(self, git: GitManager, approved: list[ProposedChange], applied: AppliedChanges) -> None:
        """Compile the approved changes; roll back only if they add errors the paper did not have.

        Like Overleaf, a paper with recoverable LaTeX errors still gives a PDF. Errors that were
        already there before the change are reported, not blamed on the change.
        """
        if not self.options.compile_before_commit:
            return
        if not self.compiler.available:
            self.log("No LaTeX compiler found - skipping compile check.", EventKind.WARNING)
            return
        result = self.compiler.compile(self.paper.main_tex(), self.paper.root)
        if not result.clean:
            revert_changes(git, applied)  # compile the paper as it was, in a separate build folder
            baseline = LatexCompiler(self.compiler.settings, self.compiler.build_root / "_baseline").compile(
                self.paper.main_tex(), self.paper.root)
            apply_changes(approved, applied)
            added = new_errors(baseline.errors, result.errors)
            if baseline.success and (not result.success or added):
                problems = result.summary() if not result.success else "\n".join(added[:15])
                raise AgentError(f"The change adds LaTeX errors the paper did not have before - rolled back.\n"
                                 f"{problems}")
            if not result.success:
                self.log("The paper did not compile before the change either; proceeding.", EventKind.WARNING)
            else:
                self.log(f"The paper already had {len(result.errors)} LaTeX error(s) before this change "
                         f"(not caused by it); the PDF is still produced, as in Overleaf:\n"
                         + "\n".join(result.errors[:5]), EventKind.WARNING)
        else:
            self.log(result.summary(), EventKind.SUCCESS)
        if result.success and self.options.preview:
            main_rel = self.paper.rel(self.paper.main_tex())
            self._approved_preview = self.preview.approved(result, self.paper.root, main_rel)
            self.log("", EventKind.PREVIEW, result=self._approved_preview)

    def preview_current(self) -> None:
        """Compile the checkout as it is and show it in the preview pane."""
        if self.options.preview and self.preview.available:
            self.log("", EventKind.PREVIEW, compiling="Compiling current version…")
            main_rel = self.paper.rel(self.paper.main_tex())
            self.log("", EventKind.PREVIEW, result=self.preview.current(self.paper.root, main_rel))

    def _preview_proposed(self, changes: list[ProposedChange]) -> None:
        if not (self.options.preview and self.preview.available):
            return
        self.set_state(WorkflowState.PREVIEWING)
        self.log("", EventKind.PREVIEW, compiling="Compiling a preview of the proposed changes…")
        result = self.preview.proposed(self.paper.root, self.paper.rel(self.paper.main_tex()), changes)
        self.log("", EventKind.PREVIEW, result=result)
        if not result.success:
            self.log("The proposed changes do not compile - see the preview pane. Rejecting is recommended.",
                     EventKind.WARNING)
        elif result.added_errors:
            self.log("The proposed changes add LaTeX error(s) the paper did not have - rejecting is recommended:\n"
                     + "\n".join(result.added_errors[:5]), EventKind.WARNING)

    def review_apply_commit(self, changes: list[ProposedChange], message: str, topic: str) -> str:
        """Approve → write → compile → commit → publish, with rollback."""
        changes = [c for c in changes if not c.is_noop]
        if not changes:
            return "No effective changes to commit."
        for change in changes:  # last line of defence, also for workflow-built changes
            # For a move only the file itself must be writable: its content is not touched, and the
            # destination folder is chosen by the app, not by the model.
            for rel in ([source for source, _target in change.moves] if change.moves else [change.rel_path]):
                self.paper.ensure_writable(rel)
        self._preview_proposed(changes)
        self.set_state(WorkflowState.AWAITING_APPROVAL)
        approved = [c for c in changes if self.gate.request(c)]
        for c in changes:
            self.pending.pop(c.rel_path, None)
        accepted = {c.rel_path for c in approved}
        for change in [c for c in approved if not set(c.requires) <= accepted]:
            self.log(f"Skipping {change.rel_path}: it depends on a rejected change.", EventKind.WARNING)
            approved.remove(change)
        if not approved:
            self.log("All proposed changes were rejected - nothing committed.", EventKind.WARNING)
            return "The reviewer rejected all changes. Nothing was written."

        self.set_state(WorkflowState.APPLYING)
        git = self.paper.git
        branch = git.create_feature_branch(topic)
        applied = AppliedChanges(self.paper.root)
        try:
            apply_changes(approved, applied)
            self.log(f"Wrote {', '.join(applied.written)}")

            self.set_state(WorkflowState.COMPILING)
            self._compile_check(git, approved, applied)

            self.set_state(WorkflowState.COMMITTING)
            sha = git.commit(applied.written,
                             f"{message}\n\nGenerated by Research Assistant Agent; reviewed by a human.")
        except Exception:
            try:
                revert_changes(git, applied)
                git.abandon_branch(branch)
            except GitOperationError as rollback_exc:
                self.log(f"Rollback problem: {rollback_exc}", EventKind.ERROR)
            raise

        if self.options.push and self.options.confirm_push:
            self.set_state(WorkflowState.CONFIRMING)
            where = git.host or "the remote"
            if not self.gate.ask(EventKind.CONFIRM_PUSH, f"Push the approved changes to {where}?",
                                 files=list(applied.written), target=where):
                git.abandon_branch(branch)
                self.log("Discarded the approved changes - nothing was pushed.", EventKind.WARNING)
                self.preview_current()
                return "Changes discarded before pushing. Nothing was sent."
        self.set_state(WorkflowState.PUBLISHING)
        target = git.publish(branch, push=self.options.push)
        if self._approved_preview is not None and self.options.push:
            self.log("", EventKind.PREVIEW, result=replace(
                self._approved_preview, kind="current", label="Current version (pushed)", changed_pages=[]))
        verb = "pushed" if self.options.push else "committed locally"
        if not self.options.push:
            self.log("Saved in the paper folder. Press 'Sync with Overleaf' when you want to send it.",
                     EventKind.INFO)
        result = f"Commit {sha} on '{branch}' {verb} (target branch: {target}); files: {', '.join(applied.written)}"
        self.log(result, EventKind.SUCCESS)
        return result


def with_identity(config: AppConfig, name: str, email: str) -> AppConfig:
    """Return ``config`` with the commit identity from the Git login applied."""
    if not (name and email):
        return config
    return replace(config, git=replace(config.git, author_name=name, author_email=email))
