# ansehBAR Stufe 1 (Monitor mit fester Liste) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ansehBAR löst den alten Streaming-Monitor ab: Login mit Zugangsprüfung,
gepflegte Rekorderliste, Live-Erkennung im Backend, PC-Übersicht mit Kacheln,
Smartphone-Raumansicht, Ton pro Kachel und Pegelanzeige im Browser.

**Architecture:** Ein -bar-Tool aus dem basicbar-Copier-Template (Django/DRF +
React/Vite). Ein eigener Container `monitor` (derselbe Backend-Code,
`manage.py run_monitor`) prüft periodisch alle aktiven Rekorder über eine
austauschbare `StreamSource` (erste Implementierung: HLS) und schreibt
den Status in Postgres. Die SPA fragt den Status per Polling ab und spielt die
Streams direkt vom Streaming-Server mit hls.js.

**Tech Stack:** Django 5.1, DRF, basicbar-auth/-integrations, Postgres 16, httpx;
React 18, react-router 6, Tailwind 3, @basicbar/ui, hls.js 1.6, vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`. Stufe 1 = Abschnitte
3, 4, 5.0–5.5 ohne alles, was Opencast braucht.

## Global Constraints

- Copier-Antworten: `project_slug=ansehbar`, `project_title=ansehBAR`,
  `brand_hue=335`, `neutral_hue=220`, `frontend_port=5179`,
  `backend_port=8007`, `keycloak_port=8086`, `postgres_port=5438`,
  `ci_host=gitlab`, `use_lti=false`, `project_description="Kontrolle der
  Live-Streams aus den Aufzeichnungsräumen"`.
- SPDX-Header (`Apache-2.0`, `Copyright 2026 Universität Osnabrück (virtUOS)`)
  in jeder neuen Quelldatei.
- Kein Django-Admin für Fachdaten. Jede Pflegemaske gehört ins Frontend.
- UI-Texte: Englisch als i18n-Key, Deutsch in
  `frontend/src/locales/de/translation.json`.
- Nie Browser-Dialoge (`window.confirm/alert/prompt`).
- Status immer mit Text **und** Symbol, nie nur über Farbe. Akzent (brand) ist
  nie eine Statusfarbe.
- ansehBAR schreibt **nie** nach Keycloak.
- Stream-Namen sind case-sensitiv (`cap-90-R12`). Niemals
  kleinschreiben.
- Standard-URL-Vorlage:
  `https://streaming.example.org/live/{stream}/playlist.m3u8`.
- „Live“ = die Chunklist existiert und ihre Media-Sequence hat sich innerhalb
  von `3 × TARGETDURATION` Sekunden geändert. HTTP 200 auf die Master-Playlist
  allein reicht nicht. Ein Offline-Stream liefert 404.
- Alle Befehle laufen im Container: `docker compose exec backend …` bzw.
  `docker compose exec frontend …`.

## Review Focus

1. **Stream endet während eine Kachel spielt:** Die Kachel verschwindet. Die
   anderen Player laufen ungestört weiter (kein Remount), und die hls.js-Instanz
   der Kachel wird zerstört. Getestet in Task 8 (`mergeRecorders` behält
   Objektidentität) und Task 7 (`HlsPlayer`-Cleanup).
2. **Ein Rekorder hängt (Timeout, DNS-Fehler, 500):** Der Zyklus wird nicht
   blockiert, andere Rekorder bleiben korrekt. Der betroffene geht auf
   `unknown`, nicht auf `offline`. Getestet in Task 5.
3. **Encoder eingefroren:** Die Master-Playlist liefert 200, die Chunklist
   bleibt stehen. Nach dem Schwellwert gilt der Stream als `offline`.
   Getestet in Task 4.
4. **Einladungen mit anderer Groß/Kleinschreibung, Leerzeichen oder einem
   Nutzer ohne E-Mail:** Der Zugang wird trotzdem korrekt erkannt bzw.
   abgelehnt. Getestet in Task 2.
5. **Stream-Namen mit Großbuchstaben oder gefährlichen Zeichen:**
   Großbuchstaben bleiben erhalten. `/`, `..`, `?`, `#` und Leerzeichen werden
   bei der Eingabe abgelehnt. Getestet in Task 3.

---

### Task 1: Gerüst aus basicbar, Repo, Pakete, Dev-Realm

**Files:**
- Create: alles aus dem Template im Projektwurzelverzeichnis `~/dev/ansehbar`
  (bestehende `alt/`, `docs/`, `.superpowers/` bleiben).
- Modify: `.gitignore` (+ `alt/`, `.superpowers/`, `.DS_Store`)
- Modify: `backend/requirements.txt`, `frontend/package.json` (Paketversionen)
- Modify: `keycloak/realm-export.json`
- Modify: `docker-compose.yml`, `docker-compose.prod.yml`, `.env.prod.example`

