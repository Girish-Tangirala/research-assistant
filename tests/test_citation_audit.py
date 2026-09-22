from pathlib import Path

from core.citation_audit import run_audit


def _by(report, category):
    return {f.key for f in report.findings if f.category == category}


def test_audit_findings(project_dir: Path):
    report = run_audit(project_dir)
    assert report.main_file == "main.tex"
    assert report.bib_files == ["refs.bib"]
    assert report.cited_keys == 5  # includes gilmer2017 from \input file
    assert _by(report, "missing-key") == {"missingkey"}
    assert _by(report, "missing-doi") == {"kipf2017", "gilmer2017"}
    assert _by(report, "doi-format") == {"velickovic2018"}
    assert _by(report, "missing-fields") == {"gilmer2017"}  # no journal
    assert _by(report, "unused-entry") == {"unused2020"}
    markdown = report.to_markdown()
    assert "| error | missing-key | `missingkey`" in markdown


def test_audit_suggests_typo_fix(project_dir: Path):
    main = project_dir / "main.tex"
    main.write_text(main.read_text().replace("\\cite{missingkey}", "\\cite{jumper2012}"))
    report = run_audit(project_dir)
    finding = next(f for f in report.findings if f.key == "jumper2012")
    assert "jumper2021" in finding.message


def test_audit_duplicate_keys(project_dir: Path):
    bib = project_dir / "refs.bib"
    bib.write_text(bib.read_text() + "\n@misc{kipf2017, title={dup}}\n")
    report = run_audit(project_dir)
    assert _by(report, "duplicate-key") == {"kipf2017"}
