"""The pre-configured agent workflows (all operate on the selected paper).

1. :class:`LiteratureReviewWorkflow` - search the literature and write a
   verifiable review (read-only; never edits the paper).
2. :class:`CitationAuditWorkflow`    - deterministic citation & BibTeX audit.
3. :class:`SafeEditWorkflow`         - safe LaTeX structural editing.
4. :class:`CustomAgentWorkflow`      - free-form ReAct task with all tools.

LLM outputs that become LaTeX are validated by :mod:`core.latex_safety` with
automatic repair rounds, and all file changes go through
:meth:`AgentEngine.review_apply_commit` for human approval.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from core.agent_engine import AgentEngine, AgentError, WorkflowState
from core.citation_audit import run_audit
from core.events import EventKind, ProposedChange
from core.latex_parser import find_section, flatten_inputs, match_brace, replace_section_body, split_sections, strip_comments
from core.latex_safety import LatexIntegrityError, protect, restore, validate_edit
from core.literature import match_bibliography, records_in_report, records_to_bibtex, verify_report
from core.llm_client import LLMTruncated, extract_tagged, text_of
from core.git_manager import tracked_files
from core.paper import read_text
from core.reorganize import plan_reorganisation, plan_to_markdown
from core.prompts import LIT_REVIEW_SYSTEM, LIT_REVIEW_TASK, REPAIR_PROMPT, SAFE_EDIT_PROMPT, SAFE_EDIT_SYSTEM
from core.tool_schemas import LITERATURE_TOOLS

MAX_REPAIR_ATTEMPTS = 3


@dataclass
class WorkflowResult:
    success: bool
    summary: str
    artifacts: list[Path] = field(default_factory=list)


def extract_title(tex: str) -> str:
    text = strip_comments(tex)
    match = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{", text)
    if not match:
        return "Untitled"
    try:
        end = match_brace(text, match.end() - 1)
    except ValueError:
        return "Untitled"
    title = re.sub(r"\\\\|\\[a-zA-Z]+\*?|[{}]", " ", text[match.end() : end])
    return " ".join(title.split()) or "Untitled"


def extract_abstract(tex: str) -> str:
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", strip_comments(tex), re.DOTALL)
    return match.group(1).strip() if match else ""


class BaseWorkflow:
    """Shared helpers for workflows."""

    name: ClassVar[str] = "Workflow"
    needs_llm: ClassVar[bool] = True

    def __init__(self, engine: AgentEngine, **params: Any) -> None:
        self.engine = engine
        self.params = params

    @classmethod
    def requires_llm(cls, params: dict[str, Any]) -> bool:
        """Whether this run needs a Claude sign-in (may depend on the options chosen)."""
        return cls.needs_llm

    def run(self) -> WorkflowResult:  # pragma: no cover - interface
        raise NotImplementedError

    def locate_section(self, title: str, path: str | None = None) -> Path:
        """File containing section ``title`` (main file first, then other .tex files)."""
        paper = self.engine.paper
        if path:
            return paper.resolve(path)
        main = paper.main_tex()
        candidates = [main] + sorted(p for p in paper.root.rglob("*.tex") if p != main and ".git" not in p.parts)
        for candidate in candidates:
            if find_section(read_text(candidate), title) is not None:
                return candidate
        raise AgentError(f"Section {title!r} not found in any .tex file of the paper")

    def log(self, message: str, kind: EventKind = EventKind.INFO, **data: Any) -> None:
        self.engine.log(message, kind, **data)

    def write_artifact(self, stem: str, content: str, suffix: str = ".md", show: bool = True) -> Path:
        path = self.engine.config.reports_dir / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{suffix}"
        path.write_text(content, encoding="utf-8")
        if show:
            self.log(f"Report saved to {path}", EventKind.ARTIFACT, path=str(path), markdown=content)
        else:
            self.log(f"Saved {path}")
        return path

    def generate_validated(self, system: str, prompt: str | list[dict[str, Any]], tag: str | None,
                           validate: Callable[[str], Any], repair_tag: str | None = None) -> tuple[Any, str]:
        """Ask the LLM for ``<tag>`` output and repair until ``validate`` passes.

        With ``tag=None`` the whole response text is passed to ``validate``
        (which raises :class:`LatexIntegrityError` on problems). ``prompt`` may be
        a list of content blocks (e.g. an image plus text).

        Returns:
            ``(validated_value, full_response_text)``.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            self.engine.cancel.raise_if_cancelled()
            response = self.engine.llm.create(system, messages)
            if response.stop_reason == "max_tokens":
                raise LLMTruncated("LLM output truncated - increase AGENT_MAX_TOKENS.")
            text = text_of(response)
            candidate = extract_tagged(text, tag) if tag else text
            if candidate is None:
                problems = [f"Output must be wrapped in <{tag}>...</{tag}> tags."]
            else:
                try:
                    return validate(candidate), text
                except LatexIntegrityError as exc:
                    problems = exc.problems
            self.log(f"Validation failed (attempt {attempt}/{MAX_REPAIR_ATTEMPTS}): "
                     + "; ".join(problems), EventKind.WARNING)
            messages += [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": REPAIR_PROMPT.format(
                    problems="\n".join(f"- {p}" for p in problems), tag=repair_tag or tag)},
            ]
        raise AgentError("LLM output could not be validated after repeated attempts; nothing was changed.")


