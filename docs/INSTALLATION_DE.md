# Forschungsassistent – Einrichtung Schritt für Schritt

Diese Anleitung führt Sie von der Download-Seite auf GitHub bis zum ersten fertigen PDF. Sie ist für einen
neuen Computer gedacht: **Sie brauchen keine Administratorrechte**, und Git und MiKTeX installiert die App
selbst.

Rechnen Sie mit **20 bis 30 Minuten**, davon die meiste Zeit Wartezeit beim Herunterladen.

> Der vollständige Funktionsüberblick steht in `USER_GUIDE.md` (englisch) im selben Ordner – dort finden Sie
> jede Aufgabe des Agenten im Detail. Diese Datei beschränkt sich auf die Einrichtung.

---

## Übersicht

| Schritt | Was | Dauer |
|---|---|---|
| 1 | Zip-Datei von der GitHub-Release-Seite herunterladen | 2 Min. |
| 2 | Entpacken und zum ersten Mal starten | 2 Min. |
| 3 | Git und MiKTeX installieren lassen (einmalig) | 10–20 Min. |
| 4 | Oberfläche auf Deutsch stellen | 1 Min. |
| 5 | Anmelden: Claude-Schlüssel und Overleaf-Token | 10 Min. |
| 6 | Erstes Paper hinzufügen | 3 Min. |
| 7 | Prüfen, ob alles funktioniert | 3 Min. |

Danach optional: die gemeinsame To-do-Liste und die Datensicherung in OneDrive.

Was Sie **vorher** besorgen sollten, weil es jeweils ein eigenes Konto braucht:

- einen **eigenen Anthropic-API-Schlüssel** (für die KI-Aufgaben) – siehe Schritt 5a;
- ein **Overleaf-Token** (um ein Paper mit Overleaf zu verbinden) – siehe Schritt 5b;
  dafür wird ein Overleaf-Premium-Zugang benötigt, Ihrer oder der der Projektinhaberin bzw. des
  Projektinhabers.

Zum Schreiben, Kompilieren und Synchronisieren ist **kein** Claude-Schlüssel nötig – nur für die
Agent-Aufgaben.

---

## Schritt 1 – Die Zip-Datei von GitHub herunterladen

1. Öffnen Sie im Browser:

   **<https://github.com/Girish-Tangirala/research-assistant/releases>**

2. Oben steht die neueste Version, gekennzeichnet mit **Latest** (zum Beispiel *v1.5.1*). Nehmen Sie immer
   diese, nicht eine ältere weiter unten.
3. Klappen Sie unter der Versionsbeschreibung den Abschnitt **Assets** auf, falls er zugeklappt ist.
4. Klicken Sie auf die Datei

   **`ResearchAssistant-windows-<Version>.zip`**  (ungefähr 38 MB)

   Das ist die Datei zum Benutzen. Die Datei mit `source` im Namen ist der Quellcode und wird nur gebraucht,
   wenn Sie die App selbst verändern wollen; `Source code (zip)` erzeugt GitHub automatisch – ignorieren Sie
   beide.
5. Der Browser lädt die Datei nach `Downloads`. Kein GitHub-Konto nötig: das Repository ist öffentlich.

> **Falls Edge oder Chrome warnt** („wird nicht häufig heruntergeladen“): Das liegt daran, dass die Datei
> neu und nicht von einem großen Hersteller signiert ist. Wählen Sie **Beibehalten** bzw. **Behalten**.
> Wenn Sie unsicher sind, fragen Sie vorher nach.

## Schritt 2 – Entpacken und starten

1. Öffnen Sie den Ordner `Downloads` im Explorer.
2. **Rechtsklick** auf die Zip-Datei → **Alle extrahieren…**
3. Wählen Sie als Ziel einen Ordner, in dem Sie schreiben dürfen, zum Beispiel

   `C:\Users\<Ihr Name>\Documents\ResearchAssistant`

   **Nicht** nach `C:\Program Files` – dort darf die App sich später nicht selbst aktualisieren.
4. **Lassen Sie den Ordner zusammen.** Neben `ResearchAssistant.exe` liegt ein Ordner `_internal`; ohne ihn
   startet die App nicht. Verschieben Sie also immer den ganzen Ordner, nie nur die `.exe`.
