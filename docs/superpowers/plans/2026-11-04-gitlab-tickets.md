# GitLab-Tickets aus der Übersicht — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jede Kachel der Übersicht bekommt einen Button, der mit Fehlermeldung, ansehBAR-/Opencast-Daten und Screenshot ein GitLab-Issue anlegt.

**Architecture:** GitLab-URL und verschlüsseltes Token liegen am Singleton `MonitorSettings`. Der Browser nimmt ein Standbild aus dem `<video>` der Kachel auf und schickt es mit der Meldung an `POST /api/recorders/<id>/ticket/`; das Backend stellt die Daten serverseitig zusammen, lädt das Bild über die GitLab-Uploads-API hoch und legt das Issue an. Opencast-Presenter werden beim Abgleich zusätzlich gespeichert.

**Tech Stack:** Django 5.1/DRF, `httpx` (vorhanden), `cryptography` (neu, Fernet), React/Vite/TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-gitlab-tickets-design.md`

## Global Constraints

- SPDX-Header `# SPDX-License-Identifier: Apache-2.0` + `# Copyright 2026 Universität Osnabrück (virtUOS)` in jeder neuen Quelldatei (TS: `//`).
- Keine Infrastrukturdetails im Repo: Beispiele nur `https://gitlab.example.com/gruppe/projekt`, Räume fiktiv („Hörsaal A“, `cap-hs-a`).
- ansehBAR schreibt nie nach Opencast oder Keycloak; GitLab nur `POST …/uploads` und `POST …/issues`.
- GitLab-Aufrufe: `httpx` mit `follow_redirects=False`, Timeout 15 s, Header `PRIVATE-TOKEN`; Token nie in Antworten, Logs oder Fehlermeldungen.
- URL nur `https`; `http` nur bei `settings.DEBUG`.
- Issue-`web_url` nur übernehmen, wenn Schema und Host (netloc, case-insensitiv) zur konfigurierten URL passen.
- UI-Texte: englischer Key, Deutsch in `frontend/src/locales/de/translation.json`; Backend-Texte gettext, Deutsch in `backend/locale/de/LC_MESSAGES/django.po` (+ `.mo` einchecken).
- Status immer Text + Symbol; keine Browser-Dialoge (`window.*`); Dialoge auf nativem `<dialog>` wie `ConfirmDialog`.
- Stream-Namen nie kleinschreiben.
- Befehle: `docker compose exec backend python manage.py test`, `docker compose exec frontend npx tsc -b`, `docker compose exec frontend npm test`, `docker compose exec frontend npm run check:i18n`, ruff wie in CLAUDE.md.

## Review Focus

1. Admin ändert die GitLab-URL, ohne ein Token einzugeben → gespeichertes Token wird gelöscht, `gitlab_token_set` = false (Test in Task 1).
2. GitLab antwortet mit 302 auf einen fremden Host → kein Folgen, HTTP 502 an den Client, Token nicht weitergereicht (Test in Task 3).
3. Kachel ist offline oder das Bild lässt sich nicht aufnehmen → Ticket geht ohne Screenshot raus, Beschreibung sagt „kein Screenshot“ (Tests in Task 3, Verhalten in Task 4).
4. Hochgeladene Datei ist kein JPEG/PNG (z. B. HTML mit `.png`-Namen) oder > 5 MB → 400, kein GitLab-Aufruf (Test in Task 3).
5. Fehlermeldung mit 500 Zeichen und Zeilenumbrüchen → Titel einzeilig und ≤ 255 Zeichen, volle Meldung in der Beschreibung (Test in Task 3).

---

### Task 1: Verschlüsselte GitLab-Einstellungen

**Files:**
- Create: `backend/common/encryption.py`
- Modify: `backend/requirements.txt` (`cryptography==50.0.2`), `backend/config/settings.py` (`TOKEN_ENCRYPTION_KEY = os.environ.get("TOKEN_ENCRYPTION_KEY", "")`), `backend/recorders/models.py` (`MonitorSettings`), neue Migration `backend/recorders/migrations/0012_gitlab.py`, `backend/recorders/serializers.py` (`MonitorSettingsSerializer`), `backend/accounts/views.py` (`whoami`), `docker-compose.prod.yml` (app: `TOKEN_ENCRYPTION_KEY: ${TOKEN_ENCRYPTION_KEY:-}`), `.env.prod.example` (auskommentierte Zeile mit Erklärung und Erzeugungsbefehl)
- Test: `backend/recorders/tests.py`, `backend/common/tests.py`