**Interfaces:**
- Produces: lauffähiger Stack. Gruppe `ansehbar-users` im Dev-Realm;
  `demo` und `admin-demo` sind Mitglied; neuer Nutzer `outsider`/`demo` ohne
  Gruppe. Env-Variablen `ANSEHBAR_ACCESS_GROUP` (Default `ansehbar-users`),
  `ANSEHBAR_BOOTSTRAP_USERS` (kommagetrennt, Default leer),
  `ANSEHBAR_ACCESS_CONTACT` (Default leer) und `MONITOR_INTERVAL_SECONDS`
  (Default `10`) sind in `config/settings.py` gelesen und in beiden
  Compose-Dateien durchgereicht.

- [ ] **Step 1:** Template erzeugen:
  `pipx run copier copy --vcs-ref HEAD ~/dev/basicbar ~/dev/ansehbar --trust --defaults --data project_slug=ansehbar --data project_title=ansehBAR --data brand_hue=335 --data frontend_port=5179 --data backend_port=8007 --data keycloak_port=8086 --data postgres_port=5438 --data ci_host=gitlab --data "project_description=Kontrolle der Live-Streams aus den Aufzeichnungsräumen"`.
  Danach `.copier-answers.yml`: `_src_path` auf
  `https://github.com/virtUOS/basicbar.git` setzen, wie bei kalkulierBAR.
- [ ] **Step 2:** Pakete heben: `auth/v0.2.2`, `integrations/v0.3.0`,
  `ui/v0.9.1`. Die Migrationsschritte aus `~/dev/basicbar/CHANGELOG.md`
  für alle dazwischenliegenden Releases ausführen.
- [ ] **Step 3:** Realm: Gruppe `ansehbar-users` anlegen und `demo` sowie
  `admin-demo` hinzufügen. Nutzer `outsider` (Passwort `demo`, E-Mail
  `outsider@example.org`, keine Gruppe) anlegen. Der Gruppen-Mapper
  `groups` existiert schon.
- [ ] **Step 4:** Settings und Env-Variablen aus *Produces* ergänzen. In
  `settings.py`: `ANSEHBAR_BOOTSTRAP_USERS = _env_list("ANSEHBAR_BOOTSTRAP_USERS", "")`.
- [ ] **Step 5:** Stack starten und prüfen:
  `docker compose up -d && docker compose exec backend python manage.py migrate && docker compose exec backend python manage.py test`
  → `OK`. `docker compose exec frontend npx tsc -b` → keine Fehler. Login auf
  http://localhost:5179 mit `demo`/`demo` zeigt „Signed in as demo“.
- [ ] **Step 6:** `git init -b main && git add -A && git commit -m "chore: Gerüst aus basicbar-Template"`,
  dann `git switch -c feature/stufe-1`.

### Task 2: Zugangsprüfung und Einladungen (Backend)

**Files:**
- Create: `backend/accounts/access.py`
- Modify: `backend/accounts/models.py` (+ `Invitation`), neue Migration
- Modify: `backend/accounts/permissions.py` (+ `HasAccess`)
- Modify: `backend/accounts/views.py` (whoami; `InvitationViewSet`)
- Create: `backend/config/api_urls.py`; Modify: `backend/config/urls.py` (`path("api/", include("config.api_urls"))`)
- Test: `backend/accounts/tests.py`

**Interfaces:**
- Produces:
  - `accounts.access.normalize_identifier(value: str) -> str`: `strip().casefold()`.
  - `accounts.access.has_access(user) -> bool`. True, wenn `user.is_authenticated`
    und eines davon zutrifft:
    - `settings.ANSEHBAR_ACCESS_GROUP` in `user.claims[OIDC_GROUPS_CLAIM]`
      (Liste oder String),
    - Benutzername oder E-Mail (normalisiert) in `ANSEHBAR_BOOTSTRAP_USERS`,
    - ein `Invitation` mit passendem `identifier`.
    - Superuser haben immer Zugang (Notzugang über ModelBackend).
  - `accounts.models.Invitation(identifier: CharField(254, unique), note: CharField(200, blank), created_by: FK User null SET_NULL, created_at: auto)`.
    `save()` normalisiert `identifier`.
  - `accounts.permissions.HasAccess` (DRF-Permission, nutzt `has_access`).
  - whoami-Payload: zusätzlich `has_access: bool` und `access_contact: str`
    (aus `ANSEHBAR_ACCESS_CONTACT`).
  - REST `/api/invitations/` (list, create, destroy), Permission `HasAccess`,
    ohne Pagination. Felder `id, identifier, note, created_by_name, created_at`.
    Ein Duplikat ergibt 400.
  - REST `/api/users/?search=<q>` (nur list, max. 20, Suche in username,
    E-Mail und Name; Felder `id, username, email, display_name`). Gebraucht von
    der Einladungsmaske jetzt und von der Empfängerauswahl in Stufe 3.