# ---------------------------------------------------------------------- #
# Workflow 1: Literature review
# ---------------------------------------------------------------------- #
class LiteratureReviewWorkflow(BaseWorkflow):
    """Search for related work and produce a verifiable review report.

    Params:
        topic: Research topic (blank = derived from the paper's title/abstract).
        focus: Optional extra guidance (sub-questions, methods, exclusions).
        max_papers: Approximate number of papers to include (default 20).
        year_from: Optional earliest publication year.
    """

    name = "Literature Review"

    def _context(self, tex: str) -> str:
        parts = []
        abstract = extract_abstract(tex)
        if abstract:
            parts.append(f"Abstract:\n{abstract}")
        titles = [s.title for s in split_sections(tex) if s.level <= 3]
        if titles:
            parts.append("Sections: " + "; ".join(titles))
        intro = find_section(tex, "Introduction")
        if intro is not None:
            parts.append(f"Introduction:\n{intro.body(tex).strip()}")
        return "\n\n".join(parts) or "(No abstract or introduction found - use read_tex_file.)"

    def run(self) -> WorkflowResult:
        engine = self.engine
        paper = engine.paper
        engine.set_state(WorkflowState.SYNCING)
        paper.git.sync()

        engine.set_state(WorkflowState.ANALYZING)
        engine.refresh_protection()
        tex = flatten_inputs(paper.main_tex(), paper.root)
        title = extract_title(tex)
        entries = engine.bib_entries()
        topic = (self.params.get("topic") or "").strip() or title
        max_papers = int(self.params.get("max_papers") or 20)
        year_from = self.params.get("year_from")
        self.log(f"Reviewing literature for '{topic}' ({len(entries)} existing bibliography entries).")

        engine.set_state(WorkflowState.SEARCHING)
        focus = (self.params.get("focus") or "").strip()
        goal = LIT_REVIEW_TASK.format(
            topic=topic,
            focus=f"Focus: {focus}\n" if focus else "",
            max_papers=max_papers,
            years=f", published {year_from} or later" if year_from else "",
            existing="\n".join(f"{e.key} | {e.get('title')}" for e in entries) or "(none)",
            title=title,
            context=self._context(tex),
        )
        answer = engine.run_agent(goal, tool_names=LITERATURE_TOOLS, system=LIT_REVIEW_SYSTEM,
                                  max_steps=max(engine.config.llm.max_agent_steps, 30))

        engine.set_state(WorkflowState.VALIDATING)
        report = extract_tagged(answer, "report") or answer
        search = engine.literature
        found = records_in_report(report, search)
        in_bib = match_bibliography(found, entries)
        unverified = verify_report(report, search)
        new_records = [r for r in found if r.key not in in_bib]

        bib_path = None
        if new_records:
            bib_text = ("% Generated from OpenAlex/Crossref/arXiv metadata - verify before use.\n\n"
                        + records_to_bibtex(new_records, existing_keys={e.key for e in entries}))
            bib_path = self.write_artifact("literature_candidates", bib_text, suffix=".bib", show=False)

        full = [f"# Literature Review: {topic}\n",
                f"*Paper:* {title}  \n*Generated:* {datetime.now():%Y-%m-%d %H:%M} by {engine.config.llm.model}. "
                "Summaries are based on abstracts - read the papers before citing them.\n",
                report.strip(), "\n## Verification\n",
                f"{len(found)} papers in this review were returned by the search tools "
                f"({len(search.registry)} retrieved in total).\n",
                "| Paper | Year | Link | Source | In your .bib |", "|---|---|---|---|---|"]
        for r in sorted(found, key=lambda x: (x.year or 0), reverse=True):
            name = r.title.replace("|", "\\|")
            full.append(f"| {name} | {r.year or ''} | {r.link} | {r.source} | {in_bib.get(r.key, '—')} |")
        if unverified:
            full.append("\n**⚠ Not returned by any search tool - verify these manually:**")
            full += [f"- {item}" for item in unverified]
        else:
            full.append("\nAll DOIs and links in this review were returned by the search tools.")
        if bib_path:
            full.append(f"\nBibTeX for the {len(new_records)} papers not yet in your bibliography: `{bib_path}` "
                        "(not added to your paper).")
            linked = [f for f, why in paper.protection.protected_files().items() if f.endswith(".bib")]
            if linked:
                full.append(f"Your reference-manager bibliography ({', '.join(linked)}) is read-only: add new "
                            "papers in Zotero/Mendeley and click Refresh in Overleaf, or paste the entries "
                            "into a separate editable .bib file.")
        markdown = "\n".join(full) + "\n"
        path = self.write_artifact("literature_review", markdown)
        if unverified:
            self.log(f"{len(unverified)} DOI(s)/link(s) could not be traced to search results - see Verification.",
                     EventKind.WARNING)
        artifacts = [path] + ([bib_path] if bib_path else [])
        return WorkflowResult(True, f"Literature review ready: {len(found)} papers, "
                                    f"{len(new_records)} not yet cited.", artifacts)


