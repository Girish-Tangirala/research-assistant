"""German: the chrome of the dialog windows - titles, headings, intro texts, buttons.

:class:`gui.dialogs._Dialog` translates its own ``title``, ``heading``, ``text`` and
primary button, so a dialog hands in plain English and the entry it needs lives here.
Nothing looked these up until the German errors were added, which left the setup window, the
sign-in windows and the update window entirely English in a German app.
"""

from __future__ import annotations

CATALOGUE: dict[str, str] = {
    # -- first start: installing Git and MiKTeX ---------------------------- #
    "Set up the Research Assistant": "Forschungsassistent einrichten",
    "A helper program is needed": "Ein Hilfsprogramm wird benötigt",
    "Two helper programs are needed": "Zwei Hilfsprogramme werden benötigt",
    "MiKTeX (builds the PDF of your paper)": "MiKTeX (erzeugt das PDF Ihres Papers)",
    "The Research Assistant installs them for you - only for your Windows account, without administrator "
    "rights, from their official websites (each download is checked against its published checksum). This "
    "takes a few minutes, mostly for MiKTeX (about 140 MB) and Git (about 60 MB).":
        "Der Forschungsassistent installiert sie für Sie – nur für Ihr Windows-Konto, ohne "
        "Administratorrechte, von den offiziellen Websites (jeder Download wird gegen die "
        "veröffentlichte Prüfsumme geprüft). Das dauert einige Minuten, vor allem für MiKTeX "
        "(etwa 140 MB) und Git (etwa 60 MB).",
    "Install now": "Jetzt installieren",

    # -- sign-in: Claude, Git hosts, OpenAlex ------------------------------ #
    "Paste your Anthropic API key. It is stored in the system credential vault and reused until you sign "
    "out or it stops working.":
        "Fügen Sie Ihren Anthropic-API-Schlüssel ein. Er wird im Anmeldeinformationsspeicher des Systems "
        "abgelegt und weiterverwendet, bis Sie sich abmelden oder er nicht mehr funktioniert.",
    "Create or copy a key at console.anthropic.com →":
        "Schlüssel auf console.anthropic.com anlegen oder kopieren →",
    "Sign in to Git": "Bei Git anmelden",
    "Sign in to {host}": "Bei {host} anmelden",
    "The token is stored in the system credential vault and sent only to this host.":
        "Das Token wird im Anmeldeinformationsspeicher des Systems abgelegt und nur an diesen Anbieter "
        "gesendet.",
    "Create a personal access token with read/write access to repositories on this host.":
        "Erstellen Sie ein persönliches Zugriffstoken mit Lese- und Schreibrechten für Repositorys bei "
        "diesem Anbieter.",
    "Overleaf → Account Settings → Git integration → Generate token. Username: git":
        "Overleaf → 'Account Settings' → 'Git integration' → 'Generate token'. Benutzername: git",
    "GitHub → Settings → Developer settings → Fine-grained token with Contents: Read and write.":
        "GitHub → 'Settings' → 'Developer settings' → feingranulares Token mit 'Contents: Read and write'.",
    "GitLab → Preferences → Access tokens (read_repository + write_repository). Username: oauth2":
        "GitLab → 'Preferences' → 'Access tokens' (read_repository + write_repository). "
        "Benutzername: oauth2",
    "Checking repository access…": "Zugriff auf das Repository wird geprüft…",
    "Saving…": "Wird gespeichert…",
    "OpenAlex API key": "OpenAlex-API-Schlüssel",
    "OpenAlex API key (optional)": "OpenAlex-API-Schlüssel (optional)",
    "Literature search works without a key, but a free key raises the daily OpenAlex budget 10×.":
        "Die Literatursuche funktioniert auch ohne Schlüssel; ein kostenloser Schlüssel erhöht das "
        "tägliche OpenAlex-Budget auf das Zehnfache.",
    "Get a free key at openalex.org/settings/api →":
        "Kostenlosen Schlüssel auf openalex.org/settings/api holen →",

    # -- paper dialog ------------------------------------------------------ #
    "Detected: {names}": "Erkannt: {names}",

    # -- approval and sending ---------------------------------------------- #
    "Review change – {file}": "Änderung prüfen – {file}",
    "Send changes?": "Änderungen senden?",
    # The four button labels of the send dialog are arguments, not literals at a
    # t() call, so only the dialog test in tests/test_gui_smoke.py guards them.
    "Push": "Senden",
    "Discard": "Verwerfen",
    "Sync now": "Jetzt synchronisieren",
    "Not now": "Jetzt nicht",
    "The approved changes are committed locally and compiled - check the PDF preview. Push sends them to "
    "your collaborators; Discard throws them away.":
        "Die genehmigten Änderungen sind lokal übernommen und kompiliert – prüfen Sie die PDF-Vorschau. "
        "'Senden' schickt sie an Ihre Mitautoren, 'Verwerfen' wirft sie weg.",

    # -- the .tex editor ---------------------------------------------------- #
    "Save your changes to {file} before closing?":
        "Ihre Änderungen an {file} vor dem Schließen speichern?",
    "Save your changes to {file}?": "Ihre Änderungen an {file} speichern?",

    # -- a task that stopped ------------------------------------------------ #
    "Anything it had not finished was undone. The full details are in the Live Log (Agent tasks).":
        "Alles, was nicht abgeschlossen wurde, ist zurückgenommen worden. Die vollständigen Angaben "
        "stehen im Live-Protokoll (Agent-Aufgaben).",

    # -- to-do list --------------------------------------------------------- #
    "Created by {who} on {when}.": "Erstellt von {who} am {when}.",
    "unknown": "unbekannt",
    "optional": "optional",
    "leave empty for the default": "leer lassen für den Standard",

    # -- OneDrive backup ---------------------------------------------------- #
    "Copies the folders that never go to Overleaf (data/, supplementary/) into OneDrive, keeping the same "
    "structure, so they have a second copy. Uploads only: nothing already in OneDrive is renamed or deleted.":
        "Kopiert die Ordner, die nie zu Overleaf gelangen (data/, supplementary/), in derselben Struktur "
        "nach OneDrive, damit sie eine zweite Kopie haben. Nur hochladen: Was bereits in OneDrive liegt, "
        "wird weder umbenannt noch gelöscht.",
    "Backing up data": "Daten werden gesichert",
    "Sign in to Microsoft 365": "Bei Microsoft 365 anmelden",
    "A browser page will ask for the code below. Only a sign-in token is stored, in the system credential "
    "vault - never your password.":
        "Eine Browser-Seite fragt den unten stehenden Code ab. Gespeichert wird nur ein Anmeldetoken, im "
        "Anmeldeinformationsspeicher des Systems – niemals Ihr Passwort.",
    "Open the sign-in page": "Anmeldeseite öffnen",

    # -- updates ------------------------------------------------------------ #
    "Updates": "Updates",
    "Update available": "Update verfügbar",
    "Version {version} is available": "Version {version} ist verfügbar",
    "You have version {current}. Your papers, settings and sign-ins are kept.":
        "Sie haben Version {current}. Ihre Paper, Einstellungen und Anmeldungen bleiben erhalten.",
    "What's new:": "Neu in dieser Version:",
    "Update now": "Jetzt aktualisieren",
    "Open release page": "Release-Seite öffnen",
    "You are running the app from its source code - update it with Git (git pull) instead.":
        "Sie führen die App aus dem Quellcode aus – aktualisieren Sie sie stattdessen mit Git (git pull).",
    "Update not installed: the app was not closed. It is downloaded; choose Update now again.":
        "Update nicht installiert: Die App wurde nicht geschlossen. Es ist heruntergeladen – wählen Sie "
        "erneut 'Jetzt aktualisieren'.",

    # -- forms -------------------------------------------------------------- #
    "e.g. 2018": "z. B. 2018",

    # -- error lines the GUI itself writes ---------------------------------- #
    "Your saved credentials were rejected. Sign in again, then re-run the workflow.":
        "Ihre gespeicherten Anmeldedaten wurden abgelehnt. Melden Sie sich erneut an und starten Sie "
        "die Aufgabe danach noch einmal.",
    "Could not map the click: {problem}":
        "Der Klick konnte nicht zugeordnet werden: {problem}",
    "Preview compile failed: {problem}":
        "Das Kompilieren der Vorschau ist fehlgeschlagen: {problem}",
    "not installed - {problem}": "nicht installiert – {problem}",
    "Saved {file}, but not committed: {problem}":
        "{file} wurde gespeichert, aber nicht übernommen: {problem}",
    "Failed - see the Live Log.": "Fehlgeschlagen – siehe Live-Protokoll.",
    "Not synced: {problem}": "Nicht synchronisiert: {problem}",

    "Try again": "Erneut versuchen",
    "You will need a sign-in for {host} under Accounts, with permission to read and write this "
    "repository.":
        "Sie brauchen unter 'Konten' eine Anmeldung für {host} mit Lese- und Schreibrechten für dieses "
        "Repository.",
}
