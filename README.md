# Scientific Research Assistant Agent

A desktop app that runs a Claude-powered agent on one of your Overleaf/GitHub LaTeX papers at a time. The agent can:

- run a literature review you can check yourself
- audit your citations against your `.bib` files
- copy-edit sections without touching math, citations or structure

You can also edit the `.tex` yourself in an Overleaf-style editor next to the PDF.

Nothing in your paper changes until you approve the diff, and nothing reaches Overleaf until you press **Sync**.

**End users:** see [docs/USER_GUIDE.md](docs/USER_GUIDE.md) (also shipped with the `.exe`, and in **Help → User guide**).
**Changing the app:** see *Sharing the app and changing it with Claude Code* at the end, and [CLAUDE.md](CLAUDE.md).

## Layout

The window opens maximised, in three columns:

- **Left, narrow:** paper selector and details, **Sync with Overleaf**, **Refresh**, **Folder**.
- **Middle:** a switch between **🤖 Agent tasks** (task dropdown, parameters, Run, and the Live Log / Report / To-Do tabs) and **✎ Edit .tex** (the source editor).
- **Right, about 60% of the width:** the PDF preview. Drag the divider to resize it.

## Features

| Workflow | What it does | Changes your paper? |
|---|---|---|
| **Edit Text** | Copy-edits one section. Math, citations, labels and structure are protected by placeholders and checked afterwards. | After approval |
| **Literature Review** | Searches OpenAlex, Crossref and arXiv (plus Claude web search if enabled) and writes a themed review with a link for every paper. Adds a verification table and a `.bib` of new candidates. | No |
| **Add Figures** | Copies images from any folder into the paper's figures folder and inserts `figure` blocks with labels. Claude can draft each caption by looking at the image and add a "Figure~\ref{…}" sentence. | After approval |
| **Add References** | Turns DOIs, arXiv IDs or links, titles, or `.bib` files from your computer into BibTeX entries, using data from OpenAlex, Crossref or arXiv; duplicates are skipped. Optionally cites them in a section. | After approval |
| **Citation & BibTeX Audit** | Flags missing or duplicate keys (with typo suggestions), missing or malformed DOIs, missing fields and unused entries. | No |
| **Custom Agent Task** | A free-form goal; Claude plans with all tools (read, search, edit, audit, compile, commit). | After approval |

### How the literature review stays checkable

- The agent may only report papers the search tools returned in that session, each with its exact DOI link or URL.
- **Verification table:** lists every reviewed paper with its source and whether it is already in your `.bib` (matched by DOI or title).
- **Flagged links:** any DOI or link in the review that no tool returned is listed under **"⚠ Not returned by any search tool"** for you to check by hand.
- **BibTeX export:** new candidates are saved as a `.bib` file built only from the retrieved metadata. Nothing is inserted into your paper.
- **Summaries:** these are based on abstracts and labelled as such. Links in the *Report* tab open in your browser.

### Adding figures

