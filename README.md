# ansehBAR

Kontrolle der Live-Streams aus den Aufzeichnungsräumen der Universität
Osnabrück — ein Werkzeug des virtUOS aus der Familie der „-bar“-Tools.

## Worum es geht

Die Hörsaal-Rekorder zeichnen die von Opencast geplanten Veranstaltungen
auf und streamen dabei immer gleichzeitig live: Kamera- und Bildschirmbild
in einem Video. Fehlt der Live-Stream während eines Termins, ist praktisch
auch die Aufzeichnung kaputt. ansehBAR zeigt auf einen Blick, welche Räume
gerade senden, und macht Bild und Ton prüfbar:

- **PC-Übersicht:** Kacheln für alle Räume, die gerade streamen, mit
  „seit HH:MM“, Pegelanzeige (auch bei stummem Video) und Ton pro Kachel.
  Räume ohne Stream stehen klar gekennzeichnet darunter.
- **Smartphone:** eine Raumansicht mit großem Player, Ton, Vollbild und
  Laufzeit, z. B. für Technikerinnen und Techniker bei wichtigen
  Veranstaltungen.
- **Klare Zustände statt schwarzer Player:** „Kein Stream“, „Status
  unbekannt“, „Wiedergabe gestört“ und ein Hinweis, wenn der Monitor selbst
  keine Daten mehr liefert.
- **Verwaltung:** Rekorder pflegen, Personen einladen, Streaming-URL
  einstellen.

ansehBAR ist ein Kontrollwerkzeug für einen kleinen Personenkreis
(Medientechnik, Team Aufzeichnungen), kein Streaming-Angebot für alle. Die
Anmeldung läuft über OIDC (Keycloak); Zugang haben Mitglieder einer
IdP-Gruppe und in ansehBAR eingeladene Personen. ansehBAR ändert nichts in
Keycloak, Opencast oder an den Rekordern — es beobachtet nur.

**Stand:** Stufe 1 — Monitor mit gepflegter Rekorderliste und
Live-Erkennung der HLS-Streams (derzeit ein HLS-Streaming-Server). Geplant sind die Anbindung
an Opencast (Stufe 2), Alarme per E-Mail und über den Monitoring-Dienst mit Ausfallprotokoll
(Stufe 3) und lernende Toleranzen (Stufe 4); Details im
[Design-Dokument](docs/superpowers/specs/2026-10-30-ansehbar-design.md).

**Technik:** erzeugt aus dem
[basicbar-Template](https://github.com/virtUOS/basicbar) — Django + DRF,
React + Vite, OIDC via Keycloak, @basicbar/ui-Designsystem, hls.js; ein
eigener Monitor-Prozess prüft die Streams.

**Einrichtung an einem Standort:** Das Repository enthält keine Angaben zu
einer konkreten Einrichtung. Streaming-Server, Rekorder, Anmeldedienst und
Domain richtet jeder Standort selbst ein, Schritt für Schritt beschrieben in
der [Konfigurationsanleitung](docs/KONFIGURATION.md).

**Lizenz:** [Apache-2.0](LICENSE), siehe auch [NOTICE](NOTICE).

## Entwicklung

```bash
docker compose up -d        # Postgres 5438, Keycloak 8086, Backend 8007, Frontend 5179
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py test
```

- SPA: http://localhost:5179 — Login mit `demo`/`demo`
  (Admin: `admin-demo`/`demo`, via Keycloak-Gruppe `ansehbar-admins`).
- Keycloak-Admin: http://localhost:8086 (`admin`/`admin`).
- Django-Admin: http://localhost:8007/admin/ (Break-glass-Konto
  per `docker compose exec backend python manage.py createsuperuser`).

## Produktion

Ein Release ist **ein Image** (Root-`Dockerfile`: SPA gebaut und ins
Django-Image gebacken). `docker-compose.prod.yml` fährt PostgreSQL, die App
(uvicorn, migriert und sammelt Statics beim Start) und Caddy (TLS, serviert
SPA/Statics/Media direkt aus Volumes):

