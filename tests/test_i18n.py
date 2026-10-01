"""The interface translates; a paper never does.

Two guarantees are checked here, because "be careful" is not a guarantee:

1. No module that writes into a paper may even reach the translation function.
2. Scaffolding a paper, inserting a figure and drawing a results chart produce
   byte-identical output in German and in English.

Plus the bookkeeping one: every string the code asks to translate has German.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core import i18n
from core.i18n import Choices, LANGUAGES, current_language, missing, set_language, t

ROOT = Path(__file__).resolve().parents[1]

# Everything these modules produce is, or becomes, part of a paper.
PAPER_MODULES = [
    "core/project_layout.py",     # main.tex, the section files, README.md, .gitignore
    "core/reorganize.py",         # code/README.md
    "core/figures.py",            # figure environments, captions, labels
    "core/results_latex.py",      # pgfplots and booktabs code
    "core/latex_parser.py",
    "core/latex_safety.py",
    "core/prompts.py",            # what Claude is told to write, which keeps its output English
]


@pytest.fixture(autouse=True)
def english_again():
    yield
    set_language("en")


# ---------------------------------------------------------------------- #
# 1. The modules that write into a paper cannot translate anything
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("name", PAPER_MODULES)
def test_a_paper_module_never_imports_the_translator(name):
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(("core.i18n", "core.lang")):
            pytest.fail(f"{name} imports the translator; its output goes into a paper")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("core.i18n", "core.lang")), \
                    f"{name} imports the translator; its output goes into a paper"


def test_what_claude_writes_is_pinned_to_english():
    """A German interface must not produce a German summary, report or caption."""
    from core.prompts import LIT_REVIEW_SYSTEM, SUMMARY_SYSTEM

    set_language("de")
    assert "Write in English" in SUMMARY_SYSTEM
    for prompt in (SUMMARY_SYSTEM, LIT_REVIEW_SYSTEM):
        assert not re.search(r"[äöüßÄÖÜ]", prompt), "a prompt picked up German"


def test_the_prompts_stay_english():
    """The prompts are what keep Claude writing English, whatever the interface says."""
    text = (ROOT / "core/prompts.py").read_text(encoding="utf-8")
    assert "i18n" not in text and "t(" not in text.replace("format(", "")


# ---------------------------------------------------------------------- #
# 2. A paper built in German is the same paper
# ---------------------------------------------------------------------- #
def build_paper_artifacts(tmp_path: Path) -> dict[str, str]:
    """Everything the app itself writes into a paper, as text."""
    from core.asset_workflows import PLACEHOLDER_CAPTION
    from core.figures import figure_block
    from core.project_layout import gitignore_text, scaffold
    from core.results_data import ResultTable
    from core.results_latex import ChartSpec, build, float_block

    root = tmp_path / f"paper-{current_language()}"
    root.mkdir()
    scaffold(root, "A Paper Title", author="Someone")
    files = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*")) if path.is_file()
    }
    files["<gitignore>"] = gitignore_text()
    files["<figure>"] = figure_block("figures/x.png", PLACEHOLDER_CAPTION, "fig:x")
    table = ResultTable("models", ["model", "accuracy"], [["ResNet50", 0.94]], "models.csv")
    spec = ChartSpec(kind="bar", x="model", series=["accuracy"], caption=PLACEHOLDER_CAPTION)
    files["<chart>"] = float_block(build(table, spec), PLACEHOLDER_CAPTION, "fig:r", "bar")
    return files


def test_a_paper_scaffolded_in_german_is_identical_to_the_english_one(tmp_path):
    set_language("en")
    english = build_paper_artifacts(tmp_path)
    set_language("de")
    assert current_language() == "de"
    assert t("Add paper…") != "Add paper…", "the German catalogue is not actually loaded"
    german = build_paper_artifacts(tmp_path)

    assert set(english) == set(german)
    for name in english:
        assert english[name] == german[name], f"{name} differs when the interface is German"


def test_no_german_reaches_a_paper(tmp_path):
    """A blunt second check: the paper files contain no German words or umlauts."""
    set_language("de")
    files = build_paper_artifacts(tmp_path)
    german_markers = re.compile(r"[äöüßÄÖÜ]|\b(?:und|der|die|das|nicht|Abbildung|Datei|Ordner)\b")
    for name, text in files.items():
        found = german_markers.search(text)
        assert not found, f"{name} contains German: {found.group(0)!r}"


def test_the_placeholder_caption_is_english_in_both_languages():
    from core.asset_workflows import PLACEHOLDER_CAPTION
    from core.results_workflow import PLACEHOLDER_CAPTION as RESULTS_PLACEHOLDER

    for language in LANGUAGES:
        set_language(language)
        assert PLACEHOLDER_CAPTION == "Caption to be written."
        assert RESULTS_PLACEHOLDER == "Caption to be written."


def test_commit_messages_stay_english():
    from core.todos import COMMIT_PREFIX

    set_language("de")
    assert COMMIT_PREFIX == "To-do: "
    assert "To-do: move the list into the shared to-do repository" in \
        (ROOT / "core/global_todos.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------- #
# 3. Everything the interface asks to translate has German
# ---------------------------------------------------------------------- #
def translated_strings() -> dict[str, list[str]]:
    """Every literal passed to ``t(...)`` in the app, by module."""
    found: dict[str, list[str]] = {}
    for folder in ("gui", "core"):
        for path in sorted((ROOT / folder).glob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:                                  # pragma: no cover
                continue
            literals = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t":
                    if node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, str):
                        literals.append(node.args[0].value)
                # Choices(["A", "B"]) translates each of its values
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id == "Choices" and node.args:
                    if isinstance(node.args[0], (ast.List, ast.Tuple)):
                        literals += [e.value for e in node.args[0].elts
                                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if literals:
                found[f"{folder}/{path.name}"] = sorted(set(literals))
    return found


def test_every_translated_string_has_german():
    by_module = translated_strings()
    assert by_module, "nothing is wrapped in t() yet"
    gaps = {name: missing("de", texts) for name, texts in by_module.items()}
    gaps = {name: texts for name, texts in gaps.items() if texts}
    assert not gaps, "no German for:\n" + "\n".join(
        f"  {name}:\n" + "\n".join(f"    {text!r}," for text in texts) for name, texts in gaps.items())


# Words German uses unchanged, and strings that are only placeholders. Listing them
# keeps the check below meaningful: anything else identical to the English is an
# entry someone forgot to translate.
SAME_IN_GERMAN = {"System", "Paper", "Branch (optional)", "{updating}\n{step}",
                  "• {tool}: {state}", "{tool}: {problem}"}


def test_the_catalogue_has_no_entry_that_is_only_the_english_back_again():
    from core.lang import german

    same = [k for k, v in german.CATALOGUE.items() if k == v and k not in SAME_IN_GERMAN]
    assert not same, f"these 'translations' are just the English: {same}"


# ---------------------------------------------------------------------- #
# 4. The machinery
# ---------------------------------------------------------------------- #
def test_an_unknown_string_falls_back_to_english():
    set_language("de")
    assert t("Something nobody translated yet") == "Something nobody translated yet"


def test_placeholders_survive_translation():
    set_language("de")
    assert "github.com" in t("Signed out of {host}.", host="github.com")
    # a translation with a broken placeholder must not take the app down
    i18n._catalogue["Signed out of {host}."] = "Von {hosst} abgemeldet."
    assert "github.com" in t("Signed out of {host}.", host="github.com")


def test_choices_keep_english_values_behind_german_labels():
    set_language("de")
    choices = Choices(["Edit Text", "Literature Review"])
    assert choices.labels == ["Text überarbeiten", "Literaturrecherche"]
    assert choices.value("Literaturrecherche") == "Literature Review"
    assert choices.label("Edit Text") == "Text überarbeiten"
    assert choices.value("something else") == "something else"


def test_an_unknown_language_falls_back_rather_than_failing():
    assert set_language("fr") == "en"
    assert t("Add paper…") == "Add paper…"
