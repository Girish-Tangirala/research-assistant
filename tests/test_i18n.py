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
def concatenated(node: ast.AST) -> str | None:
    """The text of a literal, including implicit and ``+`` concatenation."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = concatenated(node.left), concatenated(node.right)
        if left is not None and right is not None:
            return left + right
    return None


# Positions that a dialog shows to a person without the call site wrapping them in
# ``t()``: :class:`gui.dialogs._Dialog` translates its own title, heading, body text
# and primary button, and a message box's title and body are read straight out of the
# call. They were English for two releases because nothing looked them up, so they are
# audited here by position rather than by hoping someone remembers the t().
MESSAGE_BOXES = {"showinfo", "showwarning", "showerror", "askyesno", "askyesnocancel", "askokcancel"}


def dialog_chrome(tree: ast.Module) -> list[str]:
    """Strings a dialog or message box shows although the call site has no ``t()``."""
    literals: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
        # super().__init__(master, title, heading, text) - _Dialog translates these
        if name == "__init__" and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Call) and ast.unparse(node.func.value) == "super()":
            literals += [text for arg in node.args[1:] for text in texts_in(arg)]
        if name == "finish_layout" and node.args:          # the primary button
            literals += texts_in(node.args[0])
        if name in MESSAGE_BOXES:                          # title and body
            literals += [text for arg in node.args[:2] for text in texts_in(arg)]
        # Labels handed to a menu as data (the Options check buttons live in a list in
        # gui/app.py and are translated in gui/menubar.py), so no t() sits at either end.
        for keyword in node.keywords:
            # text= on a configure() is a button or label being relabelled after the fact
            # (the setup dialog's primary button becomes "Try again" / "Restart now").
            if keyword.arg in {"options", "label"} or (keyword.arg == "text" and name == "configure"):
                literals += texts_in(keyword.value)
    return [text for text in literals if is_prose(text) and not text.startswith(("http", "{"))]


def is_prose(text: str) -> bool:
    """Whether a literal is text for a person rather than punctuation or a separator."""
    return any(char.isalpha() for char in text)


def texts_in(node: ast.AST) -> list[str]:
    """The literal text(s) an argument can show.

    Structural on purpose: it follows both arms of ``a if c else b`` and the items of a
    list, but never walks into an f-string. Walking caught the pieces of
    ``f"{done:.0f} of {total:.0f} MB"`` - " of ", " MB", ".0f" - and demanded German for
    them. A ``t(...)`` call is skipped because it is collected where it is written.
    """
    if isinstance(node, ast.IfExp):
        return texts_in(node.body) + texts_in(node.orelse)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [text for element in node.elts for text in texts_in(element)]
    if isinstance(node, ast.Call):
        return []
    if (text := concatenated(node)) is not None and is_prose(text):
        return [text]
    return []


def constant_tables(tree: ast.Module) -> dict[str, list[str]]:
    """Module-level ``NAME = {...}`` / ``NAME = [...]`` tables of strings."""
    tables: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        values = node.value.values if isinstance(node.value, ast.Dict) else \
            (node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [])
        strings = [text for item in values if (text := concatenated(item))]
        if strings:
            tables[target.id] = strings
    return tables


def translated_strings() -> dict[str, list[str]]:
    """Every literal the app translates, by module - via ``t(...)`` or by position.

    ``t(LABELS[tool])`` and ``t(HELP.get(host, "…"))`` hide their text in a table, so
    the table a ``t()`` call reads is pulled in as well - wherever it is defined, since
    ``GIT_TOKEN_HELP`` lives in :mod:`core.credentials` and is translated in
    :mod:`gui.dialogs`. The MiKTeX line of the setup dialog and the Git token hints
    were the only English left in an otherwise German window.
    """
    trees = {f"{folder}/{path.name}": ast.parse(path.read_text(encoding="utf-8"))
             for folder in ("gui", "core") for path in sorted((ROOT / folder).glob("*.py"))}
    shared: dict[str, list[str]] = {}
    for tree in trees.values():
        shared.update(constant_tables(tree))

    found: dict[str, list[str]] = {}
    for folder in ("gui", "core"):
        for path in sorted((ROOT / folder).glob("*.py")):
            tree = trees[f"{folder}/{path.name}"]
            literals = dialog_chrome(tree) if folder == "gui" else []
            tables = shared
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t":
                    if node.args and (text := concatenated(node.args[0])) is not None:
                        literals.append(text)
                    elif node.args:                   # t(TABLE[key]) / t(TABLE.get(key, "…"))
                        for inner in ast.walk(node.args[0]):
                            if isinstance(inner, ast.Name):
                                literals += tables.get(inner.id, [])
                            elif isinstance(inner, ast.Constant) and isinstance(inner.value, str) \
                                    and is_prose(inner.value):
                                literals.append(inner.value)
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
                  "• {tool}: {state}", "{tool}: {problem}", "optional", "Updates"}


def test_the_catalogue_has_no_entry_that_is_only_the_english_back_again():
    from core.lang import german

    same = [k for k, v in german.CATALOGUE.items() if k == v and k not in SAME_IN_GERMAN]
    assert not same, f"these 'translations' are just the English: {same}"



# ---------------------------------------------------------------------- #
# 3b. Every error message core raises has German
#
# core raises English *templates* that carry their fields (core.user_errors), so
# str(exc) stays English for the log, the model's tool results and the reports,
# while the GUI shows core.i18n.translated(exc). The templates are not t() calls,
# so they are collected here by walking the raise statements and resolving the
# exception class: anything that is a UserMessage needs German.
# ---------------------------------------------------------------------- #
# Deliberately English, with the reason, because each is read by something other
# than a person. Everything else must be translated.
ENGLISH_ON_PURPOSE = {
    # core/latex_parser.py names a character index; it is a diagnostic for the log
    # and for the model's tool results, not a sentence a user acts on.
    "No opening brace at index {open_index}",
    "Unbalanced braces starting at index {open_index}",
    "Unterminated entry at index {open_index}",
    # Read by the model, which repairs its own plan - like the prompts.
    "LaTeX integrity check failed:\n- {problems}",
}
# The Microsoft Graph route is built but hidden from the interface (see the README),
# so its messages cannot be reached and are not translated until it comes back.
NOT_REACHABLE = {"core/sharepoint.py"}


def raised_templates() -> dict[str, list[str]]:
    """Every English template raised as a :class:`core.user_errors.UserMessage`."""
    import importlib

    from core.user_errors import UserMessage

    found: dict[str, list[str]] = {}
    for path in sorted((ROOT / "core").glob("*.py")):
        key = f"core/{path.name}"
        if key in NOT_REACHABLE or path.name == "__init__.py":
            continue
        module = importlib.import_module(f"core.{path.stem}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        templates = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            cls = getattr(module, name, None)
            if not (isinstance(cls, type) and issubclass(cls, UserMessage)):
                continue
            if node.exc.args and (text := concatenated(node.exc.args[0])) is not None:
                templates.append(text)
        if templates:
            found[key] = sorted(set(templates))
    return found


def test_every_error_message_core_raises_has_german():
    by_module = raised_templates()
    assert by_module, "no error templates found - has core.user_errors been removed?"
    gaps = {name: [text for text in texts
                   if text not in ENGLISH_ON_PURPOSE and missing("de", [text])]
            for name, texts in by_module.items()}
    gaps = {name: texts for name, texts in gaps.items() if texts}
    assert not gaps, "no German for the error(s):\n" + "\n".join(
        f"  {name}:\n" + "\n".join(f"    {text!r}," for text in texts) for name, texts in gaps.items())


def test_an_error_is_english_in_the_log_and_german_on_the_screen():
    """The same exception must be able to be both - that is the whole point."""
    from core.git_errors import GitOperationError
    from core.i18n import translated
    from core.user_errors import english

    exc = GitOperationError("No remote named '{remote}'", remote="origin")
    set_language("de")
    assert str(exc) == "No remote named 'origin'", "the log line must stay English"
    assert english(exc) == "No remote named 'origin'"
    assert translated(exc) == "Kein Remote mit dem Namen 'origin'", translated(exc)
    assert "origin" in translated(exc), "the field was lost in translation"
    set_language("en")
    assert translated(exc) == "No remote named 'origin'"


def test_an_error_built_the_old_way_still_works():
    """A finished sentence as the template falls back to English instead of breaking."""
    from core.git_errors import GitOperationError
    from core.i18n import translated

    exc = GitOperationError("Something nobody templated")
    set_language("de")
    assert str(exc) == "Something nobody templated"
    assert translated(exc) == "Something nobody templated"


def test_a_broken_template_does_not_mask_the_error():
    from core.git_errors import GitOperationError

    exc = GitOperationError("Missing {field} here", other="x")
    assert "Missing {field} here" in str(exc)

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


# ---------------------------------------------------------------------- #
# 5. The German guide ships and is the one a German app opens
# ---------------------------------------------------------------------- #
def test_the_german_installation_guide_exists_and_is_german():
    guide = ROOT / "docs" / "INSTALLATION_DE.md"
    assert guide.exists(), "docs/INSTALLATION_DE.md is missing"
    text = guide.read_text(encoding="utf-8")
    assert re.search(r"[äöüÄÖÜ]", text), "the German guide has no German in it"
    # It must start where a colleague starts: the release page.
    assert "github.com/Girish-Tangirala/research-assistant/releases" in text
    assert "ResearchAssistant-windows-" in text
    # The steps have to name the buttons the app really shows in German.
    from core.lang import german

    for label in ("Jetzt installieren", "Forschungsassistent einrichten", "Zugriffstoken",
                  "Mit Overleaf synchronisieren", "Daten sichern"):
        assert label in text, f"the guide never mentions {label!r}"
        assert label in german.CATALOGUE.values() or any(label in v for v in german.CATALOGUE.values()), \
            f"the guide tells the user to click {label!r}, which the app does not say"


def test_both_guides_are_packaged():
    """A guide that is not in --add-data is missing from the .exe (see Help ▸ User guide)."""
    build = (ROOT / "scripts" / "build_exe.py").read_text(encoding="utf-8")
    assert "INSTALLATION_DE.md" in build, "the German guide is not in the build script"
    assert "GUIDES" in build and "--add-data" in build


def test_a_german_app_opens_the_german_guide(tmp_path, monkeypatch):
    """Help ▸ Benutzerhandbuch must not open the English guide for a German interface."""
    import gui.app as app_module

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "USER_GUIDE.md").write_bytes(b"english")
    (docs / "INSTALLATION_DE.md").write_bytes(b"deutsch")
    opened: list[str] = []
    monkeypatch.setattr(app_module, "open_path", lambda path: opened.append(path.name))

    class Stub:
        config_ = None
        panel = type("P", (), {"append": staticmethod(lambda *a: None)})()
        _open_user_guide = app_module.ResearchAssistantApp._open_user_guide

    monkeypatch.setattr(app_module, "__file__", str(tmp_path / "gui" / "app.py"))
    for language, expected in (("en", "USER_GUIDE.md"), ("de", "INSTALLATION_DE.md")):
        set_language(language)
        opened.clear()
        Stub()._open_user_guide()
        assert opened == [expected], f"{language}: opened {opened}"


def test_no_translation_loses_or_invents_a_placeholder():
    """A German entry that drops ``{host}`` would show a sentence with the fact missing.

    ``t()`` survives a *broken* placeholder by falling back to the English, but an entry
    that simply leaves one out formats cleanly and silently says less than the original -
    which no test would otherwise notice.
    """
    from core.lang import german

    wrong = []
    for english_text, translation in german.CATALOGUE.items():
        fields = set(re.findall(r"{(\w+)}", english_text))
        translated_fields = set(re.findall(r"{(\w+)}", translation))
        if fields != translated_fields:
            wrong.append(f"{english_text[:60]!r}: {sorted(fields)} -> {sorted(translated_fields)}")
    assert not wrong, "placeholders changed in translation:\n  " + "\n  ".join(wrong)
