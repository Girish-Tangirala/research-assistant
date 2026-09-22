"""Workflows that add material to the paper: figures and references.

5. :class:`AddFiguresWorkflow`    - copy images from anywhere on the computer
   into the paper, insert ``figure`` environments (captions optionally drafted by
   Claude from the image itself) and load ``graphicx`` if needed.
6. :class:`AddReferencesWorkflow` - turn DOIs / arXiv IDs / titles / .bib files
   into verified BibTeX entries, optionally with a sentence citing them.

Both go through the same approval → compile → commit → push pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.agent_engine import AgentError, WorkflowState
from core.events import EventKind, ProposedChange
from core.figures import (
    CONVERTIBLE, FigureError, check_image, convert_to_png, ensure_graphicx, figure_block, graphics_dir,
    image_content_block, include_path, insert_at_section_end, safe_stem, unique_label, unique_rel_path,
)
from core.latex_parser import find_bib_files, find_section, flatten_inputs
from core.latex_safety import LatexIntegrityError, check_braces, check_environments, cite_keys, validate_fragment
from core.llm_client import extract_tagged
from core.paper import read_text
from core.prompts import (
    CITE_SENTENCE_PROMPT, CITE_SENTENCE_SYSTEM, FIGURE_PROMPT, FIGURE_SENTENCE_REQUEST, FIGURE_SYSTEM,
)
from core.references import (
    append_entries, declare_bib_file, plan_references, plan_to_markdown, split_identifiers,
)
from core.workflows import BaseWorkflow, WorkflowResult

PLACEHOLDER_CAPTION = "Caption to be written."


def _structure_problems(tex: str) -> list[str]:
    return check_braces(tex) + check_environments(tex)


def _check_new_structure(before: str, after: str) -> None:
    """The edited file must not have more structural problems than before."""
    new = [p for p in _structure_problems(after) if p not in _structure_problems(before)]
    if new:
        raise LatexIntegrityError(new)


# ---------------------------------------------------------------------- #
# Workflow 5: Add figures
# ---------------------------------------------------------------------- #
class AddFiguresWorkflow(BaseWorkflow):
    """Insert one figure per selected image at the end of a section's text.

    Params:
        files: Absolute paths of images anywhere on the computer (required).
        section_title: Section to place the figures in (required).
        caption: Caption to use (only when a single image is added).
        width: ``\\includegraphics`` width (default ``0.8\\linewidth``).
        placement: Float placement (default ``htbp``).
        draft_captions: Let Claude write captions from the image (default True).
        reference_sentence: Add a sentence referring to each figure (default True).
        folder: Destination folder in the paper (default: auto-detected).
        mode: ``"replace"`` swaps the image of an existing figure instead
            (see :mod:`core.figure_replace` for its parameters).
    """

    name = "Add Figures"

    @classmethod
    def requires_llm(cls, params: dict[str, Any]) -> bool:
        if params.get("mode") == "replace":
            return bool(params.get("draft_captions") and not (params.get("caption") or "").strip())
        needs_caption = params.get("draft_captions", True) and not (params.get("caption") or "").strip()
        return bool(needs_caption or params.get("reference_sentence", True))

    def _caption_and_sentence(self, image: Path, original: Path, section_title: str, section_text: str,
                              label: str, allowed: set[str]) -> tuple[str, str]:
        user_caption = (self.params.get("caption") or "").strip() if len(self.params["files"]) == 1 else ""
        draft = self.params.get("draft_captions", True) and not user_caption
        want_sentence = self.params.get("reference_sentence", True)
        if not (draft or want_sentence):
            return user_caption or PLACEHOLDER_CAPTION, ""

        text = FIGURE_PROMPT.format(
            section_title=section_title, label=label, file_name=original.name, section_text=section_text,
            user_hint=(f"The author's caption (use it as the caption): {user_caption}\n" if user_caption else ""),
            sentence_request=FIGURE_SENTENCE_REQUEST.format(label=label) if want_sentence else "",
        )
        block = image_content_block(image)
        if block is None:
            self.log(f"{original.name} is too large to show to Claude; the caption will rely on the section text.",
                     EventKind.WARNING)
        content = ([block] if block else []) + [{"type": "text", "text": text}]

        def validate(response: str) -> tuple[str, str]:
            problems: list[str] = []
            caption = user_caption or extract_tagged(response, "caption") or ""
            if not caption:
                problems.append("Missing <caption>...</caption>.")
            sentence = (extract_tagged(response, "sentence") or "") if want_sentence else ""
            if want_sentence and f"\\ref{{{label}}}" not in sentence:
                problems.append(f"The <sentence> must reference the figure as Figure~\\ref{{{label}}}.")
            for fragment in filter(None, (caption, sentence)):
                problems += validate_fragment(fragment, allowed).errors
            if "\\label" in caption:
                problems.append("The caption must not contain \\label.")
            if problems:
                raise LatexIntegrityError(problems)
            return caption, sentence

        (caption, sentence), _ = self.generate_validated(FIGURE_SYSTEM, content, None, validate,
                                                         repair_tag="caption> and <sentence")
        return caption, sentence

    def run(self) -> WorkflowResult:
        if self.params.get("mode") == "replace":
            from core.figure_replace import run_replace

            return run_replace(self)
        engine, paper = self.engine, self.engine.paper
        files = [Path(f) for f in self.params.get("files") or []]
        title = (self.params.get("section_title") or "").strip()
        if not files:
            raise AgentError("Choose at least one image to add.")
        if not title:
            raise AgentError("Choose the section the figures should go into.")
        try:
            for warning in [w for f in files for w in check_image(f)]:
                self.log(warning, EventKind.WARNING)
        except FigureError as exc:
            raise AgentError(str(exc)) from exc

        engine.set_state(WorkflowState.SYNCING)
        paper.git.sync()
        engine.set_state(WorkflowState.ANALYZING)
        engine.refresh_protection()
        target = self.locate_section(title)
        target_rel = paper.rel(target)
        paper.ensure_writable(target_rel)
        main = paper.main_tex()
        main_rel = paper.rel(main)
        tex = read_text(target)
        main_src = tex if target == main else read_text(main)
        section = find_section(tex, title)
        folder = (self.params.get("folder") or "").strip().strip("/") or graphics_dir(paper.root, main_src)
        allowed = {e.key for e in engine.bib_entries()}
        all_tex = [read_text(p) for p in paper.root.rglob("*.tex") if ".git" not in p.parts]
        work_dir = engine.config.build_dir / "_assets" / paper.root.name
        width = self.params.get("width") or r"0.8\linewidth"
        placement = self.params.get("placement") or "htbp"

        engine.set_state(WorkflowState.DRAFTING)
        taken_paths: set[str] = set()
        taken_labels: set[str] = set()
        changes: list[ProposedChange] = []
        rows: list[tuple[str, str, str]] = []
        new_tex = tex
        for original in files:
            self.engine.cancel.raise_if_cancelled()
            image = convert_to_png(original, work_dir) if original.suffix.lower() in CONVERTIBLE else original
            stem = safe_stem(original.stem)
            asset_rel = unique_rel_path(paper.root, folder, stem, image.suffix.lower(), taken_paths)
            paper.ensure_writable(asset_rel)
            label = unique_label(stem, all_tex, taken_labels)
            caption, sentence = self._caption_and_sentence(image, original, section.title,
                                                           section.body(new_tex), label, allowed)
            block = figure_block(include_path(asset_rel, main_rel), caption, label, width, placement)
            new_tex = insert_at_section_end(new_tex, section.title, f"{sentence}\n\n{block}" if sentence else block)
            section = find_section(new_tex, title)
            changes.append(ProposedChange(paper.root, asset_rel, "", "", f"Add image {original.name}",
                                          source_file=image))
            rows.append((str(original), asset_rel, label))
            if caption == PLACEHOLDER_CAPTION:
                self.log(f"{label}: no caption given - edit the placeholder caption later.", EventKind.WARNING)

        engine.set_state(WorkflowState.VALIDATING)
        requires = tuple(c.rel_path for c in changes)
        if target == main:
            new_tex = ensure_graphicx(new_tex) or new_tex
        else:
            with_graphicx = ensure_graphicx(main_src)
            if with_graphicx:
                paper.ensure_writable(main_rel)
                changes.append(ProposedChange(paper.root, main_rel, main_src, with_graphicx,
                                              "Load the graphicx package"))
                requires += (main_rel,)
        _check_new_structure(tex, new_tex)
        changes.append(ProposedChange(paper.root, target_rel, tex, new_tex,
                                      f"Insert {len(files)} figure(s) into '{section.title}'", requires=requires))

        result = engine.review_apply_commit(changes, f"Add {len(files)} figure(s) to '{section.title}'",
                                            topic="figures")
        lines = [f"# Figures added to '{section.title}'", "", "| Source file | In the paper | Refer to it with |",
                 "|---|---|---|"]
        lines += [f"| {src} | `{rel}` | `Figure~\\ref{{{label}}}` |" for src, rel, label in rows]
        report = self.write_artifact("figures", "\n".join(lines + ["", result]) + "\n")
        return WorkflowResult(True, result, [report])


# ---------------------------------------------------------------------- #
# Workflow 6: Add references
# ---------------------------------------------------------------------- #
class AddReferencesWorkflow(BaseWorkflow):
    """Add verified BibTeX entries (and optionally a citing sentence).

    Params:
        identifiers: DOIs, arXiv IDs/links or titles, one per line.
        bib_files: Paths of .bib files anywhere on the computer to import.
        target_bib: Repo-relative .bib to append to (default: first editable one).
        cite_section: Optional section to cite the new references in.
        write_sentence: Let Claude write the citing sentence (default False).
    """

    name = "Add References"

    @classmethod
    def requires_llm(cls, params: dict[str, Any]) -> bool:
        return bool(params.get("cite_section") and params.get("write_sentence"))

    def _target_bib(self, main_source: str) -> str:
        paper = self.engine.paper
        requested = (self.params.get("target_bib") or "").strip().replace("\\", "/")
        if requested:
            if not requested.endswith(".bib"):
                raise AgentError("The target file must be a .bib file.")
            paper.resolve(requested, for_write=True)
            return requested
        for path in find_bib_files(main_source, paper.root):
            rel = paper.rel(path) if paper.root in path.parents else ""
            if rel and path.is_file() and paper.protection.reason(rel) is None:
                return rel
        name = "references.bib"
        if (paper.root / name).exists() or paper.protection.reason(name):
            name = "references-added.bib"
        self.log(f"No editable .bib file found - new references go into {name}.", EventKind.INFO)
        return name

    def _citing_sentence(self, tex: str, section_title: str, plan: Any, allowed: set[str]) -> str:
        cite_command = "cite"
        existing = [c for c in ("citep", "parencite", "autocite") if f"\\{c}{{" in tex]
        if existing:
            cite_command = existing[0]
        refs = "\n".join(f"{r.key} | {r.record.title} ({r.record.year}) | {r.record.abstract[:600]}"
                         for r in plan.added)
        refs += "".join(f"\n{k} | (imported entry)" for k, _ in plan.imported)
        new_keys = set(plan.new_keys)

        def validate(fragment: str) -> str:
            report = validate_fragment(fragment, allowed)
            problems = list(report.errors)
            if not cite_keys(fragment) & new_keys:
                problems.append("Cite at least one of the new keys.")
            if problems:
                raise LatexIntegrityError(problems)
            return fragment.strip()

        section = find_section(tex, section_title)
        sentence, _ = self.generate_validated(CITE_SENTENCE_SYSTEM, CITE_SENTENCE_PROMPT.format(
            section_title=section.title, cite_command=cite_command, references=refs,
            section_text=section.body(tex)), "latex", validate)
        return sentence

    def run(self) -> WorkflowResult:
        engine, paper = self.engine, self.engine.paper
        identifiers = split_identifiers(self.params.get("identifiers") or "")
        files = [Path(f) for f in self.params.get("bib_files") or []]
        if not identifiers and not files:
            raise AgentError("Enter at least one DOI, arXiv ID or title, or choose a .bib file.")
        for f in files:
            if not f.is_file() or f.suffix.lower() != ".bib":
                raise AgentError(f"Not a .bib file: {f}")

        engine.set_state(WorkflowState.SYNCING)
        paper.git.sync()
        engine.set_state(WorkflowState.ANALYZING)
        engine.refresh_protection()
        main = paper.main_tex()
        main_rel = paper.rel(main)
        main_src = read_text(main)
        flat = flatten_inputs(main, paper.root)
        entries = engine.bib_entries()
        target_rel = self._target_bib(flat)

        engine.set_state(WorkflowState.SEARCHING)
        plan = plan_references(identifiers, files, entries, engine.literature)
        if not plan.bibtex:
            report = self.write_artifact("references", plan_to_markdown(plan, target_rel))
            return WorkflowResult(True, "No new references to add - see the report.", [report])

        engine.set_state(WorkflowState.DRAFTING)
        bib_path = paper.root / target_rel
        bib_original = read_text(bib_path) if bib_path.exists() else ""
        changes = [ProposedChange(paper.root, target_rel, bib_original, append_entries(bib_original, plan.bibtex),
                                  f"Add {len(plan.bibtex)} BibTeX entr{'y' if len(plan.bibtex) == 1 else 'ies'}")]
        bib_ref = include_path(target_rel, main_rel)
        edited: dict[str, tuple[str, str]] = {}
        declared = declare_bib_file(main_src, bib_ref)
        if declared is not None:
            paper.ensure_writable(main_rel)
            edited[main_rel] = (main_src, declared)

        section_title = (self.params.get("cite_section") or "").strip()
        if section_title:
            target = self.locate_section(section_title)
            rel = paper.rel(target)
            paper.ensure_writable(rel)
            before = edited[rel][1] if rel in edited else read_text(target)
            allowed = {e.key for e in entries} | set(plan.new_keys)
            if self.params.get("write_sentence"):
                addition = self._citing_sentence(before, section_title, plan, allowed)
            else:
                addition = "\\cite{" + ",".join(plan.new_keys) + "}"
                self.log("Added a bare \\cite{} at the end of the section - reword it in context.", EventKind.WARNING)
            after = insert_at_section_end(before, find_section(before, section_title).title, addition)
            _check_new_structure(before, after)
            edited[rel] = (edited[rel][0] if rel in edited else before, after)

        for rel, (before, after) in edited.items():
            changes.append(ProposedChange(paper.root, rel, before, after,
                                          "Load the new .bib file / cite the new references",
                                          requires=(target_rel,)))
        result = engine.review_apply_commit(changes, f"Add {len(plan.bibtex)} reference(s)", topic="references")
        report = self.write_artifact("references", plan_to_markdown(plan, target_rel) + "\n" + result + "\n")
        return WorkflowResult(True, result, [report])
