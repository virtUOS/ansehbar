# Projekt-Website

Quellen der Projekt-Website (GitHub Pages) mit Startseite, Anleitung und
Installationsüberblick — zweisprachig: Deutsch an der Wurzel der Website,
Englisch unter `/en/`. Aufbau wie bei abstimmBAR.

## Zwei Sprachen

Die Website besteht aus zwei MkDocs-Konfigurationen, ohne i18n-Plugin:

- `mkdocs.yml` — Deutsch, Quellen in diesem Ordner, Ausgabe `site/`.
- `mkdocs.en.yml` — Englisch, erbt per `INHERIT` Theme, CSS, `overrides/`,
  Hooks und Markdown-Erweiterungen; Quellen in `en/` (englische Dateinamen,
  z. B. `en/guide/room-view.md`), Ausgabe `site/en/`.
- `hooks/i18n.py` verknüpft die Seiten paarweise (Tabelle `PAGES`) für den
  Sprachumschalter im Kopf (`overrides/partials/alternate.html`) und stellt
  der englischen Seite die gemeinsamen `assets/` bereit.

**Beide Sprachen synchron halten:** Jede Änderung an einer deutschen Seite
braucht die passende Änderung in `en/`. Neue oder umbenannte Seiten in beide
`nav`-Listen und in `PAGES` eintragen.

## Screenshots (`bilder/`, `en/bilder/`)

Die Bilder in `bilder/` (deutsch) und `en/bilder/` (englisch, gleiche
Dateinamen) erzeugt ein Skript — nicht von Hand ersetzen, sondern das Skript
anpassen und neu laufen lassen.

Voraussetzungen: das Frontend läuft (`docker compose up -d frontend`,
Port 5179), auf dem Rechner sind Google Chrome und ffmpeg installiert, und
die Frontend-Abhängigkeiten sind auch lokal da (`cd frontend && npm install`).

```bash
cd frontend
npm run docs:shots                        # deutsch → website/bilder/
DOCS_SHOTS_LANG=en npm run docs:shots     # englisch → website/en/bilder/
```

Das Skript (`frontend/e2e/docs-screenshots.spec.ts`) beantwortet **alle**
API-Anfragen selbst aus erfundenen Daten (`frontend/e2e/docs-data.ts`):
Räume wie „Hörsaal A“, Streams wie `cap-hs-a`, Adressen unter `example.org`.
Backend und Datenbank werden nicht gefragt, echte Räume können also nicht ins
Bild geraten. Die Live-Streams sind kurze HLS-Videos einer erzeugten Folie
(ffmpeg); die Uhr steht auf Dienstag, 10.11.2026, 10:47 (Europe/Berlin).
Google Chrome statt Playwrights Chromium, weil diesem die Codecs der
HLS-Streams (H.264/AAC) fehlen.

- Desktop 1440 × 900 bei Skalierung 1,5, Handy 390 × 844 bei Skalierung 2;
  helles Design, dazu eine Übersicht im dunklen Design.
- `DOCS_SHOTS_ONLY=uebersicht,raumansicht npm run docs:shots` schreibt nur
  die genannten Bilder; `DOCS_SHOTS_DIR=<ordner>` schreibt woanders hin.
- Ohne `DOCS_SHOTS` gibt es kein Playwright-Projekt; Vitest ignoriert
  `e2e/`.

## Website bauen und ansehen

Der Workflow `.github/workflows/docs.yml` baut die Website bei Änderungen
(Pull Requests nur bauen, `main` auch veröffentlichen). Lokal, in einer
eigenen virtuellen Umgebung, alle Befehle **im Repo-Root**:

```bash
python3 -m venv /tmp/ansehbar-docs && . /tmp/ansehbar-docs/bin/activate
pip install -r website/requirements.txt
mkdocs serve -f website/mkdocs.yml             # deutsch, http://127.0.0.1:8000/ansehbar/
mkdocs serve -f website/mkdocs.en.yml          # englisch, …/ansehbar/en/
# wie in CI — erst Deutsch (räumt site/ auf), dann Englisch nach site/en/:
mkdocs build --strict -f website/mkdocs.yml
mkdocs build --strict -f website/mkdocs.en.yml
```

`mkdocs serve` zeigt jeweils nur eine Sprache; der Sprachumschalter führt
dort ins Leere. Die Gesamtseite: beide bauen und `site/` statisch
ausliefern, z. B.
`mkdir -p /tmp/pages && ln -sfn "$PWD/site" /tmp/pages/ansehbar && python3 -m http.server -d /tmp/pages`.

- `index.md` — Startseite, `anleitung/` — Anleitung (ein Kapitel pro Datei),
  `installation.md` — Überblick mit Links auf `docs/KONFIGURATION.md`,
  `assets/` — Theme (Farben wie in der App) und Logo; `en/` — dasselbe auf
  Englisch (`en/guide/`).