5. Doppelklick auf **`ResearchAssistant.exe`**.
6. Beim ersten Start meldet sich meist **„Der Computer wurde durch Windows geschützt“** (SmartScreen).
   Das kommt daher, dass die App kein kostenpflichtiges Signaturzertifikat hat. Klicken Sie auf
   **Weitere Informationen** und dann auf **Trotzdem ausführen**.
7. Nützlich: Rechtsklick auf die `.exe` → **Weitere Optionen anzeigen** → **Senden an → Desktop
   (Verknüpfung erstellen)**.

## Schritt 3 – Git und MiKTeX installieren lassen (einmalig)

Die App braucht zwei Hilfsprogramme: **Git** für die Versionsgeschichte Ihrer Paper und die Verbindung zu
Overleaf, und **MiKTeX**, um das PDF zu erzeugen. Fehlt eines davon, öffnet sich beim Start automatisch das
Fenster **„Forschungsassistent einrichten“**.

1. Klicken Sie auf **Jetzt installieren**.
2. Warten Sie. Es werden etwa **200 MB** geladen (MiKTeX ca. 140 MB, Git ca. 60 MB). Je Programm steht eine
   Zeile im Fenster, und der Fortschrittsbalken zeigt den Stand. Zwischendurch kann ein eigenes
   MiKTeX-Installationsfenster erscheinen – das ist normal, lassen Sie es durchlaufen.
3. Klicken Sie am Ende auf **Jetzt neu starten**. Die App startet sich selbst neu und findet die beiden
   Programme dann.

Gut zu wissen:

- Beide kommen von ihren **offiziellen Websites**, und jeder Download wird gegen die dort veröffentlichte
  **Prüfsumme (SHA-256)** geprüft. Stimmt sie nicht, wird die Datei gelöscht und nicht ausgeführt.
- Installiert wird **nur für Ihr Windows-Konto**, ohne Administratorrechte. Git landet im App-eigenen Ordner
  `%LOCALAPPDATA%\ResearchAssistant\tools`, MiKTeX normal in Ihrem Benutzerprofil.
- Übersprungen? Sie öffnen das Fenster jederzeit erneut über **Hilfe → Git / MiKTeX installieren…**
- Das **erste PDF** dauert etwas länger: MiKTeX lädt die LaTeX-Pakete Ihres Papers beim ersten Mal nach.
  Fragt MiKTeX, ob ein Paket installiert werden soll, bestätigen Sie mit **Install**.
- Blockiert Ihre IT das Installieren von Programmen, bitten Sie die IT, *Git for Windows* und *MiKTeX* zu
  installieren. Die App benutzt dann die vorhandene Installation.

## Schritt 4 – Oberfläche auf Deutsch stellen

1. In der Menüleiste oben: **Language → Deutsch**.
2. Die App fragt, ob sie neu starten darf – bestätigen Sie. Die Beschriftungen werden beim Öffnen des
   Fensters festgelegt, deshalb gilt die Sprache erst nach einem Neustart.

Danach heißen die Menüs **Datei, Konten, Optionen, Ansicht, Hilfe, Sprache**, und die Schaltflächen links
**Hinzufügen, Bearbeiten, Entfernen, Ordner, ⇄ Mit Overleaf synchronisieren, ☁ Daten sichern,
⟳ Aktualisieren**.

> **Ihre Paper bleiben immer englisch.** Die Sprache ändert nur die Oberfläche – nicht die Ordnerstruktur,
> nicht das LaTeX, nicht die Bildunterschriften und nichts, was der Assistent für Sie schreibt. Das ist
> Absicht: Sie veröffentlichen auf Englisch, und kein deutsches Wort soll versehentlich in ein Manuskript
> geraten.

## Schritt 5 – Anmelden

Die App fragt die Zugangsdaten, sobald sie sie zum ersten Mal braucht. Ändern können Sie sie jederzeit im
Menü **Konten**. Alles wird im **Windows-Anmeldeinformationsspeicher** gespeichert (Systemsteuerung →
Anmeldeinformationsverwaltung → Windows-Anmeldeinformationen) – nie im App-Ordner, nie in einer Datei, nie
im Protokoll.

