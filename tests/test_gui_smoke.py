"""Smoke test of the assembled main window.

The window is built from mixins that reach across each other (``self.todo`` lives
on one, ``self._workflow_running`` on another). Those attribute references are
resolved at runtime, so a rename that misses a call site imports cleanly, passes
every other test, and then raises ``AttributeError`` the first time a user clicks
something. Building the real window and calling those methods catches it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.credentials import CredentialStore
from gui.editor_mixin import AGENT_MODE, EDITOR_MODE, TODO_MODE
from tests.test_engine_integration import make_config

ctk = pytest.importorskip("customtkinter")


class FakeStore(CredentialStore):
    """No keyring in tests: nothing is stored, nothing is read."""

    def __init__(self) -> None:  # noqa: D107 - deliberately does not call super()
        pass

    def _get(self, key: str):
        return None

    def _set(self, key: str, value: str) -> None:
        pass

    def _delete(self, key: str) -> None:
        pass

    def git_hosts(self) -> list[str]:
        return []


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """The real window, built once (one CTk per module - several in a row are flaky)."""
    tmp_path = tmp_path_factory.mktemp("gui")
    config = make_config(tmp_path)
    paper = config.papers_dir / "test-paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_bytes(b"\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n")
    config.settings_file.write_text(json.dumps({
        "papers": [{"name": "Test paper", "remote_url": "", "local_path": str(paper)}],
        "selected": "Test paper", "author_name": "Tester", "author_email": "t@test.org",
        "todo_repo": {"url": "", "branch": ""},
    }), encoding="utf-8")

    from gui.app import ResearchAssistantApp

    try:
        window = ResearchAssistantApp(config, store=FakeStore())
    except Exception as exc:  # pragma: no cover - no display available
        pytest.skip(f"Tk window could not be created: {exc}")
    window.update()
    yield window
    window.destroy()


def test_the_window_builds_with_every_column(app):
    assert app.panel is not None and app.editor is not None and app.todo is not None
    assert list(app.mode_switch.cget("values")) == [AGENT_MODE, EDITOR_MODE, TODO_MODE]


@pytest.mark.parametrize("mode", [AGENT_MODE, EDITOR_MODE, TODO_MODE, AGENT_MODE])
def test_switching_the_middle_column_works(app, mode):
    app.show_mode(mode)
    app.update()
    assert app.mode_switch.get() == mode


def test_methods_that_reach_across_mixins_do_not_raise(app):
    """Each of these once referenced an attribute that had moved or gone."""
    assert app._editor_save_blocked() is None          # editor_mixin -> workflow state
    assert app.update_blocked() is None                # update_dialog -> to-do state
    app.recompile_preview(quiet=True)                  # preview_pane -> workflow state
    app._auto_recompile_tick()                         # the background timer's body
    app._refresh_papers()                              # papers -> self.todo.paper_changed()
    app.update()


def test_the_accounts_menu_can_be_built_without_any_sign_in(app):
    sections = app._account_sections()
    assert sections and all(s.status for s in sections)
    # No shared-list line while no to-do repository is configured.
    assert not any("Shared to-do list" in s.status for s in sections)


def test_the_accounts_menu_offers_the_to_do_host_when_it_differs(app):
    from core.app_state import TodoRepoSettings

    app.app_state.todo_repo = TodoRepoSettings(url="https://github.com/me/research-todo.git")
    try:
        statuses = [s.status for s in app._account_sections()]
        assert any("Shared to-do list (github.com)" in s for s in statuses)
    finally:
        app.app_state.todo_repo = TodoRepoSettings()


def test_the_to_do_panel_says_what_is_missing_instead_of_raising(app):
    from core.todos import TodoError

    with pytest.raises(TodoError, match="not set up yet"):
        app._todo_store()


# ---------------------------------------------------------------------- #
# Dialog sizing (a colleague's screen pushed Save and Cancel out of reach)
# ---------------------------------------------------------------------- #
def open_paper_dialog(app):
    from gui.dialogs import PaperDialog

    dialog = PaperDialog(app, None, set(), app.config_.papers_dir, lambda *a: None)
    app.update()
    dialog.update_idletasks()
    return dialog


def test_the_dialog_buttons_are_inside_the_window(app):
    dialog = open_paper_dialog(app)
    try:
        bottom = dialog.primary.winfo_rooty() - dialog.winfo_rooty() + dialog.primary.winfo_reqheight()
        assert bottom <= dialog.winfo_height(), "the Save button falls outside the dialog"
        assert dialog.winfo_width() > 400, "the dialog is too narrow for its fields"
    finally:
        dialog.destroy()


def test_a_tall_dialog_is_clamped_to_the_screen_and_keeps_its_buttons(app, monkeypatch):
    """The tallest dialog on a short screen: the buttons must survive, not the height."""
    from gui.dialogs import _Dialog

    monkeypatch.setattr(_Dialog, "MAX_HEIGHT_FRACTION", 0.45)   # a short laptop screen
    dialog = open_paper_dialog(app)
    try:
        limit = int(dialog.winfo_screenheight() * 0.45) + 2      # rounding through the scaling factor
        assert dialog.winfo_height() <= limit, "the dialog is taller than the screen allows"
        bottom = dialog.primary.winfo_rooty() - dialog.winfo_rooty() + dialog.primary.winfo_reqheight()
        assert bottom <= dialog.winfo_height(), "the Save button was pushed off a short screen"
    finally:
        dialog.destroy()


def test_the_window_can_leave_full_screen(app):
    app.set_fullscreen(False)
    app.update()
    assert app.fullscreen_var.get() is False
    app.toggle_fullscreen()
    app.update()
    assert app.fullscreen_var.get() is True
    app.set_fullscreen(False)      # leave the test window usable
