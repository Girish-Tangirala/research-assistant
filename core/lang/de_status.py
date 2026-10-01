"""German: status lines, warnings and the questions the app asks.

The agent's own step-by-step log stays English (it is compared with the code and
with what colleagues see), as do commit messages and the saved reports.
"""

from __future__ import annotations

CATALOGUE: dict[str, str] = {
    # -- running a task --------------------------------------------------- #
    "A workflow is already running.": "Es läuft bereits eine Aufgabe.",
    "Add a paper first.": "Fügen Sie zuerst ein Paper hinzu.",
    "Add and sync a paper first.": "Fügen Sie zuerst ein Paper hinzu und synchronisieren Sie es.",
    "Cancellation requested - stopping after the current step…":
        "Abbruch angefordert – wird nach dem aktuellen Schritt beendet…",
    "The task did not finish": "Die Aufgabe wurde nicht abgeschlossen",
    "Claude sign-in is required for this workflow.":
        "Für diese Aufgabe ist eine Anmeldung bei Claude erforderlich.",
    "A task is running - the form is filled in; run it when the task has finished.":
        "Eine Aufgabe läuft – das Formular ist ausgefüllt; führen Sie es aus, wenn die Aufgabe fertig ist.",
    "A task is running - save when it has finished (your text is kept).":
        "Eine Aufgabe läuft – speichern Sie, wenn sie fertig ist (Ihr Text bleibt erhalten).",
    "A task is running - update when it has finished.":
        "Eine Aufgabe läuft – aktualisieren Sie, wenn sie fertig ist.",
    "The to-do list is saving - update when it has finished.":
        "Die To-do-Liste wird gespeichert – aktualisieren Sie, wenn das fertig ist.",

    # -- papers ----------------------------------------------------------- #
    "Checking…": "Wird geprüft…",
    "No Overleaf link yet": "Noch kein Overleaf-Link",
    "Not set up yet - press Refresh to clone or create the folder.":
        "Noch nicht eingerichtet – auf 'Aktualisieren' klicken, um den Ordner zu klonen oder anzulegen.",
    "Create a new paper folder, or add the Overleaf/GitHub repository of one you already have.":
        "Legen Sie einen neuen Paper-Ordner an oder fügen Sie das Overleaf-/GitHub-Repository eines "
        "vorhandenen hinzu.",
    "The Overleaf project already has a paper, so its files were left as they are.":
        "Das Overleaf-Projekt enthält bereits ein Paper, daher wurden seine Dateien unverändert gelassen.",
    "The paper is not cloned yet - click 'Sync paper' first.":
        "Das Paper ist noch nicht geklont – klicken Sie zuerst auf 'Paper aktualisieren'.",
    "To sort its files into folders, use File ▸ Organise paper into folders…":
        "Um seine Dateien in Ordner zu sortieren: Datei ▸ Paper in Ordner sortieren…",
    "Remove paper": "Paper entfernen",
    "on this computer only": "nur auf diesem Computer",
    "Folders: {names}": "Ordner: {names}",
    "Read-only: {files}": "Schreibgeschützt: {files}",
    "{count} file(s) not in folders yet - File ▸ Organise paper into folders…":
        "{count} Datei(en) noch nicht in Ordnern – Datei ▸ Paper in Ordner sortieren…",
    "Only on this computer": "Nur auf diesem Computer",
    " · {n} change(s) saved": " · {n} Änderung(en) gespeichert",
    " · add an Overleaf link with Edit paper to share it":
        " · einen Overleaf-Link über 'Paper bearbeiten' ergänzen, um es zu teilen",
    "{n} change(s) to send": "{n} Änderung(en) zu senden",
    "{n} waiting from Overleaf": "{n} von Overleaf ausstehend",
    " (as of the last sync)": " (Stand der letzten Synchronisierung)",
    "In sync with Overleaf as of the last sync":
        "Bei der letzten Synchronisierung mit Overleaf abgeglichen",

    # -- PDF preview ------------------------------------------------------- #
    "Click Recompile to build the PDF of this paper.":
        "Auf 'Neu kompilieren' klicken, um das PDF dieses Papers zu erzeugen.",
    "Sync the paper, then click Recompile to see the PDF.":
        "Das Paper aktualisieren und dann auf 'Neu kompilieren' klicken, um das PDF zu sehen.",
    "Compiling current version…": "Aktuelle Fassung wird kompiliert…",
    "Last compiled version - click Recompile to refresh":
        "Zuletzt kompilierte Fassung – auf 'Neu kompilieren' klicken zum Aktualisieren",
    "No LaTeX compiler found - install MiKTeX or TeX Live to see the PDF.":
        "Kein LaTeX-Compiler gefunden – installieren Sie MiKTeX oder TeX Live, um das PDF zu sehen.",
    "The paper is busy - recompile when the current task is done.":
        "Das Paper ist belegt – kompilieren Sie neu, wenn die laufende Aufgabe fertig ist.",
    "Looking up the source…": "Quellstelle wird gesucht…",
    "No source line found for that spot.": "Für diese Stelle wurde keine Quellzeile gefunden.",
    "Bibliography clicked - add references here, or run the Citation & BibTeX Audit.":
        "Auf das Literaturverzeichnis geklickt – hier Quellen hinzufügen oder 'Zitate & BibTeX prüfen' "
        "ausführen.",
    "Click text to edit its section with the agent, a figure to replace it; right-click for more.":
        "Auf Text klicken, um seinen Abschnitt mit dem Agenten zu bearbeiten, auf eine Abbildung, um sie zu "
        "ersetzen; Rechtsklick für mehr.",
    "Click opens the .tex line in the editor; right-click for more.":
        "Klick öffnet die '.tex'-Zeile im Editor; Rechtsklick für mehr.",
    "Clicking is off - right-click still opens the menu.":
        "Klicken ist aus – Rechtsklick öffnet weiterhin das Menü.",
    "Click a link to open the paper in your browser.":
        "Auf einen Link klicken, um das Paper im Browser zu öffnen.",

    # -- approval and pushing ---------------------------------------------- #
    "Approved changes are written, compiled, committed on a feature branch and pushed (if enabled).":
        "Genehmigte Änderungen werden geschrieben, kompiliert, auf einem Feature-Branch committet und – "
        "falls aktiviert – gepusht.",
    "The approved changes are committed locally and compiled - check the PDF preview. Push sends them to "
    "your collaborators; Discard throws them away.":
        "Die genehmigten Änderungen sind lokal committet und kompiliert – prüfen Sie die PDF-Vorschau. "
        "'Senden' schickt sie an Ihre Mitautorinnen und Mitautoren; 'Verwerfen' löscht sie.",

    # -- accounts ----------------------------------------------------------- #
    "Signed in.": "Angemeldet.",
    "Verifying key…": "Schlüssel wird geprüft…",
    "Signed out of Claude.": "Von Claude abgemeldet.",
    "OpenAlex key removed.": "OpenAlex-Schlüssel entfernt.",
    "Signed out of {host}.": "Von {host} abgemeldet.",
    "Claude: not signed in": "Claude: nicht angemeldet",
    "Claude: signed in ({key})": "Claude: angemeldet ({key})",
    "Git ({host}): not signed in": "Git ({host}): nicht angemeldet",
    "Git ({host}): signed in as {user}": "Git ({host}): angemeldet als {user}",
    "Git: add a paper first": "Git: zuerst ein Paper hinzufügen",
    "Git: no sign-in needed (local or SSH)": "Git: keine Anmeldung nötig (lokal oder SSH)",
    "Shared to-do list ({host}): not signed in": "Gemeinsame To-do-Liste ({host}): nicht angemeldet",
    "Shared to-do list ({host}): signed in as {user}":
        "Gemeinsame To-do-Liste ({host}): angemeldet als {user}",
    "OpenAlex key: set": "OpenAlex-Schlüssel: gesetzt",
    "OpenAlex key: not set (optional)": "OpenAlex-Schlüssel: nicht gesetzt (optional)",
    "This token is used only for the shared to-do list.":
        "Dieses Token wird nur für die gemeinsame To-do-Liste verwendet.",
    "Update your Git credentials.": "Aktualisieren Sie Ihre Git-Zugangsdaten.",
    "Sign in to {host} to sync this paper.":
        "Melden Sie sich bei {host} an, um dieses Paper zu synchronisieren.",

    # -- to-do list ---------------------------------------------------------- #
    "Click ⟳ Refresh to load the shared to-do list.":
        "Auf '⟳ Aktualisieren' klicken, um die gemeinsame To-do-Liste zu laden.",
    "No tasks here.": "Keine To-dos hier.",
    "Local copy - not synced yet": "Lokale Kopie – noch nicht synchronisiert",
    "Syncing…": "Wird synchronisiert…",
    "The task text cannot be empty.": "Der Text des To-dos darf nicht leer sein.",
    "unassigned": "nicht zugewiesen",
    "There are no papers to move a list from.":
        "Es gibt keine Paper, aus denen eine Liste übernommen werden könnte.",
    "The shared to-do list is not set up yet - choose Options ▸ Shared to-do list… and paste the repository "
    "link.":
        "Die gemeinsame To-do-Liste ist noch nicht eingerichtet – wählen Sie Optionen ▸ Gemeinsame "
        "To-do-Liste… und fügen Sie den Link zum Repository ein.",
    "Sign in to {host} (Accounts menu) to use the shared to-do list.":
        "Melden Sie sich bei {host} an (Menü 'Konten'), um die gemeinsame To-do-Liste zu verwenden.",

    # -- backup --------------------------------------------------------------- #
    "A backup is already running.": "Es läuft bereits eine Sicherung.",
    "Set up the data backup first (Accounts menu).":
        "Richten Sie zuerst die Datensicherung ein (Menü 'Konten').",
    "Backup cancelled - nothing was copied.": "Sicherung abgebrochen – es wurde nichts kopiert.",
    "Starting…": "Wird gestartet…",
    "Stopping after the current file…": "Wird nach der aktuellen Datei beendet…",
    "Stopping after the current step…": "Wird nach dem aktuellen Schritt beendet…",
    "Signed out. Files already uploaded stay where they are.":
        "Abgemeldet. Bereits hochgeladene Dateien bleiben, wo sie sind.",
    "Asking Microsoft for a code…": "Code wird bei Microsoft angefordert…",
    "Waiting for you to finish signing in…": "Warten auf den Abschluss Ihrer Anmeldung…",

    # -- tools and updates ------------------------------------------------------ #
    "Git and MiKTeX": "Git und MiKTeX",
    "Git and MiKTeX are both installed.": "Git und MiKTeX sind beide installiert.",
    "Done. Restart the Research Assistant to use them.":
        "Fertig. Starten Sie den Forschungsassistenten neu, um sie zu verwenden.",
    "You can also do it later: Help ▸ Install Git / MiKTeX…":
        "Sie können das auch später tun: Hilfe ▸ Git / MiKTeX installieren…",
    "No log file yet.": "Noch keine Protokolldatei.",

    # -- language ---------------------------------------------------------------- #
    "Restart to change the language": "Für den Sprachwechsel neu starten",
    "The language changes when the app restarts.\n\nRestart now?":
        "Die Sprache ändert sich beim Neustart der Anwendung.\n\nJetzt neu starten?",
    "The language will change the next time you start the app.":
        "Die Sprache ändert sich beim nächsten Start der Anwendung.",

    # -- Accounts menu: the data backup line ------------------------------- #
    "Data backup: not set up (optional)": "Datensicherung: nicht eingerichtet (optional)",
    "Data backup: OneDrive folder {folder}": "Datensicherung: OneDrive-Ordner {folder}",
    "Data backup: signed in as {account}": "Datensicherung: angemeldet als {account}",
    "Data backup: signed in": "Datensicherung: angemeldet",
    "Data backup: set up, not signed in": "Datensicherung: eingerichtet, nicht angemeldet",
    "Change settings…": "Einstellungen ändern…",
    "Set up…": "Einrichten…",
}
