"""Launch the Scientific Research Assistant Agent desktop application.

Also the entry point of the packaged Windows app (``scripts/build_exe.py``). That
app has no console, so start-up problems are shown in a message box and written
to ``~/.research_agent/crash.log`` instead of being printed.
"""

import os
import sys
import traceback
from pathlib import Path


def _show_error(title: str, message: str) -> None:
    import tkinter
    from tkinter import messagebox

    root = tkinter.Tk()
    root.withdraw()
    messagebox.showerror(title, message, parent=root)
    root.destroy()


def _put_git_on_path() -> None:
    """GitPython runs ``git``: put the one we found (installed, or our PortableGit) on PATH.

    If there is none, the app still starts and its setup window offers to install it.
    """
    os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")  # a missing git is handled by the setup window
    from core.dependencies import find_git

    git = find_git()
    if git:
        os.environ["PATH"] = os.pathsep.join([str(Path(git).parent), os.environ.get("PATH", "")])


def main() -> None:
    _put_git_on_path()
    try:
        from gui.app import run

        run()
    except Exception:  # noqa: BLE001 - last resort for the console-less app
        log = Path.home() / ".research_agent" / "crash.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        _show_error("Research Assistant stopped", f"Something went wrong while starting.\n\nDetails were saved "
                                                  f"to {log} - send that file to whoever maintains the app.")
        sys.exit(1)


if __name__ == "__main__":
    main()
