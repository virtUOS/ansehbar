# ansehBAR Stufe 2 (Opencast) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ansehBAR kennt die Opencast-Capture-Agents und die Termine. Es zeigt
„Stream fehlt“, wenn während eines Termins kein Stream läuft, dazu Titel und
Zeitfenster der Termine, „Heute noch geplant“ und die Zuordnung Agent ↔ Stream.

**Architecture:**
- Neue Backend-App `opencast` mit drei Teilen:
  - ein reiner HTTP-Client für die External API (nur GET, `httpx`),
  - eine Sync-Logik, die Agents und Termine in Postgres spiegelt,
  - eine Sync-Statuszeile.
- Der bestehende Prozess `run_monitor` synchronisiert alle
  `OPENCAST_SYNC_SECONDS` (unabhängig vom Stream-Zyklus). Ein Fehler beim Sync
  stört die Live-Erkennung nie.
- Die Rekorder-API liefert pro Rekorder den laufenden und den nächsten Termin
  des Tages sowie `missing_since`. Das Frontend leitet daraus den neuen Zustand
  „missing“ ab.
- Ohne `OPENCAST_URL` verhält sich alles wie in Stufe 1.

**Tech Stack:** wie Stufe 1 (Django 5.1, DRF, httpx, Postgres 16; React 18, vitest).

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`. Stufe 2 umfasst:
- Abschnitt 6,
- die Opencast-Teile von 5.0, 5.1, 5.2 und 5.4.

Vorfälle, Alarme und Kalender (Abschnitt 7) gehören nicht dazu.

**Erkundet an `https://stable.opencast.org` (External API v1.12.0, 2026-11-01):**
- `GET /api/agents?limit=&offset=` liefert
  `[{"agent_id","status","update","url","inputs"}]`. Für `status` sind u. a.
  `idle` und `capturing` belegt.
- `GET /api/events?withscheduling=true&filter=start:<from>/<to>&sort=start_date:ASC&limit=&offset=`
  liefert Events. Geplante Events haben `scheduling: {"agent_id","start","end","inputs"}`
  und `location` = Agent-ID. Bei verarbeiteten Events ohne Planung ist `scheduling` gleich `{}`.
  Weitere Felder: `identifier`, `title`, `series`, `status`
  (`EVENTS.EVENTS.STATUS.SCHEDULED` usw.).
- Alle Zeiten sind UTC mit `Z`. Das Datumsformat im Filter ist `2026-11-01T00:00:00Z`.
- Der Server wird täglich zurückgesetzt und hat sonst keine geplanten Termine.
  Für manuelle Tests legt man dort selbst einen an (Task 8).

## Global Constraints

- SPDX-Header (`Apache-2.0`, `Copyright 2026 Universität Osnabrück (virtUOS)`)
  in jeder neuen Quelldatei.
- **ansehBAR schreibt nie nach Opencast.**
  - Der Client kennt nur GET.
  - Kein Testcode und kein Produktcode legt etwas in Opencast an.
  - Einzige Ausnahme ist die manuelle Abnahme gegen den Testserver in Task 8.
- Opencast-Zugangsdaten nur per Env (`OPENCAST_USER`, `OPENCAST_PASSWORD`).
  Sie erscheinen nie in Logs, API-Antworten oder Fehlermeldungen an die SPA.
- Keine Infrastrukturdetails im Repo. Test-Fixtures nutzen fiktive Agents
  (`cap-90-R12`, `rec-hall`) und `https://opencast.example.org`.
- Stream-Namen und Agent-IDs sind case-sensitiv; nie normalisieren.
- Kein Django-Admin für Fachdaten. Pflege nur im Frontend.
- UI-Texte englisch als i18n-Key, Deutsch in `frontend/src/locales/de/translation.json`.
  Backend-Texte über gettext, Deutsch in `backend/locale/de/LC_MESSAGES/django.po`.
- Status immer mit Text **und** Symbol; brand ist nie Statusfarbe.
  Dark-Mode-Text mindestens `slate-300`.
- „Status unbekannt“ wird nie als „Stream fehlt“ dargestellt.
- „Heute“ bezieht sich auf den lokalen Kalendertag in `TIME_ZONE` (`Europe/Berlin`).
- Befehle im Container: `docker compose exec backend …` und
  `docker compose exec frontend …`.
- Commits enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Arbeit auf Branch `feature/opencast`, am Ende ein PR gegen `main`. Der Mensch merged.

## Review Focus

1. **Opencast ist nicht erreichbar oder bricht mitten in der Paginierung ab:**
   - Kein Termin wird gelöscht, die alten Daten bleiben.
   - Die Live-Erkennung läuft ungestört weiter.
   - Nach drei Sync-Intervallen erscheint ein Banner „Opencast-Daten veraltet“.
   - Tests: Task 1 (`OpencastError` bei Seite 2 = 500), Task 2
     (`run_opencast_sync` übernimmt nichts), Task 3 (Monitor-Zyklus läuft trotz
     Sync-Fehler), Task 6 (`opencastStale`).
2. **Agent-ID taugt nicht als Stream-Name** (z. B. Leerzeichen), oder ein
   anderer Rekorder belegt den Stream-Namen schon:
   - Der Agent wird übersprungen und protokolliert.
   - Kein Absturz, keine doppelte Verknüpfung.
   - Test: Task 2.
