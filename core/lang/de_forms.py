"""German: the task forms and the dialogs, including their explanatory notes."""

from __future__ import annotations

CATALOGUE: dict[str, str] = {
    # -- Edit Text ------------------------------------------------------- #
    "Editing instructions": "Anweisungen für die Überarbeitung",
    "Improve clarity, flow and concision. Keep all technical content.":
        "Verständlichkeit, Lesefluss und Prägnanz verbessern. Alle fachlichen Inhalte beibehalten.",
    "File (optional)": "Datei (optional)",
    "Repo-relative path; blank = search all .tex files":
        "Pfad relativ zum Repository; leer = alle '.tex'-Dateien durchsuchen",

    # -- Literature Review ----------------------------------------------- #
    "Topic": "Thema",
    "Focus (optional) - sub-questions, methods, exclusions":
        "Schwerpunkt (optional) – Teilfragen, Methoden, Ausschlüsse",
    "Approx. number of papers": "Ungefähre Anzahl Paper",
    "Published from (year, optional)": "Erschienen ab (Jahr, optional)",
    "Searches OpenAlex, Crossref and arXiv (plus Claude web search if enabled). Read-only: writes a review "
    "with a link for every paper,\na verification table and a .bib of new candidates.":
        "Durchsucht OpenAlex, Crossref und arXiv (und die Claude-Websuche, falls aktiviert). Nur lesend: "
        "erstellt eine Übersicht mit einem Link\nzu jedem Paper, eine Prüftabelle und eine '.bib' mit neuen "
        "Kandidaten.",

    # -- Literature Review: summarising a paper you already have ---------- #
    "Blank = derived from the selected paper's title and abstract":
        "Leer = aus Titel und Abstract des gewählten Papers abgeleitet",
    "Search for papers": "Nach Papern suchen",
    "Summarise papers I have": "Vorhandene Paper zusammenfassen",
    "PDFs of papers you already have": "PDFs von Papern, die Sie bereits haben",
    "Choose the PDF of a paper": "PDF eines Papers auswählen",
    "No PDFs chosen - click 'Add files…', or give a DOI or link below.":
        "Keine PDFs ausgewählt – auf 'Dateien hinzufügen…' klicken oder unten eine DOI bzw. einen Link "
        "angeben.",
    "…and/or DOIs, arXiv IDs or links - one per line":
        "…und/oder DOIs, arXiv-IDs oder Links – einer pro Zeile",
    "Each paper is summarised on its own: what it does, its results, how it relates to your topic\n"
    "and its limitations. Read-only - a report, never a change to your paper.\n"
    "A link is resolved through the same indexes as a search, so its DOI is confirmed. A PDF is read\n"
    "as text (figures and tables are not seen); if it prints a DOI, that is looked up to confirm it.":
        "Jedes Paper wird einzeln zusammengefasst: worum es geht, die Ergebnisse, der Bezug zu Ihrem Thema\n"
        "und die Grenzen. Nur lesend – ein Bericht, nie eine Änderung an Ihrem Paper.\n"
        "Ein Link wird über dieselben Indexe wie bei der Suche aufgelöst, seine DOI ist also bestätigt. Ein "
        "PDF wird\nals Text gelesen (Abbildungen und Tabellen werden nicht gesehen); eine darin gedruckte "
        "DOI wird nachgeschlagen.",

    # -- Add Figures ----------------------------------------------------- #
    "Images from anywhere on your computer (PNG, JPG, PDF; TIFF/BMP/GIF/WebP are converted)":
        "Bilder von beliebiger Stelle auf dem Computer (PNG, JPG, PDF; TIFF/BMP/GIF/WebP werden umgewandelt)",
    "Place the figures at the end of section": "Abbildungen am Ende dieses Abschnitts einfügen",
    "Caption (optional, used when adding a single image)":
        "Bildunterschrift (optional, wird bei einem einzelnen Bild verwendet)",
    "Width": "Breite",
    "Let Claude draft captions by looking at each image":
        "Claude die Bildunterschriften anhand der Bilder entwerfen lassen",
    "Add a sentence that refers to each figure (Figure~\\ref{…})":
        "Einen Satz ergänzen, der auf jede Abbildung verweist (Figure~\\ref{…})",
    "Images are copied into the paper's figures folder only after you approve them.":
        "Bilder werden erst nach Ihrer Genehmigung in den Abbildungsordner des Papers kopiert.",
    "Add new figures": "Neue Abbildungen hinzufügen",
    "Replace a figure": "Abbildung ersetzen",
    "Figure to replace (or click a figure in the PDF preview)":
        "Zu ersetzende Abbildung (oder in der PDF-Vorschau auf eine Abbildung klicken)",
    "New image": "Neues Bild",
    "Choose the new image file": "Neue Bilddatei auswählen",
    "Choose the new image": "Neues Bild auswählen",
    "New caption (optional - blank keeps the current caption)":
        "Neue Bildunterschrift (optional – leer behält die bisherige bei)",
    "Let Claude update the caption for the new image":
        "Claude die Bildunterschrift für das neue Bild anpassen lassen",
    "Same file type: the image file is replaced in place (no LaTeX change). Otherwise the new file is added\n"
    "and the figure points to it. Nothing changes until you approve.":
        "Gleicher Dateityp: die Bilddatei wird direkt ersetzt (keine LaTeX-Änderung). Sonst wird die neue "
        "Datei ergänzt\nund die Abbildung verweist darauf. Es ändert sich nichts ohne Ihre Genehmigung.",
    "No figures with \\includegraphics were found.": "Keine Abbildungen mit \\includegraphics gefunden.",

    # -- Add References -------------------------------------------------- #
    "DOIs, arXiv IDs / links or paper titles - one per line":
        "DOIs, arXiv-IDs / Links oder Titel – einer pro Zeile",
    "…and/or import entries from .bib files on your computer":
        "…und/oder Einträge aus '.bib'-Dateien auf Ihrem Computer importieren",
    "Add to .bib file (blank = first editable .bib of the paper, or a new references.bib)":
        "In '.bib'-Datei eintragen (leer = erste bearbeitbare '.bib' des Papers oder eine neue references.bib)",
    "Cite them in section (optional)": "In diesem Abschnitt zitieren (optional)",
    "Metadata comes from OpenAlex / Crossref / arXiv or your file - never invented. Duplicates are skipped; "
    "read-only (Zotero) .bib files are never edited.":
        "Die Metadaten stammen aus OpenAlex / Crossref / arXiv oder Ihrer Datei – nie erfunden. Duplikate "
        "werden übersprungen; schreibgeschützte (Zotero-) '.bib'-Dateien werden nie verändert.",

    # -- Results figures ------------------------------------------------- #
    "Result files or a folder (CSV, Excel, JSON history, classification report, confusion matrix)":
        "Ergebnisdateien oder ein Ordner (CSV, Excel, JSON-Verlauf, Klassifikationsbericht, Konfusionsmatrix)",
    "Files are only read. Nothing is written to data/ or supplementary/, and the raw files never\nleave your "
    "computer - only the numbers that end up in the figure do.":
        "Die Dateien werden nur gelesen. In 'data/' und 'supplementary/' wird nichts geschrieben, und die "
        "Rohdaten verlassen\nIhren Computer nie – nur die Zahlen, die in der Abbildung landen.",
    "What to draw": "Was gezeichnet werden soll",
    "Let Claude choose": "Claude entscheiden lassen",
    "Training curves (line chart)": "Trainingskurven (Liniendiagramm)",
    "Comparison bar chart": "Balkendiagramm zum Vergleich",
    "Confusion matrix (heat map)": "Konfusionsmatrix (Heatmap)",
    "Table of results": "Ergebnistabelle",
    "Place it at the end of section": "Am Ende dieses Abschnitts einfügen",
    "Caption (optional - Claude drafts one from the numbers and the section)":
        "Bildunterschrift (optional – Claude entwirft eine aus den Zahlen und dem Abschnitt)",
    "X axis label (optional)": "Beschriftung der x-Achse (optional)",
    "Y axis label (optional)": "Beschriftung der y-Achse (optional)",
    "Decimal places": "Nachkommastellen",
    "Chart width": "Diagrammbreite",
    "Add a sentence that refers to it (Figure~\\ref{…})":
        "Einen Satz ergänzen, der darauf verweist (Figure~\\ref{…})",
    "Charts are written as pgfplots/booktabs code, so you see every number in the approval window\nand can "
    "edit it later in Overleaf. Nothing changes until you approve.":
        "Diagramme werden als pgfplots-/booktabs-Code geschrieben: Sie sehen jede Zahl im Genehmigungsfenster\n"
        "und können sie später in Overleaf ändern. Es ändert sich nichts ohne Ihre Genehmigung.",
    "Choose a folder of results": "Ordner mit Ergebnissen auswählen",
    "Choose result files": "Ergebnisdateien auswählen",
    "Nothing chosen - click 'Add files…' for single files, or 'Add folder…' for a whole run.":
        "Nichts ausgewählt – 'Dateien hinzufügen…' für einzelne Dateien, 'Ordner hinzufügen…' für einen "
        "ganzen Durchlauf.",
    "No files chosen - click 'Add files…' (repeat for other folders).":
        "Keine Dateien ausgewählt – auf 'Dateien hinzufügen…' klicken (für weitere Ordner wiederholen).",

    # -- Audit / custom task --------------------------------------------- #
    "Read-only check of the selected paper: missing or duplicate citation keys, missing or malformed DOIs,\n"
    "missing required fields and unused entries. DOIs are never invented. No Claude sign-in needed.":
        "Nur lesende Prüfung des gewählten Papers: fehlende oder doppelte Zitierschlüssel, fehlende oder "
        "fehlerhafte DOIs,\nfehlende Pflichtfelder und ungenutzte Einträge. DOIs werden nie erfunden. Keine "
        "Claude-Anmeldung nötig.",
    "Describe the task (the agent can read, search literature, edit, audit, compile and commit - every edit "
    "needs your approval)":
        "Beschreiben Sie die Aufgabe (der Agent kann lesen, Literatur suchen, bearbeiten, prüfen, "
        "kompilieren und committen – jede Änderung braucht Ihre Genehmigung)",
    "Read the paper and suggest a clearer abstract; stage the edit.":
        "Lies das Paper und schlage ein klareres Abstract vor; bereite die Änderung vor.",

    # -- paper dialog ---------------------------------------------------- #
    "Add a paper": "Paper hinzufügen",
    "Edit paper": "Paper bearbeiten",
    "Add paper": "Paper hinzufügen",
    "The paper lives in a folder on this computer. An Overleaf (or GitHub) link is optional - you can add it "
    "later and send your work with the Sync button.":
        "Das Paper liegt in einem Ordner auf diesem Computer. Ein Overleaf- (oder GitHub-)Link ist optional – "
        "Sie können ihn später ergänzen und Ihre Arbeit mit der Schaltfläche 'Synchronisieren' senden.",
    "Paper name": "Name des Papers",
    "e.g. GNN folding paper": "z. B. GNN-Faltungs-Paper",
    "Overleaf or Git URL (optional)": "Overleaf- oder Git-URL (optional)",
    "Local folder": "Lokaler Ordner",
    "Branch (optional)": "Branch (optional)",
    "blank = the repository's default branch (Overleaf: main)":
        "leer = Standard-Branch des Repositorys (Overleaf: main)",
    "Set up the folder structure for a new paper": "Ordnerstruktur für ein neues Paper anlegen",
    "Title of the paper (used in main.tex)": "Titel des Papers (wird in main.tex verwendet)",
    "blank = the paper name": "leer = der Name des Papers",
    "Read-only files (the agent may read but never edit them)":
        "Schreibgeschützte Dateien (der Agent darf sie lesen, aber nie bearbeiten)",
    "e.g. zotero.bib, refs/*.bib": "z. B. zotero.bib, refs/*.bib",
    "Also auto-protect Zotero / Mendeley / ReadCube .bib files":
        "Zotero-/Mendeley-/ReadCube-'.bib'-Dateien zusätzlich automatisch schützen",
    "Overleaf overwrites reference-manager .bib files when you click Refresh, so edits to them would be lost.":
        "Overleaf überschreibt '.bib'-Dateien der Literaturverwaltung beim Aktualisieren – Änderungen daran "
        "gingen verloren.",
    "No reference-manager .bib files detected. Add file names manually if Overleaf shows a .bib as linked to "
    "Zotero/Mendeley.":
        "Keine '.bib'-Dateien einer Literaturverwaltung gefunden. Tragen Sie Dateinamen von Hand ein, wenn "
        "Overleaf eine '.bib' als mit Zotero/Mendeley verknüpft anzeigt.",
    "Folder not cloned yet - save, sync the paper, then use Detect again.":
        "Ordner noch nicht geklont – speichern, das Paper synchronisieren, dann erneut 'Erkennen' verwenden.",

    # -- sign-in dialogs -------------------------------------------------- #
    "Sign in to Claude": "Bei Claude anmelden",
    "API key": "API-Schlüssel",
    "Username": "Benutzername",
    "Access token": "Zugriffstoken",
    "Commit author name": "Name für Commits",
    "Commit author email": "E-Mail für Commits",
    "Enter the name and a valid email to use for commits.":
        "Geben Sie den Namen und eine gültige E-Mail-Adresse für Commits an.",
    "Username and token are required.": "Benutzername und Token sind erforderlich.",

    # -- shared to-do list ------------------------------------------------ #
    "Shared to-do list": "Gemeinsame To-do-Liste",
    "Repository link": "Link zum Repository",
    "One shared to-do list for all your papers, kept in a small Git repository of its own - not in a paper, "
    "so a to-do change never touches a manuscript and never waits for Sync.\n\nCreate an empty private "
    "repository (tick “Add a README”), invite the people you work with, and paste its link below. Everyone "
    "signs in to that host under Accounts with their own token.":
        "Eine gemeinsame To-do-Liste für alle Ihre Paper, in einem eigenen kleinen Git-Repository – nicht in "
        "einem Paper. So berührt eine To-do-Änderung nie ein Manuskript und wartet nie auf das "
        "Synchronisieren.\n\nLegen Sie ein leeres privates Repository an (mit „Add a README“), laden Sie "
        "Ihre Mitarbeitenden ein und fügen Sie den Link unten ein. Alle melden sich unter 'Konten' mit "
        "ihrem eigenen Token bei diesem Anbieter an.",
    "One list for all your papers. Everything except the task text is optional; naming a paper is\njust a "
    "label, so tasks that belong to no paper are fine too.":
        "Eine Liste für alle Ihre Paper. Außer dem Text ist alles optional; ein Paper zu nennen ist nur eine "
        "Beschriftung,\nTo-dos ohne Paper sind also völlig in Ordnung.",
    "New task, e.g. 'Update Fig. 3 with the new results'":
        "Neues To-do, z. B. „Abb. 3 mit den neuen Ergebnissen aktualisieren“",
    "Move the to-do lists": "To-do-Listen verschieben",

    # -- backup ----------------------------------------------------------- #
    "Back up data to OneDrive": "Daten in OneDrive sichern",
    "Folder on this computer that OneDrive syncs":
        "Ordner auf diesem Computer, den OneDrive synchronisiert",
    "Folder inside it for the papers": "Ordner darin für die Paper",
    "Folders of each paper to back up": "Zu sichernde Ordner jedes Papers",
    "Choose the OneDrive folder to back up into": "OneDrive-Ordner für die Sicherung auswählen",
    "OneDrive then uploads them by itself. The tick marks in Explorer show when a file has arrived.":
        "OneDrive lädt sie anschließend selbst hoch. Die Häkchen im Explorer zeigen, wann eine Datei "
        "angekommen ist.",
    "OneDrive uploads them afterwards; watch the tick marks in Explorer.":
        "OneDrive lädt sie danach hoch; achten Sie auf die Häkchen im Explorer.",
    "No sign-in needed here: OneDrive does the uploading. Sign in to OneDrive itself if it is not syncing.":
        "Hier ist keine Anmeldung nötig: OneDrive lädt hoch. Melden Sie sich bei OneDrive selbst an, wenn es "
        "nicht synchronisiert.",
}
