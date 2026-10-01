"""Summarising papers the researcher already has (Literature Review, second mode).

The search mode finds papers and summarises what the indexes return. This mode
takes papers the researcher names - a PDF on their computer, or a DOI, arXiv id
or link - and summarises each one the same way.

Where a summary's facts come from is never blurred:

* **a link** is resolved through :class:`~core.literature.ScholarlySearch`, so the
  DOI and metadata are the indexes' own and the usual verification table applies;
* **a PDF** is summarised from its own text. A file carries no guaranteed DOI, so
  one printed inside it is only ever used to *look up* verified metadata; if that
  lookup fails the entry says plainly that it came from the researcher's file and
  carries no confirmed DOI.

Read-only, like the review it sits next to: it writes a report and never touches
the manuscript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.agent_engine import AgentError, WorkflowState
from core.events import EventKind
from core.literature import (
    LiteratureError, PaperRecord, match_bibliography, records_to_bibtex,
)
from core.pdf_text import PdfText, PdfTextError, read_pdf
from core.prompts import SUMMARY_ABSTRACT_ONLY, SUMMARY_FULL_TEXT, SUMMARY_PROMPT, SUMMARY_SYSTEM

if TYPE_CHECKING:                                   # pragma: no cover
    from core.workflows import LiteratureReviewWorkflow, WorkflowResult

MAX_PAPERS = 12            # one Claude call each: enough for a reading session, bounded cost
NO_DOI = "no DOI found in the file"


@dataclass
class Summary:
    """One paper and what was said about it."""

    title: str
    summary: str = ""                      # empty until Claude has written one (or it failed)
    record: PaperRecord | None = None      # set when an index confirmed the paper
    file: Path | None = None               # set when it came from the researcher's computer
    note: str = ""                         # how it was read, shown under the heading
    problems: list[str] = field(default_factory=list)

    @property
    def link(self) -> str:
        return self.record.link if self.record else ""

    @property
    def verified(self) -> bool:
        """Did a search index confirm this paper, rather than only the file?"""
        return self.record is not None


def split_identifiers(text: str) -> list[str]:
    """One DOI / arXiv id / link per line, blanks and duplicates removed."""
    seen, out = set(), []
    for line in (text or "").splitlines():
        value = line.strip()
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


def _provenance(pdf: PdfText | None) -> str:
    """What Claude is told about where this material came from."""
    if pdf is None:
        return SUMMARY_ABSTRACT_ONLY
    truncation = ("Only the first part of the PDF was read, so later sections may be missing."
                  if pdf.truncated else "")
    return SUMMARY_FULL_TEXT.format(truncation=truncation).strip()


def _material(summary: Summary, pdf: PdfText | None) -> str:
    """The text Claude is given: the paper itself, or its catalogue entry."""
    parts = []
    if summary.record is not None:
        record = summary.record
        parts.append(f"Title: {record.title}")
        if record.authors:
            parts.append("Authors: " + ", ".join(record.authors[:12]))
        for label, value in (("Year", record.year), ("Venue", record.venue), ("DOI", record.doi),
                             ("Link", record.link), ("Type", record.work_type)):
            if value:
                parts.append(f"{label}: {value}")
        if record.abstract:
            parts.append(f"\nAbstract:\n{record.abstract}")
    if pdf is not None:
        parts.append(f"\nFull text extracted from {pdf.name} ({pdf.pages} page(s)):\n{pdf.text}")
    return "\n".join(parts).strip()


def run_summary(workflow: "LiteratureReviewWorkflow") -> "WorkflowResult":
    """Summarise each paper the researcher named. Returns a report, changes nothing."""
    from core.workflows import WorkflowResult, extract_title

    engine = workflow.engine
    paper = engine.paper
    files = [Path(f) for f in workflow.params.get("files") or []]
    identifiers = split_identifiers(workflow.params.get("identifiers", ""))
    if not files and not identifiers:
        raise AgentError("Choose a PDF or enter a DOI, arXiv id or link of the paper to summarise.")
    if len(files) + len(identifiers) > MAX_PAPERS:
        raise AgentError(f"That is {len(files) + len(identifiers)} papers; summarise at most {MAX_PAPERS} "
                         "at a time so one run stays quick and affordable.")

    engine.set_state(WorkflowState.SYNCING)
    paper.git.sync()
    engine.set_state(WorkflowState.ANALYZING)
    from core.latex_parser import flatten_inputs

    tex = flatten_inputs(paper.main_tex(), paper.root)
    own_title = extract_title(tex)
    topic = (workflow.params.get("topic") or "").strip() or own_title
    entries = engine.bib_entries()
    search = engine.literature

    engine.set_state(WorkflowState.SEARCHING)
    summaries: list[Summary] = []
    for identifier in identifiers:
        engine.cancel.raise_if_cancelled()
        summaries.append(_from_identifier(workflow, search, identifier, topic))
    for path in files:
        engine.cancel.raise_if_cancelled()
        summaries.append(_from_pdf(workflow, search, path, topic))

    usable = [s for s in summaries if s.summary]
    if not usable:
        raise AgentError("None of the papers could be read. " + " ".join(
            problem for s in summaries for problem in s.problems))

    engine.set_state(WorkflowState.VALIDATING)
    records = [s.record for s in usable if s.record is not None]
    in_bib = match_bibliography(records, entries)
    bib_path = None
    new_records = [r for r in records if r.key not in in_bib]
    if new_records:
        bib_text = ("% Generated from OpenAlex/Crossref/arXiv metadata - verify before use.\n\n"
                    + records_to_bibtex(new_records, existing_keys={e.key for e in entries}))
        bib_path = workflow.write_artifact("summary_candidates", bib_text, suffix=".bib", show=False)

    report = _report(summaries, usable, topic, own_title, in_bib, bib_path, engine.config.llm.model)
    path = workflow.write_artifact("paper_summaries", report)
    return WorkflowResult(True, f"Summarised {len(usable)} paper(s); nothing in your paper was changed.",
                          [path])


def _from_identifier(workflow: "LiteratureReviewWorkflow", search, identifier: str, topic: str) -> Summary:
    """Resolve a DOI / arXiv id / link, then summarise its abstract."""
    try:
        record = search.details(identifier)
    except (LiteratureError, OSError) as exc:      # a lookup must never abort the whole run
        workflow.log(f"{identifier}: {exc}", EventKind.WARNING)
        return Summary(title=identifier, summary="", problems=[f"{identifier}: {exc}"])
    summary = Summary(title=record.title or identifier, record=record,
                      note=f"From {record.source}; summarised from the abstract.")
    if not record.abstract:
        summary.note = f"From {record.source}; no abstract was available."
    summary.summary = _ask(workflow, summary, None, topic)
    return summary


def _from_pdf(workflow: "LiteratureReviewWorkflow", search, path: Path, topic: str) -> Summary:
    """Read a PDF, look up its printed DOI if it has one, then summarise its text."""
    try:
        pdf = read_pdf(path)
    except PdfTextError as exc:
        workflow.log(str(exc), EventKind.WARNING)
        return Summary(title=path.name, file=path, summary="", problems=[str(exc)])

    summary = Summary(title=path.name, file=path)
    doi = pdf.doi()
    if doi:
        try:
            summary.record = search.details(doi)
            summary.title = summary.record.title or path.name
            summary.note = (f"Read from your file {path.name} ({pdf.pages} page(s)); the DOI printed in it "
                            f"was confirmed by {summary.record.source}.")
        except (LiteratureError, OSError) as exc:
            workflow.log(f"{path.name}: the DOI {doi} in the file could not be confirmed ({exc}).",
                         EventKind.WARNING)
            summary.note = (f"Read from your file {path.name} ({pdf.pages} page(s)); the DOI printed in it "
                            f"({doi}) could not be confirmed, so it is not quoted here.")
    else:
        summary.note = f"Read from your file {path.name} ({pdf.pages} page(s)); {NO_DOI}."
    if pdf.truncated:
        summary.note += " Only the first part of the file was read."
    summary.summary = _ask(workflow, summary, pdf, topic)
    return summary


def _ask(workflow: "LiteratureReviewWorkflow", summary: Summary, pdf: PdfText | None, topic: str) -> str:
    workflow.log(f"Summarising {summary.title[:70]}…")
    prompt = SUMMARY_PROMPT.format(topic=topic, provenance=_provenance(pdf),
                                   material=_material(summary, pdf))
    response = workflow.engine.llm.create(SUMMARY_SYSTEM, [{"role": "user", "content": prompt}])
    from core.llm_client import text_of

    return text_of(response).strip()


def _report(summaries: list[Summary], usable: list[Summary], topic: str, own_title: str,
            in_bib: dict[str, str], bib_path: Path | None, model: str) -> str:
    """The report: every paper, how it was read, and what could not be confirmed."""
    lines = [f"# Paper summaries: {topic}\n",
             f"*Your paper:* {own_title}  \n*Generated:* {datetime.now():%Y-%m-%d %H:%M} by {model}. "
             "Each summary covers only the paper above it.\n"]
    for summary in usable:
        lines.append(f"## {summary.title}\n")
        details = []
        if summary.record is not None:
            record = summary.record
            if record.authors:
                details.append(", ".join(record.authors[:6]) + (" et al." if len(record.authors) > 6 else ""))
            if record.year:
                details.append(str(record.year))
            if record.venue:
                details.append(record.venue)
            if record.link:
                details.append(record.link)
        elif summary.file is not None:
            details.append(f"`{summary.file}`")
        if details:
            lines.append(" · ".join(details) + "  ")
        lines.append(f"*{summary.note}*\n")
        lines.append(summary.summary.strip() + "\n")

    lines.append("## Where these came from\n")
    lines.append("| Paper | Confirmed by an index | Link | In your .bib |")
    lines.append("|---|---|---|---|")
    for summary in usable:
        name = summary.title.replace("|", "\\|")
        confirmed = summary.record.source if summary.record else "no - your file only"
        where = in_bib.get(summary.record.key, "—") if summary.record else "—"
        lines.append(f"| {name} | {confirmed} | {summary.link or '—'} | {where} |")

    unconfirmed = [s for s in usable if not s.verified]
    if unconfirmed:
        lines.append("\n**⚠ Summarised from your file only.** No index confirmed these, so no DOI is quoted "
                     "for them - check the details yourself before citing:")
        lines += [f"- {s.title}" for s in unconfirmed]
    failed = [s for s in summaries if not s.summary]
    if failed:
        lines.append("\n**Could not be read:**")
        lines += [f"- {problem}" for s in failed for problem in s.problems]
    if bib_path:
        lines.append(f"\nBibTeX for the papers not yet in your bibliography: `{bib_path}` "
                     "(not added to your paper).")
    lines.append("\nNothing in your paper was changed.")
    return "\n".join(lines) + "\n"