3. **Status `unknown` während eines Termins:** nie `missing_since`, nie
   „Stream fehlt“. Tests: Task 4 (Serializer) und Task 5 (`presentation`).
4. **Termin wird in Opencast abgesagt oder verschoben:** Er verschwindet beim
   nächsten Sync. Termine außerhalb des Sync-Fensters (Historie) bleiben
   unangetastet. Test: Task 2.
5. **Tagesgrenze und Zeitzone:**
   - Opencast liefert UTC.
   - Ein Termin um 23:30 Berliner Zeit ist „heute“, einer um 00:30 am
     Folgetag nicht.
   - Ein Termin über Mitternacht, der gerade läuft, ist `current_event`.
   - Test: Task 4.

---

### Task 1: Opencast-Client (External API, nur lesend)

**Files:**
- Create: `backend/opencast/__init__.py`, `apps.py`, `client.py`, `tests.py`, `fixtures/agents.json`, `fixtures/events.json`
- Modify: `backend/config/settings.py` (INSTALLED_APPS `"opencast"`, Env-Variablen),
  `docker-compose.yml` (backend-env), `.env.prod.example`

**Interfaces:**
- Produces (`opencast/client.py`, ohne Django-Imports wie `streams/sources.py`):
  - `@dataclass(frozen=True) class Agent: agent_id: str; state: str; updated_at: datetime | None`
  - `@dataclass(frozen=True) class Event: identifier: str; agent_id: str; title: str; series: str; start: datetime; end: datetime`.
    `start` und `end` stammen aus `scheduling`, nicht aus dem Dublin-Core-`start`.
  - `class OpencastError(Exception)`. Die Meldung enthält den Pfad und den
    HTTP-Status bzw. den Fehlertyp, aber nie Zugangsdaten.
  - `class OpencastClient(base_url: str, user: str, password: str, client: httpx.Client, timeout: float = 10.0, page_size: int = 100, max_pages: int = 50)`
    - `agents() -> list[Agent]`
    - `scheduled_events(start: datetime, end: datetime) -> list[Event]`
- Settings: `OPENCAST_URL` (Default `""`, ohne abschließenden `/`),
  `OPENCAST_USER`, `OPENCAST_PASSWORD`,
  `OPENCAST_SYNC_SECONDS` (`_int_or_default`, 60),
  `OPENCAST_LOOKAHEAD_DAYS` (`_int_or_default`, 7),
  `OPENCAST_ENABLED = bool(OPENCAST_URL)`.

- [ ] **Step 1: Failing tests** in `opencast/tests.py`. Sie nutzen `httpx.MockTransport`
  mit Antworten aus `fixtures/*.json`. Die Fixtures haben die Form von oben
  und fiktive Werte. `events.json` enthält:
  - zwei geplante Events (`cap-90-R12`, `rec-hall`),
  - ein Event mit `"scheduling": {}`,
  - ein Event, dem `scheduling.end` fehlt.

  Tests:
  - `test_agents_parses_state_and_update`: `agent_id` bleibt case-sensitiv;
    `updated_at` ist ein aware datetime in UTC.
  - `test_agents_paginates`: `page_size=2`, drei Agents verteilt auf zwei
    Seiten. Das Ergebnis enthält alle drei. Die Requests tragen `offset=0`
    und `offset=2`.
  - `test_events_request_uses_scheduling_and_window`: Der Request enthält
    `withscheduling=true`, `filter=start:2026-11-01T00:00:00Z/2026-11-02T00:00:00Z`
    und `sort=start_date:ASC`.
  - `test_events_skips_unscheduled_and_incomplete`: Nur die zwei geplanten
    Events kommen zurück. `start` und `end` stammen aus `scheduling`.
  - `test_basic_auth_and_accept_json`: Header `Authorization: Basic …` und `Accept: application/json`.
  - `test_error_on_http_500_page_two`: Seite 2 liefert 500, Ergebnis `OpencastError`.
  - `test_error_on_network_and_invalid_json`: Ein `ConnectError` und ein
    Body `"<html>"` führen jeweils zu `OpencastError`. Die Meldung enthält
    das Passwort nicht.
  - `test_error_when_max_pages_exceeded`: `OpencastError`, kein endloses Paginieren.
  - `test_only_get_requests`: Der MockTransport protokolliert die Methoden;
    alle sind `GET`.
- [ ] **Step 2:** `docker compose exec backend python manage.py test opencast` → FAIL.
- [ ] **Step 3:** `client.py` implementieren.
  - Paginierung endet, wenn eine Seite weniger als `page_size` Einträge hat.
  - Zeitstempel parsen mit `datetime.fromisoformat` (`Z` → `+00:00`).
  - Einträge mit fehlenden Pflichtfeldern überspringen.
  - Settings und Compose-/Env-Beispiel ergänzen, kommentiert wie die
    bestehenden Einträge. Im Dev-Compose gilt der Default „leer = aus“.
- [ ] **Step 4:** Tests → PASS; `ruff check .` sauber.
- [ ] **Step 5:** Commit `feat(opencast): lesender Client für die External API`.

### Task 2: Datenmodell und Sync von Agents und Terminen

