"""Replace the image of an existing figure (the "Replace a figure" mode of Add Figures).

* Same file type: the image file in the paper is overwritten in place, so the
  LaTeX source does not change (unless the caption does).
* Different file type: the new image is added next to the old one and the
  figure's ``\\includegraphics`` points to it; the old file is left in place.
* The caption can be kept, replaced by the author's text or updated by Claude
  after looking at the new image.

Everything goes through the normal preview → approval → compile → push pipeline.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from core.agent_engine import AgentError, WorkflowState
from core.events import EventKind, ProposedChange
from core.figures import (
    CONVERTIBLE, FigureError, check_image, convert_to_png, graphics_dir, image_content_block, include_path,
    safe_stem, unique_rel_path,
)
from core.latex_safety import LatexIntegrityError, check_braces, check_environments, validate_fragment
from core.paper import read_text
from core.prompts import FIGURE_REPLACE_PROMPT, FIGURE_SYSTEM
from core.source_map import caption_span, find_figure, resolve_graphic
from core.workflows import WorkflowResult

if TYPE_CHECKING:
    from core.asset_workflows import AddFiguresWorkflow

CONTEXT_CHARS = 3000


def _structure_problems(tex: str) -> list[str]:
    return check_braces(tex) + check_environments(tex)


def _new_caption(workflow: AddFiguresWorkflow, image: Path, original: Path, label: str, old_caption: str,
                 context: str, allowed: set[str]) -> str:
    """The caption to use: the author's, Claude's, or the current one."""

    def problems_in(caption: str) -> list[str]:
        problems = validate_fragment(caption, allowed).errors
        if "\\label" in caption:
            problems.append("The caption must not contain \\label.")
        return problems

    user_caption = (workflow.params.get("caption") or "").strip()
    if user_caption:
        problems = problems_in(user_caption)
        if problems:
            raise AgentError("The new caption is not valid LaTeX: " + "; ".join(problems))
        return user_caption
    if not workflow.params.get("draft_captions"):
        return old_caption
    block = image_content_block(image)
    if block is None:
        workflow.log(f"{original.name} is too large to show to Claude - keeping the current caption.",
                     EventKind.WARNING)
        return old_caption
    prompt = FIGURE_REPLACE_PROMPT.format(label=label or "(no label)", file_name=original.name,
                                          old_caption=old_caption or "(none)", context=context)

    def validate(text: str) -> str:
        problems = problems_in(text.strip())
        if problems:
            raise LatexIntegrityError(problems)
        return text.strip()

    caption, _ = workflow.generate_validated(FIGURE_SYSTEM, [block, {"type": "text", "text": prompt}],
                                             "caption", validate)
    return caption


def run_replace(workflow: AddFiguresWorkflow) -> WorkflowResult:
    """Params: ``files`` (one image), ``replace_tex``, ``replace_graphic``, ``replace_label``,
    ``replace_line``, ``caption`` (optional) and ``draft_captions``."""
    engine, paper, params = workflow.engine, workflow.engine.paper, workflow.params
    files = [Path(f) for f in params.get("files") or []]
    rel = (params.get("replace_tex") or "").strip().replace("\\", "/")
    graphic = (params.get("replace_graphic") or "").strip()
    label = (params.get("replace_label") or "").strip()
    if len(files) != 1:
        raise AgentError("Choose exactly one new image for the figure.")
    if not rel or not graphic:
        raise AgentError("Choose the figure to replace - click it in the PDF preview or pick it from the list.")
    original = files[0]
    try:
        for warning in check_image(original):
            workflow.log(warning, EventKind.WARNING)
    except FigureError as exc:
        raise AgentError(str(exc)) from exc

    engine.set_state(WorkflowState.SYNCING)
    paper.git.sync()
    engine.set_state(WorkflowState.ANALYZING)
    engine.refresh_protection()
    path = paper.resolve(rel)
    if not path.is_file():
        raise AgentError(f"{rel} no longer exists - sync the paper and pick the figure again.")
    tex = read_text(path)
    figure = find_figure(tex, rel, label, graphic, int(params.get("replace_line") or 0))
    if figure is None:
        raise AgentError(f"The figure ({label or graphic}) was not found in {rel} - the paper may have changed. "
                         "Recompile the preview and click the figure again.")
    main = paper.main_tex()
    main_rel = paper.rel(main)
    main_src = tex if main == path else read_text(main)
    old_rel = resolve_graphic(paper.root, main_rel, main_src, graphic)
    work_dir = engine.config.build_dir / "_assets" / paper.root.name
    image = convert_to_png(original, work_dir) if original.suffix.lower() in CONVERTIBLE else original
    suffix = image.suffix.lower()

    engine.set_state(WorkflowState.DRAFTING)
    changes: list[ProposedChange] = []
    edits: list[tuple[int, int, str]] = []
    if old_rel and PurePosixPath(old_rel).suffix.lower() == suffix:
        paper.ensure_writable(old_rel)
        asset_rel = old_rel
        changes.append(ProposedChange(paper.root, old_rel, "", "", f"Replace {old_rel} with {original.name}",
                                      source_file=image, replaces=True))
    else:
        folder = str(PurePosixPath(old_rel).parent) if old_rel else graphics_dir(paper.root, main_src)
        stem = PurePosixPath(old_rel).stem if old_rel else safe_stem(original.stem)
        asset_rel = unique_rel_path(paper.root, "" if folder == "." else folder, stem, suffix, set())
        paper.ensure_writable(asset_rel)
        changes.append(ProposedChange(paper.root, asset_rel, "", "", f"Add {original.name} as {asset_rel}",
                                      source_file=image))
        target = figure.graphics[0]
        edits.append((target.start, target.end, include_path(asset_rel, main_rel)))
        if old_rel:
            workflow.log(f"{old_rel} stays in the project but is no longer used - delete it in Overleaf "
                         "if you don't need it.", EventKind.INFO)
        else:
            workflow.log(f"The current image file for '{graphic}' was not found; the figure will point to "
                         f"{asset_rel}.", EventKind.WARNING)

    allowed = {e.key for e in engine.bib_entries()}
    context = tex[max(0, figure.start - CONTEXT_CHARS):figure.end + CONTEXT_CHARS // 2]
    caption = _new_caption(workflow, image, original, figure.label, figure.caption, context, allowed)
    span = caption_span(tex, figure)
    if caption != figure.caption:
        if span is None:
            workflow.log("This figure has no \\caption, so the caption was not changed.", EventKind.WARNING)
        else:
            edits.append((span[0], span[1], caption))

    engine.set_state(WorkflowState.VALIDATING)
    if edits:
        paper.ensure_writable(rel)
        new_tex = tex
        for start, end, text in sorted(edits, reverse=True):
            new_tex = new_tex[:start] + text + new_tex[end:]
        new = [p for p in _structure_problems(new_tex) if p not in _structure_problems(tex)]
        if new:
            raise LatexIntegrityError(new)
        changes.append(ProposedChange(paper.root, rel, tex, new_tex,
                                      f"Update figure {figure.label or graphic}", requires=(asset_rel,)))

    name = figure.label or graphic
    result = engine.review_apply_commit(changes, f"Replace figure {name}", topic="figures")
    lines = [f"# Figure {name} replaced", "", f"- New image: {original}", f"- In the paper: `{asset_rel}`",
             f"- Source: `{rel}` line {figure.start_line}",
             f"- Caption: {'updated' if caption != figure.caption and span else 'unchanged'}", "", result]
    report = workflow.write_artifact("figure-replace", "\n".join(lines) + "\n")
    return WorkflowResult(True, result, [report])