```bash
cp .env.prod.example .env      # ausfüllen — Pflichtvariablen erzwingt compose
# Caddyfile: Domain und ACME-Mail eintragen
docker compose -f docker-compose.prod.yml up -d --build
```

GitHub Actions lintet, testet und baut jeden Pull Request
(`.github/workflows/ci.yml`). Ein Tag `vX.Y.Z` veröffentlicht das Image als
`ghcr.io/virtuos/ansehbar` (`.github/workflows/release.yml`); alternativ wird
es auf dem Server per `up -d --build` aus dem Checkout gebaut.

Die Settings verweigern den Start mit dem Entwicklungs-`SECRET_KEY`, sobald
`DJANGO_DEBUG=0` ist.

## Standortkonfiguration

Das Repository enthält keine Angaben zur Infrastruktur der betreibenden
Einrichtung. Stream-Hostnamen, Rekorder-/Stream-Namen und Raumnamen stehen in
einer lokalen JSON-Datei, die nicht eingecheckt wird (`*.local.json` ist in
`.gitignore`). Sie enthält die Stream-URL-Vorlage (`stream_url_template`,
optional) und die Liste der Rekorder (`stream_name`, `room_name`, optional
`active`, Standard `true`).

Datei anlegen: `backend/site.example.json` nach `backend/site.local.json`
kopieren und mit den echten Werten füllen. Stream-Namen sind case-sensitiv.

Laden in der Entwicklung:

```bash
docker compose exec backend python manage.py load_site_config
# Optionen: --path PFAD, --deactivate-missing, --dry-run
```

Laden in Produktion (ohne Mount, die Datei kommt über stdin):

```bash
docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py load_site_config --path - < site.local.json
```

Die Datei wird vollständig geprüft, bevor etwas geschrieben wird; bei Fehlern
bricht der Befehl mit einer Liste aller Probleme ab. Rekorder werden anhand des
Stream-Namens angelegt oder aktualisiert, nie gelöscht. Mit
`--deactivate-missing` werden Rekorder, die nicht in der Datei stehen,
deaktiviert. `--dry-run` zeigt nur die Zusammenfassung (angelegt / aktualisiert
/ unverändert / deaktiviert). Mehrfaches Laden ist unschädlich.

Hinweis: Änderungen, die die Verwaltung später im Frontend vornimmt, liegen nur
in der Datenbank. Ein erneutes Laden der Datei überschreibt Raumname und
Aktiv-Status aller dort aufgeführten Rekorder (und die Stream-URL-Vorlage, falls
angegeben).

## Betrieb

Die App läuft als zwei Prozesse aus demselben Image: Web/API (`backend` in
der Entwicklung, `app` in `docker-compose.prod.yml`) und
`monitor` (`python manage.py run_monitor`). Der Monitor prüft alle aktiven
Rekorder im Intervall und schreibt den Status in die Datenbank. Läuft er
nicht, frieren die Status auf dem letzten Stand ein (ein Stream kann also
weiter als „live“ erscheinen). Das Frontend fragt deshalb mit den Rekordern
den Herzschlag `GET /api/monitor/health/` ab und zeigt in Übersicht und
Raumansicht ein Banner „Monitor liefert keine Daten seit … – Status kann
veraltet sein“, sobald die letzte Prüfung länger als drei Intervalle
(Serverzeit) zurückliegt. Beide Dienste brauchen dieselben
Umgebungsvariablen (siehe `.env.prod.example`).

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `ANSEHBAR_ACCESS_GROUP` | IdP-Gruppe (Keycloak), deren Mitglieder die App nutzen dürfen | `ansehbar-users` |
| `ANSEHBAR_BOOTSTRAP_USERS` | Kommagetrennte Benutzernamen/E-Mails mit Zugang ohne Gruppe (erste Einrichtung); weitere Personen lädt die Verwaltung unter „Einladungen“ ein | leer |
| `ANSEHBAR_ACCESS_CONTACT` | Kontakt (z. B. Mailadresse), der Personen ohne Zugang angezeigt wird | leer |
| `MONITOR_INTERVAL_SECONDS` | Sekunden zwischen zwei Prüfläufen des Monitors | `10` |
| `ANSEHBAR_SITE_CONFIG` | Pfad der Standortkonfiguration für `load_site_config` (siehe „Standortkonfiguration“) | `backend/site.local.json` |