**Files:**
- Create: `backend/opencast/models.py`, `backend/opencast/sync.py`, `backend/opencast/migrations/0001_initial.py`
- Modify: `backend/recorders/models.py` (+ Migration `0003_opencast`),
  `backend/recorders/management/commands/load_site_config.py`,
  `backend/site.example.json`, `backend/opencast/tests.py`, `backend/recorders/tests.py`

**Interfaces:**
- Consumes: `Agent`, `Event`, `OpencastClient`, `OpencastError` aus Task 1;
  `validate_stream_name` aus `recorders/validators.py`.
- Produces:
  - `Recorder.agent_id: CharField(100, null=True, blank=True, unique=True)`.
    `NULL` heißt „nicht verknüpft“; leere Strings werden als `None` gespeichert.
  - `Recorder.room_name`: jetzt `blank=True`. Leer heißt „Raumname fehlt“.
  - `RecorderStatus` bekommt drei neue Felder:
    - `agent_state: CharField(20, blank=True)`, Opencast-Status roh,
      `""` = nie gesehen;
    - `agent_updated_at: DateTimeField(null=True)`;
    - `offline_since: DateTimeField(null=True)`, gefüllt ab Task 3.
  - `MonitorSettings.missing_grace_minutes: PositiveSmallIntegerField(default=3, validators 0..30)`.
  - `opencast.models.ScheduledEvent`:
    - `identifier: CharField(128, unique)`
    - `recorder: FK Recorder CASCADE related_name="events"`
    - `title: CharField(300, blank)`, `series: CharField(300, blank)`
    - `start`, `end: DateTimeField`, Index auf (`recorder`, `start`)
    - `updated_at: auto_now`
    - Ordering `start`
  - `opencast.models.OpencastSyncState`: Singleton `pk=1`, `load()`, mit
    `last_attempt_at`, `last_success_at` (beide null), `last_error: CharField(300, blank)`.
  - `opencast.sync.sync_agents(agents: list[Agent], now: datetime) -> AgentSyncResult`
    mit `created: int, linked: int, skipped: list[str], gone: int`.
  - `opencast.sync.sync_events(events: list[Event], window_start: datetime, window_end: datetime) -> EventSyncResult`
    mit `upserted: int, deleted: int, unmatched: int`.
  - `opencast.sync.sync_window(now: datetime, lookahead_days: int) -> tuple[datetime, datetime]`
    - Start: lokale Mitternacht heute minus 1 Tag.
    - Ende: lokale Mitternacht heute plus `lookahead_days + 1` Tage.
    - Beide aware.
  - `opencast.sync.run_opencast_sync(client: OpencastClient, now: datetime, lookahead_days: int) -> None`

- [ ] **Step 1: Failing tests** in `opencast/tests.py` (Klasse `SyncTests`):
  - `test_new_agent_creates_review_recorder`: Agent `cap-90-R12` ist unbekannt.
    Danach gibt es einen Rekorder mit `agent_id="cap-90-R12"`,
    `stream_name="cap-90-R12"`, `room_name=""`, `active=True`,
    `needs_review=True` und `status.agent_state="idle"`.
  - `test_agent_links_existing_recorder_by_stream_name`: Rekorder
    `stream_name="rec-hall"` ohne `agent_id` wird verknüpft. Das gibt
    `linked=1` und keinen neuen Rekorder. `needs_review` bleibt unverändert.
  - `test_agent_with_invalid_stream_name_is_skipped`: Agent `"Hall 1"` landet in
    `skipped`, es entsteht kein Rekorder.
  - `test_agent_stream_name_taken_by_other_agent_is_skipped`: Rekorder
    `stream_name="x"`, `agent_id="y"`. Agent `x` landet in `skipped`.
  - `test_missing_agent_becomes_unknown`: Ein verknüpfter Rekorder, dessen
    Agent fehlt, bekommt `agent_state="unknown"`; `gone=1`. Es wird nichts
    gelöscht oder deaktiviert.
  - `test_events_upsert_and_delete_cancelled_in_window`:
    - Lauf 1 mit den Events A und B.
    - Lauf 2 nur mit A (Titel geändert): A ist aktualisiert, B gelöscht.
    - Ein Event C mit Start vor `window_start` bleibt erhalten.
  - `test_event_for_unknown_agent_is_unmatched`: `unmatched=1`, nichts gespeichert.
  - `test_sync_window_local_midnight`: `now=2026-11-01T23:30Z` liegt in Berlin
    schon am 2.11. um 00:30 MEZ. Das Fenster ist
    `(2026-10-31T23:00Z, 2026-11-09T23:00Z)` bei `lookahead_days=7`.
  - `test_run_sync_applies_nothing_on_error`: Der Client wirft beim zweiten
    Aufruf (`scheduled_events`) `OpencastError`. Es ändern sich weder
    Rekorder noch Events. `OpencastSyncState.last_error` ist gesetzt,
    `last_success_at` nicht.
  - `test_run_sync_success_records_state`: `last_success_at == now`, `last_error == ""`.
  - In `recorders/tests.py`: `test_load_site_config_accepts_agent_id`. Ein
    optionales `agent_id` pro Eintrag wird gesetzt. Doppelte `agent_id` in
    der Datei werden als Problem gemeldet.
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** Implementieren.
  - `run_opencast_sync` holt zuerst beide Listen. Erst wenn beide vollständig
    sind, wendet es sie in einem `transaction.atomic()` an:
    `sync_agents`, danach `sync_events`.
  - Übersprungene Agents und nicht zugeordnete Events werden auf WARNING
    geloggt, je Agent-ID höchstens einmal pro Prozesslauf (Modulvariable).
  - `site.example.json` bekommt bei einem Eintrag ein Beispiel-`agent_id`.
