# Research Assistant – User Guide

The Research Assistant is a desktop app for writing LaTeX papers that live on Overleaf. With it you can:

- edit the `.tex` files yourself, with a live PDF next to them, like in Overleaf;
- let Claude (an AI) do tasks on the paper: copy-edit a section, add figures or references, check citations, write a literature review;
- keep working offline, and decide yourself when your changes go to Overleaf.

**Nothing in your paper changes without your OK.** Every change the AI proposes is shown to you first. Nothing goes to Overleaf until you press **Sync**.

---

## 1. What you need

| What | Why | Where to get it |
|---|---|---|
| Windows 10 or 11 | the app is a Windows program | – |
| **Git** and **MiKTeX** | keep the history of your paper / build the PDF | **nothing to do**: the app installs them itself the first time it starts (see section 2) |
| **Your own Claude API key** | for the AI tasks (not needed for editing, the PDF or Sync) | https://console.anthropic.com → *API keys* (see section 3) |
| **Overleaf Git access** | for linking a paper to Overleaf | an Overleaf premium plan, yours or the project owner's (see section 3) |

## 2. Installing and starting

1. Unzip `ResearchAssistant-windows-….zip` somewhere you like, for example `Documents\ResearchAssistant`.
   **Keep the whole folder together.** The `.exe` needs the `_internal` folder next to it.
2. Double-click **`ResearchAssistant.exe`**.
3. The first time, Windows may say *"Windows protected your PC"*. This appears because the app isn't signed by a publisher. Click **More info → Run anyway**.
4. **First start only:** if Git or MiKTeX is missing, a *Set up the Research Assistant* window offers to install
   them. Click **Install now**, wait a few minutes (about 200 MB is downloaded), then click **Restart now**.
   - Both come from their official websites, and every download is checked against its published checksum.
   - Both are installed only for your Windows account, so no administrator rights are needed. Git goes into the
     app's own folder (`%LOCALAPPDATA%\ResearchAssistant\tools`); MiKTeX is installed normally for you.
   - A MiKTeX progress window may appear. Later, MiKTeX fetches extra LaTeX packages by itself the first time a
     paper needs them, which makes the very first PDF a bit slower.
   - Skipped it? **Help → Install Git / MiKTeX…** opens the window again.
5. Tip: right-click the `.exe` → *Show more options* → **Send to → Desktop (create shortcut)**.

**Updates arrive by themselves.** When a new version has been published, the app shows *Update available* at start, with what's new. Click **Update now**: it downloads the new version, checks it, closes, replaces itself and starts again in a few seconds. **Later** skips it until the next start, and **Help → Check for updates…** checks at any time. Your papers, settings and sign-ins are kept, because they are stored elsewhere (see section 13). Updating needs the app folder to be somewhere you can write to, such as Documents (not *Program Files*).

## 3. Signing in (once)

The app asks for these the first time it needs them. You can change them any time in the **Accounts** menu.

### Claude API key: your own account

Every person uses **their own** Claude account. Your key is stored only in *Windows Credential Manager* on your computer. It is never put in the app folder and never sent to anyone except Anthropic.

1. Go to https://console.anthropic.com and sign in, or create an account.
2. Add a payment method or credits under *Billing*. AI tasks are charged to that account per use. Small tasks (one section) cost little; long ones (a literature review, custom tasks) cost more. The Console's *Usage* page shows what you have spent.
3. Open *API keys* → **Create key**, copy it, and paste it into the app when asked.

> **Note:** a Claude *Pro/Max* chat subscription (claude.ai) and an *API key* are billed separately. The app needs an API key. If your institute has an Anthropic organisation, ask for a key from its workspace.

### Overleaf token

1. In Overleaf: **Account Settings → Git integration → Generate token**. Copy it; Overleaf shows it only once.
2. When the app asks you to sign in to `git.overleaf.com`, use username **`git`** and the token as the password.
   One token works for all your Overleaf projects.
3. The same window asks for your name and email. They appear in the history next to your changes.

## 4. The screen