Hinweise:

- **Gruppenentzug wirkt erst beim nächsten Login.** Der Zugang wird beim
  Login aus den OIDC-Claims übernommen; wer die Gruppe verliert, behält die
  laufende Sitzung, bis er sich neu anmeldet. Soll der Zugang sofort enden,
  die Sitzung beenden bzw. den Benutzer in Keycloak abmelden.
- **Der Streaming-Server muss CORS erlauben.** Der Browser lädt die
  HLS-Playlists direkt vom Streaming-Server; dieser muss dafür
  `Access-Control-Allow-Origin` (ansehBAR-Domain oder `*`) senden. Ohne
  CORS-Header bleibt die Vorschau leer, auch wenn der Monitor „live“ meldet.
  Alle Anforderungen an den Streaming-Server stehen in der
  [Konfigurationsanleitung](docs/KONFIGURATION.md#1-voraussetzungen-am-streaming-server).
- **„seit“ in Stufe 1:** Die Uhrzeit zeigt, wann der Monitor den Stream
  erstmals als live gesehen hat, nicht den tatsächlichen Aufzeichnungsbeginn.
  Sie übersteht einen Neustart des Monitors und Prüfungen mit unklarem
  Ergebnis („Status unbekannt“): Nach einem längeren Ausfall des Monitors
  steht dort daher noch die alte Startzeit, bis der Monitor den Stream wieder
  als beendet erkannt hat.
- Die Stream-URL-Vorlage und der Frische-Faktor stehen im Frontend unter
  „Verwaltung → Einstellungen“.
- Backend-Texte sind englische gettext-Schlüssel, die deutschen Übersetzungen
  liegen in `backend/locale/de/LC_MESSAGES/` (`.po` und `.mo` sind
  eingecheckt). Nach Änderungen: `makemessages -l de`, übersetzen,
  `compilemessages`.

## Basis aktualisieren

Die gemeinsamen Bausteine kommen aus dem basicbar-Repo (Changelog dort ist
die Upgrade-Anleitung):

- **Backend-Pakete** (`backend/requirements.txt`): Tag in der URL heben.
- **@basicbar/ui** (`frontend/package.json`): Tarball-Version heben.
- **Projektgerüst**: `pipx run copier update --vcs-ref HEAD` spielt
  Template-Änderungen ein. Identitäts- und Inhaltsdateien (Farb-Ramps,
  `App.tsx`, Kataloge, README/CLAUDE.md, Keycloak-Realm, Caddyfile,
  `.env.prod.example`) überschreibt es nicht — die gehören diesem Tool.

## Konventionen

Apache-2.0 mit SPDX-Headern; jede App hält Tests neben dem Code
(`docker compose exec backend python manage.py test`); Frontend-Typecheck
mit `docker compose exec frontend npx tsc -b`; Übersetzungs-Check mit
`docker compose exec frontend npm run check:i18n`; Lint mit ruff
(`backend/pyproject.toml`, inkl. Import-Sortierung). CI (GitHub Actions):
Lint, Backend-Tests gegen PostgreSQL, Frontend-Build, -Tests und
Übersetzungs-Check.

Beiträge laufen über Pull Requests: `main` ist geschützt, gearbeitet wird
auf Branches (`feature/…`, `fix/…`, `chore/…`, `docs/…`).