- [ ] **Step 1: Failing tests** in `accounts/tests.py`:
  - `test_group_claim_grants_access`: `claims={"groups": ["ansehbar-users"]}` → True.
  - `test_group_claim_as_string`: `claims={"groups": "ansehbar-users"}` → True.
  - `test_no_group_no_invite_denied`: `claims={"groups": ["other"]}` → False.
  - `test_invitation_by_username_case_insensitive`: Invitation `" Max.Muster "`,
    User `username="max.muster"` → True.
  - `test_invitation_by_email_when_username_differs`: Invitation
    `max@example.org`, User mit dieser E-Mail und einem anderen
    Benutzernamen → True.
  - `test_user_without_email_not_matched_by_empty_invite`: User mit `email=""`
    und keine Einladung → False. Eine Einladung mit leerem `identifier` wird
    beim Speichern abgelehnt.
  - `test_bootstrap_user` mit `override_settings(ANSEHBAR_BOOTSTRAP_USERS=["Boss"])`
    und `username="boss"` → True.
  - `test_revoked_invitation_denies_next_request`: GET `/api/invitations/` → 200,
    Einladung löschen, dieselbe Session erneut → 403.
  - `test_whoami_reports_has_access_false_for_outsider`.
  - `test_invitations_api_requires_access` (403 ohne Zugang, 201 beim Anlegen
    mit Zugang, 400 bei einem Duplikat in anderer Schreibweise).
  - `test_user_search_limited_and_requires_access`.
- [ ] **Step 2:** `docker compose exec backend python manage.py test accounts` → FAIL.
- [ ] **Step 3:** Implementieren wie unter *Produces*, Migration
  `makemigrations accounts`.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(accounts): Zugang über IdP-Gruppe, Einladungen und Bootstrap-Liste`.

Hinweis: Gruppenentzug im IdP wirkt erst beim nächsten Login, weil die Claims
nur dort aktualisiert werden. Das ist bewusst so und kommt als Hinweis in die
README.

### Task 3: Rekorder, Monitor-Einstellungen, Startdaten (Backend)

**Files:**
- Create: App `backend/recorders/` (`models.py`, `serializers.py`, `views.py`, `validators.py`, `tests.py`, `migrations/0001_initial.py`, `migrations/0002_seed_recorders.py`)
- Modify: `backend/config/settings.py` (INSTALLED_APPS), `backend/config/api_urls.py`

**Interfaces:**
- Produces:
  - `Recorder(room_name: CharField(100), stream_name: CharField(100, unique), active: Bool=True, needs_review: Bool=False, created_at, updated_at)`,
    Ordering `room_name`.
  - `RecorderStatus(recorder: OneToOne Recorder related_name="status", state: CharField choices live|offline|unknown default unknown, live_since: DateTime null, checked_at: DateTime null, media_sequence: BigInt null, sequence_changed_at: DateTime null, detail: CharField(200, blank))`.
  - `MonitorSettings` (Singleton, `pk=1`, `MonitorSettings.load() -> MonitorSettings`):
    `url_template: CharField(300)` mit der Standard-URL-Vorlage als Default,
    `stale_factor: PositiveSmallInteger=3`.
  - `recorders.validators.validate_stream_name(value: str) -> None`, Regex
    `^[A-Za-z0-9][A-Za-z0-9._-]*$`.
  - `recorders.validators.validate_url_template(value: str) -> None`: Schema
    `https://` (oder `http://` nur bei DEBUG), genau ein `{stream}`.
  - REST `/api/recorders/` (list, retrieve, create, partial_update; kein
    delete; ohne Pagination; Permission `HasAccess`). Felder:
    - `id, room_name, stream_name, active, needs_review, playback_url`,
    - `status` mit `{state, live_since, checked_at}`.
    - `?active=1` filtert auf aktive.
    - `playback_url = settings.url_template.format(stream=stream_name)`.
  - REST `/api/settings/monitor/` GET/PUT (`url_template`, `stale_factor` 2..10).

- [ ] **Step 1: Failing tests** in `recorders/tests.py`:
  - `test_stream_name_keeps_case`: Anlegen mit `cap-90-R12` → gespeichert
    und in `playback_url` unverändert.
  - `test_stream_name_rejects_unsafe` parametrisiert über `["a/b", "..", "a b", "a?x", "a#x", ""]` → 400.
  - `test_list_includes_status_and_playback_url`.
  - `test_list_requires_access` → 403 für `outsider`.
  - `test_delete_not_allowed` → 405.
  - `test_settings_rejects_template_without_placeholder` → 400.
  - `test_seed_created_33_active_recorders`: nach Migration 33 Rekorder,
    darunter `stream_name="rec-hall"` mit `room_name="20/R06 (Hall)"` und
    `stream_name="cap-90-r12"` mit `room_name="90/R12"`.
