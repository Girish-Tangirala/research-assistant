"""Deterministic citation / BibTeX audit (Workflow 2 and the ``validate_bib`` tool).

The audit is intentionally LLM-free: metadata such as DOIs must never be
invented. Findings include "did you mean" suggestions for likely typos.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.latex_parser import (
    BibEntry,
    Citation,
    extract_citations,
    find_bib_files,
    find_main_tex,
    flatten_inputs,
    load_bib_files,
)

DOI_EXPECTED_TYPES = {"article", "inproceedings", "incollection", "conference", "proceedings"}
DOI_OPTIONAL_TYPES = {"book", "inbook", "phdthesis", "mastersthesis", "techreport"}
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "article": ("author", "title", "journal", "year"),
    "inproceedings": ("author", "title", "booktitle", "year"),
    "conference": ("author", "title", "booktitle", "year"),
    "book": ("title", "publisher", "year"),
    "incollection": ("author", "title", "booktitle", "year"),
    "phdthesis": ("author", "title", "school", "year"),
    "misc": ("title",),
}
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


@dataclass
class Finding:
    severity: str  # "error" | "warning" | "info"
    category: str
    key: str
    message: str
    location: str = ""


@dataclass
class AuditReport:
    main_file: str
    bib_files: list[str]
    cited_keys: int
    bib_entries: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["summary"] = dict(Counter(f.category for f in self.findings))
        return data

    def to_markdown(self) -> str:
        lines = [
            "# Citation & BibTeX Audit",
            "",
            f"- **Main file:** `{self.main_file}`",
            f"- **Bibliography files:** {', '.join(f'`{b}`' for b in self.bib_files) or '_none_'}",
            f"- **Distinct cited keys:** {self.cited_keys}",
            f"- **Bibliography entries:** {self.bib_entries}",
            f"- **Errors / warnings / info:** {len(self.errors)} / "
            f"{sum(f.severity == 'warning' for f in self.findings)} / "
            f"{sum(f.severity == 'info' for f in self.findings)}",
            "",
        ]
        if not self.findings:
            lines.append("No issues found. ✅")
            return "\n".join(lines)
        lines += ["| Severity | Category | Key | Issue | Location |", "|---|---|---|---|---|"]
        order = {"error": 0, "warning": 1, "info": 2}
        for f in sorted(self.findings, key=lambda x: (order[x.severity], x.category, x.key)):
            message = f.message.replace("|", "\\|")
            lines.append(f"| {f.severity} | {f.category} | `{f.key}` | {message} | {f.location} |")
        lines += [
            "",
            "> DOIs are never auto-generated. Verify missing DOIs at https://doi.org or "
            "https://search.crossref.org before adding them.",
        ]
        return "\n".join(lines)


def audit_citations(citations: list[Citation], entries: list[BibEntry]) -> list[Finding]:
    """Compare citation usage against bibliography entries."""
    findings: list[Finding] = []
    by_key: dict[str, list[BibEntry]] = {}
    for entry in entries:
        by_key.setdefault(entry.key, []).append(entry)
    lower_map = {k.lower(): k for k in by_key}
    all_keys = list(by_key)

    cited_lines: dict[str, list[int]] = {}
    for c in citations:
        cited_lines.setdefault(c.key, []).append(c.line)

    for key, lines in sorted(cited_lines.items()):
        if key in by_key:
            continue
        hint = ""
        if key.lower() in lower_map:
            hint = f" Case mismatch – bib has `{lower_map[key.lower()]}`."
        else:
            close = difflib.get_close_matches(key, all_keys, n=2, cutoff=0.75)
            if close:
                hint = f" Did you mean {', '.join(f'`{c}`' for c in close)}?"
        findings.append(
            Finding("error", "missing-key", key, f"Cited but not defined in any .bib file.{hint}",
                    f"lines {', '.join(map(str, sorted(set(lines))[:8]))}")
        )

    for key, dupes in by_key.items():
        if len(dupes) > 1:
            locs = ", ".join(f"{d.source}:{d.line}" for d in dupes)
            findings.append(Finding("error", "duplicate-key", key, "Key defined more than once.", locs))

    cited_set = set(cited_lines)
    for key, (entry, *_rest) in by_key.items():
        loc = f"{entry.source}:{entry.line}"
        if key not in cited_set and "*" not in cited_set:
            findings.append(Finding("info", "unused-entry", key, "Entry is never cited.", loc))
        doi = entry.get("doi").strip()
        if doi:
            normalised = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi, flags=re.I)
            if not DOI_RE.match(normalised):
                findings.append(Finding("warning", "malformed-doi", key, f"DOI looks malformed: `{doi}`", loc))
            elif normalised != doi:
                findings.append(Finding("info", "doi-format", key, "Store the bare DOI (10.xxxx/...), not a URL/prefix.", loc))
        elif entry.entry_type in DOI_EXPECTED_TYPES and key in cited_set:
            findings.append(Finding("warning", "missing-doi", key, f"@{entry.entry_type} entry has no DOI.", loc))
        elif entry.entry_type in DOI_OPTIONAL_TYPES and key in cited_set:
            findings.append(Finding("info", "missing-doi", key, f"@{entry.entry_type} entry has no DOI/ISBN.", loc))
        missing_fields = [f for f in REQUIRED_FIELDS.get(entry.entry_type, ()) if not entry.get(f)]
        if entry.entry_type in ("book", "inbook") and not (entry.get("author") or entry.get("editor")):
            missing_fields.append("author/editor")
        if missing_fields:
            findings.append(
                Finding("warning", "missing-fields", key, f"Missing required field(s): {', '.join(missing_fields)}", loc)
            )
    return findings


def run_audit(project_root: Path, main_tex: Path | None = None) -> AuditReport:
    """Audit a whole project rooted at ``project_root``.

    Raises:
        FileNotFoundError: if no main .tex document can be found.
    """
    main = main_tex or find_main_tex(project_root)
    if main is None:
        raise FileNotFoundError(f"No .tex file with \\documentclass found under {project_root}")
    tex = flatten_inputs(main, project_root)
    bib_paths = find_bib_files(tex, project_root)
    entries = load_bib_files(bib_paths, project_root)
    citations = extract_citations(tex)
    report = AuditReport(
        main_file=main.relative_to(project_root).as_posix(),
        bib_files=[p.relative_to(project_root).as_posix() if project_root in p.parents else str(p) for p in bib_paths],
        cited_keys=len({c.key for c in citations}),
        bib_entries=len(entries),
    )
    for path in bib_paths:
        if not path.is_file():
            report.findings.append(Finding("error", "missing-bib-file", path.name, "Declared .bib file does not exist."))
    if "\\begin{thebibliography}" in tex:
        report.findings.append(
            Finding("info", "manual-bibliography", "-", "Document uses an inline thebibliography environment; "
                    "entries there are not checked.")
        )
    report.findings.extend(audit_citations(citations, entries))
    return report
