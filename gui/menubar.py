"""Native menu bar: File, Accounts, Options, View and Help.

The Accounts menu is rebuilt each time it opens so it always shows the current
sign-in state for Claude, the selected paper's Git host and OpenAlex.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field

HELP_LINKS = (
    ("Overleaf Git integration guide", "https://docs.overleaf.com/integrations-and-add-ons/"
                                       "git-integration-and-github-synchronization/git-integration"),
    ("Create an Overleaf Git token", "https://www.overleaf.com/user/settings"),
    ("Create a GitHub fine-grained token", "https://github.com/settings/personal-access-tokens"),
    ("Create a Claude API key", "https://console.anthropic.com/settings/keys"),
    ("Get an OpenAlex API key", "https://openalex.org/settings/api"),
    ("Register the app for SharePoint (Azure portal)",
     "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"),
)


@dataclass
class AccountSection:
    """One block of the Accounts menu: a status line plus actions."""

    status: str
    actions: list[tuple[str, Callable[[], None], bool]] = field(default_factory=list)


@dataclass
class MenuActions:
    add_paper: Callable[[], None]
    edit_paper: Callable[[], None]
    remove_paper: Callable[[], None]
    sync_paper: Callable[[], None]
    publish_paper: Callable[[], None]
    backup_data: Callable[[], None]
    open_folder: Callable[[], None]
    organise_paper: Callable[[], None]
    open_reports: Callable[[], None]
    open_log: Callable[[], None]
    exit_app: Callable[[], None]
    accounts: Callable[[], list[AccountSection]]
    options_changed: Callable[[], None]
    appearance_changed: Callable[[str], None]
    toggle_preview: Callable[[], None]
    recompile: Callable[[], None]
    about: Callable[[], None]
    user_guide: Callable[[], None] | None = None
    setup_tools: Callable[[], None] | None = None
    check_updates: Callable[[], None] | None = None


class AppMenuBar:
    """Builds and owns the window's menu bar."""

    def __init__(self, root: tk.Misc, actions: MenuActions, options: list[tuple[str, tk.BooleanVar]],
                 appearance: tk.StringVar, preview_visible: tk.BooleanVar) -> None:
        self.actions = actions
        self.bar = tk.Menu(root, tearoff=False)

        file_menu = tk.Menu(self.bar, tearoff=False)
        file_menu.add_command(label="Add paper…", command=actions.add_paper, accelerator="Ctrl+N")
        file_menu.add_command(label="Edit paper…", command=actions.edit_paper)
        file_menu.add_command(label="Remove paper…", command=actions.remove_paper)
        file_menu.add_separator()
        file_menu.add_command(label="Refresh paper", command=actions.sync_paper, accelerator="F5")
        file_menu.add_command(label="Sync with Overleaf…", command=actions.publish_paper,
                              accelerator="Ctrl+Shift+S")
        file_menu.add_command(label="Back up data to SharePoint…", command=actions.backup_data)
        file_menu.add_separator()
        file_menu.add_command(label="Organise paper into folders…", command=actions.organise_paper)
        file_menu.add_separator()
        file_menu.add_command(label="Open paper folder", command=actions.open_folder)
        file_menu.add_command(label="Open reports folder", command=actions.open_reports)
        file_menu.add_command(label="Open log file", command=actions.open_log)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=actions.exit_app)
        self.bar.add_cascade(label="File", menu=file_menu, underline=0)

        self.accounts_menu = tk.Menu(self.bar, tearoff=False, postcommand=self._rebuild_accounts)
        self.bar.add_cascade(label="Accounts", menu=self.accounts_menu, underline=0)
        self._rebuild_accounts()

        options_menu = tk.Menu(self.bar, tearoff=False)
        for label, var in options:
            options_menu.add_checkbutton(label=label, variable=var, command=actions.options_changed)
        self.bar.add_cascade(label="Options", menu=options_menu, underline=0)

        view_menu = tk.Menu(self.bar, tearoff=False)
        view_menu.add_checkbutton(label="Show PDF preview", variable=preview_visible,
                                  command=actions.toggle_preview, accelerator="Ctrl+P")
        view_menu.add_command(label="Recompile PDF", command=actions.recompile, accelerator="F6")
        view_menu.add_separator()
        appearance_menu = tk.Menu(view_menu, tearoff=False)
        for mode in ("Dark", "Light", "System"):
            appearance_menu.add_radiobutton(label=mode, value=mode, variable=appearance,
                                            command=lambda m=mode: actions.appearance_changed(m))
        view_menu.add_cascade(label="Appearance", menu=appearance_menu)
        self.bar.add_cascade(label="View", menu=view_menu, underline=0)

        help_menu = tk.Menu(self.bar, tearoff=False)
        if actions.user_guide:
            help_menu.add_command(label="User guide", command=actions.user_guide)
        if actions.check_updates:
            help_menu.add_command(label="Check for updates…", command=actions.check_updates)
        if actions.setup_tools:
            help_menu.add_command(label="Install Git / MiKTeX…", command=actions.setup_tools)
        if actions.user_guide or actions.setup_tools or actions.check_updates:
            help_menu.add_separator()
        for label, url in HELP_LINKS:
            help_menu.add_command(label=label, command=lambda u=url: webbrowser.open(u))
        help_menu.add_separator()
        help_menu.add_command(label="About", command=actions.about)
        self.bar.add_cascade(label="Help", menu=help_menu, underline=0)

        root.configure(menu=self.bar)
        root.bind_all("<Control-n>", lambda _e: actions.add_paper())
        root.bind_all("<F5>", lambda _e: actions.sync_paper())
        root.bind_all("<Control-S>", lambda _e: actions.publish_paper())
        root.bind_all("<F6>", lambda _e: actions.recompile())
        root.bind_all("<Control-p>", lambda _e: actions.toggle_preview())  # keeps preview_visible in sync

    def _rebuild_accounts(self) -> None:
        menu = self.accounts_menu
        menu.delete(0, "end")
        for index, section in enumerate(self.actions.accounts()):
            if index:
                menu.add_separator()
            menu.add_command(label=section.status, state="disabled")
            for label, command, enabled in section.actions:
                menu.add_command(label=f"    {label}", command=command, state="normal" if enabled else "disabled")