- [ ] **Step 2:** Tests laufen lassen → FAIL.
- [ ] **Step 3:** Implementieren. Datenmigration `0002_seed_recorders`:
  - Quelle ist das `recorders`-Array aus `alt/streaming-monitor/index.html`
    (33 Einträge, als Literal in die Migration kopiert; Schreibweise exakt
    übernehmen).
  - `room_name` = Teil nach dem ersten `-`, dann `-` → `/` und
    Großbuchstaben. Beispiele: `rec-40-r28` → `40/R28`,
    `cap-10-r16` → `10/R16`.
  - Ausnahme: `rec-hall` → `20/R06 (Hall)`.
  - Alle Rekorder `active=True`, `needs_review=False`.
  - `RecorderStatus` wird per `post_save`-Signal zu jedem Recorder angelegt;
    die Migration legt die Status-Datensätze selbst an.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(recorders): Rekorderliste, Monitor-Einstellungen, Startdaten aus altem Monitor`.

### Task 4: StreamSource und Live-Bewertung

**Files:**
- Create: `backend/streams/__init__.py`, `backend/streams/sources.py`, `backend/streams/hls.py`, `backend/streams/tests.py`
- Modify: `backend/requirements.txt` (+ `httpx==0.28.1`)

**Interfaces:**
- Produces (`streams` hat keine Django-Models und importiert nichts aus Django):
  - `@dataclass(frozen=True) class Probe: reachable: bool; exists: bool; media_sequence: int | None; target_duration: float | None; detail: str = ""`.
    Bedeutung der Kombinationen:
    - `reachable=False`: Netzwerkfehler, Timeout oder 5xx.
    - `exists=False`: 404/410.
  - `class StreamSource(Protocol): def playback_url(self, stream_name: str) -> str: ...; def probe(self, stream_name: str) -> Probe: ...`
  - `class HlsStreamSource(url_template: str, client: httpx.Client, timeout: float = 5.0)`.
    `probe` lädt die Master-Playlist, folgt der ersten Variante (relative URI
    gegen die Master-URL auflösen) und liest `#EXT-X-MEDIA-SEQUENCE` und
    `#EXT-X-TARGETDURATION`. Eine Media-Playlist ohne Varianten wird direkt
    gelesen.
  - `streams.hls.parse_master(text: str) -> list[str]`,
    `streams.hls.parse_media(text: str) -> tuple[int | None, float | None]`.
  - `@dataclass(frozen=True) class LiveState: state: str; live_since: datetime | None; media_sequence: int | None; sequence_changed_at: datetime | None; detail: str`.
  - `streams.sources.evaluate(prev: LiveState, probe: Probe, now: datetime, stale_factor: int) -> LiveState`:
    - `reachable=False` → `unknown`; die übrigen Felder von `prev` bleiben.
    - `exists=False` → `offline`, `live_since=None`.
    - Die Sequence hat sich geändert, oder `prev.media_sequence is None` →
      `sequence_changed_at=now`.
    - `live`, wenn `now - sequence_changed_at <= stale_factor × target_duration`
      (Fallback `target_duration=6`), sonst `offline`.
    - Bei einem Wechsel nach `live` gilt `live_since = now`. Bleibt der Zustand
      `live`, bleibt `live_since` erhalten.
    - Erstes Erkennen: `prev.media_sequence is None` mit existierender
      Chunklist zählt sofort als `live`.

- [ ] **Step 1: Failing tests** in `streams/tests.py` (`unittest`, `httpx.MockTransport`):
  - `test_parse_master_returns_variant_uris` mit dem HLS-Beispiel
    `#EXT-X-STREAM-INF:BANDWIDTH=…\nchunklist_w123.m3u8`.
  - `test_parse_media_reads_sequence_and_target`.
  - `test_probe_404_means_not_exists`.
  - `test_probe_timeout_means_unreachable` (Transport wirft `httpx.ConnectTimeout`).
  - `test_probe_resolves_relative_chunklist`.
  - `test_evaluate_frozen_encoder_goes_offline`: gleiche Sequence, `now`
    liegt 19 s nach `sequence_changed_at`, `target=6`, `factor=3` → `offline`.
    Bei 17 s → `live`.
  - `test_evaluate_keeps_live_since_while_live`.
  - `test_evaluate_unreachable_keeps_previous_fields_but_unknown`.
