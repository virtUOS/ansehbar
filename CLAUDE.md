# ansehBAR — Hinweise für Claude

Kontrolle der Live-Streams aus den Aufzeichnungsräumen Django-Backend (`backend/`, Apps `config`/`accounts`/
`common`) + React/Vite-SPA (`frontend/`). Gemeinsame Basis der virtUOS
"-bar"-Tools aus dem basicbar-Repo: `basicbar-auth` (OIDC), `basicbar-integrations`
(LibreTranslate/LiteLLM) und `@basicbar/ui`
(Tailwind-Preset, base.css, Theme, i18n, TranslatableField, Preferences). Paketcode
nie lokal patchen — Änderungen gehören ins basicbar-Repo, Upgrade per
Versions-Bump (Changelog dort = Migrationsanleitung).

## Befehle

```bash
docker compose exec backend python manage.py test      # Backend-Tests
docker compose exec frontend npx tsc -b                # Frontend-Typecheck
docker compose exec backend sh -c "pip install -q ruff && ruff check ."  # Lint (wie CI, Config in backend/pyproject.toml)
```

## Workflow

- Branch + PR/MR, nie direkt auf `main`; der Mensch merged.
- Release = Git-Tag `vX.Y.Z`;
  Deployment über `docker-compose.prod.yml` (siehe README).
- Gerüst-Updates: `pipx run copier update --vcs-ref HEAD` (Identitäts- und
  Inhaltsdateien sind davon ausgenommen, siehe README).

## Konventionen

- Apache-2.0, SPDX-Header in jeder Quelldatei.
- Jede App hält mindestens Basis-Tests in ihrer `tests.py`.
- UI-Texte: Englisch als i18n-Key, Deutsch in `src/locales/de/translation.json`.
- Design: Ramps in `tailwind.config.js` sind die Identität dieses Tools;
  Struktur kommt aus dem @basicbar/ui-Preset.