- [ ] **Step 4:** Tests → PASS (auch die bestehenden `recorders`-Tests).
  `makemigrations --check` meldet nichts mehr.
- [ ] **Step 5:** Commit `feat(opencast): Agents und Termine in die Datenbank spiegeln`.

### Task 3: Monitor-Integration und Herzschlag

**Files:**
- Modify: `backend/recorders/monitor.py`, `backend/recorders/management/commands/run_monitor.py`,
  `backend/recorders/views.py` (`MonitorHealthView`), `backend/recorders/tests.py`

**Interfaces:**
- Consumes: `run_opencast_sync`, `OpencastClient`, `OpencastSyncState` aus Task 1 und 2.
- Produces:
  - `run_cycle` pflegt `RecorderStatus.offline_since`:
    - Es wird `now`, wenn der neue Zustand `offline` ist und der vorherige
      nicht `offline` war.
    - Es bleibt erhalten, solange der Zustand `offline` bleibt.
    - Es wird `None` bei `live`.
    - Bei `unknown` bleibt es unverändert.
  - `GET /api/monitor/health/` hat zusätzlich
    `"opencast": {"enabled": bool, "last_success": iso|null, "sync_seconds": int}`.
    Es enthält keinen Fehlertext und keine URL.

- [ ] **Step 1: Failing tests:**
  - `test_offline_since_set_on_transition_and_kept`: Folge live → offline
    (t1) → offline (t2). `offline_since` ist t1. Danach live → `None`.
  - `test_offline_since_survives_unknown`
  - `test_run_monitor_syncs_opencast_when_enabled`:
    - `override_settings(OPENCAST_URL="https://opencast.example.org")`,
      `run_opencast_sync` gemockt.
    - `call_command("run_monitor", "--once")` ruft den Sync genau einmal auf
      und prüft danach die Streams.
  - `test_run_monitor_stream_cycle_survives_sync_error`:
    - Der Sync wirft `RuntimeError`.
    - Der Stream-Zyklus läuft trotzdem (`checked_at` gesetzt).
    - Das Log enthält kein Passwort.
  - `test_run_monitor_skips_opencast_when_disabled`
  - `test_health_reports_opencast_block`: Bei ausgeschaltetem Opencast
    `enabled=false`, bei eingeschaltetem mit `last_success` aus `OpencastSyncState`.
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** Implementieren.
  - `run_monitor` hält einen eigenen `httpx.Client` für Opencast mit
    `auth=(user, password)`.
  - Synchronisiert wird vor dem Stream-Zyklus, wenn seit dem letzten Versuch
    `OPENCAST_SYNC_SECONDS` vergangen sind. Gemessen wird mit `time.monotonic`;
    beim Start und bei `--once` sofort.
  - Fehler werden mit `logger.warning` und `OpencastError`-Text geloggt.
    Den Stacktrace gibt es nur bei unerwarteten Ausnahmen.
  - In jedem Fall geht es mit dem Stream-Zyklus weiter.
  - Die Summary-Zeile bekommt `opencast=ok|error|off` dazu.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(monitor): Opencast-Sync im Monitor, offline_since, Herzschlag`.

### Task 4: Rekorder-API mit Terminen und „Stream fehlt“

**Files:**
- Modify: `backend/recorders/serializers.py`, `backend/recorders/views.py`, `backend/recorders/tests.py`,
  `backend/locale/de/LC_MESSAGES/django.po/.mo` (falls neue Meldungen)

**Interfaces:**
- Consumes: `ScheduledEvent`, `RecorderStatus.offline_since`, `MonitorSettings.missing_grace_minutes`.
- Produces, als Felder von `/api/recorders/` (Liste und Detail):
  - `room_name`: darf leer sein.
  - `agent_id`: string|null, schreibbar. `""` wird zu `null`. Eindeutig:
    sonst 400 mit Feldfehler.
  - `needs_review`: schreibbar.
  - `status`: zusätzlich `agent_state` und `agent_updated_at`.
  - `current_event`: `{title, series, start, end}|null`. Das Event dieses
    Rekorders mit `start <= now < end`; bei mehreren das mit dem frühesten
    `start`.
  - `next_event`: `{title, series, start, end}|null`. Das erste Event mit
    `start > now` und `start <` lokaler Mitternacht morgen.
  - `missing_since`: iso|null. Gesetzt nur, wenn alle drei Bedingungen gelten:
    - Der Rekorder ist aktiv.
    - Es gibt ein `current_event`.
    - `status.state == "offline"` und `now >= current_event.start + grace`.

    Wert: `max(current_event.start + grace, status.offline_since)`, wobei ein
    fehlendes `offline_since` nicht zählt.
  - `/api/settings/monitor/`: zusätzlich `missing_grace_minutes` (0..30).
- Die View lädt die Termine aller Rekorder mit **einer** Abfrage. Gemeinsam mit
  `now` und `grace` gehen sie in den Serializer-Kontext. Für die Liste gibt es
  keine Abfrage pro Rekorder.

- [ ] **Step 1: Failing tests:**
  - `test_current_and_next_event`: Termin 10–12 Uhr und 14–16 Uhr, `now` ist
    11:00 Berlin. Dann ist `current_event.title` der erste Termin und
    `next_event.start` 14:00.
  - `test_next_event_only_today_local`: `now` ist 22:00 Berlin, Termine um
    23:30 und um 00:30 am nächsten Tag. `next_event` ist der Termin um 23:30.
  - `test_overnight_event_is_current`: Termin 23:00–01:00, `now` ist 00:30.
  - `test_missing_since_after_grace`: offline, Termin seit 10:00, grace 3.
    Um 10:02 ist `missing_since` null, um 10:05 ist es 10:03.
  - `test_missing_since_uses_offline_since_mid_event`: `offline_since` ist
    10:40, dann ist `missing_since` 10:40.
  - `test_unknown_during_event_is_never_missing`
  - `test_inactive_recorder_is_never_missing`
  - `test_agent_id_blank_becomes_null_and_unique_enforced`
  - `test_list_query_count_constant`: Die Liste mit 3 und mit 10 Rekordern
    (je 2 Termine) braucht gleich viele Queries (`assertNumQueries`).
  - `test_settings_grace_bounds`: 31 → 400.
  - `now` wird über `mock.patch("django.utils.timezone.now")` gesetzt.
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** Implementieren. `now` und das Tagesende werden pro Request einmal berechnet.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(recorders): Termine, missing_since und Agent-Felder in der API`.