```
┌──────────┬──────────────────────────────┬─────────────────────────────────┐
│ Paper    │ [🤖 Agent tasks] [✎ Edit .tex]│  PDF preview                    │
│ dropdown │                              │  ⟳ Recompile  Auto-recompile    │
│ Add/Edit │  either the AI task forms    │  Click in PDF: Agent|Edit.tex|Off│
│ ⇄ Sync   │  or the .tex editor          │  [ the PDF of your paper ]      │
│ Refresh  │                              │  [ LaTeX errors, if any ]       │
└──────────┴──────────────────────────────┴─────────────────────────────────┘
```

- **Left:** which paper you're working on, and the **Sync** button.
- **Middle:** switch between **Agent tasks** (the AI) and **Edit .tex** (you edit the source yourself). This switch and the *Click in PDF* switch above the PDF move together. The app starts in **Agent** mode.
- **Right:** the PDF. Drag the divider to make it wider or narrower. **View → Show PDF preview** (Ctrl+P) hides or shows it.

## 5. Adding a paper

1. Click **Add** (left panel).
2. **Paper name:** anything, for example *Tool classification – IEEE Access*.
3. **Overleaf link:** open the project in Overleaf and copy the address from your browser (`https://www.overleaf.com/project/…`).
4. Leave the other fields empty and click **Save**.
5. The app downloads the project, asking for your Overleaf token the first time, and builds the PDF.

To start a **brand-new** paper instead, leave the link empty. The app creates a ready-made folder structure with a `main.tex`. Link it to a new, empty Overleaf project later with **Edit**.

## 6. Editing the .tex yourself (like Overleaf)

Click **✎ Edit .tex** at the top of the middle panel.

- **File list** (top left) shows every `.tex`, `.bib`, `.cls` and similar file of the paper, main file first.
- Type as usual. **Ctrl+Z / Ctrl+Y** undo and redo, and **Ctrl+F** finds text (Enter finds the next match).
- **Ctrl+S** or **💾 Save & Recompile** saves the file and rebuilds the PDF.
  Each save is recorded in the paper's history on your computer. It goes to Overleaf the next time you press **Sync**.
- **Jump from the PDF to the source:** with **Click in PDF: Edit .tex** selected (above the PDF), click any text in the PDF. The editor opens that line and highlights it.
- **Jump to an error:** click a red LaTeX error under the PDF to open that line.
- If a file changes on disk while it's open (after a Sync or an AI task), the editor reloads it. Your unsaved typing is never thrown away; you get a **Reload from disk** button instead.
- Reference-manager `.bib` files (Zotero, Mendeley) open **read-only**, because Overleaf overwrites them.

## 7. Letting the AI work (Agent tasks)

Click **🤖 Agent tasks**, pick a **Task** from the dropdown, fill in the form and click **▶ Run**.

| Task | What it does | Changes the paper? |
|---|---|---|
| **Edit Text** | copy-edits one section; formulas, citations and labels are protected | after your OK |
| **Literature Review** | searches OpenAlex, Crossref and arXiv and writes a review with a link for every paper | no, report only |
| **Add Figures** | adds images from any folder, with captions; can also **replace** a figure | after your OK |
| **Add References** | turns DOIs, arXiv IDs or titles into BibTeX entries | after your OK |
| **Results Figures & Tables** | turns your training or inference results into a graph or a table in the paper | after your OK |
| **Citation & BibTeX Audit** | finds missing, duplicate or broken citations | no, report only |
| **Custom Agent Task** | any instruction in your own words | after your OK |

**Making a graph or a table from your results**

Choose **Results Figures & Tables**, click **Add files...** (or **Add folder...**) and pick the files your
training run produced: a CSV or Excel table, a saved Keras/PyTorch history (`.json`), or a text file with a
`classification_report` or a confusion matrix. Pick what to draw - training curves, a bar chart, a confusion
matrix, a table - or leave it on *Let Claude choose*.

The AI decides which columns are worth showing and writes the caption. **It never types a number**: the app
reads the values out of your file and draws them, so the graph always matches the file. The graph is added as
real LaTeX (`pgfplots`), not as a picture, so the fonts match your paper and you can still change it in
Overleaf later.