class SyncWorkflow(BaseWorkflow):
    """Reload the paper: pull if it has a remote, refresh protection, compile the preview."""

    name = "Refresh paper"
    needs_llm = False

    def run(self) -> WorkflowResult:
        engine = self.engine
        engine.set_state(WorkflowState.SYNCING)
        sha = engine.paper.git.sync()
        engine.refresh_protection()
        engine.set_state(WorkflowState.PREVIEWING)
        engine.preview_current()
        where = "" if engine.paper.git.has_remote else " (local paper)"
        return WorkflowResult(True, f"Refreshed {engine.paper.spec.name} @ {sha}{where}")


class PublishWorkflow(BaseWorkflow):
    """The Sync button: fetch, replay the local commits on top, push.

    Nothing leaves the computer until this runs, so the local repository is the
    working copy and Overleaf is updated when the author decides.
    """

    name = "Sync with Overleaf"
    needs_llm = False

    def run(self) -> WorkflowResult:
        engine = self.engine
        git = engine.paper.git
        if not git.has_remote:
            raise AgentError("This paper is only on this computer. Add its Overleaf project link with "
                             "Edit paper, then press Sync again.")
        where = git.host or "the remote"
        engine.set_state(WorkflowState.SYNCING)
        git.ensure_repo()
        git.fetch()
        ahead, behind = git.counts()
        if not ahead and not behind:
            self.log(f"Already in sync with {where}.", EventKind.SUCCESS)
            return WorkflowResult(True, f"Already in sync with {where} - nothing to send.")
        if ahead and engine.options.confirm_push:
            engine.set_state(WorkflowState.CONFIRMING)
            changes = ", ".join(git.pending_commits()) or f"{ahead} commit(s)"
            question = (f"Send {ahead} change(s) to {where}?"
                        + (f" {behind} change(s) made there will be merged in first." if behind else ""))
            if not engine.gate.ask(EventKind.CONFIRM_PUSH, question, files=git.pending_commits(),
                                   target=where, detail="These changes are in your local paper folder. "
                                                        "Sync sends them to Overleaf and brings back anything "
                                                        "your co-authors changed there."):
                self.log(f"Sync cancelled - nothing was sent. ({changes})", EventKind.WARNING)
                return WorkflowResult(True, "Sync cancelled - nothing was sent.")
        engine.set_state(WorkflowState.PUBLISHING)
        pushed, pulled = git.sync_with_remote()
        engine.refresh_protection()
        engine.set_state(WorkflowState.PREVIEWING)
        engine.preview_current()
        summary = f"Sync complete: {pushed} change(s) sent to {where}, {pulled} received."
        self.log(summary, EventKind.SUCCESS)
        return WorkflowResult(True, summary)