**Interfaces:**
- Produces: `common.encryption.encrypt(text: str) -> str`, `decrypt(token: str) -> str` (leer ↔ leer; nicht entschlüsselbar → `""` + Warnung), Verhalten wie ausleihBAR `catalog/encryption.py` (Schlüssel aus `TOKEN_ENCRYPTION_KEY`, sonst SHA-256 von `SECRET_KEY`).
- Produces: `MonitorSettings.gitlab_url: URLField(blank=True, max_length=500)`, `MonitorSettings.gitlab_token: TextField(blank=True, default="")` (Chiffrat); Methoden `gitlab_token_plain() -> str`, `set_gitlab_token(plain: str) -> None`, Property `tickets_enabled -> bool` (URL und Klartext-Token nicht leer).
- Produces: Serializer-Felder `gitlab_url` (lesen/schreiben), `gitlab_token` (write-only, optional, `allow_blank`), `gitlab_token_set` (read-only bool).
- Produces: `whoami` liefert `"tickets_enabled": bool` (nur `True`, wenn `has_access(request.user)` und `MonitorSettings.tickets_enabled`; per `filter().first()` lesen, GET legt keine Zeile an).

- [ ] **Step 1: Failing tests**

`common/tests.py`: `test_encrypt_roundtrip` (`decrypt(encrypt("glpat-x")) == "glpat-x"`, Chiffrat ≠ Klartext), `test_empty_stays_empty`, `test_wrong_key_yields_empty` (mit `override_settings(TOKEN_ENCRYPTION_KEY=<anderer Fernet-Key>)` beim Entschlüsseln → `""`).

`recorders/tests.py` (Klasse `GitLabSettingsTests`, API über `/api/settings/monitor/` mit Access-User wie bestehende Settings-Tests):
- `test_token_is_write_only`: PUT mit `gitlab_url="https://gitlab.example.com/g/p"`, `gitlab_token="glpat-secret"` → Antwort enthält kein `gitlab_token`, `gitlab_token_set is True`; DB-Feld ≠ `"glpat-secret"`; `gitlab_token_plain() == "glpat-secret"`.
- `test_put_without_token_keeps_it`: zweiter PUT gleiche URL ohne `gitlab_token` → `gitlab_token_set is True`.
- `test_url_change_without_token_clears_it`: PUT mit `gitlab_url="https://gitlab.example.com/other/p"` ohne Token → `gitlab_token_set is False`.
- `test_url_change_with_new_token_keeps_new`.
- `test_empty_token_clears`: `gitlab_token=""` → `gitlab_token_set is False`.
- `test_http_url_rejected_without_debug`: `http://gitlab.example.com/g/p` → 400 auf `gitlab_url`; mit `override_settings(DEBUG=True)` → 200.
- `test_whoami_tickets_enabled`: false ohne Konfiguration, true mit URL+Token.

- [ ] **Step 2: Tests laufen lassen** — `docker compose exec backend python manage.py test common recorders.tests.GitLabSettingsTests` → FAIL (Import/Feld fehlt). Vorher `docker compose build backend` bzw. `pip install` für `cryptography`.

- [ ] **Step 3: Implementieren** — Dateien wie oben; Serializer-Logik in `update()`: neues Token setzen, wenn Schlüssel `gitlab_token` im Request; sonst, wenn sich `gitlab_url` geändert hat, Token leeren. URL-Validierung in `validate_gitlab_url` (leer erlaubt; Schema `https`, `http` nur bei DEBUG; Pfad nach Abschneiden von `/-/…` nicht leer).

- [ ] **Step 4: Tests grün** — gleicher Befehl → PASS; dazu die ganze Suite und ruff.

- [ ] **Step 5: Commit** — `feat(settings): encrypted GitLab project settings`

### Task 2: Presenter aus Opencast

**Files:**
- Modify: `backend/opencast/client.py` (`Event` + `scheduled_events`), `backend/opencast/models.py` (`ScheduledEvent.presenters = models.CharField(max_length=300, blank=True)`), Migration `backend/opencast/migrations/0007_event_presenters.py`, `backend/opencast/sync.py` (defaults: `"presenters": event.presenters[:300]`), `backend/recorders/serializers.py` (`_event_data` und die Event-Serialisierung um Zeile 186: Feld `presenters` ergänzen), `frontend/src/api.ts` (`EventBrief.presenters: string`)
- Test: `backend/opencast/tests.py`

**Interfaces:**
- Produces: `Event.presenters: str` (Namen aus `raw["presenter"]`, nur `str`-Elemente, gestrippt, leere verworfen, mit `", "` verbunden; Nicht-Liste → `""`); `ScheduledEvent.presenters: str`.