### Task 5: Frontend-Datenschicht

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/recorders.ts`, `frontend/src/recorders.test.ts`, `frontend/src/useRecorders.ts`

**Interfaces:**
- Consumes: die API-Felder aus Task 3 und 4.
- Produces:
  - `api.ts`:
    - `interface EventBrief { title: string; series: string; start: string; end: string }`.
    - `Recorder` bekommt `agent_id: string | null`, `current_event`,
      `next_event: EventBrief | null` und `missing_since: string | null`.
    - `status` bekommt `agent_state: string` und `agent_updated_at: string | null`.
    - `MonitorHealth.opencast: { enabled: boolean; last_success: string | null; sync_seconds: number }`.
    - `MonitorSettings.missing_grace_minutes: number`.
  - `recorders.ts`:
    - `Presentation` bekommt `"missing"`. `presentation()` liefert `"missing"`,
      wenn der Rekorder aktiv ist, `state === "offline"` gilt und
      `missing_since` gesetzt ist. `unknown` bleibt `unknown` bzw. `live-unknown`.
    - `sortForOverview`: Reihenfolge `missing` → `keepsPlayer` → Rest. Innerhalb
      einer Gruppe nach `displayName` mit `localeCompare("de", {numeric: true})`.
    - `type OverviewMode = "now" | "today" | "all"`.
    - `filterOverview(list, mode: OverviewMode, query)`:
      - `now` = `keepsPlayer || missing`.
      - `today` = `now` oder `current_event` oder `next_event`.
      - Die Suche berücksichtigt zusätzlich `agent_id`.
    - `upcomingToday(list: Recorder[], now: Date): Recorder[]`: aktive Rekorder
      mit `next_event`, nach `next_event.start` sortiert.
    - `quietToday(list: Recorder[]): Recorder[]`: aktive Rekorder ohne
      Treffer in `today`.
    - `displayName(r): string` = `room_name.trim()`, sonst `agent_id`, sonst `stream_name`.
    - `roomNameMissing(r): boolean`.
    - `untilParts(startIso: string, now: Date): { hours: number; minutes: number }`.
      Abgerundet auf Minuten, nie negativ.
    - `opencastStale(health: MonitorHealth): boolean`:
      - `false`, wenn Opencast nicht eingeschaltet ist.
      - `true` ohne `last_success`.
      - Sonst `true`, wenn das Alter (Serverzeit) größer als `3 × sync_seconds` ist.
    - `same()` vergleicht alle neuen Felder. Events werden feldweise verglichen.
  - `useRecorders` liefert zusätzlich `opencastEnabled: boolean`,
    `opencastStale: boolean` und `opencastLastSuccess: string | null`.
    Das sind Primitive, wie bei `monitorStale`.

- [ ] **Step 1: Failing tests** in `recorders.test.ts`:
  - `presentation` liefert `"missing"` für offline mit `missing_since`. Bei
    unknown mit `missing_since` (Race) kommt `"unknown"`, bei inaktiv
    `"inactive"`.
  - `sortForOverview`: missing vor live vor offline.
  - `filterOverview`:
    - `today` enthält Rekorder mit `next_event` und lässt ruhige weg.
    - Die Suche findet `agent_id`.
  - `upcomingToday`: sortiert nach Start, ohne inaktive Rekorder.
  - `displayName` und `roomNameMissing` für `room_name: "  "`.
  - `untilParts("…T12:43:00Z", new Date("…T11:00:00Z"))` → `{hours: 1, minutes: 43}`. Ein Start in der Vergangenheit ergibt `{0, 0}`.
  - `opencastStale`: Ausgeschaltet → false. Kein Erfolg → true. Bei 180 s
    Alter und `sync_seconds` 60 → false, bei 181 s → true.
  - `mergeRecorders`: Ein geänderter `next_event.title` liefert ein neues
    Objekt, ein unveränderter behält die Identität.
  - Die bestehenden Tests werden an `OverviewMode` angepasst; die Testdaten
    bekommen die neuen Felder.
- [ ] **Step 2:** `docker compose exec frontend npm test` → FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests → PASS; `npx tsc -b` sauber.
- [ ] **Step 5:** Commit `feat(frontend): Datenschicht für Termine und „Stream fehlt“`.

### Task 6: Übersicht, Kachel, Raumliste

**Files:**
- Modify: `frontend/src/pages/Overview.tsx`, `components/RecorderTile.tsx`, `components/RoomList.tsx`,
  `components/StatusBadge.tsx`, `components/StreamPlaceholder.tsx`, `components/MonitorBanner.tsx`,
  `frontend/src/locales/de/translation.json`
- Create: `frontend/src/components/UpcomingList.tsx`

**Interfaces:**
- Consumes: alles aus Task 5.
- Produces: UI nach Spec 5.1 und 5.2 mit diesen Keys (EN → DE):
  - `"Stream missing"` → „Stream fehlt“. Badge mit Symbol `⚠` und Klassen
    `bg-red-100 text-red-950 ring-1 ring-red-700 dark:bg-red-950 dark:text-red-100`.
  - `"Stream missing for {{minutes}} min"` → „Stream fehlt – seit {{minutes}} min“.
    Platzhaltertext bei `missing`; die Minuten werden aus `missing_since`
    berechnet und jede Minute aktualisiert.
  - `"from"` → „ab“ und `"until {{time}}"` → „bis {{time}}“.
  - `"Today"` → „Heute“: dritter Chip zwischen „Jetzt“ und „Alle Räume“, nur
    wenn `opencastEnabled`.
  - `"Still scheduled today"` → „Heute noch geplant“.
  - `"in {{hours}} h {{minutes}} min"` → „in {{hours}} h {{minutes}} min“ und
    `"in {{minutes}} min"` → „in {{minutes}} min“.
  - `"No recording today"` → „Heute ohne Aufzeichnung“.
  - `"No stream – no recording scheduled"` → „Kein Stream – keine Aufzeichnung geplant“.
  - `"next: {{time}}"` → „nächste: {{time}}“.
  - `"Room name missing"` → „Raumname fehlt“.
  - `"Opencast data out of date – last update {{time}}"` → „Opencast-Daten veraltet – letzte Aktualisierung {{time}}“.
  - `"Opencast data not available yet"` → „Opencast-Daten noch nicht verfügbar“.
  - `"Stream missing in {{room}}"` → „Stream fehlt in {{room}}“, als `aria-live`-Ansage.

- [ ] **Step 1:** `StatusBadge` bekommt den Zustand `"missing"`. `StreamPlaceholder`
  bekommt `kind="missing"` und `kind="offline"` mit optionalem `scheduled=false`.
  `scheduled=false` heißt: Opencast ist an und heute ist nichts geplant. Dann
  lautet der Text „Kein Stream – keine Aufzeichnung geplant“.
- [ ] **Step 2: `RecorderTile`:**
  - Bei `missing`:
    - roter Rahmen (`border-red-700`), Platzhalter mit Minuten,
    - groß „ab HH:MM“ (Termin-Start), klein „bis HH:MM“,
    - Titel des Termins.
  - Bei live mit `current_event`: groß „seit HH:MM“ wie bisher, dazu klein
    „bis HH:MM“ und der Titel.
  - In „Alle Räume“ zeigen ruhige Rekorder mit `next_event` „nächste: HH:MM“.
  - Als Hauptbezeichnung dient `displayName`. Fehlt der Raumname, steht der
    Hinweis „Raumname fehlt“ als Text mit Symbol daneben.
- [ ] **Step 3: `Overview`:**
  - drei Modi;
  - Kacheln wie bisher, aber mit `missing` (Reihenfolge aus `sortForOverview`);
  - darunter `UpcomingList` (`upcomingToday`): je Zeile das Zeitfenster
    `HH:MM–HH:MM` in `text-brand-700 dark:text-brand-300 font-bold`, Raum
    (Link), Titel, „in …“. Keine Kacheln.
  - Darunter die Zeile „Heute ohne Aufzeichnung: …“ (`quietToday`) anstelle
    von „Currently without stream“, aber nur, wenn `opencastEnabled`. Ohne
    Opencast bleibt alles wie bisher.
  - Die Zeile „Status unknown“ bleibt.
  - `aria-live="polite"`: Ansage, wenn ein Rekorder neu in `missing` wechselt.
    Beim ersten Laden wird nichts angesagt (Muster wie `stateTransition`).
- [ ] **Step 4: `RoomList` (Smartphone):** Badge `missing`, rechts „ab HH:MM“
  bzw. „seit HH:MM“ bzw. für Termine später am Tag „heute ab HH:MM“ (Key
  `"today from {{time}}"` → „heute ab {{time}}“).
- [ ] **Step 5: `MonitorBanner`:** eine zweite Meldung bei `opencastStale`. Sie
  ist eigenständig und kann neben der Monitor-Meldung stehen.
- [ ] **Step 6:**
  - `npm test`, `npx tsc -b` und `npm run check:i18n` sauber.
  - Im Browser bei 1280 px und 320 px prüfen, im Hell- und Dunkelmodus: Ist
    der Kontrast der neuen Badges ausreichend, und läuft der Header über?
- [ ] **Step 7:** Commit `feat(frontend): „Stream fehlt“, Heute-Filter und „Heute noch geplant“`.

### Task 7: Raumansicht und Verwaltung

**Files:**
- Modify: `frontend/src/pages/RoomView.tsx`, `pages/admin/RecordersAdmin.tsx`, `pages/admin/SettingsAdmin.tsx`,
  `frontend/src/admin.ts` (falls `FIELDS`/Fehler-Mapping betroffen), `locales/de/translation.json`

**Interfaces:**
- Consumes: Task 5 und 6.
- Produces (Keys EN → DE):
  - `"Opencast agent"` → „Opencast-Agent“ und `"Not linked"` → „nicht verknüpft“.
  - Agent-Status: `"idle"` → „bereit“, `"capturing"` → „zeichnet auf“,
    `"uploading"` → „lädt hoch“, `"offline"` → „offline“,
    `"unknown"` → „unbekannt“. Andere Werte werden roh angezeigt.
    Literal-`t()`-Aufrufe über eine Map, damit der i18n-Check sie sieht.
  - `"Next today: {{time}} {{title}}"` → „Heute als Nächstes: {{time}} {{title}}“.
  - `"New – please check"` → „Neu – bitte prüfen“.
  - `"Opencast capture agent; leave empty if not linked."` → „Opencast-Capture-Agent; leer lassen, wenn nicht verknüpft.“
  - `"Grace period before “stream missing” (minutes)"` → „Wartezeit bis „Stream fehlt“ (Minuten)“.

- [ ] **Step 1: `RoomView`:**
  - Platzhalter und Badge für `missing` wie in der Kachel.
  - Unter dem Player der Titel des laufenden Termins und das Zeitfenster
    `HH:MM–HH:MM`. Ohne laufenden Termin, aber mit `next_event`: „Heute als
    Nächstes: …“.
  - Klein dazu: Stream-Name, `Opencast-Agent: <id> · <Status>` oder „nicht verknüpft“.
  - `aria-live` kündigt den Wechsel nach `missing` an
    („Stream fehlt in {{room}}“).
  - Der Raumwechsel-Select nutzt `displayName`.
- [ ] **Step 2: `RecordersAdmin`:**
  - Spalte bzw. Zeile mit `agent_id`.
  - Hinweis „Neu – bitte prüfen“ (Text und Symbol) bei `needs_review`.
  - Im Formular das Feld `agent_id` (optional, mit Hilfetext). `room_name`
    ist keine Pflicht mehr. Speichern sendet `needs_review: false`.
  - Neue Rekorder mit `needs_review` stehen oben in der Liste.
- [ ] **Step 3: `SettingsAdmin`:** Feld `missing_grace_minutes` (0–30) mit Feldfehler-Anzeige wie die anderen Felder.
- [ ] **Step 4:** `npm test`, `npx tsc -b` und `check:i18n` sauber. Im Browser:
  - Rekorder bearbeiten: Ein doppelter Agent ergibt einen Feldfehler auf Deutsch.
  - Speichern entfernt den Hinweis „Neu – bitte prüfen“.
- [ ] **Step 5:** Commit `feat(frontend): Termine in der Raumansicht, Agent-Zuordnung in der Verwaltung`.

### Task 8: Doku, Übersetzungen, Abnahme gegen den Testserver

**Files:**
- Modify: `docs/KONFIGURATION.md`, `README.md`, `CLAUDE.md`, `backend/locale/de/LC_MESSAGES/django.po/.mo`

- [ ] **Step 1: `docs/KONFIGURATION.md`:** neuer Abschnitt „Opencast anbinden
  (optional)“ nach „Standortkonfiguration laden“; die folgenden Abschnitte
  werden umnummeriert. Inhalt:
  - Env-Variablen (`OPENCAST_URL`, `OPENCAST_USER`, `OPENCAST_PASSWORD`,
    `OPENCAST_SYNC_SECONDS`, `OPENCAST_LOOKAHEAD_DAYS`).
  - Ein eigenes Konto nur mit Leserechten. Rollen: `ROLE_API`,
    `ROLE_API_CAPTURE_AGENTS_VIEW`, `ROLE_API_EVENTS_VIEW`,
    `ROLE_API_EVENTS_SCHEDULING_VIEW`. Dazu ein Hinweis: Das Konto muss die
    geplanten Events lesen dürfen (Rolle in den Event-ACLs bzw.
    ACL-Vorlagen); sonst bleibt die Terminliste leer.
  - Prüfen per `curl -u … https://<opencast>/api/agents` und `/api/events?withscheduling=true`.
  - Zuordnung Agent ↔ Stream: Standard gleicher Name, sonst `agent_id` in
    `site.local.json` oder in der Verwaltung.
  - Neue Agents erscheinen als „Neu – bitte prüfen“ ohne Raumnamen.
  - Fehlersuche-Tabelle um drei Fälle ergänzen:
    - „Opencast-Daten veraltet“,
    - „Termine fehlen“ (ACL),
    - „Agent wird übersprungen“ (Name ungültig oder belegt, siehe Log).