- [ ] **Step 2:** `docker compose exec backend python manage.py test streams` → FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(streams): HLS-Live-Erkennung hinter austauschbarer StreamSource`.

### Task 5: Monitor-Prozess

**Files:**
- Create: `backend/recorders/monitor.py`, `backend/recorders/management/commands/run_monitor.py`
- Modify: `backend/recorders/tests.py`, `docker-compose.yml`, `docker-compose.prod.yml`

**Interfaces:**
- Consumes: `Recorder`, `RecorderStatus`, `MonitorSettings` (Task 3);
  `StreamSource`, `HlsStreamSource`, `evaluate`, `LiveState` (Task 4).
- Produces:
  - `recorders.monitor.run_cycle(source: StreamSource, now: datetime, max_workers: int = 8) -> int`.
    Prüft alle aktiven Rekorder parallel (ThreadPoolExecutor, nur `probe` im
    Thread), schreibt die `RecorderStatus` im Hauptthread und gibt die Zahl
    geprüfter Rekorder zurück. Eine Exception in einem `probe` wird wie
    `reachable=False` behandelt. Inaktive Rekorder werden auf `unknown`
    gesetzt und nicht geprüft.
  - `manage.py run_monitor [--once]`: Schleife mit `MONITOR_INTERVAL_SECONDS`.
    Pro Zyklus lädt sie `MonitorSettings` neu, damit Änderungen der
    URL-Vorlage ohne Neustart greifen. Sie loggt eine Zeile pro Zyklus
    (Anzahl live/offline/unknown) und beendet sich sauber bei SIGTERM.
  - Compose-Dienst `monitor`: gleiches Image und gleiche Env wie `backend`,
    `command: python manage.py run_monitor`, `depends_on: db`.

- [ ] **Step 1: Failing tests:**
  - `test_run_cycle_one_failing_probe_does_not_affect_others`: Die
    Fake-Source wirft für Rekorder A, B ist live. Erwartet: A `unknown`, B
    `live`, Rückgabe 2 bei 2 aktiven Rekordern.
  - `test_run_cycle_sets_inactive_unknown_and_skips_probe`.
  - `test_run_once_command_exits`: `call_command("run_monitor", "--once")` mit
    gepatchter Source.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** PASS. Danach `docker compose up -d monitor` und
  `docker compose logs monitor` → Zykluszeilen. Tagsüber während der
  Vorlesungszeit zeigt `curl -s localhost:8007/api/recorders/` (mit Session)
  echte `live`-Status.
- [ ] **Step 5:** Commit `feat(monitor): run_monitor prüft Rekorder periodisch`.

### Task 6: Frontend-Grundlage: API, Routing, Zugang, Polling

**Files:**
- Modify: `frontend/package.json` (+ `hls.js@^1.6.15`, dev `vitest@^3`, Script `"test": "vitest run"`)
- Modify: `frontend/src/api.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`
- Create: `frontend/src/pages/Landing.tsx`, `frontend/src/pages/NoAccess.tsx`, `frontend/src/useRecorders.ts`, `frontend/src/recorders.ts`, `frontend/src/recorders.test.ts`
- Modify: `.gitlab-ci.yml` (`frontend-build`: zusätzlich `npm test`)

**Interfaces:**
- Consumes: REST aus Task 2 und 3.
- Produces:
  - Typen in `api.ts`:
    - `RecorderState = "live" | "offline" | "unknown"`
    - `Recorder { id: number; room_name: string; stream_name: string; active: boolean; needs_review: boolean; playback_url: string; status: { state: RecorderState; live_since: string | null; checked_at: string | null } }`
    - `Invitation { id: number; identifier: string; note: string; created_by_name: string; created_at: string }`
    - `MonitorSettings { url_template: string; stale_factor: number }`
    - `UserHit { id: number; username: string; email: string; display_name: string }`
    - `Whoami` + `has_access: boolean; access_contact: string`
  - `api.recorders.list()`, `.get(id)`, `.create(data)`, `.update(id, data)`;
    `api.invitations.list()`, `.create({identifier, note})`, `.remove(id)`;
    `api.users.search(q)`; `api.settings.get()`, `.put(data)`.
  - `recorders.ts`:
    - `mergeRecorders(prev: Recorder[], next: Recorder[]) -> Recorder[]`: gibt
      für unveränderte Einträge das **alte Objekt** zurück (strukturelle
      Gleichheit).
    - `sortForOverview(list: Recorder[]) -> Recorder[]`: zuerst `live`, dann
      nach `room_name` mit `localeCompare(…, "de", {numeric: true})`.
    - `formatClock(iso: string, locale: string) -> string` (`HH:MM`).
    - `formatDuration(fromIso: string, now: Date) -> string` (`47:12` bzw.
      `1:47:12`).
  - `useRecorders(intervalMs = 8000) -> { recorders: Recorder[]; error: string | null; loading: boolean }`:
    pollt, nutzt `mergeRecorders` und pausiert bei `document.hidden`.
  - Routen:
    - `/` Overview (Task 8)
    - `/raum/:id` RoomView (Task 9)
    - `/verwaltung/rekorder`, `/verwaltung/einladungen`,
      `/verwaltung/einstellungen` (Task 10)
  - App-Gate:
    - nicht angemeldet → `Landing` (Login-Knopf),
    - angemeldet ohne Zugang → `NoAccess` (zeigt `access_contact`, falls
      gesetzt, und Abmelden),
    - sonst die Kopfzeile mit Navigation „Übersicht · Verwaltung“ und Outlet.
    - Die Container-Breite wird auf volle Breite geändert (`max-w-3xl` raus).

- [ ] **Step 1: Failing tests** `recorders.test.ts`:
  - `mergeRecorders keeps identity of unchanged items` (`toBe`).
  - `mergeRecorders replaces changed status`.
  - `sortForOverview puts live first then numeric room order`: live
    `"90/R12"` vor offline `"40/R22"`; unter den Offline-Rekordern
    `"40/R22"` < `"40/R05"` < `"70/R01"`, weil Ziffern vor Buchstaben
    sortieren.
  - `formatDuration` für 47 min 12 s und 1 h 47 min 12 s.
- [ ] **Step 2:** `docker compose exec frontend npm test` → FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `npm test` → PASS, `npx tsc -b` → OK. Manuell: Mit
  `outsider` erscheint die „Kein Zugang“-Seite, mit `demo` die Kopfzeile mit
  Navigation.
- [ ] **Step 5:** Commit `feat(frontend): API-Client, Routing, Zugangs-Gate, Polling`.

### Task 7: Player, Audio-Engine und Pegelanzeige

**Files:**
- Create: `frontend/src/media/HlsPlayer.tsx`, `frontend/src/media/audio.ts`, `frontend/src/media/level.ts`, `frontend/src/media/level.test.ts`, `frontend/src/media/LevelMeter.tsx`, `frontend/src/media/AudioUnlockButton.tsx`, `frontend/src/media/AudioContextProvider.tsx`

**Interfaces:**
- Produces:
  - `level.ts`:
    - `rmsToDbfs(samples: Float32Array) -> number`; Stille ergibt `-Infinity`.
    - `dbfsToMeter(db: number) -> number`: Skala `-60 dBFS → 0`, `0 dBFS → 1`,
      geklemmt.
    - `describeLevel(db: number) -> "silent" | "low" | "normal"`: Schwellen
      `< -50` → silent, `< -30` → low, sonst normal.
  - `AudioContextProvider` / `useAudio()` liefert
    `{ unlocked: boolean; unlock(): Promise<void>; audibleId: number | null; setAudible(id: number | null): void; attach(id: number, el: HTMLVideoElement): (() => void) | null; analyser(id: number): AnalyserNode | null }`.
    - **Ein** `AudioContext` pro Seite.
    - Pro Element: `MediaElementSource → Analyser → Gain → destination`.
    - Gain ist 1 nur für `audibleId`, sonst 0.
    - Das Video-Element ist nach `unlock` **nicht** `muted`. Vor `unlock`
      bleibt es `muted`, damit Autoplay klappt.
  - `HlsPlayer({ id, src, className, onError? })`:
    - Nutzt hls.js, wenn `Hls.isSupported()`, sonst natives HLS über
      `canPlayType("application/vnd.apple.mpegurl")`.
    - `autoplay`, `playsInline`, initial `muted`.
    - Beim Unmount: `hls.destroy()` und `detach()`.
    - Bei einem fatalen hls.js-Fehler: `onError` und ein eigener Retry
      (max. alle 10 s).
  - `LevelMeter({ id })`:
    - Senkrechter Balken per `requestAnimationFrame` aus `analyser(id)`.
    - Vor `unlock` zeigt er einen grauen Zustand mit sichtbarem Text bzw. Label
      „Level after click“.
    - Ohne Analyser (natives HLS) zeigt er „Level unavailable“.
    - `role="meter"` mit `aria-valuetext` aus `describeLevel`. Der Text
      ändert sich nur, wenn sich die Stufe ändert.
    - Respektiert `prefers-reduced-motion`: dann Aktualisierung höchstens
      4×/s.
  - `AudioUnlockButton`: Text „Enable level & sound“; nach dem Klick
    ausgeblendet.

- [ ] **Step 1: Failing tests** `level.test.ts`:
  - `rmsToDbfs of full-scale sine ≈ -3.01`.
  - `rmsToDbfs of zeros is -Infinity`.
  - `dbfsToMeter clamps (-80 → 0, 0 → 1, -30 → 0.5)`.
  - `describeLevel thresholds (-55 silent, -40 low, -20 normal)`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** PASS. Dazu ein manueller Test auf einer Wegwerf-Route oder
  in Task 8 mit einem echten Live-Stream: Der Pegel schlägt nach dem
  Freischalten aus, obwohl nichts zu hören ist. Wird ein Ton eingeschaltet,
  ist nur dieser hörbar.
- [ ] **Step 5:** Commit `feat(media): HLS-Player, Audio-Engine, Pegelanzeige`.

### Task 8: PC-Übersicht und Raumliste auf dem Smartphone

**Files:**
- Create: `frontend/src/pages/Overview.tsx`, `frontend/src/components/RecorderTile.tsx`, `frontend/src/components/StatusBadge.tsx`, `frontend/src/components/RoomList.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `useRecorders`, `sortForOverview`, `formatClock` (Task 6);
  `HlsPlayer`, `LevelMeter`, `useAudio`, `AudioUnlockButton` (Task 7).
