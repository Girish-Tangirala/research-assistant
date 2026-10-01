"""Errors whose text a person reads: English in the log, translated on the screen.

``core`` raises English **templates** rather than finished sentences::

    raise GitOperationError("No remote named {name}", name=self.settings.remote_name)

:class:`UserMessage` keeps the template and its fields apart, so one error can be two
things at once:

* ``str(exc)`` is the English sentence - what ``agent.log``, the saved reports and
  Git's own history see, and what the project promises stays English;
* :func:`core.i18n.translated` renders the same sentence in the interface language,
  which is what every dialog and status line shows.

**Why a template and not just ``t()`` at the raise site.** A module that writes into a
paper - :mod:`core.figures`, :mod:`core.latex_safety`, :mod:`core.results_latex`,
:mod:`core.latex_parser` - must never be able to reach the translator at all, and
``tests/test_i18n.py`` fails the build if one so much as imports it. Carrying the
template lets those modules raise an error a German window can show without ever
seeing a German string: the translation happens later, in the GUI.

An error built the old way still works. ``GitOperationError(f"...{value}...")`` has an
already-finished sentence as its template, which no catalogue matches, so it falls back
to English instead of breaking - the same rule as every other missing translation.
"""

from __future__ import annotations


class UserMessage:
    """Mixin for an exception that carries its English template and its fields.

    Mixed in *before* the built-in exception class, so ``super().__init__`` still
    reaches ``RuntimeError``/``ValueError`` and ``str(exc)`` keeps working::

        class GitOperationError(UserMessage, RuntimeError): ...
    """

    template: str = ""
    fields: dict[str, object]

    def __init__(self, text: str = "", **fields: object) -> None:
        self.template = text
        self.fields = fields
        super().__init__(self.english)

    @property
    def english(self) -> str:
        """The finished English sentence, whatever the interface language is."""
        if not self.fields:
            return self.template
        try:
            return self.template.format(**self.fields)
        except (KeyError, IndexError, ValueError):     # a bad template must not mask the error
            return self.template


def english(exc: BaseException) -> str:
    """The English sentence of any exception (the template's, if it has one)."""
    return exc.english if isinstance(exc, UserMessage) else str(exc)