- [ ] **Step 1: Failing tests** — `test_scheduled_events_reads_presenters` (Fake-Antwort mit `"presenter": ["Dr. Erika Muster", "Max Beispiel"]` → `"Dr. Erika Muster, Max Beispiel"`); `test_presenter_not_a_list` (`"presenter": "x"` → `""`); `test_sync_stores_presenters` (nach `sync_events` hat die Zeile den Wert und ein zweiter Sync mit geändertem Presenter überschreibt ihn). Bestehende Fake-Client-/Fixture-Muster in `opencast/tests.py` nutzen.
- [ ] **Step 2:** `docker compose exec backend python manage.py test opencast` → FAIL.
- [ ] **Step 3:** Implementieren wie oben.
- [ ] **Step 4:** Tests + ganze Suite + ruff grün; `npx tsc -b` grün.
- [ ] **Step 5: Commit** — `feat(opencast): store event presenters`

### Task 3: Ticket-Endpunkt und GitLab-Client

**Files:**
- Create: `backend/recorders/tickets.py`
- Modify: `backend/recorders/views.py` (`RecorderViewSet`: `@action(detail=True, methods=["post"], parser_classes=[MultiPartParser])` `ticket`), `backend/locale/de/LC_MESSAGES/django.po/.mo`
- Test: `backend/recorders/tests.py` (Klasse `TicketTests`)

**Interfaces:**
- Consumes: `MonitorSettings.gitlab_url`, `.gitlab_token_plain()`, `.tickets_enabled` (Task 1); `ScheduledEvent.presenters` (Task 2); bestehendes `RecorderStatus`; laufender Termin = `ScheduledEvent.objects.filter(recorder=recorder, start__lte=now, end__gt=now).order_by("start").first()` (gleiche Regel wie `RecorderSerializer._current`).
- Produces (`tickets.py`):
  - `class GitLabError(Exception)` — Meldung ohne Token.
  - `parse_project_url(url: str) -> tuple[str, str] | None` — `("https://gitlab.example.com", "g/sub/p")`; `/-/…` abgeschnitten.
  - `safe_web_url(web_url: object, configured_url: str) -> str | None`.
  - `build_title(recorder, message: str) -> str` — `"<Raum> (<stream_name>): <erste Zeile der Meldung>"`, Raum = `room_name` oder sonst Anzeigename; auf 255 Zeichen mit `…` gekürzt.
  - `build_description(recorder, message: str, user, now: datetime, image_markdown: str | None, screenshot_note: str | None) -> str` — Markdown-Abschnitte laut Spec (Meldung; Raum/Stream/Agent; Zeitpunkt in `Europe/Berlin`, Format `%d.%m.%Y %H:%M`; Status inkl. live seit / offline seit / Stille seit / Pegel dBFS / Agent-Status; laufender Termin mit Titel, Serie, Vortragende, geplante Zeit, Opencast-Status oder „kein laufender Termin“; Ersteller `Vorname Nachname <E-Mail>` bzw. Username; Link `<FRONTEND_BASE_URL ohne /> /raum/<id>`; Bild oder Hinweis). Texte gettext.
  - `upload_image(client: httpx.Client, base: str, project: str, token: str, data: bytes, filename: str, content_type: str) -> str` — gibt `markdown` aus der Antwort zurück; `GitLabError` bei Nicht-2xx/kein `markdown`.
  - `create_issue(client, base, project, token, title: str, description: str) -> dict`.
  - `create_ticket(recorder, message: str, user, screenshot: tuple[bytes, str] | None, now: datetime | None = None, client: httpx.Client | None = None) -> str` — Ablauf: Upload (Fehler → weiter ohne Bild, `screenshot_note`), Issue (Fehler → `GitLabError`), `safe_web_url` (None → `GitLabError`). Gibt `web_url` zurück.
- Produces (API): `POST /api/recorders/<id>/ticket/`, multipart `message` (Pflicht, gestrippt nicht leer, max. 2000), optional `screenshot` (Datei). Antworten: 201 `{"web_url": "…"}`; 400 Feldfehler; 409 `{"detail": …}` wenn `tickets_enabled` false; 502 `{"detail": …}` bei `GitLabError`. Permission `HasAccess` (vom ViewSet).

