"""Literature search clients (with canned HTTP) and the literature-review workflow."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
from git import Repo

from core.latex_parser import parse_bib
from core.literature import (
    LiteratureError, ScholarlySearch, match_bibliography, normalize_doi, reconstruct_abstract,
    records_to_bibtex, verify_report,
)
from core.workflows import LiteratureReviewWorkflow
from tests.conftest import REFS_BIB
from tests.test_engine_integration import FakeLLM, build, text_msg, tool_msg

OPENALEX_RESULTS = {"results": [
    {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1038/S41586-021-03819-2",
     "title": "Highly accurate protein structure prediction with AlphaFold", "publication_year": 2021,
     "authorships": [{"author": {"display_name": "John Jumper"}}],
     "primary_location": {"source": {"display_name": "Nature"}, "landing_page_url": "https://www.nature.com/x"},
     "abstract_inverted_index": {"Proteins": [0], "are": [1], "essential": [2]},
     "cited_by_count": 20000, "type": "article"},
    {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.1000/gnn.2024.7",
     "title": "Equivariant Graph Networks for Protein Design & Folding", "publication_year": 2024,
     "authorships": [{"author": {"display_name": "Ada Müller"}}, {"author": {"display_name": "Bo Li"}}],
     "primary_location": {"source": {"display_name": "NeurIPS"}},
     "abstract_inverted_index": None, "cited_by_count": 12, "type": "article"},
]}
CROSSREF_RESULT = {"message": {"items": [{
    "DOI": "10.5555/xyz", "title": ["Message Passing for Molecules"], "author": [{"given": "Justin", "family": "Gilmer"}],
    "issued": {"date-parts": [[2017, 4]]}, "container-title": ["ICML"], "URL": "https://doi.org/10.5555/xyz",
    "abstract": "<jats:p>We study <jats:italic>MPNNs</jats:italic>.</jats:p>", "type": "proceedings-article"}]}}
ARXIV_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry><id>http://arxiv.org/abs/2401.01234v2</id><published>2024-01-03T00:00:00Z</published>
    <title>Diffusion  Models for
      Proteins</title><summary> We propose a diffusion model. </summary>
    <author><name>C. Doe</name></author></entry>
</feed>"""


class FakeHTTP:
    def __init__(self):
        self.urls = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        host = urlparse(url).hostname
        if host == "api.openalex.org":
            return json.dumps(OPENALEX_RESULTS).encode()
        if host == "api.crossref.org":
            return json.dumps(CROSSREF_RESULT).encode()
        if host == "export.arxiv.org":
            return ARXIV_FEED
        raise AssertionError(url)


def test_openalex_search_and_registry():
    http = FakeHTTP()
    search = ScholarlySearch(mailto="me@uni.edu", openalex_key="KEY", fetch=http)
    records = search.search("protein folding", limit=5, year_from=2020)
    assert [r.doi for r in records] == ["10.1038/s41586-021-03819-2", "10.1000/gnn.2024.7"]
    assert records[0].abstract == "Proteins are essential"
    assert records[0].link == "https://doi.org/10.1038/s41586-021-03819-2"
    query = parse_qs(urlparse(http.urls[0]).query)
    assert query["api_key"] == ["KEY"] and query["filter"] == ["from_publication_date:2020-01-01"]
    assert len(search.registry) == 2
    assert records[1].to_tool_dict()["abstract"] == "(no abstract available)"


def test_crossref_and_arxiv():
    search = ScholarlySearch(fetch=FakeHTTP())
    [cr] = search.search("message passing", source="crossref")
    assert cr.abstract == "We study MPNNs ." and cr.year == 2017 and cr.venue == "ICML"
    [ax] = search.search("diffusion proteins", source="arxiv")
    assert ax.title == "Diffusion Models for Proteins" and ax.year == 2024 and ax.source_id == "2401.01234v2"
    with pytest.raises(LiteratureError):
        search.search("x", source="scopus")
    with pytest.raises(LiteratureError):
        search.search("   ")


def test_helpers():
    assert normalize_doi("https://dx.doi.org/10.1/ABC.") == "10.1/abc"
    assert reconstruct_abstract({"b": [1], "a": [0]}) == "a b"


def test_verify_report_flags_untraceable_identifiers():
    search = ScholarlySearch(fetch=FakeHTTP())
    search.search("protein")
    search.seen_urls.add("https://blog.example.com/post")
    report = ("See https://doi.org/10.1038/s41586-021-03819-2 and https://blog.example.com/post. "
              "Also https://doi.org/10.9999/made.up and https://fake.example.org/paper")
    assert verify_report(report, search) == ["DOI 10.9999/made.up", "Link https://fake.example.org/paper"]


def test_bibliography_matching_and_bibtex_export():
    search = ScholarlySearch(fetch=FakeHTTP())
    records = search.search("protein")
    matches = match_bibliography(records, parse_bib(REFS_BIB))
    assert matches == {"doi:10.1038/s41586-021-03819-2": "jumper2021"}
    bib = records_to_bibtex(records[1:], existing_keys={"muller2024equivariant"})
    [entry] = parse_bib(bib)
    assert entry.key == "muller2024equivariantb"
    assert entry.get("author") == "Ada Müller and Bo Li"
    assert "\\&" in entry.get("title") and entry.get("doi") == "10.1000/gnn.2024.7"


def test_literature_review_workflow_end_to_end(tmp_path, git_project):
    remote, _ = git_project
    llm = FakeLLM([
        tool_msg(("search_papers", {"query": "graph neural network protein folding"})),
        text_msg("<report>\n## Papers by Theme\n### Structure prediction\n"
                 "**Highly accurate protein structure prediction with AlphaFold** - Jumper (2021)\n"
                 "Link: https://doi.org/10.1038/s41586-021-03819-2\n\n"
                 "**Equivariant Graph Networks for Protein Design & Folding** - Müller, Li (2024)\n"
                 "Link: https://doi.org/10.1000/gnn.2024.7\n\n"
                 "**Invented** Link: https://doi.org/10.9999/fake\n</report>"),
    ])
    engine, approver = build(tmp_path, remote, llm, literature=ScholarlySearch(fetch=FakeHTTP()))
    try:
        result = LiteratureReviewWorkflow(engine, topic="", max_papers=10).run()
    finally:
        approver.stop()

    first_prompt = llm.calls[0][0]["content"]
    assert "Topic: Graph Neural Networks for Protein Folding" in first_prompt
    assert "jumper2021 | Highly accurate" in first_prompt
    assert "Protein folding is hard" in first_prompt  # introduction included as context
    assert set(llm.tools[0][i]["name"] for i in range(len(llm.tools[0]))) >= {"search_papers", "get_paper_details"}
    assert "edit_section" not in {t["name"] for t in llm.tools[0]}

    report_path, bib_path = result.artifacts
    report = report_path.read_text(encoding="utf-8")
    assert "## Verification" in report
    assert "| jumper2021 |" in report  # already cited
    assert "DOI 10.9999/fake" in report  # flagged
    assert "1 papers not yet cited" not in result.summary and "1 not yet cited" in result.summary
    assert "10.1000/gnn.2024.7" in bib_path.read_text(encoding="utf-8")
    assert not Repo(tmp_path / "clone").is_dirty()  # read-only
    assert any(e.kind.value == "artifact" for e in approver.events)