### 5a – Eigener Claude-API-Schlüssel

Jede Person benutzt ihr **eigenes** Anthropic-Konto; abgerechnet wird pro Nutzung über dieses Konto.

1. Öffnen Sie **<https://console.anthropic.com>** und melden sich an oder legen ein Konto an.
2. Hinterlegen Sie unter *Billing* eine Zahlungsart oder Guthaben.
3. Gehen Sie auf *API keys* → **Create key**, kopieren Sie den Schlüssel (er beginnt mit `sk-ant-…`).
4. In der App: **Konten → Claude**, Schlüssel in das Feld **API-Schlüssel** einfügen, **Anmelden**.
   Die App prüft den Schlüssel sofort und sagt, welches Modell verfügbar ist.

> **Wichtig:** Ein *Claude-Pro/Max-Abo* (claude.ai) und ein *API-Schlüssel* sind zwei verschiedene Dinge und
> werden getrennt abgerechnet. Die App braucht den **API-Schlüssel**. Hat Ihr Institut eine
> Anthropic-Organisation, fragen Sie dort nach einem Schlüssel aus deren Workspace.
>
> Kosten: Eine kleine Aufgabe (ein Abschnitt) kostet wenig, eine Literaturrecherche oder eine eigene Aufgabe
> mehr. Die Seite *Usage* in der Console zeigt den Verbrauch.

### 5b – Overleaf-Token

1. In Overleaf: **Account Settings → Git integration → Generate token**. Kopieren Sie das Token sofort –
   Overleaf zeigt es nur einmal.
2. Wenn die App Sie auffordert, sich bei `git.overleaf.com` anzumelden:
   - **Benutzername:** `git`
   - **Zugriffstoken:** das kopierte Token
3. Im selben Fenster stehen **Name für Commits** und **E-Mail für Commits**. Diese erscheinen in der
   Versionsgeschichte neben Ihren Änderungen – tragen Sie Ihren echten Namen ein.
4. Ein Token gilt für **alle** Ihre Overleaf-Projekte.

### 5c – Optional: OpenAlex-Schlüssel

Die Literatursuche funktioniert ohne Schlüssel. Ein kostenloser Schlüssel von
<https://openalex.org/settings/api> erhöht das Tagesbudget auf das Zehnfache: **Konten → OpenAlex**.

## Schritt 6 – Erstes Paper hinzufügen

1. Klicken Sie links auf **Hinzufügen**.
2. **Name des Papers:** frei wählbar, zum Beispiel *Werkzeugklassifikation – IEEE Access*.
3. **Overleaf- oder Git-URL:** Öffnen Sie das Projekt in Overleaf und kopieren Sie die Adresse aus der
   Adresszeile (`https://www.overleaf.com/project/…`).
4. Die übrigen Felder leer lassen, **Speichern**.
5. Die App klont das Projekt – beim ersten Mal fragt sie das Overleaf-Token – und baut das PDF.

Für ein **ganz neues** Paper lassen Sie die URL leer; die App legt eine fertige Ordnerstruktur mit
`main.tex` an. Den Link zu einem **neuen, leeren** Overleaf-Projekt ergänzen Sie später über **Bearbeiten**.

> Damit Sie ein Paper sehen, brauchen Sie Zugriff auf das zugehörige Overleaf-Projekt – lassen Sie sich
> dort einladen.

## Schritt 7 – Prüfen, ob alles funktioniert

Arbeiten Sie diese kurze Liste ab; danach wissen Sie, dass die Einrichtung vollständig ist.

| Prüfung | So geht's | Erwartet |
|---|---|---|
| PDF wird gebaut | Paper auswählen, rechts **⟳ Neu kompilieren** | Das PDF erscheint rechts |
| Git funktioniert | **⟳ Aktualisieren** links | Keine Fehlermeldung |
| Claude funktioniert | **🤖 Agent-Aufgaben → Aufgabe: Zitate & BibTeX prüfen → ▶ Ausführen** | Ein Bericht im Reiter **Bericht** (diese Aufgabe ändert nichts am Paper) |
| Synchronisieren | **⇄ Mit Overleaf synchronisieren** | Entweder „nichts zu senden“ oder eine Liste zum Bestätigen |
| Version | **Hilfe → Über** | Die Versionsnummer aus Schritt 1 |