- [ ] **Step 1: Failing tests** — GitLab per `httpx.MockTransport` (Client via Parameter oder `unittest.mock.patch` von `recorders.tickets._client`) simulieren; Recorder „Hörsaal A“ / `cap-hs-a` mit laufendem `ScheduledEvent` (Titel „Mathe I“, Presenter „Dr. Erika Muster“) und Status live seit 10:00.
  - `test_parse_project_url` (Subgruppe, `/-/issues` angehängt, fehlender Pfad → None, `ftp:` → None).
  - `test_safe_web_url` (gleicher Host ok, fremder Host/`javascript:` → None).
  - `test_title_shortened_single_line` (Meldung 500 Zeichen mit `\n` → keine `\n`, `len <= 255`, beginnt mit `"Hörsaal A (cap-hs-a): "`).
  - `test_description_contains_details` (enthält Meldung, `cap-hs-a`, „Mathe I“, „Dr. Erika Muster“, `/raum/<id>`, Benutzer-E-Mail, Bild-Markdown).
  - `test_ticket_endpoint_uploads_and_creates` (PNG-Bytes `b"\x89PNG\r\n\x1a\n" + …`) → 201 mit `web_url`; Mock sah zuerst `/api/v4/projects/g%2Fp/uploads`, dann `/issues` mit `PRIVATE-TOKEN`, Issue-Beschreibung enthält das Upload-Markdown.
  - `test_upload_failure_still_creates_issue` (Upload 500 → Issue ohne Bild, Beschreibung enthält Hinweis, 201).
  - `test_without_screenshot` (kein Feld → kein Upload-Aufruf, Hinweis „kein Screenshot“).
  - `test_redirect_not_followed` (Issue-Antwort 302 `Location: https://evil.example/…` → 502, nur ein Request an Issues, keiner an evil).
  - `test_foreign_web_url_rejected` (201 mit `web_url` auf anderem Host → 502).
  - `test_invalid_image_rejected` (`b"<html>"` als `shot.png` → 400, kein GitLab-Request); `test_image_too_large` (> 5 MB → 400).
  - `test_blank_message_rejected` (400); `test_not_configured` (409); `test_requires_access` (Nutzer ohne Zugang → 403).
  - `test_token_not_in_error` (GitLab 401 → 502, Antworttext enthält das Token nicht).
- [ ] **Step 2:** `docker compose exec backend python manage.py test recorders.tests.TicketTests` → FAIL.
- [ ] **Step 3:** Implementieren. Bildprüfung über Magic Bytes (`\xff\xd8\xff` → `image/jpeg`, `\x89PNG\r\n\x1a\n` → `image/png`); Dateiname `ansehbar-<stream_name>-<YYYYmmdd-HHMM>.jpg|png`. Logging: Warnung mit Recorder-ID und HTTP-Status, nie Token/Header.
- [ ] **Step 4:** `makemessages -l de`, Übersetzungen eintragen, `compilemessages`; ganze Suite + ruff grün.
- [ ] **Step 5: Commit** — `feat(recorders): create GitLab tickets with status, Opencast details and screenshot`

### Task 4: Frontend — Button, Dialog, Screenshot, Einstellungen

**Files:**
- Create: `frontend/src/media/snapshot.ts`, `frontend/src/components/TicketDialog.tsx`, `frontend/src/media/snapshot.test.ts`
- Modify: `frontend/src/media/HlsPlayer.tsx` (`crossOrigin="anonymous"` am `<video>`, als JSX-Attribut, damit es vor jedem `src`/`attachMedia` gesetzt ist), `frontend/src/components/RecorderTile.tsx`, `frontend/src/pages/Overview.tsx` (Flag durchreichen), `frontend/src/api.ts`, `frontend/src/pages/admin/SettingsAdmin.tsx`, `frontend/src/locales/de/translation.json`
- Test: `frontend/src/media/snapshot.test.ts`

