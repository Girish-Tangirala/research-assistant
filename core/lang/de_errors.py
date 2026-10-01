"""German: the errors the services raise - Git, sign-in, Claude, updates, OneDrive.

These are the English templates raised in ``core`` (see :mod:`core.user_errors`), not
``t()`` calls: ``str(exc)`` stays English for the log, the model's tool results and the
saved reports, while the dialog shows :func:`core.i18n.translated`.
``test_every_error_message_core_raises_has_german`` lists anything missing here.

The errors about a paper's own content - figures, results, sections, PDFs, literature -
are in :mod:`core.lang.de_content`.
"""

from __future__ import annotations

CATALOGUE: dict[str, str] = {
    # -- core/compiler.py ---------------------------------------------------- #
    "No LaTeX compiler was found (install MiKTeX or TeX Live, or set PDFLATEX_PATH).":
        "Es wurde kein LaTeX-Compiler gefunden (installieren Sie MiKTeX oder TeX Live oder setzen Sie "
        "PDFLATEX_PATH).",
    "This paper needs {engine}, which was not found.":
        "Dieses Paper benötigt {engine}; das Programm wurde nicht gefunden.",
    "Compiler executable not found: {program}": "Compiler-Programm nicht gefunden: {program}",

    # -- core/credentials.py ------------------------------------------------- #
    "Please enter an API key.": "Bitte geben Sie einen API-Schlüssel ein.",
    "This API key was rejected. Check that it was copied completely.":
        "Dieser API-Schlüssel wurde abgelehnt. Prüfen Sie, ob er vollständig kopiert wurde.",
    "The key is valid but lacks permission: {problem}":
        "Der Schlüssel ist gültig, hat aber keine Berechtigung: {problem}",
    "The key works, but model '{model}' is not available to it.":
        "Der Schlüssel funktioniert, aber das Modell '{model}' ist für ihn nicht verfügbar.",
    "Could not reach the Claude API - check your internet connection.":
        "Die Claude-API ist nicht erreichbar – prüfen Sie Ihre Internetverbindung.",
    "Claude API error {status}: {problem}": "Claude-API-Fehler {status}: {problem}",
    "git is not installed or not on PATH.": "Git ist nicht installiert oder nicht im PATH.",
    "Timed out contacting {host}.": "Zeitüberschreitung bei der Verbindung zu {host}.",
    "{host} rejected these credentials.\n{detail}":
        "{host} hat diese Anmeldedaten abgelehnt.\n{detail}",
    "Could not access the repository:\n{detail}":
        "Auf das Repository konnte nicht zugegriffen werden:\n{detail}",
    "OpenAlex rejected this API key.": "OpenAlex hat diesen API-Schlüssel abgelehnt.",
    "OpenAlex returned HTTP {status}.": "OpenAlex hat HTTP {status} zurückgegeben.",
    "Could not reach OpenAlex: {problem}": "OpenAlex ist nicht erreichbar: {problem}",
    "Could not read from the credential vault: {problem}":
        "Aus dem Anmeldeinformationsspeicher konnte nicht gelesen werden: {problem}",
    "Could not save to the credential vault: {problem}":
        "Im Anmeldeinformationsspeicher konnte nicht gespeichert werden: {problem}",
    "Could not delete from the credential vault: {problem}":
        "Aus dem Anmeldeinformationsspeicher konnte nicht gelöscht werden: {problem}",

    # -- core/dependencies.py (first start: Git and MiKTeX) ------------------ #
    "Download cancelled.": "Download abgebrochen.",
    "No published checksum for {name} - not downloading it.":
        "Für {name} ist keine Prüfsumme veröffentlicht – die Datei wird nicht heruntergeladen.",
    "{name} does not match its published checksum - it was deleted and not run. Try again later.":
        "{name} stimmt nicht mit der veröffentlichten Prüfsumme überein – die Datei wurde gelöscht und "
        "nicht ausgeführt. Versuchen Sie es später erneut.",
    "The latest Git for Windows release has no PortableGit for {arch}.":
        "Die neueste Version von Git für Windows enthält kein PortableGit für {arch}.",
    "The MiKTeX download page has changed - install MiKTeX from {page} instead.":
        "Die MiKTeX-Downloadseite hat sich geändert – installieren Sie MiKTeX stattdessen von {page}.",
    "The folder {folder} has too long a path for Git's files.":
        "Der Pfad des Ordners {folder} ist für die Dateien von Git zu lang.",
    "Unpacking Git failed (exit {code}).": "Das Entpacken von Git ist fehlgeschlagen (Code {code}).",
    "The MiKTeX installer stopped with exit code {code}.":
        "Das MiKTeX-Installationsprogramm wurde mit dem Code {code} beendet.",

    # -- core/events.py ------------------------------------------------------ #
    "Workflow cancelled by user": "Aufgabe von der Benutzerin oder dem Benutzer abgebrochen",

    # -- core/git_manager.py ------------------------------------------------- #
    "Nothing to commit": "Nichts zu übernehmen",
    "Staged files are identical to HEAD - nothing to commit":
        "Die vorbereiteten Dateien sind mit HEAD identisch – es gibt nichts zu übernehmen",
    "No remote named '{remote}'": "Kein Remote mit dem Namen '{remote}'",
    "Repository is in detached-HEAD state": "Das Repository ist im Zustand 'detached HEAD'",
    "Refusing to undo a commit the app did not just create.":
        "Ein Commit, den die App nicht gerade selbst erstellt hat, wird nicht zurückgenommen.",
    "Refusing to clone into non-empty directory {folder}":
        "In den nicht leeren Ordner {folder} wird nicht geklont",
    "{folder} is not a Git repository": "{folder} ist kein Git-Repository",
    "{folder} is not a Git repository and no remote URL was provided":
        "{folder} ist kein Git-Repository, und es wurde keine Remote-URL angegeben",
    "{folder} has uncommitted changes; commit or stash them before syncing":
        "In {folder} gibt es nicht übernommene Änderungen; übernehmen oder verwerfen Sie sie vor dem "
        "Synchronisieren",
    "{folder} contains a .git folder that is not a working repository. Delete that folder (or choose "
    "another one) and try again.":
        "{folder} enthält einen '.git'-Ordner, der kein funktionierendes Repository ist. Löschen Sie "
        "diesen Ordner (oder wählen Sie einen anderen) und versuchen Sie es erneut.",
    "Your approved changes conflict with edits made on the remote since the last sync. They are kept on "
    "local branch '{branch}'; sync the paper and run the workflow again.\n{detail}":
        "Ihre genehmigten Änderungen stehen im Konflikt mit Änderungen, die seit dem letzten "
        "Synchronisieren auf dem Remote gemacht wurden. Sie bleiben im lokalen Branch '{branch}' "
        "erhalten; synchronisieren Sie das Paper und führen Sie die Aufgabe erneut aus.\n{detail}",

    # -- core/git_sync.py ---------------------------------------------------- #
    "This paper has no Overleaf (or Git) link yet - add one with Edit paper.":
        "Dieses Paper hat noch keinen Overleaf- (oder Git-)Link – ergänzen Sie ihn über "
        "'Paper bearbeiten'.",
    "There are uncommitted changes in the paper folder; the app commits its own edits, so commit or undo "
    "the others before syncing.":
        "Im Paper-Ordner gibt es nicht übernommene Änderungen. Die App übernimmt ihre eigenen "
        "Bearbeitungen selbst – übernehmen oder verwerfen Sie die übrigen vor dem Synchronisieren.",
    "This paper and the {host} project were started separately, so they have nothing in common - merging "
    "them automatically would be guesswork. Nothing was sent.\nEither link the paper to a brand-new "
    "(empty) Overleaf project, or add this paper again from the Overleaf project link and copy your files "
    "into that folder.":
        "Dieses Paper und das Projekt bei {host} wurden getrennt voneinander begonnen und haben daher "
        "keine gemeinsame Grundlage – sie automatisch zusammenzuführen wäre geraten. Es wurde nichts "
        "gesendet.\nVerknüpfen Sie das Paper entweder mit einem völlig neuen (leeren) Overleaf-Projekt, "
        "oder fügen Sie dieses Paper erneut über den Link des Overleaf-Projekts hinzu und kopieren Sie "
        "Ihre Dateien in diesen Ordner.",

    # -- core/llm_client.py -------------------------------------------------- #
    "Not signed in to Claude. Use Accounts → Claude to sign in.":
        "Nicht bei Claude angemeldet. Melden Sie sich über 'Konten → Claude' an.",
    "Claude rejected the stored API key. Sign in again via Accounts → Claude.":
        "Claude hat den gespeicherten API-Schlüssel abgelehnt. Melden Sie sich über 'Konten → Claude' "
        "erneut an.",
    "Claude API permission denied: {problem}": "Claude-API: Zugriff verweigert: {problem}",
    "Model '{model}' not found or not enabled for this key.":
        "Das Modell '{model}' wurde nicht gefunden oder ist für diesen Schlüssel nicht freigegeben.",
    "Rate limited by the Claude API (retry after {seconds}s).":
        "Die Claude-API hat die Anfragerate begrenzt (erneut versuchen in {seconds} s).",
    "Claude API rejected the request: {problem}{hint}":
        "Die Claude-API hat die Anfrage abgelehnt: {problem}{hint}",
    "Claude API error {status}: {problem} (request id: {request})":
        "Claude-API-Fehler {status}: {problem} (Anfrage-ID: {request})",
    "Could not reach the Claude API - check your network connection.":
        "Die Claude-API ist nicht erreichbar – prüfen Sie Ihre Netzwerkverbindung.",
    "The model declined this request (category: {category}).":
        "Das Modell hat diese Anfrage abgelehnt (Kategorie: {category}).",

    # -- core/sharepoint_folder.py (the OneDrive backup) --------------------- #
    "{folder} does not exist. Open OneDrive, make sure that folder is synced to this computer, then "
    "choose it again.":
        "{folder} existiert nicht. Öffnen Sie OneDrive, stellen Sie sicher, dass dieser Ordner auf "
        "diesen Computer synchronisiert wird, und wählen Sie ihn dann erneut aus.",
    "{folder} is a file, not a folder.": "{folder} ist eine Datei, kein Ordner.",
    "{folder} cannot be written to. Check your access to the library.":
        "In {folder} kann nicht geschrieben werden. Prüfen Sie Ihre Zugriffsrechte auf die Bibliothek.",
    "'{file}' is outside the library folder.":
        "'{file}' liegt außerhalb des Bibliotheksordners.",
    "Could not create '{folder}' in the library folder: {problem}":
        "'{folder}' konnte im Bibliotheksordner nicht angelegt werden: {problem}",
    "Could not copy {name} into the library folder: {problem}":
        "{name} konnte nicht in den Bibliotheksordner kopiert werden: {problem}",

    # -- core/todos.py ------------------------------------------------------- #
    "Enter the task text.": "Geben Sie den Text des To-dos ein.",
    "The task text cannot be empty.": "Der Text des To-dos darf nicht leer sein.",
    "This task no longer exists - someone may have deleted it.":
        "Dieses To-do existiert nicht mehr – möglicherweise hat es jemand gelöscht.",
    "Could not save the to-do change.": "Die To-do-Änderung konnte nicht gespeichert werden.",
    "Due date must look like 2026-10-01, got '{value}'.":
        "Das Fälligkeitsdatum muss die Form 2026-10-01 haben, erhalten wurde '{value}'.",

    # -- core/updater.py ----------------------------------------------------- #
    "Could not reach GitHub to check for updates ({problem}).":
        "GitHub ist für die Update-Prüfung nicht erreichbar ({problem}).",
    "Release {version} has no checksum for {name} - not installing it.":
        "Die Veröffentlichung {version} enthält keine Prüfsumme für {name} – sie wird nicht "
        "installiert.",
    "Release {version} has no Windows app attached.":
        "Der Veröffentlichung {version} ist keine Windows-App beigefügt.",
    "The app's folder {folder} is not writable - move the Research Assistant folder to e.g. Documents "
    "and update again.":
        "Der App-Ordner {folder} ist nicht beschreibbar – verschieben Sie den Ordner des "
        "Forschungsassistenten z. B. nach 'Dokumente' und aktualisieren Sie erneut.",
    "Unexpected file in the update: {file}": "Unerwartete Datei im Update: {file}",
    "The update does not contain {name}.": "Das Update enthält {name} nicht.",
}