## Updates

**Updates kommen von selbst.** Ist eine neue Version veröffentlicht, zeigt die App beim Start
**Update verfügbar** samt Änderungsliste. Klicken Sie auf **Jetzt aktualisieren**: Die App lädt die neue
Version, prüft deren Prüfsumme, schließt sich, ersetzt sich selbst und startet in wenigen Sekunden neu.
**Später** verschiebt das auf den nächsten Start, **Hilfe → Nach Updates suchen…** prüft jederzeit.

Ihre Paper, Einstellungen und Anmeldungen bleiben erhalten, weil sie außerhalb des App-Ordners liegen
(siehe unten). Voraussetzung ist, dass der App-Ordner an einem beschreibbaren Ort liegt – also in
`Dokumente` und nicht in `Program Files`.

## Gemeinsame To-do-Liste (optional, pro Computer einmal)

Die To-do-Liste ist **eine Liste für alle Paper**, in einem eigenen kleinen Git-Repository – nicht in einem
Paper. Sie ist die dritte Stellung des Schalters in der Mitte: **☑ To-dos**.

Damit sie bei Ihnen funktioniert, brauchen Sie dreierlei:

1. eine **Einladung** zum Repository (die Person, die es angelegt hat, lädt Sie unter *Settings →
   Collaborators* ein);
2. ein **eigenes GitHub-Konto**;
3. ein **eigenes feingranulares Token** für dieses Repository mit dem Recht *Contents: Read and write*
   (GitHub → *Settings* → *Developer settings* → *Fine-grained tokens*).

Dann in der App:

1. **Optionen → Gemeinsame To-do-Liste…** und den Link zum Repository einfügen.
2. **Konten → Gemeinsame To-do-Liste (github.com)** und mit Ihrem Token anmelden.

> **Fallstrick:** Tokens werden **pro Anbieter** gespeichert, nicht pro Repository. Ein einziges
> github.com-Token muss also für jedes GitHub-Repository reichen, das die App benutzt. Zeigt GitHub
> „Repository not found“, obwohl der Link stimmt, ist meistens das Token eines anderen Kontos gespeichert.

Änderungen sind sofort für alle sichtbar – für die To-do-Liste gibt es kein Genehmigungsfenster und kein
Synchronisieren, weil sie nicht Teil eines Papers ist.

## Datensicherung in OneDrive (optional)

