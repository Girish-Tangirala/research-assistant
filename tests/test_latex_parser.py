from pathlib import Path

from core.latex_parser import (
    extract_citations, find_bib_files, find_main_tex, find_section, flatten_inputs,
    insert_section, parse_bib, replace_section_body, split_sections, strip_comments,
)
from tests.conftest import MAIN_TEX, REFS_BIB


def test_strip_comments_keeps_escaped_percent():
    assert strip_comments("50\\% done % comment\nnext") == "50\\% done \nnext"


def test_split_sections_hierarchy():
    sections = split_sections(MAIN_TEX)
    assert [(s.command, s.title) for s in sections] == [
        ("section", "Introduction"), ("subsection", "Contributions"), ("section", "Method"),
    ]
    intro = sections[0]
    # Introduction spans its subsection and stops at \section{Method}
    assert "Experiments on CASP" in intro.body(MAIN_TEX)
    assert "\\section{Method}" not in intro.body(MAIN_TEX)
    # The last section stops before the bibliography
    assert "\\bibliography" not in sections[2].body(MAIN_TEX)


def test_find_and_replace_section_body():
    section = find_section(MAIN_TEX, "method")
    assert section is not None
    new = replace_section_body(MAIN_TEX, section, "New body.")
    assert "\\section{Method}\nNew body.\n" in new
    assert new.endswith("\\bibliography{refs}\n\\end{document}\n")


def test_insert_section_after_introduction():
    new = insert_section(MAIN_TEX, "Related Work", "Body \\cite{kipf2017}.", label="sec:rw")
    assert new.index("\\section{Related Work}") < new.index("\\section{Method}")
    assert new.index("\\section{Related Work}") > new.index("Experiments on CASP")
    assert "\\label{sec:rw}" in new


def test_extract_citations_ignores_comments_and_handles_multi_keys():
    keys = [c.key for c in extract_citations(MAIN_TEX)]
    assert keys == ["jumper2021", "kipf2017", "velickovic2018", "missingkey"]
    assert "commented" not in keys


def test_parse_bib_fields_and_skips_comment():
    entries = {e.key: e for e in parse_bib(REFS_BIB, "refs.bib")}
    assert set(entries) == {"jumper2021", "kipf2017", "velickovic2018", "gilmer2017", "unused2020"}
    assert entries["kipf2017"].get("year") == "2017"
    assert entries["kipf2017"].get("author") == "Kipf, Thomas and Welling, Max"
    assert entries["jumper2021"].get("title") == "Highly accurate protein structure prediction with {AlphaFold}"
    assert entries["jumper2021"].raw.startswith("@article{jumper2021")
    assert entries["kipf2017"].line == 9


def test_parse_bib_paren_form_and_concatenation():
    entries = parse_bib('@article(k1, title = "A" # {B}, year = 1999)')
    assert entries[0].key == "k1"
    assert entries[0].get("title") == "AB"


def test_project_helpers(project_dir: Path):
    main = find_main_tex(project_dir)
    assert main == project_dir / "main.tex"
    flat = flatten_inputs(main, project_dir)
    assert "message passing \\cite{gilmer2017}" in flat
    assert find_bib_files(flat, project_dir) == [project_dir / "refs.bib"]
