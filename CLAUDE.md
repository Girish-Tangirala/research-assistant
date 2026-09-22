# CLAUDE.md – Research Assistant (for Claude Code)

A Windows desktop app (CustomTkinter + Anthropic Python SDK + GitPython) for LaTeX papers kept in
Overleaf via Git. Users edit `.tex` themselves or let a Claude agent do tasks. Every agent change is
approved in a diff window, and nothing reaches Overleaf until the user presses **Sync**.
`README.md` describes every feature and has the module map (*Architecture*). `docs/USER_GUIDE.md` is
the end-user guide shipped with the `.exe`.

## Commands (Windows, project folder)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py                                  # run from source
.venv\Scripts\python -m pytest -q --timeout 300               # all tests (~4-5 min, needs MiKTeX)
.venv\Scripts\python scripts\build_exe.py                     # dist\ResearchAssistant\ + two zips
```

- LaTeX tests are skipped without MiKTeX/TeX Live. If MiKTeX was installed after the shell started,
  prepend `%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64` to PATH.
- Always pass `--timeout` (pytest-timeout): multi-user Git tests have deadlocked before.
- After a change, run the tests and, for GUI work, start the app and look at it. To avoid touching a real
  workspace, set `AGENT_WORKSPACE` to a scratch folder (papers, settings and builds live there;
  default `~/.research_agent`).

## Design rules (agreed with the users – keep them, ask before changing)

- **No LangGraph/LangChain.** Direct Anthropic SDK with a manual tool loop (`core/agent_engine.py`), so
  every step can be gated and cancelled. Default model `claude-opus-5`, set in `config.py`.
- **Approval first:** the agent never writes a file without the diff window. Nothing is pushed except by
  the Sync button (`PublishWorkflow`). Commits are local first.
- **Secrets only in the OS vault** (`keyring` → Windows Credential Manager): the Claude key, Git tokens and
  OpenAlex key. Never in `.env`, `.git/config`, logs or the build. Git tokens go per command via
  `GIT_CONFIG_*` env vars. Each user signs in with their **own** Claude API key.
- **The agent touches only the paper folder**, never `data/` or `code/`, never reference-manager `.bib`
  files (`core/protection.py`), and never `todo.md`. Files the user picks come in through file pickers.
- **Checkable literature:** only papers returned by the search tools, each with its DOI/URL; never invent
  DOIs. The citation audit is deterministic (no LLM).
- **Compiling works like Overleaf:** no `-halt-on-error`; latexmk runs with `-f -g`.
  `CompileResult.success` means "a fresh PDF was produced" and `.clean` means "no errors". An approved change
  is rolled back only if it adds errors (`compiler.new_errors`) or stops the PDF from being produced.
- **One paper at a time** (paper dropdown). Papers are local folders with their own Git history.
  New papers with a link are **cloned first** (`PapersMixin._clone_new_paper`). A separately-started
  history can't be merged with Overleaf.
- The **.tex editor** (`gui/tex_editor.py`) commits every save locally. Sync and the agent refuse
  uncommitted trees, so never leave the editor's writes uncommitted.
- **Files stay under 500 lines**; split into mixins/modules (see `gui/*_mixin.py`, `gui/pdf_links.py`).

## Pitfalls that cost time before

- Git Bash heredocs collapse `\\` to `\`. Write multi-line Python patches to a file and run the file.
- Git Bash has Perl, so `latexmk` gets used there, but not when the app is started normally (no Perl →
  engine + bibtex/biber directly). Test both routes when touching `core/compiler.py`.
- This MiKTeX can keep a rewritten PDF's old timestamp, so don't rely on mtimes. The compiler deletes
  the old PDF first.
- Tk in pytest: create **one** `CTk()` per module (a fixture); creating many in a row fails intermittently
  on Windows ("Can't find a usable init.tcl").
- Files written with `write_text("\r\n")` on Windows become `\r\r\n`. Use `write_bytes` in tests.
- Every `subprocess.run` of a console program needs `creationflags=NO_WINDOW` (`core/proc.py`), or the
  windowless `.exe` flashes a console window.
- GUI screenshots with PIL `ImageGrab` capture whatever is on top. Set `-topmost` on the window first.

## Releases and updates

`version.py` holds `__version__` and `UPDATE_REPO` (public GitHub repository). A release =
`.venv\Scripts\python scripts\release.py <new version> --notes "..."` on a clean `main`: tests, build, commit,
tag `v<version>`, push, GitHub release with both zips. Installed apps check the latest release at start
(`core/updater.py`, `gui/update_dialog.py`), verify GitHub's SHA-256 digest of the zip and swap their folder with a
batch script (tested in `tests/test_updater.py`; use full `%SystemRoot%\System32` paths there, because Git's Unix
`find` can shadow Windows' `find`). Never publish without the user asking for it: a release reaches every colleague.

## Packaging

`scripts/build_exe.py` (PyInstaller, one-folder, windowed) makes `dist/ResearchAssistant/`, the user zip
(with `USER_GUIDE.md` and `READ ME FIRST.txt`) and a source zip without `.venv`, `.env`, caches or build
output. Git and MiKTeX are installed on first start by `gui/setup_dialog.py` + `core/dependencies.py`
(PortableGit into `%LOCALAPPDATA%\ResearchAssistant\tools`; MiKTeX `--unattended --private`; SHA-256
checked). Don't install them on a developer machine to test that; use the fakes in `tests/test_dependencies.py`.
`main.py` puts a found Git on PATH and writes start-up crashes to `~/.research_agent/crash.log`.
New data files the app reads at runtime must be added with `--add-data` and located via `sys._MEIPASS` (see `_open_user_guide` in `gui/app.py`).
