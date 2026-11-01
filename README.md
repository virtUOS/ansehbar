# ansehBAR

Kontrolle der Live-Streams aus den Aufzeichnungsräumen

Erzeugt aus dem [basicbar-Template](https://github.com/virtUOS/basicbar)
(Django + DRF, React + Vite, OIDC via Keycloak, @basicbar/ui-Designsystem,
optionale KI-/Übersetzungs-Integrationen).

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

Die Pipeline auf der Uni-GitLab lintet, testet und baut; das Release-Image
wird auf dem Server per `up -d --build` aus dem Checkout gebaut.

Die Settings verweigern den Start mit dem Entwicklungs-`SECRET_KEY`, sobald
`DJANGO_DEBUG=0` ist.

## Betrieb

Die App läuft als zwei Prozesse aus demselben Image: `backend` (Web/API) und
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

Hinweise:

- **Gruppenentzug wirkt erst beim nächsten Login.** Der Zugang wird beim
  Login aus den OIDC-Claims übernommen; wer die Gruppe verliert, behält die
  laufende Sitzung, bis er sich neu anmeldet. Soll der Zugang sofort enden,
  die Sitzung beenden bzw. den Benutzer in Keycloak abmelden.
- **Der Streaming-Server muss CORS erlauben.** Der Browser lädt die
  HLS-Playlists direkt vom Streaming-Server
  (`streaming.example.org` antwortet mit `Access-Control-Allow-Origin: *`).
  Ohne CORS-Header bleibt die Vorschau leer, auch wenn der Monitor „live“ meldet.
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
(`backend/pyproject.toml`, inkl. Import-Sortierung). CI
(Uni-GitLab):
Lint, Backend-Tests gegen PostgreSQL, Frontend-Build.
