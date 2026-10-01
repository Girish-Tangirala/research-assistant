"""German: the errors about a paper's own content - sections, figures, results, PDFs.

The counterpart of :mod:`core.lang.de_errors`, which covers the services (Git, sign-in,
Claude, updates, OneDrive). Both hold the English templates raised in ``core``; see
:mod:`core.user_errors` for why the template and not the finished sentence.

Several of these come from modules that write into a paper
(:mod:`core.figures`, :mod:`core.results_latex`), which may never import the
translator - they carry the template and the GUI translates it.
"""

from __future__ import annotations

CATALOGUE: dict[str, str] = {
    # -- core/agent_engine.py (the agent's own tools) ------------------------ #
    "File not found: {file}": "Datei nicht gefunden: {file}",
    "Section '{section}' not found in {file}":
        "Abschnitt '{section}' wurde in {file} nicht gefunden",
    "Section '{section}' already exists - use edit_section instead":
        "Abschnitt '{section}' existiert bereits – verwenden Sie stattdessen 'edit_section'",
    "No staged changes.": "Keine vorbereiteten Änderungen.",
    "Model output was truncated (max_tokens). Increase AGENT_MAX_TOKENS.":
        "Die Antwort des Modells wurde abgeschnitten (max_tokens). Erhöhen Sie AGENT_MAX_TOKENS.",
    "Agent did not finish within {limit} steps (AGENT_MAX_STEPS).":
        "Der Agent war nach {limit} Schritten nicht fertig (AGENT_MAX_STEPS).",
    "The change adds LaTeX errors the paper did not have before - rolled back.\n{problems}":
        "Die Änderung fügt LaTeX-Fehler hinzu, die das Paper vorher nicht hatte – sie wurde "
        "zurückgenommen.\n{problems}",

    # -- core/asset_workflows.py (figures and references) -------------------- #
    "Choose at least one image to add.":
        "Wählen Sie mindestens ein Bild zum Hinzufügen aus.",
    "Choose the section the figures should go into.":
        "Wählen Sie den Abschnitt aus, in den die Abbildungen sollen.",
    "Enter at least one DOI, arXiv ID or title, or choose a .bib file.":
        "Geben Sie mindestens eine DOI, arXiv-ID oder einen Titel ein, oder wählen Sie eine "
        "'.bib'-Datei aus.",
    "The target file must be a .bib file.": "Die Zieldatei muss eine '.bib'-Datei sein.",
    "Not a .bib file: {file}": "Keine '.bib'-Datei: {file}",

    # -- core/citation_audit.py ---------------------------------------------- #
    "No .tex file with \\documentclass found under {folder}":
        "Unter {folder} wurde keine '.tex'-Datei mit \\documentclass gefunden",

    # -- core/figure_replace.py ---------------------------------------------- #
    "Choose exactly one new image for the figure.":
        "Wählen Sie genau ein neues Bild für die Abbildung aus.",
    "Choose the figure to replace - click it in the PDF preview or pick it from the list.":
        "Wählen Sie die zu ersetzende Abbildung aus – klicken Sie sie in der PDF-Vorschau an oder "
        "wählen Sie sie aus der Liste.",
    "{file} no longer exists - sync the paper and pick the figure again.":
        "{file} existiert nicht mehr – synchronisieren Sie das Paper und wählen Sie die Abbildung "
        "erneut aus.",
    "The figure ({figure}) was not found in {file} - the paper may have changed. Recompile the preview "
    "and click the figure again.":
        "Die Abbildung ({figure}) wurde in {file} nicht gefunden – das Paper hat sich möglicherweise "
        "geändert. Kompilieren Sie die Vorschau neu und klicken Sie die Abbildung erneut an.",

    # -- core/figures.py ----------------------------------------------------- #
    "{name}: {suffix} files cannot be included directly. {hint}":
        "{name}: '{suffix}'-Dateien können nicht direkt eingebunden werden. {hint}",
    "{name}: unsupported image type {suffix} - use PNG, JPG or PDF.":
        "{name}: nicht unterstützter Bildtyp {suffix} – verwenden Sie PNG, JPG oder PDF.",
    "{name} is {size} MB - Overleaf accepts files up to {limit} MB.":
        "{name} ist {size} MB groß – Overleaf nimmt Dateien bis {limit} MB an.",
    "Could not find a free file name for {name}":
        "Für {name} wurde kein freier Dateiname gefunden",
    "Pillow is required to convert images (pip install pillow).":
        "Zum Umwandeln von Bildern wird Pillow benötigt (pip install pillow).",
    "Could not find the preamble to add \\usepackage for {package}.":
        "Die Präambel zum Ergänzen von \\usepackage für {package} wurde nicht gefunden.",
    "Section '{section}' not found": "Abschnitt '{section}' wurde nicht gefunden",

    # -- core/literature.py --------------------------------------------------- #
    "Search query must not be empty.": "Die Suchanfrage darf nicht leer sein.",
    "Unknown source '{source}'; use one of {known}.":
        "Unbekannte Quelle '{source}'; verwenden Sie eine von {known}.",
    "Could not resolve '{identifier}' (expected a DOI, arXiv id or OpenAlex id).":
        "'{identifier}' konnte nicht aufgelöst werden (erwartet wurde eine DOI, arXiv-ID oder "
        "OpenAlex-ID).",
    "{host} rate limit or daily budget reached (HTTP 429).{extra}":
        "Bei {host} ist die Anfragerate oder das Tagesbudget erreicht (HTTP 429).{extra}",
    "Not found at {host}.": "Bei {host} nicht gefunden.",
    "{host} returned HTTP {status}.": "{host} hat HTTP {status} zurückgegeben.",
    "Network error contacting {host}: {problem}":
        "Netzwerkfehler bei der Verbindung zu {host}: {problem}",
    "Unexpected response from {host}": "Unerwartete Antwort von {host}",
    "Unexpected response from arXiv": "Unerwartete Antwort von arXiv",

    # -- core/literature_summary.py ------------------------------------------- #
    "Choose a PDF or enter a DOI, arXiv id or link of the paper to summarise.":
        "Wählen Sie ein PDF aus oder geben Sie DOI, arXiv-ID oder Link des zusammenzufassenden "
        "Papers ein.",
    "That is {count} papers; summarise at most {limit} at a time so one run stays quick and affordable.":
        "Das sind {count} Paper; fassen Sie höchstens {limit} auf einmal zusammen, damit ein Durchlauf "
        "schnell und günstig bleibt.",

    # -- core/paper.py -------------------------------------------------------- #
    "No main .tex file (with \\documentclass) in {folder}":
        "Keine Haupt-'.tex'-Datei (mit \\documentclass) in {folder}",
    "Path escapes the repository: {file}": "Der Pfad führt aus dem Repository heraus: {file}",
    "Access to .git is not allowed": "Der Zugriff auf '.git' ist nicht erlaubt",
    "{file} already exists - choose another name.":
        "{file} existiert bereits – wählen Sie einen anderen Namen.",
    "{file} changed on disk since it was read - aborting.":
        "{file} hat sich auf dem Datenträger geändert, seit sie gelesen wurde – Abbruch.",
    "{file} is no longer there - sync the paper and try again.":
        "{file} ist nicht mehr vorhanden – synchronisieren Sie das Paper und versuchen Sie es erneut.",
    "{file} already exists - aborting.": "{file} existiert bereits – Abbruch.",

    # -- core/pdf_text.py ------------------------------------------------------ #
    "{file} is not a file.": "{file} ist keine Datei.",
    "{name}: only PDF files can be summarised from your computer.":
        "{name}: Von Ihrem Computer können nur PDF-Dateien zusammengefasst werden.",
    "{name} is {size} MB - too large to read (limit {limit} MB).":
        "{name} ist {size} MB groß – zu groß zum Lesen (Grenze {limit} MB).",
    "Reading PDFs needs the pypdfium2 package.":
        "Zum Lesen von PDFs wird das Paket pypdfium2 benötigt.",
    "{name} could not be read: {problem}": "{name} konnte nicht gelesen werden: {problem}",
    "{name} has almost no text to read ({count} characters). It is probably a scan of the printed pages; "
    "a PDF with real text is needed, or use the paper's DOI instead.":
        "{name} enthält fast keinen lesbaren Text ({count} Zeichen). Wahrscheinlich ist es ein Scan der "
        "gedruckten Seiten; es wird ein PDF mit echtem Text benötigt – oder verwenden Sie stattdessen "
        "die DOI des Papers.",

    # -- core/results_data.py --------------------------------------------------- #
    "{table}: no column named '{column}' (it has {columns})":
        "{table}: keine Spalte mit dem Namen '{column}' (vorhanden sind {columns})",
    "{name} has no rows.": "{name} enthält keine Zeilen.",
    "{name} has no table of results: expected columns of values separated by commas, semicolons or tabs.":
        "{name} enthält keine Ergebnistabelle: erwartet wurden Wertespalten, die durch Kommas, "
        "Semikolons oder Tabulatoren getrennt sind.",
    "{name} has no sheet with a header row and data.":
        "{name} enthält kein Tabellenblatt mit Kopfzeile und Daten.",
    "{name} is not valid JSON ({problem}, line {line}).":
        "{name} ist kein gültiges JSON ({problem}, Zeile {line}).",
    "{name}: no table of numbers found. Expected a history (a loss/accuracy list), a list of records or "
    "one object per model.":
        "{name}: keine Zahlentabelle gefunden. Erwartet wurde ein Trainingsverlauf (eine Liste von "
        "Loss-/Accuracy-Werten), eine Liste von Datensätzen oder ein Objekt pro Modell.",
    "{name}: no classification report, confusion matrix or table of columns found.":
        "{name}: kein 'classification report', keine Konfusionsmatrix und keine Spaltentabelle "
        "gefunden.",
    "{name} is {size} MB - too large to read (limit {limit} MB). Export the summary you want to plot.":
        "{name} ist {size} MB groß – zu groß zum Lesen (Grenze {limit} MB). Exportieren Sie die "
        "Zusammenfassung, die Sie darstellen möchten.",
    "{name}: {kind} is not supported (supported: {known}).":
        "{name}: {kind} wird nicht unterstützt (unterstützt werden: {known}).",
    "Reading .xlsx files needs the openpyxl package (pip install openpyxl). Save the sheet as CSV "
    "instead.":
        "Zum Lesen von '.xlsx'-Dateien wird das Paket openpyxl benötigt (pip install openpyxl). "
        "Speichern Sie das Tabellenblatt stattdessen als CSV.",

    # -- core/results_latex.py --------------------------------------------------- #
    "Column '{column}' has no numeric values to plot.":
        "Die Spalte '{column}' enthält keine Zahlenwerte zum Darstellen.",
    "A confusion matrix needs as many rows as plotted columns ({rows} rows, {columns} columns).":
        "Eine Konfusionsmatrix braucht so viele Zeilen wie dargestellte Spalten ({rows} Zeilen, "
        "{columns} Spalten).",
    "{count} classes do not fit in a readable matrix (limit {limit}); plot a table instead.":
        "{count} Klassen passen nicht in eine lesbare Matrix (Grenze {limit}); stellen Sie "
        "stattdessen eine Tabelle dar.",
    "The matrix cell in row {row}, column '{column}' is not a number.":
        "Die Matrixzelle in Zeile {row}, Spalte '{column}' ist keine Zahl.",

    # -- core/results_workflow.py ------------------------------------------------ #
    "Choose the results file(s) or folder to read.":
        "Wählen Sie die Ergebnisdatei(en) oder den Ordner zum Einlesen aus.",
    "Choose the section the figure should go into.":
        "Wählen Sie den Abschnitt aus, in den die Abbildung soll.",
    "The chart could not be drawn: {problem}":
        "Die Grafik konnte nicht gezeichnet werden: {problem}",

    # -- core/source_map.py (clicking in the PDF) -------------------------------- #
    "This PDF was built before click-to-edit existed - click Recompile once.":
        "Dieses PDF wurde erzeugt, bevor es den Klick zum Bearbeiten gab – klicken Sie einmal auf "
        "'Neu kompilieren'.",
    "Nothing to edit there - click on text or a figure.":
        "Dort gibt es nichts zu bearbeiten – klicken Sie auf Text oder eine Abbildung.",
    "That text comes from {name}, which is not part of the paper (e.g. a package or class file).":
        "Dieser Text stammt aus {name} und gehört nicht zum Paper (z. B. eine Paket- oder "
        "Klassendatei).",

    # -- core/workflows.py -------------------------------------------------------- #
    "Section '{section}' not found in any .tex file of the paper":
        "Abschnitt '{section}' wurde in keiner '.tex'-Datei des Papers gefunden",
    "Please specify the section title to edit.":
        "Geben Sie den Titel des zu überarbeitenden Abschnitts an.",
    "Please describe the task for the agent.":
        "Beschreiben Sie die Aufgabe für den Agenten.",
    "LLM output could not be validated after repeated attempts; nothing was changed.":
        "Die Antwort des Modells konnte auch nach mehreren Versuchen nicht geprüft werden; es wurde "
        "nichts geändert.",
    "LLM output truncated - increase AGENT_MAX_TOKENS.":
        "Die Antwort des Modells wurde abgeschnitten – erhöhen Sie AGENT_MAX_TOKENS.",
    "This paper is only on this computer. Add its Overleaf project link with Edit paper, then press Sync "
    "again.":
        "Dieses Paper liegt nur auf diesem Computer. Ergänzen Sie den Link zum Overleaf-Projekt über "
        "'Paper bearbeiten' und drücken Sie dann erneut auf 'Synchronisieren'.",
}
