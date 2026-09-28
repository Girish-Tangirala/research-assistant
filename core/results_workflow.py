"""Workflow 7: turn experiment results into a figure or a table.

The user picks result files (or a folder) with a file picker; :mod:`core.results_data`
parses them; Claude chooses which table to show and how (a :class:`ChartSpec`) and
writes the caption; :mod:`core.results_latex` draws it as pgfplots/booktabs code.

The split matters: **Claude never supplies a number**. It names columns that must
already exist, and a spec naming anything else is rejected and repaired. So a chart
can disagree with the file only if the file itself changed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.agent_engine import AgentError, WorkflowState
from core.events import EventKind, ProposedChange
from core.figures import ensure_package, insert_at_section_end, safe_stem
from core.latex_parser import find_section
from core.latex_safety import LatexIntegrityError, validate_fragment
from core.llm_client import extract_tagged
from core.paper import read_text
from core.prompts import RESULTS_PROMPT, RESULTS_SENTENCE_REQUEST, RESULTS_SYSTEM
from core.results_data import ResultTable, ResultsError, collect, summarise
from core.results_latex import ChartSpec, build, float_block, packages_for, unique_label, validate_spec
from core.workflows import BaseWorkflow, WorkflowResult, extract_abstract, extract_title

KIND_WORD = {"table": "Table", "line": "Figure", "bar": "Figure", "matrix": "Figure"}
KIND_CHOICES = {"Let Claude choose": "", "Training curves (line chart)": "line",
                "Comparison bar chart": "bar", "Confusion matrix (heat map)": "matrix",
                "Table of results": "table"}
PLACEHOLDER_CAPTION = "Caption to be written."
_PLAN_LINE = re.compile(r"^\s*([a-z_]+)\s*:\s*(.*?)\s*$")


def parse_plan(text: str) -> dict[str, str]:
    """Read the ``key: value`` lines of the model's <plan> block."""
    plan: dict[str, str] = {}
    for line in text.splitlines():
        match = _PLAN_LINE.match(line)
        if match:
            plan[match.group(1)] = match.group(2)
    return plan


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def plan_to_spec(plan: dict[str, str], caption: str, forced_kind: str, decimals: int) -> ChartSpec:
    legend = {}
    for pair in _split(plan.get("legend", "")):
        if "=" in pair:
            column, nicer = pair.split("=", 1)
            legend[column.strip()] = nicer.strip()
    return ChartSpec(kind=forced_kind or plan.get("kind", "line").strip().lower(),
                     x=plan.get("x", "").strip(), series=_split(plan.get("series", "")),
                     columns=_split(plan.get("series", "")), legend=legend,
                     x_label=plan.get("x_label", "").strip(), y_label=plan.get("y_label", "").strip(),
                     caption=caption, decimals=decimals)


