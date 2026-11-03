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

**Stand:** Stufe 3c (auf Stufe 2 aufbauend) — Monitor mit gepflegter Rekorderliste und
Live-Erkennung der HLS-Streams (derzeit ein HLS-Streaming-Server) sowie
optionaler Anbindung an Opencast (geplante Aufzeichnungen, „Stream fehlt“,
„Heute noch geplant“; nur lesend), mit verständlichen Fehlermeldungen, Abgleich
auf Knopfdruck und Löschen deaktivierter Rekorder. Stufe 3a ergänzt Alarme „Stream fehlt“ per E-Mail und über `/metrics` für
Prometheus (Alarmmodus pro Rekorder, Empfänger in der Verwaltung, Entwarnung nach
stabiler Rückkehr). Stufe 3b ergänzt den Alarm „Ton fehlt“ (Pegelmessung mit
ffmpeg, Badge „Still seit“, Entwarnung per E-Mail, Metrik für Prometheus). Stufe 3c ergänzt den
Raumkalender (Wochen- und Tagesansicht mit Zeitleiste, Vorfällen und Pegelkurve)
und eine einstellbare Aufbewahrung alter Daten.
Geplant sind lernende Toleranzen (Stufe 4); Details im
[Design-Dokument](docs/superpowers/specs/2026-10-30-ansehbar-design.md).

**Technik:** erzeugt aus dem
[basicbar-Template](https://github.com/virtUOS/basicbar) — Django + DRF,
React + Vite, OIDC via Keycloak, @basicbar/ui-Designsystem, hls.js; ein
eigener Monitor-Prozess prüft die Streams.

**Einrichtung an einem Standort:** Das Repository enthält keine Angaben zu
einer konkreten Einrichtung. Streaming-Server, Rekorder, Anmeldedienst und
Domain richtet jeder Standort selbst ein, Schritt für Schritt beschrieben in
der [Konfigurationsanleitung](docs/KONFIGURATION.md).

**Website und Anleitung:** [virtuos.github.io/ansehbar](https://virtuos.github.io/ansehbar/)
(Deutsch und Englisch, Quellen in [`website/`](website/README.md)).

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
| `AUDIO_MONITOR_ENABLED` | `1` = Pegelmessung (Ton, Alarm „Ton fehlt“) an, `0` = aus; Details in der [Konfigurationsanleitung](docs/KONFIGURATION.md#7-alarme-e-mail-und-metriken) | `1` |
| `AUDIO_MAX_PARALLEL` | Gleichzeitige Pegelmessungen | `4` |
| `AUDIO_SAMPLE_SECONDS` | Länge eines Messfensters (Sekunden) | `10` |
| `AUDIO_INTERVAL_SECONDS` | Mindestabstand zwischen den Starts zweier Messdurchläufe | `30` |
| `OPENCAST_URL` | Basisadresse von Opencast (nur `https://`, außer mit `DJANGO_DEBUG=1`); leer = Opencast-Anbindung aus (siehe [Konfigurationsanleitung](docs/KONFIGURATION.md#5-opencast-anbinden-optional)) | leer |
| `OPENCAST_USER` | Benutzer (nur Leserechte) für die Opencast External API | leer |
| `OPENCAST_PASSWORD` | Passwort dieses Benutzers | leer |
| `OPENCAST_SYNC_SECONDS` | Sekunden zwischen zwei Abgleichen mit Opencast | `60` |
| `OPENCAST_LOOKAHEAD_DAYS` | Tage Terminplan im Voraus | `7` |
| `OPENCAST_LOOKBACK_DAYS` | Tage Rückblick für den Hinweis „Letzte Aufzeichnung hatte Probleme“ | `7` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` (`1`/`0`), `EMAIL_TIMEOUT` | SMTP-Zugang für Alarm-E-Mails (siehe [Konfigurationsanleitung](docs/KONFIGURATION.md#7-alarme-e-mail-und-metriken)) | `localhost`, `25`, leer, leer, `0`, `10` |
| `DEFAULT_FROM_EMAIL` | Absender der Alarm-E-Mails | `ansehbar@localhost` |
| `EMAIL_BACKEND` | Django-E-Mail-Backend, nur zum Überschreiben (etwa für Tests) | SMTP; mit `DEBUG` die Konsole |
| `ALARM_LANGUAGE` | Sprache der Alarm-E-Mails (`de`/`en`), für alle Empfänger gleich | `de` |
| `METRICS_TOKEN` | Bearer-Token für `/metrics`; leer = Endpoint aus (404). Siehe [Monitoring](docs/monitoring.md) | leer |
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
- In der Entwicklung braucht die `.env` keine Mail-Einstellungen: Mit
  `DJANGO_DEBUG=1` schreibt der Monitor Alarm-E-Mails auf die Konsole
  (`docker compose logs monitor`).
- **Ton (Stufe 3b):** Der Monitor misst den Pegel live laufender Räume mit
  ffmpeg (im Image enthalten; `audio_monitor.py`, `streams/audio.py`), zeigt
  ihn in der Raumansicht und alarmiert bei langer Stille. Kalibrieren der
  Schwelle: `docker compose exec backend python manage.py measure_audio <stream>`
  (siehe Konfigurationsanleitung, Abschnitt 7). Jede Messung lädt den Stream
  für `AUDIO_SAMPLE_SECONDS` (Standard 10 Sekunden, ca. 2 bis 4 Mbit/s).
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
