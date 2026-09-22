"""Adding references: resolve identifiers to verified metadata and build BibTeX.

Every added entry comes either from a scholarly index (OpenAlex / Crossref /
arXiv) or from a ``.bib`` file the user chose - never from the language model.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.latex_parser import BibEntry, comment_mask, parse_bib, strip_comments
from core.literature import (
    ARXIV_ID_RE, DOI_IN_TEXT_RE, LiteratureError, PaperRecord, ScholarlySearch, make_bib_key,
    match_bibliography, normalize_doi, normalize_title, records_to_bibtex,
)

TITLE_MATCH_THRESHOLD = 0.9
_KEY_IN_RAW_RE = re.compile(r"^(@\s*[A-Za-z]+\s*[{(]\s*)([^,\s]+)")


@dataclass
class Resolution:
    """Outcome for one requested reference."""

    query: str
    record: PaperRecord | None = None
    key: str = ""
    existing_key: str = ""
    error: str = ""
    suggestions: list[PaperRecord] = field(default_factory=list)


def split_identifiers(text: str) -> list[str]:
    """One reference per non-empty line (titles may contain commas)."""
    seen, items = set(), []
    for line in (text or "").splitlines():
        item = line.strip().strip("•-* ").strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            items.append(item)
    return items


def classify(identifier: str) -> tuple[str, str]:
    """Return ``(kind, value)`` with kind in doi | arxiv | openalex | url | title."""
    text = identifier.strip()
    doi = DOI_IN_TEXT_RE.search(text)
    if doi and (text.lower().startswith(("10.", "doi:", "https://doi.org", "http://doi.org", "https://dx.doi.org"))
                or text == doi.group(0)):
        return "doi", normalize_doi(doi.group(0))
    if re.search(r"arxiv\.org/(abs|pdf)/|^arxiv:", text, re.I) or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", text):
        match = ARXIV_ID_RE.search(text)
        if match:
            return "arxiv", match.group(1)
    if re.fullmatch(r"W\d{4,}", text) or "openalex.org/W" in text:
        return "openalex", text.rsplit("/", 1)[-1]
    if doi:
        return "doi", normalize_doi(doi.group(0))
    if re.match(r"https?://", text):
        return "url", text
    return "title", text


def resolve(identifier: str, search: ScholarlySearch) -> Resolution:
    kind, value = classify(identifier)
    result = Resolution(query=identifier)
    try:
        if kind in {"doi", "arxiv", "openalex"}:
            result.record = search.details(value if kind != "arxiv" else f"arXiv:{value}")
        elif kind == "url":
            result.error = "Only DOI, arXiv and OpenAlex links are supported - paste the DOI or the title."
        else:
            candidates = search.search(value, limit=5)
            wanted = normalize_title(value)
            scored = sorted(((difflib.SequenceMatcher(None, wanted, normalize_title(c.title)).ratio(), c)
                             for c in candidates), key=lambda x: -x[0])
            if scored and scored[0][0] >= TITLE_MATCH_THRESHOLD:
                result.record = scored[0][1]
            else:
                result.error = "No paper with a matching title was found."
                result.suggestions = [c for _, c in scored[:3]]
    except LiteratureError as exc:
        result.error = str(exc)
    return result


def rekey(raw: str, key: str) -> str:
    return _KEY_IN_RAW_RE.sub(lambda m: m.group(1) + key, raw.strip(), count=1)


@dataclass
class ReferencePlan:
    """What will be appended to the target .bib file."""

    added: list[Resolution] = field(default_factory=list)
    duplicates: list[Resolution] = field(default_factory=list)
    unresolved: list[Resolution] = field(default_factory=list)
    imported: list[tuple[str, str]] = field(default_factory=list)   # (new key, original key)
    import_duplicates: list[tuple[str, str]] = field(default_factory=list)  # (key, existing key)
    bibtex: list[str] = field(default_factory=list)

    @property
    def new_keys(self) -> list[str]:
        return [r.key for r in self.added] + [k for k, _ in self.imported]


def plan_references(identifiers: list[str], import_files: list[Path], existing: list[BibEntry],
                    search: ScholarlySearch) -> ReferencePlan:
    """Resolve, de-duplicate and render new BibTeX entries."""
    plan = ReferencePlan()
    used_keys = {e.key for e in existing}
    known = list(existing)
    for identifier in identifiers:
        res = resolve(identifier, search)
        if res.record is None:
            plan.unresolved.append(res)
            continue
        match = match_bibliography([res.record], known)
        if match:
            res.existing_key = next(iter(match.values()))
            plan.duplicates.append(res)
            continue
        entry_text = records_to_bibtex([res.record], used_keys)
        res.key = _KEY_IN_RAW_RE.match(entry_text).group(2)
        used_keys.add(res.key)
        plan.added.append(res)
        plan.bibtex.append(entry_text.strip())
        known.extend(parse_bib(entry_text))

    for path in import_files:
        for entry in parse_bib(path.read_text(encoding="utf-8", errors="replace"), path.name):
            same = _find_same(entry, known)
            if same:
                plan.import_duplicates.append((entry.key, same))
                continue
            key = entry.key
            if key in used_keys:
                record = PaperRecord("bib", key, entry.get("title"), [entry.get("author").split(" and ")[0]],
                                     int(entry.get("year")) if entry.get("year").isdigit() else None)
                key = make_bib_key(record, used_keys)
            used_keys.add(key)
            plan.imported.append((key, entry.key))
            plan.bibtex.append(rekey(entry.raw, key))
            known.append(entry)
    return plan


def _find_same(entry: BibEntry, known: list[BibEntry]) -> str:
    doi = normalize_doi(entry.get("doi"))
    title = normalize_title(entry.get("title"))
    for other in known:
        if doi and normalize_doi(other.get("doi")) == doi:
            return other.key
        if title and normalize_title(other.get("title")) == title:
            return other.key
        if other.key == entry.key and not title:
            return other.key
    return ""


def append_entries(bib_source: str, entries: list[str]) -> str:
    if not entries:
        return bib_source
    body = "\n\n".join(entries)
    prefix = bib_source.rstrip() + "\n\n" if bib_source.strip() else ""
    return f"{prefix}% Added by Research Assistant Agent (metadata from OpenAlex/Crossref/arXiv or your file)\n{body}\n"


def declare_bib_file(main_source: str, bib_rel: str) -> str | None:
    """Make the main file load ``bib_rel``; ``None`` if it already does."""
    body = strip_comments(main_source)
    name = bib_rel[:-4] if bib_rel.endswith(".bib") else bib_rel
    if re.search(r"\\usepackage(\[[^\]]*\])?\{biblatex\}", body):
        if re.search(r"\\addbibresource(\[[^\]]*\])?\{" + re.escape(bib_rel) + r"\}", body):
            return None
        match = re.search(r"\\addbibresource(?:\[[^\]]*\])?\{[^}]*\}[^\n]*\n", main_source)
        anchor = match.end() if match else re.search(r"\\usepackage(\[[^\]]*\])?\{biblatex\}[^\n]*\n",
                                                        main_source).end()
        return main_source[:anchor] + f"\\addbibresource{{{bib_rel}}}\n" + main_source[anchor:]
    mask = comment_mask(main_source)
    for match in re.finditer(r"\\bibliography\s*\{([^}]*)\}", main_source):
        if mask[match.start()]:
            continue
        names = [n.strip() for n in match.group(1).split(",")]
        if name in names or bib_rel in names:
            return None
        new = f"\\bibliography{{{','.join(names + [name])}}}"
        return main_source[:match.start()] + new + main_source[match.end():]
    end = main_source.rfind("\\end{document}")
    if end < 0:
        raise ValueError("Could not find \\end{document} to add the bibliography.")
    return (main_source[:end] + f"\\bibliographystyle{{plain}}\n\\bibliography{{{name}}}\n\n"
            + main_source[end:])


def plan_to_markdown(plan: ReferencePlan, bib_rel: str) -> str:
    lines = [f"# References added to `{bib_rel}`", ""]
    if plan.added or plan.imported:
        lines += ["| Key | Title | Year | Link |", "|---|---|---|---|"]
        for res in plan.added:
            r = res.record
            lines.append(f"| `{res.key}` | {r.title.replace('|', '/')} | {r.year or ''} | {r.link} |")
        for new_key, old_key in plan.imported:
            note = "" if new_key == old_key else f" (renamed from `{old_key}`)"
            lines.append(f"| `{new_key}` | imported from your .bib{note} | | |")
        lines += ["", "Cite them with " + ", ".join(f"`\\cite{{{k}}}`" for k in plan.new_keys) + "."]
    if plan.duplicates or plan.import_duplicates:
        lines += ["", "## Already in your bibliography (skipped)"]
        lines += [f"- {r.query} → `{r.existing_key}`" for r in plan.duplicates]
        lines += [f"- `{k}` from your file → `{e}`" for k, e in plan.import_duplicates]
    if plan.unresolved:
        lines += ["", "## Not added - please check"]
        for res in plan.unresolved:
            lines.append(f"- **{res.query}**: {res.error}")
            lines += [f"  - did you mean: {s.title} ({s.year}) {s.link}" for s in res.suggestions]
    lines += ["", "> Metadata comes from OpenAlex, Crossref or arXiv (or your own .bib file). "
                  "Check author names and venues before submission."]
    return "\n".join(lines) + "\n"