- **Choosing images:** click **Add files…** as often as you like, from any folder or drive. Nothing is copied until you approve.
- **Formats:**
  - PNG, JPG and PDF are used as they are.
  - TIFF, BMP, GIF and WebP are converted to PNG.
  - SVG and EPS must be exported to PDF first.
  - Files over 50 MB (Overleaf's limit) are refused.
- **Where images go:** the folder set by `\graphicspath`, otherwise an existing `figures/`, `images/` or similar folder, otherwise a new `figures/`. File names are cleaned (`Loss Curve.png` becomes `loss-curve.png`) and never overwrite an existing file.
- **Where figures go:** each figure is placed at the end of the chosen section's own text, before any subsections, as `\begin{figure}[htbp] … \label{fig:<name>}`. `\usepackage{graphicx}` is added if missing.
- **Captions:**
  - Your caption is used if you add a single image.
  - Otherwise Claude drafts one from the picture itself (PDF figures are sent as documents).
  - With both options off, a placeholder caption is used.
- **Approval:** each image appears in the approval window with a preview. If you reject an image, the text change that references it is dropped too.
- **Replacing a figure:** switch the tab to **Replace a figure** (or just click the figure in the PDF preview), choose the new image and optionally a new caption.
  - **Same file type:** the image file in the paper is overwritten; the LaTeX stays as it is.
  - **Different type** (e.g. PNG → PDF): the new file is added next to the old one and that figure's `\includegraphics` points to it. The old file stays in the project; delete it in Overleaf if you no longer need it.
  - **Caption:** kept as it is, replaced with yours, or updated by Claude after looking at the new image (tick the box).
  - The approval window shows the current and the new image side by side. Read-only files are respected.

### Adding references

- **Input:** one entry per line: a DOI or `https://doi.org/…`, an arXiv ID or link, an OpenAlex ID, or an exact paper title. You can also import entries from `.bib` files anywhere on your computer.
- **Titles:** only accepted when a search result matches closely (at least 90% similar). Otherwise the report lists up to three suggestions for you to check.
- **Duplicates:** entries already in your bibliography (same DOI or title) are skipped and the report shows their existing key. Imported keys that clash are renamed.
- **Where entries go:** the first editable `.bib` file of the paper, or the one you pick. If every `.bib` is read-only, a new `references.bib` is created and added to `\bibliography` / `\addbibresource`.
- **Citing them (optional):** choose a section, and Claude writes a sentence citing the new keys; this is checked like any other edit. Without Claude, a plain `\cite{…}` is added for you to reword.

## PDF preview (Overleaf-style)

The right-hand pane shows the compiled PDF of the selected paper, so you can check every change without opening Overleaf. Toggle it with **View → Show PDF preview** (Ctrl+P).

- **Before you approve:** when a workflow proposes changes, the app compiles a copy of the paper with them applied, outside your repository. It shows that PDF with an orange badge, **"PREVIEW – not approved yet"**.
  - Pages whose text changed get an orange outline, and **Next change ▸** jumps between them. Text that merely moved to the next page isn't counted.
  - The approval window no longer blocks the rest of the app, so you can scroll and zoom the preview while you decide.
  - If the proposal doesn't compile, the LaTeX errors appear under the preview. The log also warns if the proposal adds errors the paper did not have before.
- **LaTeX errors work like Overleaf:** LaTeX carries on after errors it can recover from, so you still get a PDF. The badge turns amber and lists the errors under the preview. Only an error LaTeX cannot recover from (for example a missing `\input` file) gives no PDF.
- **After you approve:** the real compile check runs, and the pane shows the result as **"Approved – not pushed yet"**. The change is rolled back only if it adds a LaTeX error the paper did not have before, or it stops the PDF from being produced. Errors that were already in the paper are reported, not blamed on the change. Then the app asks **Push** or **Discard** (turn this off with **Options → Confirm before pushing**). Discard deletes the local commit, and nothing is sent.
- **Any time:**
  - **⟳ Recompile** (F6) builds the paper as it is on disk; syncing the paper does this too.
  - **Auto-recompile** rebuilds whenever files in the paper folder change, for example if you edit them in another editor.
  - Zoom with the buttons or Ctrl+mouse wheel; **⤢** fits the page to the width.
  - **Open PDF** opens it in your usual PDF viewer.
  - The scroll position is kept when the PDF is rebuilt.
- **Settings:** **Options → Preview changes before approval** turns off the pre-approval build, which saves a compile per change on very large papers.
### Click in PDF: Agent task | Edit .tex | Off

The switch above the PDF decides what a left click does. It moves together with the **Agent tasks / Edit .tex** switch of the middle column: change either one and the other follows (Off leaves the middle column as it is). Both start in **Agent** mode.

- **Agent task** (default): the click fills in an agent task, as described below, and brings **🤖 Agent tasks** forward.
- **Edit .tex** (like Overleaf's "go to code"): the **✎ Edit .tex** editor opens the clicked file at that line and highlights it.
- **Off:** left clicks do nothing. Right-click still works in every mode.

In **Agent task** mode:

- **Click text** (a paragraph, heading, equation or table): the **Edit Text** task opens with that section and its file already selected, and a blue line shows the file, line number and text you clicked. Write your instructions and click Run.
- **Click an image:** the **Add Figures** tab opens in **Replace a figure** mode with that figure selected. For a figure with several images, the one you clicked is selected.
- **Click the bibliography:** the **Add References** tab opens.
- **Right-click** anywhere for all options: edit the line in the .tex editor, replace this figure, edit the section with the agent, add a figure or references to it, create a to-do for it, open the file in another program, or copy `file:line`.
- The status line above the PDF says what was found, or why nothing was (for example a click in the margin).
- **How it works:** the app compiles with SyncTeX, which records which source line produced each piece of the PDF. Text inside `\input` files is traced back to the section that includes them. Clicking a *proposed-changes* preview maps to the proposed text, and figures are replaced in the current version.
- **Limits:**
  - The match is per **line**, not per word. Clicks in empty space between lines may select the nearest line, and text that LaTeX places automatically (page numbers, running heads) belongs to no section.
  - Clicks only work on PDFs built by the app. Recompile once after updating, since older builds have no SyncTeX data.
  - TikZ drawings and `\rule` boxes are not images, so they can't be replaced this way.

### Editing the .tex yourself

**✎ Edit .tex** (top of the middle column) is a source editor for the selected paper:

- **Files:** a dropdown lists every `.tex`, `.bib`, `.cls`, `.sty`, `.bst`, `.md` and `.txt` file of the paper, with the main document first. **↻** rescans the folder.
- **Editing:** line numbers, LaTeX colouring (commands, environments, headings, inline math, comments), current-line highlight, undo/redo (Ctrl+Z / Ctrl+Y), and **Find** (Ctrl+F; Enter for the next match, Shift+Enter for the previous one).
- **💾 Save & Recompile (Ctrl+S):** writes the file with its original line endings, **commits it locally** (`Edit <file> in the editor`) and rebuilds the PDF. The commit keeps **Sync** and the agent working, since both refuse uncommitted changes. It reaches Overleaf with the next Sync.
- **From the PDF:** in *Edit .tex* click mode, a click opens the source line. **Click a LaTeX error** under the PDF to jump to its line.
- **Changes on disk** (a sync, an approved agent change) reload the open file automatically. If you have unsaved edits, they are kept, the status line warns you, and **Reload from disk** appears.
- **Protection:** reference-manager `.bib` files open read-only. `data/` and `code/` are read-only for the *agent* only, so you can edit them here.
- **Safety:** saving is blocked while a task is running, to avoid racing the agent. Switching files, switching papers or closing the app asks about unsaved changes.

### Preview limits

- **Limits:** the preview is only as close to Overleaf's output as your local TeX distribution allows. Fonts, packages or Overleaf's compiler setting can differ; see *Setup*. Build files go to `~/.research_agent/_build/_preview`.

## Shared to-do list

The **To-Do** tab (next to Live Log and Report) shows a to-do list for the selected paper, shared with everyone who works on it.

- **Where it lives:** `todo.md` in the paper's repository, so anyone who can sync the paper (Overleaf or GitHub) sees the same list; no extra accounts or servers. It's readable in Overleaf, where you can tick `[x]` or reword a task directly.
- **What you can do:**
  - add tasks with an optional assignee, due date and section;
  - tick tasks off, edit them or delete them;
  - filter by **Open / Mine / Overdue / Done / All**. "Mine" means tasks assigned to the name you use for Git.
- **Saving:** each change is committed and pushed at once (`To-do: add '…'`), with no approval window.
  - **Someone pushed first:** the app pulls again, re-applies your change and retries, so simultaneous edits are not lost. For the same task, the last change wins.
  - **Push is off (Options menu):** the change stays on your computer.
- **When it updates:**
  - when you open the tab (if the list is more than a minute old);
  - when you click ⟳ Refresh;
  - every 5 minutes in the background, silently and only while no workflow is running.
- **Protection:** the AI agent can never edit `todo.md`.
- **Limits:**
  - one list per paper;
  - updates arrive on sync, not instantly;
  - every change appears as a small commit in the Overleaf/GitHub history;
  - on GitHub, the default branch must accept direct pushes.

## Sign-in (once, inside the app)

On first launch the app asks for your credentials. They are stored in **Windows Credential Manager** (Keychain on macOS) and reused until you sign out or a service rejects them. If a key or token stops working, the app asks you to sign in again.

- **Claude:** your Anthropic API key, from console.anthropic.com. It is checked against the configured model before it is saved.
- **Git:** one token per host, and the app asks for it when you add a paper on a new host. It is checked with `git ls-remote` against your repository, and the dialog also asks for your commit name and email.
  - **Overleaf:** Account Settings → Git integration → token. Username: `git`.
  - **GitHub:** a fine-grained token with Contents: read/write. Username: `x-access-token`.
  - **GitLab:** an access token. Username: `oauth2`.
- **OpenAlex (optional):** a free key from openalex.org/settings/api raises the daily search budget 10×.

Manage all three from the **Accounts** menu (it shows the current status plus Sign in / Change / Sign out). Tokens are sent to git per command through `GIT_CONFIG_*` environment variables. They are never written to `.git/config` or the remote URL, and are redacted from errors.

## Papers: local first

A paper is a folder on your computer with its own history. The assistant works there, and
**nothing leaves your computer until you press Sync**.

Use the **Paper** dropdown to choose what you're working on, and **Add / Edit / Remove** to manage the list.
- **New paper:** in **Add paper**, leave *Set up the folder structure* ticked and give it a title. The app
  creates the folders below, a `main.tex` that compiles in Overleaf as it is, and a local repository with a
  first commit. An Overleaf link is optional — add it whenever you want to share the work.
- **data/ in every paper:** each paper folder gets a local-only `data/` for datasets, also papers cloned from
  Overleaf. It is kept out of Git through `.git/info/exclude`, which is private to this computer, so nothing is
  added to the Overleaf project; new papers also list it in their `.gitignore`.
- **Existing paper:** paste the Overleaf or GitHub link. The project is **cloned first**, so the folder shares
  Overleaf's history and Sync works. It is used exactly as it is; the folder structure is only added if the
  Overleaf project has no `.tex` files yet. You can sort it into folders later (see *Organise an existing paper*).
- **Remove** only drops the paper from the list; files on disk are kept.
- The list is saved in `~/.research_agent/app_state.json`, which holds no secrets.

### The folder structure

| Folder | What goes in it | Sent to Overleaf |
|---|---|---|
| `manuscript/` | the text, one `.tex` file per section | yes |
| `figures/` | images used in the paper | yes |
| `bibliography/` | `.bib` files | yes |
| `code/` | scripts that produce the results | yes |
| `notes/` | working notes, drafts, meeting notes | yes |
| `data/` | datasets | **no** — listed in `.gitignore`, stays on this computer |

`main.tex` sits in the root (that is what Overleaf compiles) and pulls in `manuscript/` with `\input`.
`README.md` in the folder explains the same thing to your co-authors. The assistant never writes to
`data/` or `code/` — they are yours.

### Organise an existing paper

A paper you wrote before using the app can be sorted into the same folders: **File ▸ Organise paper into
folders…**. The sidebar says when a paper isn't organised yet.

- **What moves:** `.tex` files into `manuscript/`, images that the paper actually uses into `figures/`,
  `.bib` into `bibliography/`, scripts into `code/`, datasets into `data/`, notes (`.md`, `.txt`) into
  `notes/`. Sub-folders are kept, so `sections/appendix/a.tex` becomes `manuscript/appendix/a.tex`.
- **What stays:** the root document (`main.tex`), class and style files (`.cls`, `.sty`, `.bst`), `README.md`,
  `todo.md`, `.gitignore`, read-only (Zotero/Mendeley) files, and images no `\includegraphics` refers to.
  The report lists everything that was left and why.
- **Paths are rewritten:** every `\input`, `\include`, `\includegraphics`, `\bibliography` and
  `\addbibresource` that pointed at a moved file is updated, keeping the style you used (a path written
  without an extension stays without one).
- **You approve it:** one window shows the whole list of moves, then a normal diff for each `.tex` file whose
  paths changed, and the preview compiles the reorganised paper before anything is written. Reject and
  nothing moves.
- **Data files** that were already in the project stay in it (and in Overleaf) after moving into `data/`;
  delete them there if you want them only on this computer.
- It becomes **one commit**, which reaches Overleaf the next time you press Sync.

### Sync with Overleaf

The **⇄ Sync with Overleaf** button (File → Sync with Overleaf, Ctrl+Shift+S) is the only thing that talks
to Overleaf:

1. it fetches what your co-authors changed there,
2. replays your local commits on top of theirs,
3. sends the result, after showing you the list of changes and asking.

The sidebar says how much is waiting, e.g. *"3 change(s) to send"*. **⟳ Refresh** pulls without sending, and
**Open folder** opens the paper in Explorer.

- **Only on this computer:** Sync offers to add an Overleaf link; until then everything stays local.
- **Conflicts:** if your text and an Overleaf edit touch the same lines, nothing is sent and the app says so;
  your commits stay in the folder.
- **Separate histories:** linking a paper you started here to an Overleaf project that already has its own
  files is refused (merging them would be guesswork). Link a new, empty Overleaf project instead.
- **Uncommitted edits:** saves in the built-in **Edit .tex** editor are committed automatically. If you edited
  files in another program, commit or undo them first; the app only sends committed work.
- **Immediate pushing:** if you prefer the old behaviour, tick **Options → Send to Overleaf right after each
  approval**.

### Overleaf (premium)

Overleaf's Git integration is a premium feature, and it's enough if either the project owner or you has a premium plan.

- **Git URL:** paste the project link from your browser (`https://www.overleaf.com/project/<id>`). The app converts it to the clone URL `https://git.overleaf.com/<id>`.
- **Local folder:** leave it blank, or choose an empty folder. It must not be a folder that already holds a different clone.
- **Sign-in:** username `git`, with a token from Overleaf Account Settings → Git integration. One token works for all your projects.
- **Branch:** Overleaf has a single branch, `main` (older clones use `master`); leave the branch field blank.
- **Pushing:** the agent commits on `agent/<topic>-<timestamp>`, fast-forwards the Overleaf branch and pushes it, so approved changes appear in the Overleaf editor and its History.
- **Co-author edits:** if someone edited the project in Overleaf after the last sync, the agent's commit is rebased on top of their edits before pushing. If you both changed the same lines, nothing is pushed and the change stays on the local `agent/…` branch.
- **Other remotes** (e.g. GitHub) get the feature branch pushed so you can open a pull request.

### Read-only files (Zotero / Mendeley .bib)

Overleaf overwrites a reference-manager `.bib` whenever you click **Refresh**, so any edit pushed to it would be lost. The agent can read these files but can never stage, write or commit them.

- **Your own list:** in **Add/Edit paper → Read-only files**, enter file names or patterns such as `zotero.bib, refs/*.bib`. **Detect** scans the cloned folder and fills in any matches.
- **Auto-protect (on by default):** also covers `.bib` files that look reference-manager generated:
  - the file name or header mentions Zotero, Better BibTeX, Mendeley, ReadCube, JabRef or Paperpile;
  - or at least 80% of its citation keys follow Zotero's `author_title_year` pattern.
- **Where it's enforced:** at the edit tools, when a change is staged, and again right before any file is written. The protected files are listed in the sidebar, in the live log after each sync, and in the agent's instructions.
- **Why a list is needed:** Overleaf doesn't mark linked files in the Git clone, so add any linked `.bib` that detection misses to the list yourself.

## Architecture

```
main.py                 → launches the GUI
config.py               → non-secret settings (model, effort, workspace, LaTeX, push strategy)
core/
  credentials.py        → keyring-backed store, host parsing, Claude/Git/OpenAlex verification
  app_state.py          → paper list + preferences (JSON), input validation
  events.py             → EventBus, ProposedChange, ApprovalGate, CancelToken
  llm_client.py         → streaming Anthropic SDK wrapper (adaptive thinking, caching, fallbacks)
  literature.py         → OpenAlex / Crossref / arXiv clients, provenance registry, verification, BibTeX
  protection.py         → read-only policy + reference-manager .bib detection
  paper.py              → selected paper: safe path resolution, write guard
  git_manager.py        → clone/pull, feature branches, commit, push strategies, auth errors
  latex_parser.py       → sections, \input flattening, \cite extraction, BibTeX parser
  latex_safety.py       → placeholder protection + integrity validation
  citation_audit.py     → deterministic cite-vs-bib audit
  compiler.py           → latexmk -f / pdflatex+bibtex, Overleaf-like error recovery, new-error detection
  proc.py               → NO_WINDOW flag for external programs (no console flashes in the .exe)
  dependencies.py       → find / download (SHA-256 checked) / install PortableGit and MiKTeX
  updater.py            → GitHub release check, staging the new version, the folder-swap script
  prompts.py            → cache-stable system prompts
  agent_engine.py       → tools, ReAct loop, approve→apply→compile→commit→push pipeline
  workflows.py          → literature review, audit, safe edit, custom task, sync
  asset_workflows.py    → Add Figures / Add References
  figures.py            → image checks, conversion, graphics folder, figure blocks
  references.py         → identifier resolution, de-duplication, BibTeX, \bibliography wiring
  registry.py           → workflow tab order
  todos.py              → shared todo.md: format, operations, replay-on-conflict syncing
  project_layout.py     → folder structure of a new local paper + starter files
  reorganize.py         → sort an existing paper into those folders, rewriting LaTeX paths
  git_sync.py           → the Sync button: fetch, counts, replay local commits, push
  git_errors.py         → Git error types shared by the two Git modules
  preview.py            → preview builds (current / proposed / approved), changed-page detection, image hit test
  synctex.py            → SyncTeX reader: PDF position → source file and line
  source_map.py         → what a click hit: section, figure, table, equation, citations; figure lookup
  figure_replace.py     → Replace a figure (in place, or new file + \includegraphics update, caption)
  tool_schemas.py       → JSON schemas of the agent's tools
gui/
  app.py                → main window: paper selector, sign-in flow, run orchestration
  menubar.py            → File / Accounts / Options / View / Help menus
  panels.py             → task selector, live log, report viewer with links
  papers.py             → paper list, add/edit dialogs, folder setup, sync status
  task_forms.py         → one parameter form per tab (file pickers, section pickers)
  todo_panel.py         → the To-Do tab (filters, add/edit/tick/delete, auto-refresh)
  accounts.py           → sign-in handling (Accounts menu, sign-in prompts)
  preview_pane.py       → PDF preview pane, push confirmation, recompile/auto-recompile glue
  pdf_view.py           → lazy, threaded PDF page renderer on a Tk canvas (click / hover)
  pdf_links.py          → click-to-edit: background source lookup, editor / tab pre-filling, right-click menu
  editor_mixin.py       → middle column: Agent tasks ↔ Edit .tex switch, editor commits, error-click jumps
  tex_editor.py         → the .tex editor (files, save & commit, disk watching, find, read-only files)
  tex_highlight.py      → text area with line numbers and LaTeX colouring
  setup_dialog.py       → first-start window that installs Git / MiKTeX, then restarts the app
  update_dialog.py      → update window + start-up / Help-menu update check
  dialogs.py            → sign-in and paper dialogs (background verification)
  diff_window.py        → colored diff with Approve / Reject
tests/                  → pytest: parsers, safety, audit, credentials, literature, Git + engine end-to-end, editor
scripts/build_exe.py    → builds the Windows app (PyInstaller) and the user / source zips
scripts/release.py      → publishes a new version as a GitHub release (the update everyone gets)
version.py              → app version and the GitHub repository updates come from
docs/USER_GUIDE.md      → end-user guide (bundled with the .exe)
CLAUDE.md               → context for Claude Code when changing the app
```

## Setup

Requirements:
- Python ≥ 3.10 with Tk
- git ≥ 2.31
- MiKTeX (per-user install is fine, with automatic package installs on) or TeX Live. Without Perl, the app skips `latexmk` and runs pdflatex/xelatex/lualatex with bibtex or biber directly. It picks the engine from the document (`fontspec` means xelatex, `% !TEX program = …` is honoured) and uses biber for biblatex.
- Internet access

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python main.py
```

```bash
.venv\Scripts\python -m pytest -q
```

Optional, non-secret settings (model, effort, workspace, LaTeX paths, push strategy) can go in `.env`; see `.env.example`.

- **Defaults:** `claude-opus-5` with adaptive thinking, `effort=high`, prompt caching, and server-side refusal fallbacks.
- **Web search:** **Options → Use Claude web search** requires web search to be enabled for your organization in the Claude Console. If it isn't, turn it off; the scholarly indexes still work.
- **Menus:** **File** (papers, sync, reports, log), **Accounts**, **Options** (push, compile, web search), **View → Appearance**, **Help** (links for tokens and keys).

Logs are written to `~/.research_agent/agent.log`; reports and `.bib` exports go to `~/.research_agent/reports`.

## Sharing the app and changing it with Claude Code

### Build the Windows app

```bash
.venv\Scripts\python -m pip install pyinstaller
```

```bash
.venv\Scripts\python scripts\build_exe.py
```

This writes to `dist\`:

| Output | For whom |
|---|---|
| `ResearchAssistant\ResearchAssistant.exe` (folder) | try it locally |
| `ResearchAssistant-windows-<date>.zip` | colleagues who **use** the app. It holds the app folder, `USER_GUIDE.md` and `READ ME FIRST.txt` |
| `ResearchAssistant-source-<date>.zip` | colleagues who want to **change** the app (source, tests, README, CLAUDE.md; no `.venv`, no `.env`) |

The app is not code-signed, so Windows SmartScreen asks once: **More info → Run anyway**.

**Git and MiKTeX install themselves.** At start-up (`gui/setup_dialog.py`, `core/dependencies.py`), if either is
missing, a *Set up the Research Assistant* window offers **Install now**:

- **Git:** the official *PortableGit* from the latest Git for Windows release (GitHub release API) is unpacked
  into `%LOCALAPPDATA%\ResearchAssistant\tools\PortableGit`. No installer runs, no administrator rights are
  needed, and nothing is changed elsewhere; `main.py` puts it on the app's PATH.
- **MiKTeX:** the basic installer listed on miktex.org/download runs with
  `--unattended --private --auto-install=yes`, for the current user only.
- **Checks:** every download must match the SHA-256 its publisher lists (GitHub's asset digest or release notes,
  and the checksum on the MiKTeX download page), or it is deleted without being run. If the MiKTeX page
  changes, the app says so instead of guessing.
- **After installing:** the app offers to restart itself. **Help → Install Git / MiKTeX…** reopens the window.

### Everyone uses their own accounts

Nothing personal is built into the app or either zip:

- **Claude:** each user enters their own Anthropic API key (console.anthropic.com) at first start. It is stored
  in *their* Windows Credential Manager, and usage is billed to *their* Anthropic account.
- **Overleaf / GitHub:** each user signs in with their own token.
- **Settings and papers** live in each user's `~/.research_agent`.

### Updates for everyone (GitHub releases)

The source lives in the public GitHub repository set in `version.py` (`UPDATE_REPO`), and every release there
is an update:

- **Colleagues:** at start the app asks GitHub for the latest release (`core/updater.py`, `gui/update_dialog.py`).
  If it's newer than `version.__version__`, *Update available* shows the release notes. **Update now** downloads
  `ResearchAssistant-windows-<version>.zip`, checks it against the SHA-256 digest GitHub computed for the upload,
  unpacks it beside the app folder and quits. A small script then waits for the app to exit, swaps the folders
  (putting the old one back if anything fails) and starts the new version. Nothing is checked when offline;
  **Help → Check for updates…** checks by hand.
- **Publishing (maintainers):** commit your changes on `main`, then run

  ```bash
  .venv\Scripts\python scripts\release.py 1.1.0 --notes "What changed, in one or two lines"
  ```

  It refuses if the repository has uncommitted changes or the version isn't newer. It then runs the tests,
  builds, commits `version.py`, tags `v1.1.0`, pushes, and creates the GitHub release with both zips. It needs a
  fine-grained token for the repository with *Contents: read and write*. Save it once with
  `release.py --set-token`: the input is hidden, the token is checked and kept in Windows Credential Manager, separate
  from the app's own sign-ins. Alternatively set `GITHUB_TOKEN`. Only people with write access to the repository can
  publish.
- **Several people changing the app:** everyone works on clones of the same repository (branches or pull
  requests), so changes meet on `main` before a release, and there is one version for everyone.

### Changing the app with your own Claude Code

1. Clone the GitHub repository (or unzip the source zip of a release).
2. Set up Python as in *Setup* above and run the tests once.
3. Open the folder in Claude Code (CLI, desktop app or IDE extension), signed in with **your own** Claude
   account. It reads `CLAUDE.md` automatically: architecture, design rules agreed with the users, test
   commands and known pitfalls.
4. Describe the change. Ask Claude to run the tests, commit, and publish it with `scripts\release.py`;
   everyone's app then offers the update at its next start.