Die Ordner `data\` und `supplementary\` jedes Papers gelangen **nie** zu Overleaf – sie sind damit das
Einzige ohne zweite Kopie. Die Schaltfläche **☁ Daten sichern** kopiert sie in OneDrive.

1. Stellen Sie sicher, dass die OneDrive-App mit Ihrem Hochschulkonto angemeldet ist (Wolkensymbol neben
   der Uhr).
2. In der App **☁ Daten sichern**, dann die Schaltfläche **…**, und Ihren OneDrive-Ordner auswählen
   (etwa `C:\Users\<Ihr Name>\OneDrive - Ihre Hochschule`). Die App prüft, ob OneDrive
   diesen Ordner wirklich synchronisiert, und nennt sonst die Ordner, die es synchronisiert.
3. **Speichern**, dann erneut **☁ Daten sichern** und bestätigen.

Es wird **nur hinaus** kopiert: nichts wird in OneDrive umbenannt, gelöscht oder zurückgeholt, und nur neue
oder geänderte Dateien werden gesendet. Keine Anmeldung, keine Codes – die App legt die Dateien ab, OneDrive
lädt sie hoch. Ob sie angekommen sind, zeigen die Symbole im Explorer: blaue Pfeile = lädt noch hoch, grünes
Häkchen oder weiße Wolke = fertig, rotes Kreuz = OneDrive hat ein Problem.

## Wo Ihre Dateien liegen

Alles liegt in **`C:\Users\<Ihr Name>\.research_agent`** – also **außerhalb** des App-Ordners, weshalb
Updates nichts davon anfassen:

| Ordner oder Datei | Inhalt |
|---|---|
| `papers\` | Ihre Paper, je ein Ordner |
| `papers\<Paper>\data\` | Ihre Datensätze. Bleibt auf diesem Computer: geht nie zu Overleaf, und der Agent ändert dort nichts |
| `papers\<Paper>\supplementary\` | Zusatzmaterial (Videos, weitere Ergebnisse, große Dateien). Bleibt ebenfalls lokal |
| `reports\` | Literaturrecherchen, Prüfberichte, `.bib`-Exporte |
| `agent.log` | Das ausführliche Protokoll – hilfreich beim Melden eines Problems |
| `app_state.json` | Ihre Paper-Liste und Einstellungen (keine Passwörter) |
| `backup\` | Merkt sich, was zuletzt gesichert wurde |

**Was wohin geht:** Für Agent-Aufgaben geht genau der Text, den die Aufgabe braucht (zum Beispiel ein
Abschnitt), an die Claude-API von Anthropic. Bearbeiten, PDF und Versionsgeschichte bleiben auf Ihrem
Computer; **Synchronisieren** spricht nur mit Overleaf, **Daten sichern** kopiert nur in Ihren eigenen
OneDrive-Ordner.

## Wenn etwas nicht klappt

| Problem | Was zu tun ist |
|---|---|
| Windows blockiert die App | **Weitere Informationen → Trotzdem ausführen** (Schritt 2) |
| Die App startet nicht, obwohl die `.exe` da ist | Liegt der Ordner `_internal` daneben? Entpacken Sie das Zip erneut vollständig (Schritt 2) |
| Das Einrichtungsfenster konnte Git oder MiKTeX nicht installieren | Internetverbindung prüfen und **Erneut versuchen**. Blockiert die IT Installationen, *Git for Windows* und *MiKTeX* von der IT installieren lassen |
| „Es wurde kein LaTeX-Compiler gefunden“ | **Hilfe → Git / MiKTeX installieren…**, danach die App neu starten |
| MiKTeX fragt nach einem Paket | **Install** klicken. Das passiert einmal pro Paket |
| „… hat diese Anmeldedaten abgelehnt“ | Token oder Schlüssel ist abgelaufen: Menü **Konten** → erneut anmelden |
| Beim Synchronisieren: „getrennt voneinander begonnen“ | Ein in der App erstelltes Paper wurde mit einem Overleaf-Projekt verknüpft, in dem schon Dateien lagen. Fügen Sie das Paper erneut **mit** dem Overleaf-Link hinzu |
| Beim Synchronisieren: Konflikt | Sie und eine Mitautorin bzw. ein Mitautor haben dieselben Zeilen geändert. In Overleaf klären, dann **⟳ Aktualisieren** |
| „Nicht übernommene Änderungen im Paper-Ordner“ | Dateien wurden außerhalb der App geändert. Im `.tex`-Editor speichern (das übernimmt automatisch) oder die Änderungen verwerfen |
| Die App hat sich unerwartet geschlossen | Senden Sie `C:\Users\<Ihr Name>\.research_agent\crash.log` und `agent.log` an die Person, die die App betreut |
| **Update verfügbar** kommt immer wieder, und **Hilfe → Über** zeigt weiter die alte Version | Nur Version 1.0.0 und 1.0.1 können sich nicht selbst aktualisieren. Einmalig: App schließen, neuestes Zip von der [Release-Seite](https://github.com/Girish-Tangirala/research-assistant/releases) laden, alten App-Ordner (und einen eventuellen Ordner `ResearchAssistant.new` daneben) löschen, neues Zip an dieselbe Stelle entpacken. Paper und Einstellungen bleiben erhalten |
| Ein Fenster zeigt deutsche Beschriftungen, aber eine englische Erklärung | Sie sind auf einer älteren Version. Aktualisieren Sie über **Hilfe → Nach Updates suchen…** |

Hilft nichts davon, schicken Sie `agent.log` mit – darin steht die englische Fassung jeder Meldung, was das
Nachvollziehen erleichtert.

---

*Wer die App **selbst verändern** möchte, fragt nach dem Quellcode-Zip; `README.md` und `CLAUDE.md` darin
erklären, wie man mit eigenem Claude Code daran arbeitet.*