Your result files are only read. Nothing is written into `data\` or `supplementary\`, and those folders still
never leave your computer - only the numbers that end up in the figure travel with the paper.

**Summarising a paper you already have**

In **Literature Review**, switch to **Summarise papers I have**. Add PDFs from your computer, or paste DOIs,
arXiv IDs or links - one per line - or both. Each paper gets its own summary: what it does, its results, how
it relates to your topic, and its limitations.

A link is looked up in the same catalogues the search uses, so its details are confirmed. A PDF is read as
text on your computer (the figures are not seen), which keeps it cheap. If a PDF has no confirmed DOI the
report says so plainly, so you know which summaries rest on the file alone. A scanned PDF with no real text
cannot be read, and the report tells you that too.

As with the review, nothing in your paper changes - you get a report.

**How approval works**

1. The AI proposes a change. A window shows the old and new text side by side, and the PDF shows the proposed version with an orange label.
2. Click **Approve** or **Reject**. Rejecting leaves your paper untouched.
3. Approved changes are saved on your computer only, until you press **Sync**.

**Shortcut from the PDF:** choose **Click in PDF: Agent task**. Clicking a paragraph then opens *Edit Text* for it, and clicking a figure opens *Replace a figure*. **Right-click** the PDF for every option.

## 8. The shared to-do list

Click **☑ To-Do** in the middle switch, next to *Agent tasks* and *Edit .tex*. It is **one list for all
your papers**, shared with everyone you work with.

**Setting it up (once per computer)**

1. On GitHub, create a new **private** repository - for example `research-todo` - and tick *Add a README*.
2. Invite the people you work with (repository **Settings ▸ Collaborators**).
3. In the app choose **Options ▸ Shared to-do list…** and paste the repository link.
4. Sign in to GitHub under **Accounts** with your own token (*Contents: read and write* on that repository).

**Using it**

Type a task and press Enter. Assignee, due date, paper and section are all optional. Naming a paper is just
a label that says where the task belongs - new tasks are labelled with the paper you have open, and tasks
that belong to no paper are perfectly fine. Use the filters to see only open tasks, only yours, only
overdue ones, or only one paper's.

Changes are saved for everyone straight away - there is no approval window and no Sync for the to-do list,
because it is not part of a paper. The list refreshes when you open it, when you come back to the window,
when you click ⟳ Refresh, and every 45 seconds by itself. If two of you change the list at the same
moment nothing is lost; for the same task, the last change wins.

**If you used the old per-paper lists**

Before version 1.3.0 each paper had its own to-do list. Choose **Options ▸ Move paper to-do lists into the
shared list…** once: it copies those tasks over with their assignee, due date and state, and then removes
`todo.md` from each paper. Press **Sync** on each paper afterwards so it disappears from Overleaf too.

## 9. Language: English or Deutsch

The **Language** menu at the top switches the app between English and Deutsch. The app asks whether to
restart, because the labels are set when the window opens.

Only the buttons and messages change language. **Your paper is always written in English** - the folder
structure, the LaTeX, the captions and everything the assistant writes for you. That is deliberate: you
publish in English, and a German word must never slip into a manuscript.

## 10. Sending your work to Overleaf: Sync

Press **⇄ Sync with Overleaf** (left panel). The app:

1. fetches what your co-authors changed in Overleaf,
2. puts your changes on top of theirs,
3. shows you the list of changes and sends them after you confirm.

The left panel shows how many changes are waiting. **⟳ Refresh** only fetches and sends nothing.

If you and a co-author changed the **same lines**, nothing is sent and the app tells you. Sort it out in Overleaf, then Sync again.

## 11. Backing up your data to OneDrive

Your `data\` and `supplementary\` folders never go to Overleaf, so they are the only things with no second
copy. Press **☁ Back up data** (left panel) to copy them into OneDrive.

The app shows you what has changed and asks before copying anything, then a window with a progress bar
tells you which file it is on (*"File 5 of 10 · 3.8 MB of 19.1 MB"*). **Cancel** stops it after the current
file; what has already gone is remembered, so nothing is sent twice when you run it again.

Your files land there in the same structure you see here:

```
<your OneDrive folder>\Research papers\<paper name>\data\...
<your OneDrive folder>\Research papers\<paper name>\supplementary\...
```

- It only ever **copies out**. Nothing already in OneDrive is renamed or deleted, and nothing is copied
  back, so running it again is always safe.
- Only files that are **new or changed** are sent, so later backups are quick.
- Some file names are not allowed (anything with `: * ? " < > |`, names like `CON.txt`, and very long
  paths). Those files are listed in the log and skipped — everything else still goes.