- Produces:
  - `StatusBadge({ state, since? })`:
    - `live` → „● LIVE“ (rot),
    - `offline` → „○ No stream“ (neutral),
    - `unknown` → „? Status unknown“ (gelb).
    - Immer Text plus Symbol.
  - `RecorderTile({ recorder })`: Player 16:9 mit `LevelMeter` rechts und Badge
    oben links. Darunter Raumname groß, **„since HH:MM“ groß und fett**,
    Stream-Name klein, Ton-Knopf mit `aria-pressed` und Label „Turn on
    sound for {room}“.
  - `Overview`:
    - Kopfzeile mit Chips **Now (n)** und **All rooms (n)** (der Chip „Today“
      kommt in Stufe 2), Suchfeld (Raum oder Stream) und `AudioUnlockButton`.
    - „Now“: Kacheln nur für `live`, darunter eine Zeile „Currently without
      stream: …“ mit Links auf `/raum/:id`.
    - „All rooms“: Kacheln für alle aktiven Rekorder. Kacheln ohne Stream
      zeigen eine gestreifte Fläche mit dem Text „No stream – the recorder is
      not sending right now“ statt eines Players.
    - Grid `repeat(auto-fill, minmax(22rem, 1fr))`.
    - Unter `md` (768 px) wird statt der Kacheln `RoomList` gezeigt: Zeilen mit
      Badge, Raum und „since HH:MM“, Link auf `/raum/:id`.
    - Leerzustand bei „Now“ ohne Live-Stream: „No recording room is streaming
      right now.“
    - Polling-Fehler: ein dezentes Banner „Status could not be updated – last
      update HH:MM“, die Player laufen weiter.
    - Tastatur: Kacheln sind `article`-Elemente mit Überschrift, und der
      Raumname ist ein Link auf `/raum/:id`.

