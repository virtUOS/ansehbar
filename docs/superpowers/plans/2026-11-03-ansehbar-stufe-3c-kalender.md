# Stufe 3c: Raumkalender, Protokoll und Aufbewahrung – Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jeder Raum bekommt einen Kalender (Woche und Tag) mit seinen
Opencast-Terminen und den Vorfällen darauf. Die Raumansicht zeigt eine
Zeitleiste des laufenden Termins. Gemessene Pegel werden als Verlauf
gespeichert und angezeigt. Alte Messwerte, Vorfälle, Termine und
Zustellprotokolle löscht der Monitor nach einstellbaren Fristen.

**Architecture:**
- Der Audio-Thread speichert jede erfolgreiche Messung als `AudioSample`.
- Zwei neue, nur lesende Endpunkte liefern die Daten:
  - `GET /api/recorders/<id>/calendar/` für einen Zeitraum, mit Terminen, Vorfällen und Problemen;
  - `GET /api/events/<id>/` für einen Termin, mit Vorfällen und Pegelverlauf.
- Die Problem-Logik aus `last_recording` wandert in ein eigenes Modul, damit Kachel und Kalender dasselbe melden.
- Im Frontend gibt es eine reine Funktion für die Einträge der Zeitleiste und eine SVG-Pegelkurve.
  Die Raumansicht nutzt beides für den laufenden Termin, die Tagesansicht des Kalenders für jeden Termin.
- Das Aufräumen läuft stündlich im `run_monitor`-Hauptzyklus.

