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
mit `docker compose exec frontend npx tsc -b`; Lint mit ruff
(`backend/pyproject.toml`, inkl. Import-Sortierung). CI
(Uni-GitLab):
Lint, Backend-Tests gegen PostgreSQL, Frontend-Build.