- [ ] **Step 1: Test** in `recorders.test.ts` ergänzen:
  `filterOverview(list, "now", "15/e")` liefert nur live-Rekorder, deren
  `room_name` oder `stream_name` `"15/e"` case-insensitiv enthält.
  `filterOverview(list: Recorder[], mode: "now" | "all", query: string) -> Recorder[]`
  lebt in `recorders.ts`.
- [ ] **Step 2:** FAIL → implementieren → PASS.
- [ ] **Step 3:** Seiten und Komponenten implementieren.
- [ ] **Step 4:** Manuell im Browser (Desktop- und Mobile-Viewport), während
  echte Streams laufen:
  - Kacheln erscheinen.
  - Wenn ein Stream endet, verschwindet seine Kachel. Die anderen laufen ohne
    Ruckler weiter.
  - Ton-Exklusivität funktioniert.
  - Unter 768 px erscheint die Raumliste.
  - Tab-Reihenfolge ist sinnvoll, und Badges sind ohne Farbe verständlich
    (Graustufen-Check).
- [ ] **Step 5:** Commit `feat(overview): PC-Übersicht mit Kacheln, Raumliste mobil`.

### Task 9: Raumansicht (Smartphone-Schwerpunkt)

**Files:**
- Create: `frontend/src/pages/RoomView.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `api.recorders.get`, `useRecorders` (für „Raum wechseln“),
  `HlsPlayer`, `LevelMeter`, `StatusBadge`, `formatDuration`, `useAudio`.
- Produces: `/raum/:id`
  - Kopf: Zurück-Link, Raumname, „Switch room“ als `<select>` mit allen
    aktiven Räumen, bei Wechsel navigieren.
  - Großer Player mit Pegel. Badge „● LIVE 47:12“; die Laufzeit kommt aus
    `live_since` und wird jede Sekunde aktualisiert, ohne Ansage im
    Screenreader.
  - Darunter der Stream-Name.
  - Zwei große Knöpfe (min. 44 px): **Sound on/off** (schaltet bei Bedarf
    zuerst `unlock`) und **Fullscreen** (`requestFullscreen` auf dem
    Player-Container, Fallback `webkitEnterFullscreen` am Video für iOS).
  - Offline: gestreifte Fläche mit „No stream – the recorder is not sending
    right now“ und „Last checked HH:MM“. Der Player wird erst montiert, wenn der
    Status `live` wird.
  - Unbekannte ID → „Room not found“ mit Link zur Übersicht.
  - Statuswechsel live↔offline werden über eine `aria-live="polite"`-Region
    angesagt („Stream in 40/R05 started/ended“).

- [ ] **Step 1:** Implementieren.
- [ ] **Step 2:** Manuell auf einem echten Smartphone (iOS Safari und Android
  Chrome) im WLAN gegen den Dev-Server bzw. ein Test-Deployment prüfen:
  - Der Stream startet stumm.
  - Ein Tippen auf „Sound on“ macht den Ton hörbar, und der Pegel schlägt aus.
  - Vollbild funktioniert.
  - Wenn der Rekorder stoppt, erscheint nach spätestens ~30 s der
    Offline-Hinweis.
  - Ein fehlender Pegel unter iOS wegen nativem HLS ist akzeptiert und zeigt
    „Level unavailable“.
- [ ] **Step 3:** `npx tsc -b` OK, `npm test` PASS.
- [ ] **Step 4:** Commit `feat(room): Raumansicht für Smartphone und PC`.

### Task 10: Verwaltung: Rekorder, Einladungen, Einstellungen

**Files:**
- Create: `frontend/src/pages/admin/RecordersAdmin.tsx`, `frontend/src/pages/admin/InvitationsAdmin.tsx`, `frontend/src/pages/admin/SettingsAdmin.tsx`, `frontend/src/pages/admin/AdminLayout.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `api.recorders.*`, `api.invitations.*`, `api.users.search`,
  `api.settings.*` (Task 6). Für die Bestätigung eines Löschens den
  `useConfirm`/Dialog aus `@basicbar/ui`, falls vorhanden, sonst einen eigenen
  `Dialog` mit Fokus auf „Cancel“.
