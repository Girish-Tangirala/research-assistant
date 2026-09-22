"""Scholarly search (OpenAlex, Crossref, arXiv) with a provenance registry.

Every paper returned to the agent is recorded in :attr:`ScholarlySearch.registry`
(and every URL seen via Claude web search in :attr:`ScholarlySearch.seen_urls`).
After the agent writes its review, :func:`verify_report` flags any DOI or link
that no tool actually returned, so the reader knows exactly what to double-check.
BibTeX is generated only from retrieved metadata - never from the model.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from core.latex_parser import BibEntry

Fetcher = Callable[[str], bytes]
OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
ARXIV = "https://export.arxiv.org/api/query"
CROSSREF_SKIP_TYPES = {"peer-review", "component", "grant", "database"}
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
DOI_IN_TEXT_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>|)\]]+", re.I)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"<>|)\]]+")
ARXIV_ID_RE = re.compile(r"(?:arxiv[:/ ]|abs/)?(\d{4}\.\d{4,5})(v\d+)?", re.I)


class LiteratureError(RuntimeError):
    """A scholarly search request failed."""


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I)
    return doi.rstrip(".,;").lower()


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = re.sub(r"\\[a-zA-Z]+|[{}]", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    """Rebuild an OpenAlex ``abstract_inverted_index`` into plain text."""
    if not inverted:
        return ""
    positions = [(pos, word) for word, poss in inverted.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))


def _strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").split())


@dataclass
class PaperRecord:
    """Metadata for one retrieved paper."""

    source: str
    source_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    cited_by: int | None = None
    work_type: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    arxiv_id: str = ""

    @property
    def key(self) -> str:
        return f"doi:{self.doi}" if self.doi else f"{self.source}:{self.source_id}"

    @property
    def link(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else self.url

    def to_tool_dict(self, max_abstract: int = 1800) -> dict[str, Any]:
        abstract = self.abstract
        if len(abstract) > max_abstract:
            abstract = abstract[:max_abstract] + " …[abstract shortened]"
        return {
            "title": self.title, "authors": self.authors[:6] + (["et al."] if len(self.authors) > 6 else []),
            "year": self.year, "venue": self.venue, "doi": self.doi or None, "link": self.link,
            "cited_by": self.cited_by, "type": self.work_type, "source": self.source,
            "abstract": abstract or "(no abstract available)",
        }


class ScholarlySearch:
    """Thin clients for free scholarly APIs, recording everything they return."""

    def __init__(self, mailto: str = "", openalex_key: str = "", fetch: Fetcher | None = None,
                 timeout: float = 25.0) -> None:
        self.mailto = mailto if "@" in mailto and not mailto.endswith("localhost") else ""
        self.openalex_key = openalex_key
        self.timeout = timeout
        self._fetch = fetch or self._http_get
        self.registry: dict[str, PaperRecord] = {}
        self.seen_urls: set[str] = set()
        self._lock = threading.Lock()
        self._last_arxiv = 0.0

    # -- HTTP ------------------------------------------------------------ #
    def _http_get(self, url: str) -> bytes:
        agent = "ScientificResearchAssistant/1.0" + (f" (mailto:{self.mailto})" if self.mailto else "")
        request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            host = urllib.parse.urlparse(url).hostname
            if exc.code == 429:
                extra = " Add a free OpenAlex API key under Accounts to raise the limit." if "openalex" in (host or "") else ""
                raise LiteratureError(f"{host} rate limit or daily budget reached (HTTP 429).{extra}") from exc
            if exc.code == 404:
                raise LiteratureError(f"Not found at {host}.") from exc
            raise LiteratureError(f"{host} returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LiteratureError(f"Network error contacting {urllib.parse.urlparse(url).hostname}: {exc}") from exc

    def _json(self, url: str) -> dict[str, Any]:
        try:
            return json.loads(self._fetch(url))
        except ValueError as exc:
            raise LiteratureError(f"Unexpected response from {urllib.parse.urlparse(url).hostname}") from exc

    def _register(self, records: Iterable[PaperRecord]) -> list[PaperRecord]:
        out = []
        with self._lock:
            for record in records:
                if not record.title:
                    continue
                self.registry.setdefault(record.key, record)
                out.append(self.registry[record.key])
        return out

    # -- OpenAlex -------------------------------------------------------- #
    def _openalex_params(self, **params: Any) -> str:
        if self.openalex_key:
            params["api_key"] = self.openalex_key
        elif self.mailto:
            params["mailto"] = self.mailto
        return urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})

    @staticmethod
    def _from_openalex(item: dict[str, Any]) -> PaperRecord:
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        biblio = item.get("biblio") or {}
        pages = "--".join(p for p in (biblio.get("first_page"), biblio.get("last_page")) if p)
        return PaperRecord(
            source="openalex",
            source_id=str(item.get("id", "")).rsplit("/", 1)[-1],
            title=item.get("title") or item.get("display_name") or "",
            authors=[(a.get("author") or {}).get("display_name", "") for a in item.get("authorships", [])],
            year=item.get("publication_year"),
            venue=source.get("display_name") or "",
            doi=normalize_doi(item.get("doi")),
            url=location.get("landing_page_url") or item.get("id", ""),
            abstract=reconstruct_abstract(item.get("abstract_inverted_index")),
            cited_by=item.get("cited_by_count"),
            work_type=item.get("type") or "",
            volume=str(biblio.get("volume") or ""),
            issue=str(biblio.get("issue") or ""),
            pages=pages,
            publisher=source.get("host_organization_name") or "",
        )

    def search_openalex(self, query: str, limit: int, year_from: int | None, year_to: int | None) -> list[PaperRecord]:
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        url = f"{OPENALEX}?" + self._openalex_params(search=query, per_page=limit, filter=",".join(filters))
        return [self._from_openalex(i) for i in self._json(url).get("results", [])]

    # -- Crossref -------------------------------------------------------- #
    @staticmethod
    def _from_crossref(item: dict[str, Any]) -> PaperRecord:
        parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
        authors = [" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "")
                   for a in item.get("author", [])]
        return PaperRecord(
            source="crossref", source_id=item.get("DOI", ""),
            title=" ".join(item.get("title") or []), authors=authors,
            year=parts[0] if parts else None,
            venue=" ".join(item.get("container-title") or []),
            doi=normalize_doi(item.get("DOI")), url=item.get("URL", ""),
            abstract=_strip_tags(item.get("abstract", "")),
            cited_by=item.get("is-referenced-by-count"), work_type=item.get("type", ""),
            volume=str(item.get("volume") or ""), issue=str(item.get("issue") or ""),
            pages=str(item.get("page") or "").replace("-", "--"), publisher=item.get("publisher") or "",
        )

    def search_crossref(self, query: str, limit: int, year_from: int | None, year_to: int | None) -> list[PaperRecord]:
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}")
        if year_to:
            filters.append(f"until-pub-date:{year_to}")
        params = {"query.bibliographic": query, "rows": limit, "filter": ",".join(filters), "mailto": self.mailto}
        url = f"{CROSSREF}?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
        items = self._json(url).get("message", {}).get("items", [])
        return [self._from_crossref(i) for i in items if i.get("type") not in CROSSREF_SKIP_TYPES]

    # -- arXiv ----------------------------------------------------------- #
    def _arxiv_get(self, params: dict[str, Any]) -> list[PaperRecord]:
        wait = 3.0 - (time.monotonic() - self._last_arxiv)  # arXiv asks for 3 s between calls
        if wait > 0 and self._fetch == self._http_get:
            time.sleep(wait)
        self._last_arxiv = time.monotonic()
        raw = self._fetch(f"{ARXIV}?" + urllib.parse.urlencode(params))
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise LiteratureError("Unexpected response from arXiv") from exc
        records = []
        for entry in root.findall("a:entry", ATOM):
            abs_url = (entry.findtext("a:id", "", ATOM) or "").strip()
            published = entry.findtext("a:published", "", ATOM) or ""
            records.append(PaperRecord(
                source="arxiv", source_id=abs_url.rsplit("/abs/", 1)[-1],
                title=" ".join((entry.findtext("a:title", "", ATOM) or "").split()),
                authors=[a.findtext("a:name", "", ATOM) for a in entry.findall("a:author", ATOM)],
                year=int(published[:4]) if published[:4].isdigit() else None,
                venue=entry.findtext("arxiv:journal_ref", "", ATOM) or "arXiv",
                doi=normalize_doi(entry.findtext("arxiv:doi", "", ATOM)),
                url=abs_url, abstract=" ".join((entry.findtext("a:summary", "", ATOM) or "").split()),
                work_type="preprint",
                arxiv_id=re.sub(r"v\d+$", "", abs_url.rsplit("/abs/", 1)[-1]),
            ))
        return records

    def search_arxiv(self, query: str, limit: int, year_from: int | None, year_to: int | None) -> list[PaperRecord]:
        terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w-]+", query)[:12])
        records = self._arxiv_get({"search_query": terms, "max_results": limit * 2 if (year_from or year_to) else limit,
                                   "sortBy": "relevance"})
        records = [r for r in records if (not year_from or (r.year or 0) >= year_from)
                   and (not year_to or (r.year or 9999) <= year_to)]
        return records[:limit]

    # -- public API ------------------------------------------------------ #
    def search(self, query: str, limit: int = 10, year_from: int | None = None,
               year_to: int | None = None, source: str = "openalex") -> list[PaperRecord]:
        if not query.strip():
            raise LiteratureError("Search query must not be empty.")
        limit = max(1, min(int(limit), 25))
        handlers = {"openalex": self.search_openalex, "crossref": self.search_crossref, "arxiv": self.search_arxiv}
        if source not in handlers:
            raise LiteratureError(f"Unknown source {source!r}; use one of {sorted(handlers)}.")
        return self._register(handlers[source](query.strip(), limit, year_from, year_to))

    def details(self, identifier: str) -> PaperRecord:
        """Look up a paper by DOI, arXiv id or OpenAlex id (W123...)."""
        identifier = identifier.strip()
        doi = normalize_doi(identifier) if DOI_IN_TEXT_RE.search(identifier) else ""
        if doi:
            try:
                item = self._json(f"{OPENALEX}/doi:{urllib.parse.quote(doi)}?" + self._openalex_params())
                return self._register([self._from_openalex(item)])[0]
            except LiteratureError:
                item = self._json(f"{CROSSREF}/{urllib.parse.quote(doi)}").get("message", {})
                return self._register([self._from_crossref(item)])[0]
        if re.fullmatch(r"W\d+", identifier, re.I) or "openalex.org/" in identifier:
            work_id = identifier.rsplit("/", 1)[-1].upper()
            return self._register([self._from_openalex(self._json(f"{OPENALEX}/{work_id}?" + self._openalex_params()))])[0]
        arxiv = ARXIV_ID_RE.search(identifier)
        if arxiv:
            records = self._arxiv_get({"id_list": arxiv.group(1)})
            if records:
                return self._register(records)[0]
        raise LiteratureError(f"Could not resolve {identifier!r} (expected a DOI, arXiv id or OpenAlex id).")


# ---------------------------------------------------------------------- #
# Post-processing
# ---------------------------------------------------------------------- #
def records_in_report(report: str, search: ScholarlySearch) -> list[PaperRecord]:
    """Registry records the report refers to (by DOI, link or exact title)."""
    text = report.lower()
    norm_text = normalize_title(report)
    found = []
    for record in search.registry.values():
        if (record.doi and record.doi in text) or (record.url and record.url.lower() in text) \
                or (len(record.title) > 20 and normalize_title(record.title) in norm_text):
            found.append(record)
    return found


def verify_report(report: str, search: ScholarlySearch) -> list[str]:
    """DOIs/links in the report that no tool returned (possible hallucinations)."""
    known_dois = {r.doi for r in search.registry.values() if r.doi}
    known_urls = {r.url.rstrip("/").lower() for r in search.registry.values() if r.url}
    known_urls |= {u.rstrip("/").lower() for u in search.seen_urls}
    problems = []
    for doi in sorted({normalize_doi(d) for d in DOI_IN_TEXT_RE.findall(report)}):
        if doi not in known_dois:
            problems.append(f"DOI {doi}")
    for url in sorted(set(URL_IN_TEXT_RE.findall(report))):
        clean = url.rstrip(".,;").rstrip("/").lower()
        if "doi.org/" in clean or clean in known_urls:
            continue
        problems.append(f"Link {url}")
    return problems


def match_bibliography(records: Iterable[PaperRecord], entries: Iterable[BibEntry]) -> dict[str, str]:
    """Map record keys to existing BibTeX keys (by DOI, then normalized title)."""
    by_doi = {normalize_doi(e.get("doi")): e.key for e in entries if e.get("doi")}
    by_title = {normalize_title(e.get("title")): e.key for e in entries if e.get("title")}
    matches = {}
    for record in records:
        key = by_doi.get(record.doi) if record.doi else None
        key = key or by_title.get(normalize_title(record.title))
        if key:
            matches[record.key] = key
    return matches


_BIB_SPECIALS = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "$": r"\$"}


def _bib_escape(value: str) -> str:
    return "".join(_BIB_SPECIALS.get(ch, ch) for ch in value).replace("{", "").replace("}", "")


def make_bib_key(record: PaperRecord, used: set[str]) -> str:
    """``surnameYEARword`` key, made unique against ``used`` (which is updated)."""
    surname = record.authors[0].split()[-1] if record.authors and record.authors[0].split() else "anon"
    word = next((w for w in normalize_title(record.title).split() if len(w) > 3), "paper")
    base = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", surname).lower()) or "anon"
    key = f"{base}{record.year or ''}{word}"
    candidate, n = key, 1
    while candidate in used:
        n += 1
        candidate = f"{key}{chr(96 + n)}"
    used.add(candidate)
    return candidate


def records_to_bibtex(records: Iterable[PaperRecord], existing_keys: Iterable[str] = ()) -> str:
    """BibTeX built strictly from retrieved metadata."""
    used = set(existing_keys)
    chunks = []
    for r in records:
        entry_type = "article" if r.work_type in {"article", "journal-article"} else \
            "inproceedings" if "proceedings" in r.work_type else "misc"
        venue_field = {"article": "journal", "inproceedings": "booktitle"}.get(entry_type, "howpublished")
        fields = {
            "title": f"{{{_bib_escape(r.title)}}}",
            "author": " and ".join(_bib_escape(a) for a in r.authors if a),
            "year": str(r.year or ""),
            venue_field: _bib_escape(r.venue),
            "volume": _bib_escape(r.volume),
            "number": _bib_escape(r.issue),
            "pages": _bib_escape(r.pages),
            "publisher": _bib_escape(r.publisher),
            "doi": r.doi,
            "eprint": r.arxiv_id,
            "archiveprefix": "arXiv" if r.arxiv_id else "",
            "url": "" if r.doi else r.url,
            "note": f"Retrieved from {r.source}",
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        chunks.append(f"@{entry_type}{{{make_bib_key(r, used)},\n{body}\n}}")
    return "\n\n".join(chunks) + ("\n" if chunks else "")