**Tech Stack:** Django 5.1, DRF, Postgres, React/Vite, react-router, vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`. Maßgeblich
sind 7.5 (Kalender, Aufbewahrung), 5.2 (Zeitleiste der Raumansicht), 5.0
(Kalender nach Raumnamen, Historie beim alten Rekorder) und 7.3 (kurze Stillen
in der Zeitleiste).

## Global Constraints

Es gelten alle Global Constraints aus
`docs/superpowers/plans/2026-11-03-ansehbar-stufe-3a-stream-alarme.md` und
`docs/superpowers/plans/2026-11-03-ansehbar-stufe-3b-ton.md`, unverändert. Die wichtigsten:
- SPDX-Header in jeder neuen Datei, auch in Migrationen.
- Texte: Backend mit gettext (`.po` und `.mo` einchecken); Frontend mit
  englischem i18n-Key, Deutsch in `translation.json`.
- Nur fiktive Werte im Repo (Räume wie „Testraum 1“, Streams wie `cap-test-1`).
- Status immer mit Text **und** Symbol; Akzentfarbe (brand) nie als Statusfarbe;
  Dark-Mode-Text mindestens `slate-300`.
- Der Monitor schreibt nur mit `save(update_fields=[…])` oder `bulk_create`/
  `delete`; der Audio-Thread schreibt am Status weiterhin nur `audio_*` und
  `silent_since`.
- ansehBAR schreibt nie nach Opencast oder Keycloak.
- Kein Django-Admin, keine Browser-Dialoge.
- Prüfbefehle wie in `CLAUDE.md`.

## Entscheidungen, die dieser Plan festlegt

- **Messwerte:** Eine Zeile `AudioSample` pro erfolgreicher Messung
  (`recorder`, `event`, `measured_at`, `level_db`; `level_db = null` heißt
  „keine Audiospur“).
  - Der Audio-Durchlauf misst höchstens alle 30 s, also etwa zwei Werte pro
    Minute. Eine eigene Tabelle mit Minutenwerten bringt da nichts. Die
    Messwerte selbst sind die verdichtete Form (7.5 „verdichtete Werte pro
    Minute“). *Meine Wahl.*
  - Fehlgeschlagene Messungen werden nicht gespeichert; sie erscheinen in der
    Kurve als Lücke.
  - Nebeneffekt: Mit dem Verlauf lässt sich die Stille-Schwelle an echten
    Vorlesungen kalibrieren (Spec §10).
- **Aufbewahrung** (in `MonitorSettings`, über die Oberfläche):

  | Feld | Standard | Bereich | löscht |
  |---|---|---|---|
  | `sample_retention_days` | 30 | 1 bis 365 | `AudioSample` mit `measured_at` älter |
  | `history_retention_days` | 400 | 183 bis 3650 | `Incident` (`started_at`), `ScheduledEvent` (`end`), `SentNotification` (`created_at`) älter |

  - 183 Tage als Untergrenze erfüllt „Vorfälle mindestens ein Semester“.
  - 400 Tage als Standard erlaubt den Vergleich mit dem Vorjahressemester.
  - Laufende oder künftige Termine und offene Vorfälle sind nie älter als die
    Frist, weil diese mindestens 183 Tage beträgt. Eine eigene Sonderregel
    dafür entfällt.
  - Das Aufräumen läuft im Hauptzyklus von `run_monitor` höchstens einmal pro
    Stunde und bei `--once` immer.
  - Der Opencast-Abgleich holt nur `OPENCAST_LOOKBACK_DAYS` zurück (Standard 7).
    Gelöschte alte Termine kommen deshalb nicht wieder.
- **Kalender = Rekorder plus gleicher Raumname** (5.0): Der Kalender des
  Rekorders X zeigt die Termine aller Rekorder mit genau demselben, nicht
  leeren `room_name`, auch inaktive. Ein Rekorder ohne Raumnamen zeigt nur
  seine eigenen. Jeder Termin trägt `recorder_id`, damit die Oberfläche bei
  mehreren Rekordern den Stream-Namen dazuschreibt.
- **Zeitraum:** `from` ist ein lokales Datum (`YYYY-MM-DD`, Zeitzone der
  App), `days` liegt zwischen 1 und 7 (Standard 7). Der Zeitraum geht von
  lokaler Mitternacht `from` bis lokaler Mitternacht `from + days`. Das
  stimmt auch über die Zeitumstellung hinweg. Ein Termin gehört zum Zeitraum,
  wenn er ihn überlappt (`start < bis` und `end > von`).
- **Wochenansicht:** Montag bis Sonntag, auf breiten Bildschirmen sieben
  Spalten, auf schmalen untereinander. Ein Termin ist eine Karte mit
  Zeitfenster, Titel und Markern. Ein Klick öffnet den Tag.
- **Tagesansicht:** jeder Termin des Tages ausgeklappt, mit Zeitleiste und
  Pegelkurve (je ein Abruf von `/api/events/<id>/`).
- **Marker auf einer Karte** (immer Symbol und Text):
  - `⚠ Stream fehlte N min`: Summe der `stream_missing`-Vorfälle.
  - `◐ Still N min`: Summe der `audio_silent`-Vorfälle.
  - `🔔 Alarm`: mindestens ein Vorfall mit `alerted_at`.
  - Opencast-Probleme in denselben Texten wie bei „Letzte Aufzeichnung“.
  - Ohne Vorfälle und Probleme bei beendeten Terminen `✓ ohne Befund`.
- **Zeitleiste eines Termins** (5.2), zeitlich sortiert:

  | Eintrag | Bedingung | Text (i18n-Key) |
  |---|---|---|
  | `stable` | laufender Termin, Stream live, kein offener `stream_missing` | `✓` „Picture stable since {{time}}“ (`time` = `max(live_since, start)`) |
  | `first_audio` | `first_audio_at` gesetzt | `🔊` „First sound at {{time}}“ |
  | `missing` | `stream_missing`, beendet | `⚠` „{{time}} Stream missing {{minutes}} min“ |
  | `missing_open` | `stream_missing`, offen | `⚠` „Stream missing since {{time}}“ |
  | `silent` | `audio_silent`, Dauer `(ended_at ?? silent_until) − started_at` | `◐` „{{time}} Silent {{minutes}} min (logged)“ |
  | `silent_open` | `audio_silent`, offen | `◐` „Silent since {{time}}“ |
  | `alarm` | Vorfall mit `alerted_at` | `🔔` „Alarm raised {{time}}“ |
  | `all_clear` | Vorfall mit `all_clear_at` | `✓` „All clear sent {{time}}“ |

  Minuten werden gerundet, mindestens 1. Ein leerer Termin in der
  Vergangenheit zeigt „No incidents“.
- **Pegelkurve:** SVG über die Termindauer, y von −70 dBFS (unten; tiefere Werte
  und `null` werden dort gezeichnet) bis 0 dBFS. Die Schwelle ist eine
  gestrichelte Linie. Zwei Messwerte mit mehr als 120 s Abstand werden nicht
  verbunden. `role="img"` mit einem `aria-label` als Zusammenfassung:
  „Level curve: {{count}} measurements, {{silent}} below the threshold“.
- **Raumansicht:** `current_event` bekommt die `id`. Läuft ein Termin, zeigt die
  Raumansicht unter dem Titel Zeitleiste und Pegelkurve. Sie lädt
  `/api/events/<id>/` beim Wechsel des Termins und danach alle 30 s neu. Ein
  Link „Calendar“ (`/raum/<id>/kalender`) steht immer neben „Raum wechseln“.
- **Nicht in 3c:** Abgleich fehlender Aufzeichnungen (7.5 „später“), Filter
  über mehrere Räume, Export, Monats- oder Semesteransicht.

## Review Focus

1. **Woche mit Zeitumstellung:** Die Woche vom 2026-10-19 bis 25 ist ein
   Beispiel. Am Sonntag, dem 25., endet die Sommerzeit. Ein Termin am
   Sonntagabend muss in `from=2026-10-19&days=7` enthalten sein, einer am
   Montag, dem 26., nicht. Den Test dafür hat Task 3.
2. **Ausgetauschter Rekorder:** Ein alter inaktiver Rekorder mit gleichem
   Raumnamen erscheint im Kalender des neuen und umgekehrt. Ein Rekorder mit
   leerem Raumnamen zieht nie fremde Termine an, auch keine anderer Rekorder
   ohne Namen. Den Test dafür hat Task 3.
3. **Unsinnige Parameter:** `from=2026-13-01`, `from=abc`, `days=0`, `days=8`
   oder `days=x` liefern 400 mit Meldung, nie 500. Eine unbekannte ID
   liefert 404. Den Test dafür hat Task 3.
4. **Aufräumen und Laufendes:** Ein Termin, der vor der Frist endete, wird
   samt seinen Vorfällen gelöscht. Ein Termin, der nach der Frist endete,
   bleibt mit allen Vorfällen, auch wenn er vor der Frist begann. Messwerte
   und Historie haben getrennte Fristen. Den Test dafür hat Task 2.
5. **Termin ohne Messwerte oder ohne Audiospur:** Die Kurve zeigt bei
   `samples = []` den Text „No level measurements“ statt einer leeren Fläche.
   `null`-Werte liegen unten an der Kurve und zählen als „below the
   threshold“. Den Test dafür hat Task 5 (für die reine Funktion
   `levelCurve`).

---

### Task 1: Messwerte speichern

**Files:**
- Modify: `backend/recorders/models.py`, `backend/recorders/audio_monitor.py`
- Create: `backend/recorders/migrations/0010_audiosample.py`
- Test: `backend/recorders/tests.py`

**Interfaces:**
- Produces: das Modell `recorders.AudioSample` mit diesen Feldern:
  - `recorder`: FK auf `Recorder`, CASCADE, `related_name="audio_samples"`;
  - `event`: FK auf `opencast.ScheduledEvent`, SET_NULL, null, `related_name="audio_samples"`;
  - `measured_at`: DateTime;
  - `level_db`: Float, null;
  - Index auf `(event, measured_at)` und auf `measured_at`; `ordering = ["measured_at"]`.

- [ ] **Step 1: Tests schreiben** (im Stil der vorhandenen `run_audio_pass`-Tests mit Fake-`measure`):
  - `test_audio_pass_stores_sample`: Nach einer Messung mit −35,0 gibt es genau ein `AudioSample` mit Rekorder, Termin, `measured_at == now` (aus `now_fn` nach den Messungen) und `level_db == -35.0`.
  - `test_audio_pass_stores_no_track_sample`: Bei `level_db=None` hat das Sample `level_db is None`.
  - `test_audio_pass_stores_clamped_sample`: −inf wird als `AUDIO_FLOOR_DB` gespeichert.
  - `test_failed_measurement_stores_no_sample`: Bei `ok=False` gibt es kein Sample.
- [ ] **Step 2:** Tests laufen lassen; sie müssen fehlschlagen.
- [ ] **Step 3:** Modell, Migration (SPDX-Header) und Schreiben umsetzen. `_write` erzeugt im Erfolgsfall ein Sample mit dem schon geklemmten `level`.
- [ ] **Step 4:** Backend-Tests, ruff, `makemigrations --check` grün.
- [ ] **Step 5: Commit** `feat(audio): store level samples`

### Task 2: Aufbewahrung

**Files:**
- Modify: `backend/recorders/models.py` (zwei Felder an `MonitorSettings`), `backend/recorders/serializers.py` (`MonitorSettingsSerializer`)
- Create: `backend/recorders/migrations/0011_retention.py`, `backend/recorders/retention.py`
- Modify: `backend/recorders/management/commands/run_monitor.py`
- Modify: `frontend/src/api.ts` (`MonitorSettings`), `frontend/src/pages/admin/SettingsAdmin.tsx`, `frontend/src/locales/de/translation.json`
- Test: `backend/recorders/tests.py`

**Interfaces:**
- Produces:
  - die Felder `sample_retention_days` und `history_retention_days` mit Standards und Bereichen wie in der Tabelle oben (`PositiveSmallIntegerField` mit Min/Max-Validatoren);
  - `prune_history(now: datetime) -> dict[str, int]` in `recorders/retention.py`:
    - liefert die Zahl gelöschter Zeilen unter den Keys `"samples"`, `"incidents"`, `"events"` und `"notifications"`;
    - löscht in dieser Reihenfolge: Samples, Notifications, Incidents, Events. Termine werden erst nach ihren Vorfällen gelöscht, damit keine Vorfälle ohne Termin übrig bleiben.
  - In `run_monitor`:
    - `_prune_due(self) -> bool` ist wahr, wenn das letzte Aufräumen mindestens 3600 s her ist oder es noch keines gab.
    - Danach folgt `prune_history(timezone.now())`.
    - Wenn etwas gelöscht wurde, wird eine Info-Zeile geloggt.
    - Ein Fehler wird geloggt und beendet den Monitor nicht (wie beim Sync).
- Frontend:
  - In den Einstellungen ein `fieldset` „History“ („Aufbewahrung“) mit zwei Zahlenfeldern in Tagen.
  - Hinweise: „Level measurements are deleted after this many days.“ und „Incidents, events and sent notifications are deleted after this many days (at least one semester).“

- [ ] **Step 1: Tests schreiben:**
  - `test_prune_deletes_old_samples_only`: Samples von vor 31 und 29 Tagen; das ältere ist weg, das jüngere bleibt.
  - `test_prune_deletes_event_with_incidents`: Termin mit Ende vor 401 Tagen, mit zwei Vorfällen und einer `SentNotification` (erstellt vor 401 Tagen); alles ist weg.
  - `test_prune_keeps_event_ending_after_cutoff`: Termin mit Start vor 400 Tagen und 1 h, Ende vor 399 Tagen; er bleibt mit seinem Vorfall.
  - `test_prune_uses_settings`: Mit `sample_retention_days=1` wird ein Sample von vor 2 Tagen gelöscht.
  - `test_settings_retention_bounds`: Die API lehnt `history_retention_days=182` und `sample_retention_days=0` mit 400 ab.
  - `test_run_monitor_once_prunes`: `run_monitor --once` ruft `prune_history` auf. `patch` wie bei den anderen `--once`-Tests.
- [ ] **Step 2:** Die Tests müssen fehlschlagen.
- [ ] **Step 3:** Backend umsetzen, dann Einstellungsseite und Übersetzungen.
- [ ] **Step 4:** Backend-Tests, ruff, `makemigrations --check`, `tsc -b`, `npm test`, `check:i18n` grün.
- [ ] **Step 5: Commit** `feat: retention of samples and history`

### Task 3: Kalender-API und gemeinsame Problem-Logik

**Files:**
- Create: `backend/recorders/history.py`
- Modify: `backend/recorders/serializers.py` (`get_last_recording` nutzt `history.py`)
- Modify: `backend/recorders/views.py` (`@action(detail=True, methods=["get"]) calendar` am `RecorderViewSet`)
- Test: `backend/recorders/tests.py`

**Interfaces:**
- Produces in `recorders/history.py`:
  - `recording_problems(event, incidents, now, silence_alarm_minutes: int) -> list[dict]`:
    - die bisherige Logik aus `get_last_recording` unverändert;
    - liefert Vorfall-Probleme mit `kind`, `from`, `to` und `minutes`, danach die Opencast-Probleme;
    - die vorhandenen `last_recording`-Tests müssen ohne Änderung grün bleiben.
  - `incident_data(incident) -> dict` mit den Keys `id`, `kind`, `started_at`, `ended_at`, `recovered`, `alerted_at`, `all_clear_at` und `silent_until`, Zeiten als ISO-Strings oder `None`.
  - `calendar_range(day: date, days: int) -> tuple[datetime, datetime]`: von lokaler Mitternacht bis lokaler Mitternacht.
- Produces (API) `GET /api/recorders/<id>/calendar/?from=YYYY-MM-DD&days=N`:
  - Ohne `from` gilt der heutige lokale Tag.
  - Antwort:

    ```json
    {
      "from": "<ISO>", "to": "<ISO>",
      "recorders": [{"id": 1, "room_name": "…", "stream_name": "…", "active": true}],
      "events": [{
        "id": 7, "recorder_id": 1, "title": "…", "series": "…",
        "start": "<ISO>", "end": "<ISO>", "opencast_status": "…",
        "first_audio_at": "<ISO>|null",
        "incidents": [<incident_data>],
        "problems": [<recording_problems, nur für beendete Termine, sonst []>]
      }]
    }
    ```

  - `recorders` enthält den angefragten Rekorder und alle mit gleichem, nicht leerem `room_name`; `events` ist nach `start` sortiert.
  - Fehler: 400 mit `{"detail": …}` (gettext) für ungültiges `from` oder `days`; 404 für eine unbekannte ID.
  - Abfragen: konstant, höchstens 4, unabhängig von der Zahl der Termine und Vorfälle.

- [ ] **Step 1: Tests schreiben** (fiktive Räume, `Europe/Berlin` wie in den vorhandenen Tests):
  - `test_calendar_week_lists_events_with_incidents`: zwei Termine mit je einem Vorfall; Struktur und Sortierung wie oben.
  - `test_calendar_week_across_dst`: der Fall aus Review Focus 1; zusätzlich `to - from == 7 Tage + 1 h` in UTC.
  - `test_calendar_includes_same_room_recorders`: ein alter inaktiver Rekorder „Testraum 1“ und ein neuer „Testraum 1“; jeder Kalender enthält beide Termine und beide Rekorder.
  - `test_calendar_empty_room_name_stays_alone`: zwei Rekorder ohne Raumnamen; jeder sieht nur seine eigenen Termine.
  - `test_calendar_rejects_bad_params`: alle Fälle aus Review Focus 3.
  - `test_calendar_overlap`: ein Termin, der vor `from` beginnt und danach endet, ist enthalten.
  - `test_calendar_problems_only_for_ended_events`: ein laufender Termin mit langem `stream_missing` hat `problems == []`, ein beendeter hat das Problem.
  - `test_calendar_query_count`: mit 1 und mit 5 Terminen gleich viele Abfragen (`assertNumQueries`).
  - `test_calendar_requires_access`: ohne Zugang 403, wie bei den anderen Endpunkten.
- [ ] **Step 2:** Die Tests müssen fehlschlagen; die vorhandenen `last_recording`-Tests laufen weiter.
- [ ] **Step 3:** `history.py` herauslösen, `get_last_recording` darauf umstellen, die Action umsetzen. Neue Meldungen mit `makemessages` und `compilemessages` übersetzen.
- [ ] **Step 4:** Backend-Tests und ruff grün.
- [ ] **Step 5: Commit** `feat(api): room calendar`

### Task 4: Termin-Detail-API

**Files:**
- Modify: `backend/opencast/views.py` (`EventDetailView(APIView)`, ohne eigenen Serializer)
- Modify: `backend/config/api_urls.py`, `backend/recorders/serializers.py` (`_event_data` bekommt `id`)
- Modify: `frontend/src/api.ts`
- Test: `backend/opencast/tests.py`, `backend/recorders/tests.py`

**Interfaces:**
- Consumes: `incident_data` aus Task 3 und `AudioSample` aus Task 1.
- Produces (API):
  - `GET /api/events/<id>/` (Name `event-detail`, Recht `HasAccess`). Antwort:

    ```json
    {
      "id": 7, "recorder_id": 1, "title": "…", "series": "…",
      "start": "<ISO>", "end": "<ISO>", "opencast_status": "…",
      "first_audio_at": "<ISO>|null",
      "threshold_db": -50,
      "incidents": [<incident_data>, nach started_at],
      "samples": [{"t": "<ISO>", "db": -35.2}]
    }
    ```

  - `samples` enthält nur Messwerte dieses Termins mit `start <= measured_at <= end`, nach Zeit sortiert. `db` ist auf eine Nachkommastelle gerundet oder `null`.
  - `threshold_db` ist die aktuelle `silence_threshold_db`.
  - Eine unbekannte ID liefert 404.
  - Abfragen: konstant, höchstens 4.
  - `EventBrief` und `_event_data` bekommen `id: number`. Damit hat `current_event` des Rekorders eine ID.
- Produces (Frontend `api.ts`):
  - die Typen `IncidentKind = "stream_missing" | "audio_silent"`, `IncidentEntry`, `CalendarEvent`, `CalendarResponse`, `LevelSample` und `EventDetail`, passend zu den beiden Antworten;
  - die Methoden `api.calendar(recorderId: number, from: string, days: number): Promise<CalendarResponse>` und `api.event(id: number): Promise<EventDetail>`.

- [ ] **Step 1: Tests schreiben:**
  - `test_event_detail_returns_incidents_and_samples`: Ein Sample vor `start` und eines nach `end` fehlen in der Antwort; Rundung auf eine Nachkommastelle.
  - `test_event_detail_404`.
  - `test_event_detail_requires_access`.
  - `test_event_detail_query_count`.
  - In den Recorder-Tests: `current_event["id"]` entspricht dem Termin.
- [ ] **Step 2:** Die Tests müssen fehlschlagen. Dann umsetzen, inklusive der Typen und Methoden in `api.ts`.
- [ ] **Step 3:** Backend-Tests, ruff und `tsc -b` grün.
- [ ] **Step 4: Commit** `feat(api): event detail with incidents and level samples`

### Task 5: Zeitleiste und Pegelkurve, Raumansicht

**Files:**
- Create: `frontend/src/timeline.ts`, `frontend/src/timeline.test.ts`
- Create: `frontend/src/components/EventTimeline.tsx`, `frontend/src/components/LevelCurve.tsx`
- Create: `frontend/src/useEventDetail.ts`
- Create: `frontend/src/problemTexts.ts`. Dorthin wandern die Problemtexte aus `LastRecordingWarning.tsx`. `LastRecordingWarning` nutzt sie danach selbst; Task 6 braucht sie für die Kalender-Marker.
- Modify: `frontend/src/pages/RoomView.tsx`, `frontend/src/components/LastRecordingWarning.tsx`, `frontend/src/locales/de/translation.json`

**Interfaces:**
- Consumes: `EventDetail`, `IncidentEntry`, `LevelSample` und `api.event` aus Task 4.
- Produces:
  - In `timeline.ts`:
    - Typ `TimelineEntry = { kind: "stable" | "first_audio" | "missing" | "missing_open" | "silent" | "silent_open" | "alarm" | "all_clear"; at: string; minutes?: number }`.
    - `timelineEntries(event: { start; end; first_audio_at; incidents }, now: Date, liveSince: string | null): TimelineEntry[]`:
      - Einträge und Bedingungen wie in der Tabelle oben, nach `at` sortiert;
      - `liveSince` nur übergeben, wenn der Termin läuft und der Raum live ist.
  - In `timeline.ts` außerdem:
    - Typ `CurveSegment = { x: number; y: number }[]`.
    - `levelCurve(samples: LevelSample[], start: string, end: string, thresholdDb: number, width: number, height: number) -> { segments: CurveSegment[]; thresholdY: number; silentCount: number }`:
      - y-Bereich −70 bis 0 dBFS; Werte darunter und `null` liegen bei −70;
      - nach einer Lücke über 120 s beginnt ein neues Segment.
  - `EventTimeline({ entries })`: eine Liste `<ol>`. Jeder Eintrag hat Symbol (`aria-hidden`), Uhrzeit (`formatClock`) und Text; die Texte stehen in der Tabelle oben.
  - `LevelCurve({ detail })` zeichnet die Kurve als SVG.
  - `useEventDetail(id: number | null, refreshMs = 30000)` liefert `{ detail, error }`:
    - Bei `id = null` lädt es nichts.
    - Bei einem Wechsel der `id` wird der alte Stand sofort verworfen.
  - In `problemTexts.ts`: `problemText(t, problem: RecordingProblem, lang: string): string`.
  - In der Raumansicht:
    - Abschnitt „Timeline“ (`<h2>`) unter dem Termintitel, nur bei laufendem Termin;
    - Link „Calendar“ (lucide `CalendarDays`, `min-h-11`) neben der Raumauswahl.

- [ ] **Step 1: vitest schreiben (`timeline.test.ts`):**
  - Ein offener `stream_missing`-Vorfall ergibt `missing_open` und kein `stable`.
  - Live ohne Vorfälle ergibt `stable` mit `at = max(liveSince, start)`.
  - `audio_silent` mit `ended_at = null` und `silent_until` 4 min nach dem Start ergibt `silent_open`. Beendet ergibt er `silent` mit `minutes = 4`.
  - Ein Vorfall mit `alerted_at` und `all_clear_at` ergibt zusätzlich `alarm` und `all_clear` an den richtigen Zeiten.
  - `minutes` ist mindestens 1, die Sortierung zeitlich.
  - `levelCurve`: Bei einer Lücke von 121 s entstehen 2 Segmente, bei 119 s eins.
  - `levelCurve`: `null` und −80 liegen bei `y = height`; 0 dBFS bei `y = 0`.
  - `levelCurve`: `silentCount` zählt Werte unter der Schwelle und `null`.
- [ ] **Step 2:** Die Tests müssen fehlschlagen. Dann umsetzen.
- [ ] **Step 3:** Prüfen: `tsc -b`, `npm test`, `check:i18n`.
- [ ] **Step 4: Im Browser prüfen.**
  - Per Django-Shell einen laufenden Testtermin anlegen, mit einer beendeten Stille (4 min), einem alarmierten `stream_missing` mit Entwarnung und etwa 20 Samples.
  - Sichtbar sein müssen:
    - Zeitleiste und Kurve;
    - Hell- und Dunkelmodus;
    - die Smartphone-Breite (375 px) ohne horizontales Scrollen.
  - Testdaten danach löschen.
- [ ] **Step 5: Commit** `feat(ui): event timeline and level curve in the room view`

### Task 6: Kalenderseite

**Files:**
- Create: `frontend/src/pages/RoomCalendar.tsx`, `frontend/src/calendar.ts`, `frontend/src/calendar.test.ts`
- Modify: `frontend/src/main.tsx` (Route `raum/:id/kalender`), `frontend/src/locales/de/translation.json`

**Interfaces:**
- Consumes:
  - `api.calendar` und `CalendarResponse` aus Task 4;
  - `EventTimeline`, `LevelCurve`, `useEventDetail`, `timelineEntries` und `problemText` aus Task 5.
- Produces in `calendar.ts`:
  - `weekStart(day: Date): Date` (Montag, lokale Zeit);
  - `isoDay(d: Date): string` (`YYYY-MM-DD`, lokale Zeit);
  - `addDays(d: Date, n: number): Date`;
  - `eventMarkers(event: CalendarEvent, now: Date): Marker[]` mit `Marker = { kind: "missing" | "silent" | "alarm" | "problem" | "clean"; minutes?: number; problem?: RecordingProblem }`;
  - `groupByDay(events, from: Date, days: number): { day: string; events: CalendarEvent[] }[]`:
    - Ein Termin über Mitternacht steht an beiden Tagen.
    - Die Tage sind lokal.
- URL-Zustand über Query-Parameter: `?ansicht=woche|tag&datum=YYYY-MM-DD`. Standard sind Woche und heute. Neu laden und Teilen behalten die Ansicht.
- Seite:
  - Kopf: „Back“ zur Raumansicht, `<h1>` „Calendar – {{room}}“, Umschalter Woche/Tag (`aria-pressed`), „Previous“, „Today“, „Next“ (`min-h-11`).
  - Bei mehr als einem Rekorder steht an jedem Termin der Stream-Name (`font-mono`, klein).
  - Wochenansicht: wie in „Entscheidungen“ beschrieben. Ein leerer Tag zeigt „No events“.
  - Tagesansicht: jeder Termin mit `<h2>` (Zeitfenster und Titel), Markern, `EventTimeline` (ohne `liveSince`; `stable` nur, wenn der Termin läuft und der Rekorder live ist) und `LevelCurve`.
  - Lade- und Fehlerzustand wie in den Admin-Seiten (`role="status"` bzw. `role="alert"`).

- [ ] **Step 1: vitest schreiben (`calendar.test.ts`):**
  - `weekStart` von Sonntag, dem 2026-10-25, liefert Montag, den 2026-10-19.
  - `isoDay(addDays(2026-10-24, 2)) === "2026-10-26"`, also über die Zeitumstellung hinweg.
  - `groupByDay`: Ein Termin von 23:00 bis 01:00 steht an beiden Tagen.
  - `eventMarkers`:
    - Summiert zwei `stream_missing` zu einem Marker.
    - Liefert `clean` nur für beendete Termine ohne Vorfälle und Probleme.
    - Liefert `alarm`, wenn ein `alerted_at` gesetzt ist.
- [ ] **Step 2:** Die Tests müssen fehlschlagen. Dann umsetzen.
- [ ] **Step 3:** Prüfen: `tsc -b`, `npm test`, `check:i18n`.
- [ ] **Step 4: Im Browser prüfen.**
  - Testdaten: mehrere Termine über eine Woche, darunter einer mit Opencast-Problem.
  - Woche und Tag ansehen, Blättern und den Link aus der Raumansicht nutzen.
  - Die Smartphone-Breite (375 px) und den Dunkelmodus prüfen.
  - Mit der Tastatur alle Bedienelemente erreichen.
  - Testdaten danach löschen.
- [ ] **Step 5: Commit** `feat(ui): room calendar`

### Task 7: Doku

**Files:**
- Modify: `docs/KONFIGURATION.md`: neuer Abschnitt „Aufbewahrung“ mit den beiden Fristen, was sie löschen und wann aufgeräumt wird.
- Modify: `README.md` (Stand) und `CLAUDE.md` (Aufbau):
  - `retention.py`, `history.py` und `AudioSample` nennen;
  - Kalender und Zeitleiste im Frontend nennen.
- Modify: Spec §9: 3c als umgesetzt markieren.
- Modify: Spec §10: Als Hilfe beim Kalibrieren den gespeicherten Pegelverlauf nennen.

- [ ] **Step 1:** Texte schreiben. Keine echten Host- oder Raumnamen.
- [ ] **Step 2:** Alle Prüfbefehle grün.
- [ ] **Step 3: Commit** `docs: room calendar, timeline and retention (stage 3c)`