- Produces:
  - **Rekorder:**
    - Tabelle mit Raum, Stream-Name, aktiv, Status und Spalte „review“.
    - Anlegen und Bearbeiten im Formular: Raumname und Stream-Name
      Pflicht, Checkbox „active“.
    - Serverfehler werden am Feld gezeigt (z. B. ungültiger Stream-Name,
      Duplikat).
    - Deaktivieren statt Löschen.
  - **Einladungen:**
    - Liste mit Kennung, Notiz, „invited by“ und Datum.
    - Hinzufügen per Freitext (Benutzername oder E-Mail) oder per Suche in
      bekannten Nutzern (`api.users.search`, Debounce 250 ms).
    - Entfernen mit Bestätigungsdialog.
    - Hinweistext: Mitglieder der IdP-Gruppe brauchen keine Einladung.
  - **Einstellungen:** `url_template` und `stale_factor`, mit Vorschau der
    URL für den ersten Rekorder.

- [ ] **Step 1:** Implementieren.
- [ ] **Step 2:** Manuell prüfen:
  - Einen Rekorder `cap-streaming` / „Capture Test“ anlegen. Er erscheint
    in der Übersicht unter „All rooms“.
  - `outsider` einladen → nach Neuladen hat `outsider` Zugang. Einladung
    entfernen → beim nächsten Poll bekommt `outsider` 403, und die
    SPA zeigt „Kein Zugang“ (`useRecorders` behandelt 403 durch erneutes
    whoami).
  - Eine URL-Vorlage ohne `{stream}` wird mit Fehlermeldung am Feld
    abgelehnt.
- [ ] **Step 3:** `npx tsc -b` OK.
- [ ] **Step 4:** Commit `feat(admin): Pflege von Rekordern, Einladungen, Einstellungen`.

### Task 11: Übersetzung, Barrierefreiheit, Doku, Abnahme

**Files:**
- Modify: `frontend/src/locales/de/translation.json`, `README.md`, `CLAUDE.md`, `.env.prod.example`

- [ ] **Step 1:** Alle neuen UI-Keys ins Deutsche übersetzen, nah am Mockup:
  - „since“ → „seit“
  - „No stream – the recorder is not sending right now“ → „Kein Stream – der
    Rekorder sendet gerade nicht“
  - „Enable level & sound“ → „Pegel & Ton aktivieren“
  - „Currently without stream“ → „Gerade ohne Stream“

  Prüfen, dass kein Key ohne Übersetzung bleibt (Sprachumschalter auf
  Deutsch, alle Seiten durchklicken).
- [ ] **Step 2:** A11y-Durchgang auf allen Seiten:
  - axe DevTools oder Lighthouse ohne Fehler der Kategorie „serious/critical“.
  - Volle Tastaturbedienung.
  - 200 % Zoom ohne horizontales Scrollen bei 320 px Breite.
  - Kontrast der Badges in Hell und Dunkel ≥ 4.5:1.
- [ ] **Step 3:** README (Betrieb):
  - Env-Variablen `ANSEHBAR_ACCESS_GROUP`, `ANSEHBAR_BOOTSTRAP_USERS`,
    `ANSEHBAR_ACCESS_CONTACT` und `MONITOR_INTERVAL_SECONDS`.
  - Dienst `monitor`.
  - Gruppenentzug wirkt erst beim nächsten Login.
  - Der Streaming-Server muss CORS erlauben.

  CLAUDE.md um Ports, Apps (`accounts`, `recorders`, `streams`) und
  Spec-/Plan-Pfade ergänzen.
- [ ] **Step 4:** Komplette Suite: `docker compose exec backend python manage.py test`
  → OK; `docker compose exec backend sh -c "pip install -q ruff && ruff check ."` → OK;
  `docker compose exec frontend sh -c "npm test && npx tsc -b && npm run build"` → OK.
- [ ] **Step 5:** Abnahme mit dem Auftraggeber während einer Vorlesungszeit,
  verglichen mit dem alten Monitor: dieselben Streams sind sichtbar.
- [ ] **Step 6:** Commit `docs: Betrieb und Übersetzung Stufe 1`, danach Merge
  Request `feature/stufe-1` → `main`.
