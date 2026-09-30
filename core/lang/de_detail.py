"""German: the messages that carry a value - a name, a count, a path or a reason.

Kept apart from :mod:`core.lang.de_status` so both stay under the line limit.
The ``{placeholders}`` must survive translation; ``core.i18n.t`` falls back to
the English if one is misspelt, and ``tests/test_i18n.py`` checks they resolve.
"""

from __future__ import annotations

CATALOGUE: dict[str, str] = {
    # -- start-up and about ------------------------------------------------ #
    "Workspace: {path}": "Arbeitsbereich: {path}",
    "The user guide was not found at {path}.": "Das Benutzerhandbuch wurde unter {path} nicht gefunden.",
    "Could not save settings: {problem}": "Einstellungen konnten nicht gespeichert werden: {problem}",
    "To-do list: {problem}": "To-do-Liste: {problem}",
    "Scientific Research Assistant Agent {version}\n\nModel: {model} (effort {effort})\n"
    "LaTeX: {latex}\nWorkspace: {workspace}":
        "Scientific Research Assistant Agent {version}\n\nModell: {model} (Aufwand {effort})\n"
        "LaTeX: {latex}\nArbeitsbereich: {workspace}",
    "State: {state}": "Status: {state}",
    "▶ {task} - {paper}": "▶ {task} – {paper}",

    # -- installing Git and MiKTeX ------------------------------------------ #
    "• {tool}: {state}": "• {tool}: {state}",
    "needed": "wird benötigt",
    "already installed ✓": "bereits installiert ✓",
    "installed ✓": "installiert ✓",
    "finding the current version…": "aktuelle Version wird ermittelt…",
    "{tool}: {problem}": "{tool}: {problem}",
    "Git (history of your papers, talking to Overleaf)":
        "Git (Versionsverlauf Ihrer Paper, Verbindung zu Overleaf)",

    # -- sign-in ------------------------------------------------------------ #
    "Signed in - {model} is available.": "Angemeldet – {model} ist verfügbar.",
    "Signed in as {account}.": "Angemeldet als {account}.",

    # -- papers -------------------------------------------------------------- #
    "Paper '{name}' saved.": "Paper '{name}' gespeichert.",
    "Remove '{name}' from the list?\n\nFiles on disk are not deleted.":
        "'{name}' aus der Liste entfernen?\n\nDateien auf dem Datenträger werden nicht gelöscht.",
    "{folder} does not exist yet - refresh or sync the paper first.":
        "{folder} existiert noch nicht – aktualisieren oder synchronisieren Sie das Paper zuerst.",
    "Setting up {folder}…": "{folder} wird eingerichtet…",
    "Could not set up the paper folder: {problem}":
        "Der Paper-Ordner konnte nicht eingerichtet werden: {problem}",
    "Cloning {url} into {folder}…": "{url} wird nach {folder} geklont…",
    "Cloned '{name}' into {folder}.": "'{name}' wurde nach {folder} geklont.",
    "Could not clone the paper: {problem}": "Das Paper konnte nicht geklont werden: {problem}",
    "Loaded {count} section titles.": "{count} Abschnittstitel geladen.",
    "Created {folder} - it stays on this computer and is never sent to Overleaf.":
        "{folder} wurde angelegt – der Ordner bleibt auf diesem Computer und wird nie an Overleaf gesendet.",
    "Read-only .bib files not listed: {files}":
        "Schreibgeschützte '.bib'-Dateien nicht aufgeführt: {files}",
    "'{name}' is only on this computer - nothing is sent anywhere until you link it to an Overleaf project.":
        "'{name}' liegt nur auf diesem Computer – es wird nichts gesendet, solange Sie es nicht mit einem "
        "Overleaf-Projekt verknüpfen.",
    "'{name}' is saved on this computer only.\n\nAdd its Overleaf project link now? You can also keep "
    "working locally and link it later.":
        "'{name}' ist nur auf diesem Computer gespeichert.\n\nJetzt den Overleaf-Projektlink ergänzen? Sie "
        "können auch lokal weiterarbeiten und ihn später verknüpfen.",
    "Sort the files of '{name}' into {folders}?\n\nThe app shows you every move and every changed "
    "\\input / \\includegraphics path, and compiles the result, before anything is written. Nothing moves "
    "until you approve.\n\nIt becomes one commit on {where}.":
        "Die Dateien von '{name}' in {folders} einsortieren?\n\nDie Anwendung zeigt Ihnen jede Verschiebung "
        "und jeden geänderten \\input-/\\includegraphics-Pfad und kompiliert das Ergebnis, bevor etwas "
        "geschrieben wird. Es wird nichts verschoben ohne Ihre Genehmigung.\n\nEs wird ein Commit auf "
        "{where}.",
    "The Overleaf project was empty, so the folder structure was added ({count} file(s)). Press Sync to "
    "send it.":
        "Das Overleaf-Projekt war leer, daher wurde die Ordnerstruktur angelegt ({count} Datei(en)). Zum "
        "Senden auf 'Synchronisieren' klicken.",

    # -- paper dialog -------------------------------------------------------- #
    "blank = {folder}\\<name>": "leer = {folder}\\<Name>",
    "{folder} already contains a paper (main.tex). Untick the structure box to use it as it is.":
        "{folder} enthält bereits ein Paper (main.tex). Entfernen Sie den Haken bei der Ordnerstruktur, um "
        "es unverändert zu verwenden.",
    "Creates {folders} and a main.tex that compiles in Overleaf. Existing files are never overwritten; "
    "data/ stays on this computer. With a link, the Overleaf project is cloned first and the structure is "
    "only added if it has no .tex files yet.":
        "Legt {folders} und eine main.tex an, die in Overleaf kompiliert. Vorhandene Dateien werden nie "
        "überschrieben; 'data/' bleibt auf diesem Computer. Mit einem Link wird das Overleaf-Projekt zuerst "
        "geklont und die Struktur nur ergänzt, wenn es noch keine '.tex'-Dateien enthält.",

    # -- the PDF and its right-click menu -------------------------------------- #
    "Found {count} figure(s).": "{count} Abbildung(en) gefunden.",
    "Edit in the .tex editor ({path}, line {line})": "Im '.tex'-Editor bearbeiten ({path}, Zeile {line})",
    "Replace this figure ({image})": "Diese Abbildung ersetzen ({image})",
    "Edit section '{section}'": "Abschnitt '{section}' bearbeiten",
    "Add a figure to '{section}'": "Abbildung zu '{section}' hinzufügen",
    "Add references to '{section}'": "Quellen zu '{section}' hinzufügen",
    "New to-do for '{section}'": "Neues To-do für '{section}'",
    "Open {path} in another program": "{path} in einem anderen Programm öffnen",
    "Copied: {text}": "Kopiert: {text}",
    "Check citations": "Zitate prüfen",
    "Check citations ({keys})": "Zitate prüfen ({keys})",
    "That comes from the preamble ({path}, line {line}) - it is not part of a section.":
        "Das stammt aus der Präambel ({path}, Zeile {line}) – es gehört zu keinem Abschnitt.",
    "{path}, line {line} is not inside a section - use a Custom Agent Task for text outside sections.":
        "{path}, Zeile {line} liegt in keinem Abschnitt – verwenden Sie für Text außerhalb von Abschnitten "
        "eine eigene Agent-Aufgabe.",
    "Page {number}": "Seite {number}",

    # -- editor ----------------------------------------------------------------- #
    "Save your changes to {file} first?": "Ihre Änderungen an {file} zuerst speichern?",
    "{file} was saved but not committed: {problem}":
        "{file} wurde gespeichert, aber nicht committet: {problem}",
    "{location} is not a file of this paper.": "{location} gehört nicht zu diesem Paper.",

    # -- approval window ---------------------------------------------------------- #
    "{path}   +{added} / −{removed} lines   (repository: {repo})":
        "{path}   +{added} / −{removed} Zeilen   (Repository: {repo})",

    # -- updates ------------------------------------------------------------------- #
    "You have the latest version ({version}).": "Sie haben die neueste Version ({version}).",
    "The update could not be installed: {problem}":
        "Das Update konnte nicht installiert werden: {problem}",
    "Could not start the update: {problem}": "Das Update konnte nicht gestartet werden: {problem}",
    "{updating}\nStarting the download…": "{updating}\nDownload wird gestartet…",
    "{updating}\n{step}": "{updating}\n{step}",

    # -- backup and the shared list -------------------------------------------------- #
    "Backing up '{paper}'": "'{paper}' wird gesichert",
    "Backup: {problem}": "Sicherung: {problem}",
    "Shared to-do list: {url}": "Gemeinsame To-do-Liste: {url}",
    "▶ Backing up {paper}": "▶ {paper} wird gesichert",
    "{problem}\n\nUse it anyway?": "{problem}\n\nTrotzdem verwenden?",
    "Enter it at {url} and sign in with your work account.":
        "Geben Sie ihn unter {url} ein und melden Sie sich mit Ihrem Arbeitskonto an.",
    "{count} file(s), {size}": "{count} Datei(en), {size}",
    "File {index} of {count} · {sent} of {total}": "Datei {index} von {count} · {sent} von {total}",
    "Data backup set up: {where} → {folder}/<paper>/":
        "Datensicherung eingerichtet: {where} → {folder}/<Paper>/",
    "Checking what has changed in {folders}…": "Es wird geprüft, was sich in {folders} geändert hat…",
    "Not uploaded - {file}: {reason}": "Nicht hochgeladen – {file}: {reason}",
    "The backup is already up to date ({count} file(s) in {folder}).":
        "Die Sicherung ist bereits aktuell ({count} Datei(en) in {folder}).",
    "Copy the {folders} folder(s) of '{paper}'?\n\n{detail}\n\nNothing already there is deleted or "
    "renamed.{handover}":
        "Die Ordner {folders} von '{paper}' kopieren?\n\n{detail}\n\nNichts, was bereits dort liegt, wird "
        "gelöscht oder umbenannt.{handover}",
    "Backup stopped. {count} file(s) were already sent and are not sent again next time.":
        "Sicherung gestoppt. {count} Datei(en) wurden bereits gesendet und werden beim nächsten Mal nicht "
        "erneut gesendet.",
    "Failed - {file}: {reason}": "Fehlgeschlagen – {file}: {reason}",
    "Backup failed: {kind}: {problem}": "Sicherung fehlgeschlagen: {kind}: {problem}",

    # -- figures, editor and to-dos ------------------------------------------------------ #
    "Image: {image}   ·   {path}, line {line}\nCaption: {caption}":
        "Bild: {image}   ·   {path}, Zeile {line}\nBildunterschrift: {caption}",
    "(none)": "(keine)",
    "{file} was changed outside the editor (by a task or a sync) after you opened it.\n\nOverwrite it with "
    "your version?":
        "{file} wurde nach dem Öffnen außerhalb des Editors geändert (durch eine Aufgabe oder eine "
        "Synchronisierung).\n\nMit Ihrer Fassung überschreiben?",
    "Delete this task for everyone?\n\n{task}": "Dieses To-do für alle löschen?\n\n{task}",
    "Move the tasks from {count} paper(s) into the shared list, then delete todo.md from each paper?\n\n"
    "The deletion is committed on this computer only - press Sync on each paper afterwards to remove it "
    "from Overleaf too.\n\nTasks already in the shared list are left alone, so this is safe to run twice.":
        "Die To-dos aus {count} Paper(n) in die gemeinsame Liste übernehmen und danach die todo.md aus "
        "jedem Paper löschen?\n\nDas Löschen wird nur auf diesem Computer committet – klicken Sie danach "
        "bei jedem Paper auf 'Synchronisieren', damit es auch aus Overleaf verschwindet.\n\nTo-dos, die "
        "bereits in der gemeinsamen Liste stehen, bleiben unberührt; ein zweiter Durchlauf schadet also "
        "nicht.",
}