- [ ] **Step 2:**
  - `README.md`: Stand auf Stufe 2 setzen und die Variablentabelle um die
    Opencast-Variablen ergänzen.
  - `CLAUDE.md`: unter Aufbau die App `opencast` aufnehmen und bei den
    Konventionen „ansehBAR schreibt nie nach Opencast“ ergänzen.
- [ ] **Step 3:** Backend-Meldungen: `makemessages -l de`, übersetzen, `compilemessages`. Danach alle Checks:
  - Backend-Tests und `ruff`,
  - `npm test`, `tsc -b`, `check:i18n`,
  - `makemigrations --check`.
- [ ] **Step 4: Manuelle Abnahme gegen `https://stable.opencast.org`.** Der
  Server wird täglich zurückgesetzt; die öffentlichen Demo-Zugangsdaten
  stehen auf seiner Startseite.
  - In der lokalen `.env` (gitignored) eintragen:
    `OPENCAST_URL=https://stable.opencast.org` sowie Benutzer und Passwort.
    Danach `docker compose up -d backend monitor`.
  - Einen Testtermin für einen vorhandenen Agent (z. B. den ersten aus
    `/api/agents`) anlegen, Start in 10 Minuten, Dauer 30 Minuten. Das ist
    der einzige schreibende Zugriff auf Opencast und geschieht von Hand,
    nicht durch ansehBAR:
    ```bash
    curl -u "$OC_USER:$OC_PASS" https://stable.opencast.org/api/events \
      -F 'metadata=[{"flavor":"dublincore/episode","fields":[{"id":"title","value":"ansehBAR Test"}]}]' \
      -F 'acl=[{"allow":true,"role":"ROLE_ADMIN","action":"read"},{"allow":true,"role":"ROLE_ADMIN","action":"write"}]' \
      -F 'processing={"workflow":"schedule-and-upload","configuration":{}}' \
      -F "scheduling={\"agent_id\":\"<AGENT>\",\"start\":\"<START>Z\",\"end\":\"<END>Z\",\"inputs\":[\"Channel A\"]}"
    ```
  - Erwartung:
    - Die Agents erscheinen als „Neu – bitte prüfen“.
    - Der Termin steht unter „Heute noch geplant“.
    - Ab Start plus Wartezeit zeigt die Kachel „Stream fehlt“ (der Testserver
      hat keine Streams).
    - Wird der Termin in Opencast gelöscht, verschwindet er beim nächsten Sync.
    - Mit falschem Passwort erscheint nach drei Intervallen das Banner
      „Opencast-Daten veraltet“, und die Stream-Kacheln laufen weiter.
  - Ergebnis in `docs/superpowers/plans/2026-11-01-ansehbar-stufe-2.md` unter
    „Abnahme“ notieren.