class ResultsFigureWorkflow(BaseWorkflow):
    """Read results files and insert one chart or table into a section.

    Params:
        files: Result files or folders anywhere on the computer (required).
        section_title: Section the figure goes into (required).
        kind: ``line``/``bar``/``matrix``/``table``, or "" to let Claude choose.
        caption: Caption to use (blank = Claude drafts it).
        reference_sentence: Add a sentence referring to the figure (default True).
        decimals: Decimal places for printed numbers (default 3).
        width: ``\\linewidth`` fraction for the chart (default ``0.85\\linewidth``).
        placement: Float placement (default ``htbp``).
    """

    name = "Results Figures & Tables"

    @classmethod
    def requires_llm(cls, params: dict[str, Any]) -> bool:
        chosen_by_hand = bool(params.get("kind") and params.get("x") and params.get("series"))
        has_caption = bool((params.get("caption") or "").strip())
        return not (chosen_by_hand and has_caption and not params.get("reference_sentence", True))

    # -- asking Claude what to draw ------------------------------------ #
    def _ask_plan(self, tables: list[ResultTable], section_title: str, section_text: str, label: str,
                  main_tex: str, allowed: set[str]) -> tuple[ResultTable, ChartSpec, str]:
        user_caption = (self.params.get("caption") or "").strip()
        forced_kind = (self.params.get("kind") or "").strip().lower()
        want_sentence = self.params.get("reference_sentence", True)
        decimals = int(self.params.get("decimals") or 3)
        abstract = extract_abstract(main_tex)
        context = (f"Abstract:\n{abstract}\n\n" if abstract else "") + \
                  f"Section text for context:\n<section>\n{section_text.strip()[:4000]}\n</section>\n"
        hint = []
        if user_caption:
            hint.append(f"The author's caption (use it as the caption): {user_caption}")
        if forced_kind:
            hint.append(f"The author asked for kind={forced_kind}; keep it and choose the columns for it.")
        prompt = RESULTS_PROMPT.format(
            title=extract_title(main_tex), context=context, section_title=section_title, label=label,
            user_hint=("\n".join(hint) + "\n") if hint else "", tables=summarise(tables),
            sentence_request=RESULTS_SENTENCE_REQUEST.format(
                label=label, kind_word=KIND_WORD.get(forced_kind, "Figure")) if want_sentence else "")

        def validate(response: str) -> tuple[ResultTable, ChartSpec, str]:
            problems: list[str] = []
            plan_text = extract_tagged(response, "plan")
            if not plan_text:
                raise LatexIntegrityError(["Missing <plan>...</plan>."])
            plan = parse_plan(plan_text)
            chosen = plan.get("table", "1")
            try:
                table = tables[int(re.sub(r"\D", "", chosen) or 1) - 1]
            except (ValueError, IndexError):
                raise LatexIntegrityError([f"table must be one of 1-{len(tables)} (got {chosen!r})."]) from None
            caption = user_caption or extract_tagged(response, "caption") or ""
            if not caption:
                problems.append("Missing <caption>...</caption>.")
            spec = plan_to_spec(plan, caption, forced_kind, decimals)
            problems += validate_spec(spec, table)
            sentence = (extract_tagged(response, "sentence") or "") if want_sentence else ""
            if want_sentence and f"\\ref{{{label}}}" not in sentence:
                problems.append(f"The <sentence> must refer to it as ~\\ref{{{label}}}.")
            for fragment in filter(None, (caption, sentence)):
                problems += validate_fragment(fragment, allowed).errors
            if "\\label" in caption:
                problems.append("The caption must not contain \\label.")
            if problems:
                raise LatexIntegrityError(problems)
            return table, spec, sentence

        (table, spec, sentence), _ = self.generate_validated(RESULTS_SYSTEM, prompt, None, validate,
                                                             repair_tag="plan> and <caption")
        return table, spec, sentence

    def _manual(self, tables: list[ResultTable]) -> tuple[ResultTable, ChartSpec, str]:
        """Everything was given in the form, so no Claude call is needed."""
        spec = plan_to_spec({"x": self.params.get("x", ""), "series": self.params.get("series", ""),
                             "x_label": self.params.get("x_label", ""),
                             "y_label": self.params.get("y_label", "")},
                            (self.params.get("caption") or "").strip() or PLACEHOLDER_CAPTION,
                            (self.params.get("kind") or "line").strip().lower(),
                            int(self.params.get("decimals") or 3))
        table = tables[0]
        problems = validate_spec(spec, table)
        if problems:
            raise AgentError(" ".join(problems))
        return table, spec, ""

    def run(self) -> WorkflowResult:
        engine, paper = self.engine, self.engine.paper
        paths = [Path(f) for f in self.params.get("files") or []]
        title = (self.params.get("section_title") or "").strip()
        if not paths:
            raise AgentError("Choose the results file(s) or folder to read.")
        if not title:
            raise AgentError("Choose the section the figure should go into.")

        engine.set_state(WorkflowState.SYNCING)
        paper.git.sync()
        engine.set_state(WorkflowState.ANALYZING)
        engine.refresh_protection()
        try:
            tables, warnings = collect(paths)
        except ResultsError as exc:
            raise AgentError(str(exc)) from exc
        for warning in warnings:
            self.log(warning, EventKind.WARNING)
        for table in tables:
            self.log(f"Read {table.name}: {len(table.rows)} rows, columns {', '.join(table.columns)} "
                     f"({table.note}).")

        target = self.locate_section(title)
        target_rel = paper.rel(target)
        paper.ensure_writable(target_rel)
        main = paper.main_tex()
        main_rel = paper.rel(main)
        tex = read_text(target)
        main_src = tex if target == main else read_text(main)
        section = find_section(tex, title)
        all_tex = [read_text(p) for p in paper.root.rglob("*.tex") if ".git" not in p.parts]
        stem = safe_stem(Path(tables[0].source).stem) or "results"

        engine.set_state(WorkflowState.DRAFTING)
        kind_hint = (self.params.get("kind") or "").strip().lower()
        label = unique_label("tab" if kind_hint == "table" else "fig", stem, all_tex, set())
        if self.requires_llm(self.params):
            allowed = {e.key for e in engine.bib_entries()}
            table, spec, sentence = self._ask_plan(tables, section.title, section.body(tex), label,
                                                   main_src, allowed)
        else:
            table, spec, sentence = self._manual(tables)
        if spec.kind == "table" and not label.startswith("tab:"):
            label = unique_label("tab", stem, all_tex, set())
        self.log(f"Plan: {spec.kind} chart of {', '.join(spec.series) or 'all columns'} "
                 f"from '{table.name}' (x = {spec.x or 'rows'}).")

        engine.set_state(WorkflowState.VALIDATING)
        try:
            body = build(table, spec)
        except ResultsError as exc:
            raise AgentError(f"The chart could not be drawn: {exc}") from exc
        block = float_block(body, spec.caption or PLACEHOLDER_CAPTION, label, spec.kind,
                            self.params.get("placement") or "htbp")
        new_tex = insert_at_section_end(tex, section.title, f"{sentence}\n\n{block}" if sentence else block)

        changes: list[ProposedChange] = []
        requires: tuple[str, ...] = ()
        for name, options, extra in packages_for(spec.kind):
            added = ensure_package(new_tex if target == main else main_src, name, options, extra)
            if added is None:
                continue
            if target == main:
                new_tex = added
            else:
                paper.ensure_writable(main_rel)
                changes.append(ProposedChange(paper.root, main_rel, main_src, added,
                                              f"Load the {name} package"))
                requires += (main_rel,)
                main_src = added
        word = KIND_WORD.get(spec.kind, "Figure").lower()
        changes.append(ProposedChange(paper.root, target_rel, tex, new_tex,
                                      f"Insert a results {word} into '{section.title}'", requires=requires))

        result = engine.review_apply_commit(
            changes, f"Add a results {word} to '{section.title}'", topic="results-figure")
        report = self.write_artifact("results_figure", self._report(table, spec, label, result))
        return WorkflowResult(True, result, [report])

    def _report(self, table: ResultTable, spec: ChartSpec, label: str, result: str) -> str:
        shown = ", ".join(spec.series) or ", ".join(table.columns)
        return "\n".join([
            f"# Results {KIND_WORD.get(spec.kind, 'Figure').lower()}: {table.name}", "",
            f"- **Source file:** `{table.source}` ({table.note})",
            f"- **Drawn as:** {spec.kind}", f"- **x axis / row labels:** {spec.x or '(rows)'}",
            f"- **Columns shown:** {shown}",
            f"- **Refer to it with:** `\\ref{{{label}}}`",
            f"- **Rows used:** {len(table.rows)}", "",
            "Every number in the figure was read from the file above; the model chose only "
            "which columns to show and the caption.", "", result, ""])