**Setting it up the first time**

1. Make sure the OneDrive app is signed in with your university account. It usually already is — look for
   the cloud icon near the clock.
2. In the app, press **☁ Back up data**, then the **…** button, and choose your OneDrive folder (something
   like `C:\Users\<you>\OneDrive - Your University`). The app checks that OneDrive really syncs the folder
   you picked, and if not it says so and lists the ones it does sync — so you can't quietly copy into a
   dead end.
3. **Save**, then press **☁ Back up data** again and confirm.

No sign-in and no codes: the app copies your files in, and OneDrive uploads them.

**Checking they arrived.** Open the folder in Explorer. The app copies the files, but **OneDrive** does the
uploading, so its icons are what confirm it:

| Icon | Meaning |
|---|---|
| Blue circular arrows | still uploading — leave OneDrive running |
| Green tick or white cloud | uploaded and safe |
| Red cross | OneDrive has a problem — open it and read the message |

## 12. LaTeX errors

Like Overleaf, the app keeps building the PDF when LaTeX can recover from an error. In that case:

- the label above the PDF turns **amber** (*"2 LaTeX errors (PDF still produced, as in Overleaf)"*);
- the errors are listed under the PDF; click one to jump to its line.

Only a serious error (for example a missing file) stops the PDF. The label turns **red**, and the last good PDF stays visible.

When the AI changes your paper, it is only rolled back if it **adds a new** error. Errors that were already there don't block it.

## 13. Where your files are

Everything is in the folder **`C:\Users\<you>\.research_agent`**:

| Folder or file | Contents |
|---|---|
| `papers\` | your papers, one folder each (you can also open them with **Folder** in the app) |
| `papers\<paper>\data\` | your datasets. Copy them in with Explorer. This folder stays on your computer: it is never sent to Overleaf, and the AI never changes it |
| `papers\<paper>\supplementary\` | supplementary material (videos, extra results, large files). Also stays on your computer; upload it to the journal yourself |
| `reports\` | literature reviews, audits, `.bib` exports |
| `agent.log` | the detailed log (useful when reporting a problem) |
| `app_state.json` | your paper list and settings (no passwords) |
| `backup\` | a note of which files were last backed up, so only changes are re-sent |

Your Claude key and Overleaf token are in **Windows Credential Manager** (Control Panel → Credential Manager → Windows Credentials).

**What is sent where:** for AI tasks, the text the task needs (for example one section) goes to Anthropic's Claude API. Editing, the PDF and the history stay on your computer; Sync talks only to Overleaf, and Back up data only copies into your own OneDrive folder.

## 14. Troubleshooting

| Problem | What to do |
|---|---|
| The setup window could not install Git or MiKTeX | Check the internet connection and click **Try again**. Some institute computers block installing programs; then ask IT to install *Git for Windows* and *MiKTeX*. |
| No PDF, "No LaTeX compiler found" | **Help → Install Git / MiKTeX…**, then restart the app. |
| MiKTeX asks to install a package | Click **Install**. This happens once per package. |
| "rejected the stored credentials" | Your token or key expired. **Accounts** menu → sign in again. |
| Sync says the paper and Overleaf project "were started separately" | You linked a paper created in the app to an Overleaf project that already has files. Add the paper again **with** the Overleaf link instead. |
| Sync says there are conflicting changes | You and a co-author changed the same lines. Resolve it in Overleaf, then **Refresh**. |
| The app closed unexpectedly | Send `C:\Users\<you>\.research_agent\crash.log` and `agent.log` to whoever maintains the app. |
| Windows blocks the app | **More info → Run anyway** (see section 2). |
| *Update available* keeps coming back and **Help → About** still shows the old version | Versions 1.0.0 and 1.0.1 cannot update themselves. Once only: close the app, download the newest `ResearchAssistant-windows-….zip` from the [releases page](https://github.com/Girish-Tangirala/research-assistant/releases), delete the old app folder (and any `ResearchAssistant.new` folder next to it), and unzip the new one in the same place. Your papers and settings are kept. Later updates install themselves. |

---

*For people who want to **change** the app itself: ask for the source-code zip. Its `README.md` and `CLAUDE.md` explain how to work on it with your own Claude Code.*