- [ ] **Step 5:** Commit `docs: Opencast-Anbindung, Abnahme Stufe 2`. Danach
  Push und PR `feat: Stufe 2 – Opencast-Anbindung` gegen `main`.

## Abnahme

Durchgeführt am 2026-11-01 gegen `https://stable.opencast.org` (öffentliche
Demo-Zugangsdaten, nur in der lokalen `.env`), auf API-Ebene (curl, Monitor-Log,
Django-Shell gegen die lokale API); die Sichtprüfung im Browser steht noch aus.
Zeiten in UTC.

- **Agents:** Beim ersten Sync (20:09) legte ansehBAR die drei Agents des
  Testservers als Rekorder mit leerem Raumnamen und `needs_review=true` an.
- **Termin:** Der von Hand per curl angelegte Testtermin (Start 20:18, Ende
  20:48) stand ab dem nächsten Sync als `next_event`, ab 20:18 als
  `current_event`.
- **Stream fehlt:** `missing_since` = 20:21:00 (Start plus Wartezeit von
  3 Minuten), sichtbar bei der Abfrage um 20:22; vorher `null`. Der Testserver
  hat keine Streams, `status.agent_state` meldete `capturing`.
- **Löschen:** Nach `DELETE` des Termins in Opencast (20:22:09) war er beim
  nächsten Sync (20:22:50) lokal entfernt, `current_event` und
  `missing_since` wieder `null`.
- **Falsches Passwort:** Monitor-Log `opencast sync failed: /api/agents: HTTP 401`
  und `opencast=error`. `opencast.last_success` blieb bei 20:22:50 stehen
  (um 20:26:52 über 4 Minuten alt, also über drei Intervallen, das Banner
  ginge an), während `last_check` der Stream-Prüfung weiter fortschritt
  (alle 10 s). Das Passwort kam in keinem Log vor.
- **Wiederherstellung:** Mit korrektem Passwort `opencast=ok`,
  `last_success` ging wieder voran (20:26:59).
- **Offen:** Sichtprüfung der Banner und Kacheln im Browser.
