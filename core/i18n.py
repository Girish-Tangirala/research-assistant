"""Translating the interface - and only the interface.

The English text is the key: ``t("Add paper…")`` looks up a German phrasing and
falls back to the English if there is none, so a missing translation shows real
words rather than ``menu.add_paper``. :func:`missing` lists what has no German
yet, which is what ``tests/test_i18n.py`` checks.

**What must never be translated.** Anything that is, or becomes, part of a paper:

* the scaffolding in :mod:`core.project_layout` and :mod:`core.reorganize`,
* the LaTeX built by :mod:`core.figures` and :mod:`core.results_latex`,
* ``PLACEHOLDER_CAPTION`` in the figure and results workflows,
* the prompts in :mod:`core.prompts` - they are what keeps Claude writing English,
* commit messages, which reach Overleaf's history,
* the agent's own step-by-step log, and the reports saved in ``reports/``.

``tests/test_i18n.py`` fails if any of those modules so much as imports this one,
and separately builds a paper in German and compares it byte for byte with the
English one. The user writes in English; only the buttons change language.
"""

from __future__ import annotations

from collections.abc import Callable

LANGUAGES = {"en": "English", "de": "Deutsch"}
DEFAULT = "en"

_language = DEFAULT
_catalogue: dict[str, str] = {}
_listeners: list[Callable[[str], None]] = []


def load(code: str) -> dict[str, str]:
    """The catalogue for ``code`` (empty for English, which is the source text)."""
    if code == "de":
        from core.lang import german

        return german.CATALOGUE
    return {}


def set_language(code: str) -> str:
    """Switch the interface language. Returns the code actually used."""
    global _language, _catalogue
    _language = code if code in LANGUAGES else DEFAULT
    _catalogue = load(_language)
    for listener in _listeners:
        listener(_language)
    return _language


def current_language() -> str:
    return _language


def t(text: str, **fields: object) -> str:
    """The interface text in the current language, with ``{placeholders}`` filled in."""
    translated = _catalogue.get(text, text)
    if fields:
        try:
            return translated.format(**fields)
        except (KeyError, IndexError, ValueError):
            return text.format(**fields)      # a broken translation must not break the app
    return translated


class Choices:
    """Translated labels for a fixed set of values that stay English inside the app.

    A lot of text on screen is also an identifier: the task names are the keys of
    :data:`core.registry.WORKFLOWS`, the middle switch is compared against
    ``AGENT_MODE``, the to-do filters drive the filtering. Those values must not
    change with the language, so the widget shows ``labels`` and every read goes
    back through :meth:`value`.
    """

    def __init__(self, values: list[str]) -> None:
        self.values = list(values)
        self.labels = [t(value) for value in self.values]
        self._to_value = dict(zip(self.labels, self.values))
        self._to_label = dict(zip(self.values, self.labels))

    def label(self, value: str) -> str:
        """What to show for an internal value."""
        return self._to_label.get(value, t(value))

    def value(self, label: str) -> str:
        """The internal value behind what the widget shows."""
        return self._to_value.get(label, label)


def missing(code: str, texts: list[str]) -> list[str]:
    """Which of ``texts`` have no translation in ``code`` (for the test)."""
    catalogue = load(code)
    return [text for text in texts if text not in catalogue]