**Interfaces:**
- Consumes: `POST /api/recorders/<id>/ticket/` (Task 3), Settings-Felder und `whoami.tickets_enabled` (Task 1).
- Produces:
  - `api.ts`: `Whoami.tickets_enabled: boolean`; `MonitorSettings.gitlab_url: string`, `gitlab_token_set: boolean`, `gitlab_token?: string` (nur beim Senden); `api.recorders.ticket(id: number, message: string, screenshot: Blob | null) => Promise<{ web_url: string }>` mit `FormData` (Datei als `screenshot.jpg`).
  - `snapshot.ts`: `snapshotSize(videoWidth: number, videoHeight: number, maxWidth = 1920): { width: number; height: number } | null` (null bei 0-Maßen; skaliert proportional auf max. Breite, ganze Pixel); `captureFrame(video: HTMLVideoElement | null): Promise<Blob | null>` (Canvas, `toBlob("image/jpeg", 0.9)`; jede Ausnahme, z. B. `SecurityError`, oder fehlendes Bild → `null`).
  - `TicketDialog({ recorder, screenshot, onClose })`: natives `<dialog>` wie `ConfirmDialog` (Portal, Escape schließt, Fokus zurück). Inhalt: Titel „Create ticket for {{room}}“, Vorschau-`<img>` aus `URL.createObjectURL(screenshot)` (Revoke beim Unmount) oder Text „No screenshot available – the ticket will be sent without one.“, Pflicht-Textarea „Error description“ (`maxLength` 2000), Buttons „Cancel“ / „Create ticket“ (deaktiviert bei leerem Text oder während des Sendens, Label dann „Creating…“). Erfolg: Text „Ticket created.“ + Link „Open ticket“ (`target="_blank" rel="noopener noreferrer"`, nur wenn `https?:`), Button „Close“. Fehler: `role="alert"` mit `ApiError.message`, Feldfehler an der Textarea.
  - `RecorderTile`: neue Prop `ticketsEnabled?: boolean`; bei true kleiner runder Icon-Button (lucide `TicketPlus` oder `MessageSquareWarning`), `aria-label`/`title` „Create ticket for {{room}}“, rechts in der Fußzeile vor dem Ton-Button, sichtbar für alle Zustände. Klick: zuerst `captureFrame(article.querySelector("video"))` (Ref auf `<article>`), dann Dialog mit dem Ergebnis öffnen.
  - `SettingsAdmin`: neues `<fieldset>` „GitLab tickets“ nach „Retention“: Feld „GitLab project URL“ (Placeholder `https://gitlab.example.com/group/project`), Passwortfeld „Access token“ mit Hinweis „Token set“ bzw. „No token set“ und Checkbox „Remove token“; Hilfetext (Project Access Token, Rolle „Reporter“, nur Scope `api`, Ablaufdatum setzen; ein geänderte URL braucht ein neues Token; privates Projekt empfohlen, Screenshots können Personen zeigen). Beim Speichern `gitlab_token` nur mitsenden, wenn eingegeben (oder `""` bei „Remove token“).

- [ ] **Step 1: Failing test** — `snapshot.test.ts`: `snapshotSize(0, 0)` → `null`; `snapshotSize(1280, 720)` → `{width:1280,height:720}`; `snapshotSize(3840, 2160)` → `{width:1920,height:1080}`; `snapshotSize(1000, 333, 500)` → `{width:500,height:167}`; `captureFrame(null)` → `null`.
- [ ] **Step 2:** `docker compose exec frontend npm test` → FAIL.
- [ ] **Step 3:** Implementieren wie oben; deutsche Übersetzungen ergänzen.
- [ ] **Step 4:** `npm test`, `npx tsc -b`, `npm run check:i18n` grün. Manuell im Browser (Dev-Stack, Login `admin-demo`): Einstellungen speichern ohne/mit Token, Button erscheint, Dialog mit Screenshot einer live Kachel öffnet sich; Absenden gegen einen nicht erreichbaren GitLab-Host zeigt die 502-Meldung (kein echtes GitLab nötig).
- [ ] **Step 5: Commit** — `feat(frontend): ticket button with screenshot on overview tiles`

### Task 5: Dokumentation

**Files:**
- Modify: `docs/KONFIGURATION.md` (neuer Abschnitt „GitLab-Tickets“: Token anlegen, URL, Verschlüsselung/`TOKEN_ENCRYPTION_KEY`, URL-Wechsel löscht Token, Datenschutz, Fehlersuche-Zeilen), `docs/deployment.md` (`TOKEN_ENCRYPTION_KEY` in `.env`-Schritt und Sicherung erwähnen: ohne den Schlüssel ist das Token nach Restore unlesbar), `website/anleitung/uebersicht.md`, `website/anleitung/einstellungen.md`, `website/en/guide/overview.md`, `website/en/guide/settings.md`, `CLAUDE.md` (Aufbau: `recorders/tickets.py`), README Funktionsliste falls vorhanden.

- [ ] **Step 1:** Texte schreiben (DE/EN gleichwertig, Beispiele fiktiv).
- [ ] **Step 2:** `docker run --rm -v "$PWD":/w -w /w python:3.12-slim sh -c "pip install -q -r website/requirements.txt && mkdocs build --strict -f website/mkdocs.yml && mkdocs build --strict -f website/mkdocs.en.yml"` → ohne Warnungen.
- [ ] **Step 3: Commit** — `docs: GitLab tickets`
