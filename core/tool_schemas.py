"""JSON schemas of the tools the agent can call (implemented in :mod:`core.agent_engine`)."""

from __future__ import annotations

from typing import Any


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required}}


_PATH = {"type": "string", "description": "Repo-relative file path; omit for the main .tex file."}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema("pull_repo", "Clone or fast-forward pull the paper's repository.", {}, []),
    _schema("list_project_files", "List .tex and .bib files and the detected main file.", {}, []),
    _schema("read_tex_file", "Read a .tex/.bib file. Optionally expand \\input/\\include recursively.",
            {"path": _PATH,
             "flatten_inputs": {"type": "boolean", "description": "Expand \\input/\\include."},
             "start_line": {"type": "integer", "description": "1-based first line (for large files)."}}, []),
    _schema("list_sections", "List sectioning commands (level, title, line span) in a .tex file.",
            {"path": _PATH}, []),
    _schema("edit_section",
            "Stage a replacement for the BODY of an existing section (header is kept). The new body is "
            "validated: math, citations, labels, refs and environments must be preserved.",
            {"path": _PATH, "section_title": {"type": "string"},
             "new_body": {"type": "string", "description": "Complete new LaTeX body (no \\section line)."},
             "rationale": {"type": "string", "description": "One-line summary shown to the reviewer."}},
            ["section_title", "new_body", "rationale"]),
    _schema("insert_section",
            "Stage a new \\section placed after `after_section` (or before the bibliography). "
            "Citations must exist in the paper's .bib files.",
            {"path": _PATH, "title": {"type": "string"}, "body": {"type": "string"},
             "after_section": {"type": "string", "description": "Title of the section to insert after."},
             "rationale": {"type": "string"}},
            ["title", "body", "rationale"]),
    _schema("validate_bib", "Audit \\cite keys against .bib files: missing keys, duplicates, missing DOIs/fields.",
            {}, []),
    _schema("compile_pdf", "Compile the paper's main .tex (current on-disk state) and report errors.", {}, []),
    _schema("commit_and_push",
            "Show all staged changes to the human for approval, then apply, compile, commit on a feature "
            "branch and push. Call once at the end.",
            {"message": {"type": "string", "description": "Commit message (imperative mood)."}}, ["message"]),
    _schema("search_papers",
            "Search scholarly indexes for papers. Returns title, authors, year, venue, DOI/link, citation "
            "count and abstract. Use several focused queries; combine sources for coverage.",
            {"query": {"type": "string", "description": "Keywords (not a full sentence)."},
             "source": {"type": "string", "enum": ["openalex", "crossref", "arxiv"],
                        "description": "openalex (default, broad), crossref (DOI metadata), arxiv (preprints)."},
             "limit": {"type": "integer", "description": "Results to return (1-25, default 10)."},
             "year_from": {"type": "integer"}, "year_to": {"type": "integer"}},
            ["query"]),
    _schema("get_paper_details", "Fetch full metadata and abstract for a DOI, arXiv id or OpenAlex id.",
            {"identifier": {"type": "string"}}, ["identifier"]),
]
LITERATURE_TOOLS = {"search_papers", "get_paper_details", "read_tex_file", "list_sections", "list_project_files"}
