# ansehBAR — Hinweise für Claude

Kontrolle der Live-Streams aus den Aufzeichnungsräumen der Universität
Osnabrück: Django-Backend (`backend/`) + React/Vite-SPA (`frontend/`). Gemeinsame Basis der virtUOS
"-bar"-Tools aus dem basicbar-Repo: `basicbar-auth` (OIDC), `basicbar-integrations`
(LibreTranslate/LiteLLM) und `@basicbar/ui`
(Tailwind-Preset, base.css, Theme, i18n, TranslatableField, Preferences). Paketcode
nie lokal patchen — Änderungen gehören ins basicbar-Repo, Upgrade per
Versions-Bump (Changelog dort = Migrationsanleitung).

## Ports (Entwicklung)

Frontend 5179, Backend 8007, Keycloak 8086, Postgres 5438.

## Aufbau

- Backend-Apps: `config` (Settings/URLs), `accounts` (User, Zugangsprüfung
  über IdP-Gruppe/Bootstrap/Einladungen, Einladungs- und Benutzersuche-API),
  `recorders` (Rekorder, Status, Monitor-Einstellungen, API, Monitor-Zyklus;
  `audio_monitor.py` führt den Ton-Durchlauf aus; `AudioSample` = ein Pegelwert
  je Messung; `history.py` = Kalender-/Vorfallsdaten, geteilt mit „Letzte
  Aufzeichnung“; `retention.py` = Aufbewahrung, `prune_history`, stündlich im
  Monitor),
  `opencast` (read-only-Client der External API, Sync von Agents und
  Terminen, `ScheduledEvent`, `OpencastSyncState`),
  `alarms` (Alarmempfänger, `SentNotification`-Protokoll, E-Mail-Zustellung
  im Monitor-Zyklus; Alarmregeln liegen in `recorders/alarm_rules.py`,
  `/metrics` in `common/views.py`),
  `streams` (HLS-Probe: Master-/Chunklist, Frische der Media-Sequence;
  `audio.py`: Pegelmessung mit ffmpeg),
  `common` (Basis).
- Monitor: eigener Compose-Dienst `monitor`, `python manage.py run_monitor`
  (`--once` für einen Lauf); Intervall `MONITOR_INTERVAL_SECONDS`. Der Monitor
  misst den Ton in einem eigenen Thread (`AUDIO_*`, Stufe 3b).
- Frontend (`frontend/src/`): `media/` (hls.js-Player, Web-Audio, Pegel),
  `pages/` (Übersicht, Raumansicht, Raumkalender `RoomCalendar`, Landing/NoAccess,
  `admin/`; Zeitleiste/Pegelkurve: `timeline.ts`, `EventTimeline`, `LevelCurve`),
  `components/` (Kachel, Raumliste, StatusBadge, Formularteile, Dialog),
  `api.ts` (Client), `locales/` (Übersetzungen).
- Website (GitHub Pages, DE/EN): `website/` (MkDocs Material, siehe
  `website/README.md`); Screenshots per `frontend/e2e/docs-screenshots.spec.ts`
  mit erfundenen API-Antworten (`frontend/e2e/docs-data.ts`).
- Spec: `docs/superpowers/specs/2026-10-30-ansehbar-design.md`,
  Plan: `docs/superpowers/plans/2026-10-30-ansehbar-stufe-1.md`.

## Befehle

```bash
docker compose exec backend python manage.py test      # Backend-Tests
docker compose exec frontend npx tsc -b                # Frontend-Typecheck
docker compose exec frontend npm test                  # Frontend-Tests (vitest)
docker compose exec frontend npm run check:i18n        # jeder t("…")-Key hat eine deutsche Übersetzung
docker compose exec backend python manage.py run_monitor --once  # ein Prüflauf
docker compose exec backend python manage.py measure_audio <stream>  # Pegel eines Streams messen (Kalibrierung der Stille-Schwelle)
docker compose exec backend python manage.py load_site_config    # Rekorder/Stream-URL aus backend/site.local.json laden
docker compose exec backend sh -c "pip install -q ruff && ruff check ."  # Lint (wie CI, Config in backend/pyproject.toml)
cd frontend && npm run docs:shots                      # Website-Screenshots (DE; DOCS_SHOTS_LANG=en für EN), braucht Chrome + ffmpeg
```

## Workflow

- Repo: `github.com/virtUOS/ansehbar` (öffentlich). Keine Infrastruktur-Details
  einer Einrichtung committen (Hostnamen, Rekorder-/Raumnamen) — die gehören in
  die ungetrackte Standortkonfiguration (`*.local.json`, siehe docs/KONFIGURATION.md).
- Vereinfachter Gitflow: `main` ist geschützt (kein direkter Push, kein
  Force-Push); Arbeit auf `feature/<slug>`, `fix/<slug>`, `chore/<slug>`,
  `docs/<slug>`; PR mit grüner CI (`.github/workflows/ci.yml`); der Mensch merged.
- Release = Git-Tag `vX.Y.Z` → `.github/workflows/release.yml` baut das Image
  nach `ghcr.io/virtuos/ansehbar`; Deployment über `docker-compose.prod.yml`
  (siehe README, docs/KONFIGURATION.md).
- Gerüst-Updates: `pipx run copier update --vcs-ref HEAD` (Identitäts- und
  Inhaltsdateien sind davon ausgenommen, siehe README).

## Konventionen

- Apache-2.0, SPDX-Header in jeder Quelldatei.
- Jede App hält mindestens Basis-Tests in ihrer `tests.py`.
- UI-Texte: Englisch als i18n-Key, Deutsch in `src/locales/de/translation.json`.
- Design: Ramps in `tailwind.config.js` sind die Identität dieses Tools;
  Struktur kommt aus dem @basicbar/ui-Preset.
- Backend-Texte: englische msgids mit gettext (`gettext`/`gettext_lazy`),
  Deutsch in `backend/locale/de/LC_MESSAGES/django.po`; `.po` und `.mo`
  einchecken (`makemessages -l de`, `compilemessages`). Die SPA sendet
  `Accept-Language` (aus `<html lang>`), `LocaleMiddleware` wählt die Sprache.
- Kein Django-Admin für Fachdaten; jede Pflegemaske gehört ins Frontend.
- Nie Browser-Dialoge (`window.confirm/alert/prompt`), stattdessen `ConfirmDialog`.
- Status immer mit Text **und** Symbol, nie nur Farbe; Akzentfarbe (brand) ist nie
  Statusfarbe. Dark-Mode-Text mindestens `slate-300` (`slate-400` verfehlt 4,5:1).
- Stream-Namen sind case-sensitiv (`cap-90-R12`), nie kleinschreiben.
- „Live“ = Chunklist existiert und ihre Media-Sequence hat sich innerhalb von
  `3 × TARGETDURATION` geändert; HTTP 200 auf die Master-Playlist allein reicht nicht.
- Keine Infrastrukturdetails der Einrichtung (Stream-Hostnamen, Rekorder-/Raumnamen)
  im Repo: sie stehen in der git-ignorierten `backend/site.local.json`
  (Vorlage `backend/site.example.json`, Befehl `load_site_config`, siehe README
  „Standortkonfiguration“). Migrationen und Tests nur mit fiktiven Werten.
- ansehBAR schreibt nie nach Keycloak und nie nach Opencast (Client kennt nur GET).