MOVES_LABEL = "(moving files)"


class OrganizeWorkflow(BaseWorkflow):
    """Move an existing paper's files into the standard folders (File → Organise…).

    The text, images, bibliography, code, notes and data of a paper that was
    written before the app existed are sorted into folders, and every LaTeX path
    that pointed at a moved file is rewritten. One approval covers the moves; the
    rewritten .tex files are shown as ordinary diffs, and the preview compiles the
    result before anything is written.
    """

    name = "Organise into folders"
    needs_llm = False

    def run(self) -> WorkflowResult:
        engine, paper = self.engine, self.engine.paper
        engine.set_state(WorkflowState.SYNCING)
        paper.git.sync()
        engine.set_state(WorkflowState.ANALYZING)
        engine.refresh_protection()
        main_rel = paper.rel(paper.main_tex())
        files = tracked_files(paper.git)
        plan = plan_reorganisation(paper.root, files, main_rel, paper.protection.reason)
        report = self.write_artifact("organise", plan_to_markdown(plan, paper.spec.name))
        if plan.empty:
            self.log("This paper is already organised - nothing to move.", EventKind.SUCCESS)
            return WorkflowResult(True, "Already organised - nothing to move.", [report])
        for warning in plan.warnings:
            self.log(warning, EventKind.WARNING)

        engine.set_state(WorkflowState.DRAFTING)
        folders = sorted({m[1].split("/", 1)[0] for m in plan.moves})
        changes = [ProposedChange(paper.root, MOVES_LABEL, "", "",
                                  f"Move {len(plan.moves)} file(s) into {', '.join(folders)}",
                                  moves=tuple(plan.moves))]
        for rel, new_text in plan.rewrites.items():
            source = next((old for old, new in plan.moves if new == rel), rel)
            original = read_text(paper.root / source)
            paper.ensure_writable(source)
            changes.append(ProposedChange(paper.root, rel, original, new_text,
                                          f"Update the paths in {rel}", requires=(MOVES_LABEL,)))
        self.log(f"{len(plan.moves)} file(s) to move; {len(plan.rewrites)} LaTeX file(s) to update.",
                 EventKind.INFO)
        result = engine.review_apply_commit(
            changes, f"Organise {len(plan.moves)} file(s) into folders", topic="organise")
        engine.preview_current()
        return WorkflowResult(True, result, [report])


# ---------------------------------------------------------------------- #
# Workflow 2: Citation & BibTeX audit
# ---------------------------------------------------------------------- #
class CitationAuditWorkflow(BaseWorkflow):
    """Deterministic audit of \\cite usage vs .bib files (read-only)."""

    name = "Citation & BibTeX Audit"
    needs_llm = False

    def run(self) -> WorkflowResult:
        engine = self.engine
        engine.set_state(WorkflowState.SYNCING)
        engine.paper.git.sync()
        engine.set_state(WorkflowState.ANALYZING)
        audit = run_audit(engine.paper.root)
        report = self.write_artifact("citation_audit", audit.to_markdown())
        counts = Counter(f.severity for f in audit.findings)
        summary = (f"Audit complete: {audit.cited_keys} cited keys, {audit.bib_entries} entries - "
                   f"{counts['error']} errors, {counts['warning']} warnings, {counts['info']} info.")
        self.log(summary, EventKind.WARNING if counts["error"] else EventKind.SUCCESS)
        return WorkflowResult(True, summary, [report])


# ---------------------------------------------------------------------- #
# Workflow 3: Safe LaTeX structural editing
# ---------------------------------------------------------------------- #
class SafeEditWorkflow(BaseWorkflow):
    """Improve clarity/flow of one section with guaranteed LaTeX preservation.

    Params:
        section_title: Section to edit (required).
        instructions: Editing instructions (default: clarity & flow).
        path: Repo-relative .tex file (default: search main file, then subfiles).
    """

    name = "Edit Text"
    DEFAULT_INSTRUCTIONS = ("Improve clarity, flow and concision. Fix grammar. Keep the academic "
                            "register, all technical content, and the paragraph structure.")

    def run(self) -> WorkflowResult:
        engine = self.engine
        paper = engine.paper
        title = (self.params.get("section_title") or "").strip()
        if not title:
            raise AgentError("Please specify the section title to edit.")

        engine.set_state(WorkflowState.SYNCING)
        paper.git.sync()

        engine.set_state(WorkflowState.ANALYZING)
        engine.refresh_protection()
        target = self.locate_section(title, self.params.get("path"))
        paper.ensure_writable(paper.rel(target))
        tex = read_text(target)
        section = find_section(tex, title)
        if section is None:
            raise AgentError(f"Section {title!r} not found in {paper.rel(target)}")
        body = section.body(tex)
        protected = protect(body)
        self.log(f"Editing '{section.title}' in {paper.rel(target)}: "
                 f"{len(protected.originals)} LaTeX constructs protected.")

        def validate(edited: str) -> str:
            restored = restore(protected, edited.strip("\n"))
            report = validate_edit(body.strip("\n"), restored)
            report.raise_if_failed()
            for warning in report.warnings:
                self.log(warning, EventKind.WARNING)
            return restored

        engine.set_state(WorkflowState.DRAFTING)
        new_body, response_text = self.generate_validated(SAFE_EDIT_SYSTEM, SAFE_EDIT_PROMPT.format(
            instructions=self.params.get("instructions") or self.DEFAULT_INSTRUCTIONS,
            text=protected.text.strip("\n"),
        ), "edited", validate)
        change_notes = extract_tagged(response_text, "changes") or ""
        if change_notes:
            self.log("Editor's change notes:\n" + change_notes)

        engine.set_state(WorkflowState.VALIDATING)
        new_tex = replace_section_body(tex, section, new_body)
        change = ProposedChange(paper.root, paper.rel(target), tex, new_tex, f"Copy-edit section '{section.title}'")
        result = engine.review_apply_commit([change], f"Improve clarity of '{section.title}' section",
                                            topic=f"edit-{section.title}")
        return WorkflowResult(True, result)


# ---------------------------------------------------------------------- #
# Workflow 4: Free-form ReAct task
# ---------------------------------------------------------------------- #
class CustomAgentWorkflow(BaseWorkflow):
    """Let Claude plan and act with the full tool set.

    Params:
        goal: Natural-language task description (required).
    """

    name = "Custom Agent Task"

    def run(self) -> WorkflowResult:
        goal = (self.params.get("goal") or "").strip()
        if not goal:
            raise AgentError("Please describe the task for the agent.")
        self.engine.set_state(WorkflowState.ANALYZING)
        answer = self.engine.run_agent(goal)
        if self.engine.pending:
            self.log("Agent finished with uncommitted staged changes - requesting review.", EventKind.WARNING)
            self.engine.review_apply_commit(list(self.engine.pending.values()),
                                            f"Agent task: {goal[:60]}", topic="agent-task")
        if answer:
            self.write_artifact("agent_task", f"# Agent Task\n\n**Goal:** {goal}\n\n{answer}")
        return WorkflowResult(True, "Agent task finished.")

