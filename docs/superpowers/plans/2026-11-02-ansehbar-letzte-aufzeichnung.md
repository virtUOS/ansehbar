# ansehBAR Hinweis „Letzte Aufzeichnung hatte Probleme“ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pro Raum einen Warnhinweis zeigen, wenn die letzte Aufzeichnung Probleme hatte, und dazu sagen, welche. Die Probleme kommen aus zwei Quellen:
- **ansehBARs eigene Beobachtung:** Der Stream fehlte während des Termins, mit Zeitspannen.
- **Opencast-Status des Termins:** Verarbeitung fehlgeschlagen, Aufzeichnung fehlgeschlagen, nie gestartet oder nicht abgeschlossen.

**Architecture:**
- Der Monitor schreibt Lücken im Stream als `Incident` (Typ `stream_missing`) mit Beginn und Ende. Das ist der erste Baustein des Ausfallprotokolls aus Stufe 3.
- Der Opencast-Abgleich speichert zusätzlich den Opencast-Status jedes Termins. Er reicht dafür 7 Tage zurück, damit der letzte Termin eines Raums auch über ein Wochenende hinweg aktuell bleibt.
- Die Rekorder-API liefert `last_recording` mit einer Liste `problems`.
- Das Frontend zeigt den Hinweis in Kachel, Raumansicht, Raumliste und Pills.

**Tech Stack:** wie bisher.

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`. Bezug: §7.1 Vorfall `stream_missing`, §7.5 Protokoll; die Alarme selbst bleiben Stufe 3. Neu ist §6b (Task 5).

**Erkundet am echten Opencast (2026-11-02, 14 Tage):**
- 247 Events. Status-Werte: `EVENTS.EVENTS.STATUS.PROCESSED`, `PROCESSING`, `PROCESSING_FAILURE`, `RECORDING`, `INGESTING`.
- 92 verarbeitete Events haben **kein** `scheduling` mehr, darunter die 3 Fehlschläge. Das sind teils Uploads.
- Damit ein geplanter Termin nach der Verarbeitung nicht aus dem Spiegel fällt, gilt: Ohne `scheduling` werden `location` als Agent-ID und Dublin-Core-`start` plus `duration` (ms) als Zeitfenster genutzt. Nur wenn `location` leer ist, wird der Termin übersprungen.

## Global Constraints

- Wie in den bisherigen Plänen:
  - SPDX-Header.
  - i18n EN → DE.
  - gettext für Backend-Texte.
  - ansehBAR schreibt nie nach Opencast.
  - Keine Zugangsdaten oder Hosts in Logs, API oder Doku.
  - Status immer mit Text **und** Symbol. Für Warnungen Amber (nicht brand, nicht Rot = „fehlt jetzt“). Dark-Text mindestens `slate-300`.
  - Stream-Namen und Agent-IDs sind case-sensitiv.
  - Kein Prettier auf ganze Dateien.
  - Commits enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- „Status unbekannt“ ist nie eine Lücke im Stream. Ein offener Vorfall bleibt bei `unknown` offen und wird nicht beendet.
- Branch `feature/letzte-aufzeichnung` (basiert auf `feature/morgen-vorschau`); am Ende ein PR, der gestapelt auf diesen Branch zielt.

## Review Focus

1. **Monitor-Neustart oder kurzes Flackern während einer Lücke:** Ein Vorfall wird nicht doppelt angelegt. Ein offener Vorfall wird fortgesetzt, nicht neu begonnen. Test in Task 1.
2. **Termin endet, während der Stream noch fehlt:** Der Vorfall wird mit dem Terminende geschlossen, nicht später. Test in Task 1.
3. **Verarbeitetes Event ohne `scheduling`:** Es bleibt dem Raum zugeordnet und wird nicht gelöscht. Test in Task 2.
4. **Termin noch in Verarbeitung (`PROCESSING`):** Das ist kein Problem. `SCHEDULED` eine halbe Stunde nach Ende heißt dagegen „nicht gestartet“. Test in Task 3.
5. **Abfragen:** Die Liste braucht weiterhin eine konstante Zahl an Datenbankabfragen. Test in Task 3.

---

### Task 1: Vorfälle „Stream fehlt“ im Monitor protokollieren

**Files:**
- Create: `backend/recorders/incidents.py`
- Modify: `backend/recorders/models.py` (+ Migration), `backend/recorders/management/commands/run_monitor.py`, `backend/recorders/tests.py`

**Interfaces:**
- Produces:
  - `recorders.models.Incident`:
    - `recorder: FK Recorder CASCADE related_name="incidents"`
    - `event: FK opencast.ScheduledEvent SET_NULL null related_name="incidents"`
    - `kind: CharField(20)`, Choices `stream_missing`
    - `started_at: DateTimeField`, `ended_at: DateTimeField(null=True)`
    - Ordering `started_at`; Index (`recorder`, `started_at`)
  - `recorders.incidents.update_incidents(now: datetime) -> None`. Läuft nach jedem `run_cycle` im Haupt-Thread. Pro aktivem Rekorder:
    - **Gerade fehlend** heißt: ein laufender Termin (`start <= now < end`), Status `offline`, und `now >= start + missing_grace_minutes`. Das ist dieselbe Regel wie `missing_since` in `serializers.py`; die Logik als gemeinsame Funktion herausziehen und an beiden Stellen nutzen.
    - Fehlt der Stream und gibt es keinen offenen Vorfall für diesen Termin, wird einer angelegt. `started_at` ist der Wert von `missing_since`.
    - Status `live` schließt einen offenen Vorfall mit `ended_at = now`.
    - Ist das Terminende erreicht und der Vorfall noch offen, wird er mit `ended_at = event.end` geschlossen.
    - Status `unknown` ändert nichts.
    - Inaktive Rekorder bekommen keine neuen Vorfälle.
    - Alles mit möglichst wenigen Abfragen: Termine und offene Vorfälle einmal laden.
  - In `run_monitor._cycle` wird `update_incidents(now)` nach `run_cycle` aufgerufen, mit eigenem `try/except` und Log-Eintrag, damit ein Fehler den Zyklus nicht stoppt.
- [ ] **Step 1: Failing tests** (`now` per Parameter):
  - `test_incident_opened_after_grace`: Termin ab 10:00, grace 3, offline. Um 10:02 gibt es keinen Vorfall, um 10:05 einen mit `started_at = 10:03`.
  - `test_incident_closed_when_live`
  - `test_incident_closed_at_event_end`: Um 12:05 ist der Vorfall noch offen, das Terminende war 12:00, also `ended_at = 12:00`.
  - `test_incident_not_duplicated_across_cycles_and_restart`: dreimal hintereinander offline ergibt genau 1 Vorfall.
  - `test_unknown_keeps_incident_open`: offline, dann unknown, dann live. Ergebnis ist 1 Vorfall, geschlossen beim Wechsel auf live.
  - `test_second_gap_same_event_new_incident`: offline, live, offline ergibt 2 Vorfälle.
  - `test_inactive_recorder_no_incident`
  - `test_update_incidents_error_does_not_stop_cycle`: in `run_monitor`.
- [ ] **Step 2–4:** FAIL, dann implementieren, dann PASS. Dazu ruff und `makemigrations --check`.
- [ ] **Step 5:** Commit `feat(monitor): Lücken im Stream während Terminen als Vorfall protokollieren`.

### Task 2: Opencast-Status der Termine und Rückblick

**Files:** Modify `backend/opencast/{client,sync,models}.py` (+ Migration), `backend/opencast/tests.py`, `backend/config/settings.py`, `docker-compose.yml`, `docker-compose.prod.yml`, `.env.prod.example`.

**Interfaces:**
- `Event` bekommt `status: str`, den rohen Wert, z. B. `"EVENTS.EVENTS.STATUS.PROCESSED"`. Fehlt er, ist der Wert `""`.
- **Client-Fallback:** Ohne `scheduling.agent_id`, aber mit nicht leerem `location`, gilt `agent_id = location`, `start` ist der Dublin-Core-`start` und `end = start + duration` (ms). Ohne beides wird der Termin übersprungen, wie bisher.
- `ScheduledEvent.opencast_status: CharField(60, blank=True)` wird beim Upsert gesetzt.
- **Rückblick:** `sync_window(now, lookahead_days, lookback_days=7)`. Das Fenster beginnt `lookback_days` vor der lokalen Mitternacht von heute (bisher 1 Tag). Neue Setting `OPENCAST_LOOKBACK_DAYS` (`_int_or_default`, 7) in Settings, beiden Compose-Dateien und `.env.prod.example`, durchgereicht bis `run_opencast_sync`.
- [ ] **Step 1: Failing tests:**
  - `test_event_status_parsed`
  - `test_processed_event_without_scheduling_uses_location_and_duration`
  - `test_event_without_scheduling_and_location_skipped`
  - `test_sync_stores_opencast_status`
  - `test_sync_window_lookback`
  - Bestehende Fenster-Tests an den neuen Parameter anpassen; das bisherige Verhalten entspricht `lookback_days=1`.
- [ ] **Step 2–4:** FAIL, dann implementieren, dann PASS. Dazu ruff und `makemigrations --check`.
- [ ] **Step 5:** Commit `feat(opencast): Status der Termine speichern, 7 Tage Rückblick`.

### Task 3: API `last_recording` mit Problemen

**Files:** Modify `backend/recorders/{serializers,views,tests}.py`, `backend/locale/de/…` (nur falls neue gettext-Texte).

**Interfaces:**
- Rekorderfeld `last_recording`: `null` oder `{title, start, end, opencast_status, problems: Problem[]}`.
  - Gemeint ist der Termin dieses Rekorders mit dem spätesten `end <= now` innerhalb des Rückblicks.
  - `Problem` = `{kind, from?: iso, to?: iso, minutes?: int}`.
- **`kind`-Werte:**
  - `stream_missing`: je ein Eintrag pro Vorfall dieses Termins, mit `from`/`to` und `minutes` (gerundet, mindestens 1).
  - `processing_failed`: `opencast_status` endet auf `PROCESSING_FAILURE`.
  - `recording_failed`: `opencast_status` endet auf `RECORDING_FAILURE`.
  - `not_started`: `opencast_status` endet auf `SCHEDULED`, und `now >= end + 30 min`.
  - `not_finished`: `opencast_status` endet auf `RECORDING` oder `INGESTING`, und `now >= end + 30 min`.
  - Kein Problem sind `PROCESSING`, `PROCESSED`, ein leerer Status und alles Übrige.
- Die View lädt die letzten Termine (`end <= now`, `end >= Fensterbeginn`) und deren Vorfälle mit je einer Abfrage zusätzlich; die Zahl der Abfragen bleibt konstant.
- [ ] **Step 1: Failing tests:**
  - `test_last_recording_none`
  - `test_last_recording_picks_latest_ended`
  - `test_last_recording_stream_missing_problems`: zwei Lücken ergeben zwei Einträge mit Minuten.
  - `test_processing_failure_problem`
  - `test_processing_is_not_a_problem`
  - `test_scheduled_after_end_is_not_started`: nach 29 Minuten noch nicht, nach 31 Minuten schon.
  - `test_recording_after_end_is_not_finished`
  - `test_list_query_count_constant_with_last_recording`
- [ ] **Step 2–4:** FAIL, dann implementieren, dann PASS.
- [ ] **Step 5:** Commit `feat(recorders): letzte Aufzeichnung mit Problemen in der API`.

### Task 4: Frontend-Hinweis

**Files:** Modify `frontend/src/api.ts`, `recorders.ts` (+ Tests), `components/{RecorderTile,RoomList,RoomPills}.tsx`, `pages/RoomView.tsx`, Locales. Create `components/LastRecordingWarning.tsx`.

**Interfaces:**
- `api.ts`: `Recorder.last_recording` wie oben typisiert. `same()` in `recorders.ts` vergleicht es per JSON-Vergleich der Probleme.
- Reiner Helfer `problemTexts(lr): {key: string, params}[]` in `recorders.ts` mit Tests. Keys (EN → DE):
  - `"Stream missing {{from}}–{{to}} ({{minutes}} min)"` → „Stream fehlte {{from}}–{{to}} ({{minutes}} min)“
  - `"Processing in Opencast failed"` → „Verarbeitung in Opencast fehlgeschlagen“
  - `"Recording failed on the recorder"` → „Aufzeichnung auf dem Rekorder fehlgeschlagen“
  - `"Recording did not start"` → „Aufzeichnung wurde nicht gestartet“
  - `"Recording did not finish"` → „Aufzeichnung wurde nicht abgeschlossen“
  - Überschrift: `"Last recording had problems"` → „Letzte Aufzeichnung hatte Probleme“
  - Bezug: `"{{title}}, {{day}} {{from}}–{{to}}"`, wobei `day` als kurzer Wochentag plus Datum formatiert wird.
- `LastRecordingWarning({recorder, compact?})`: Nur wenn `problems.length > 0`.
  - Amber-Box (`bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100`) mit `AlertTriangle` und Text. `role="note"`, keine aria-live-Ansage.
  - `compact`: eine Zeile „⚠ Letzte Aufzeichnung hatte Probleme“; die Details stehen im `title` und in der Raumansicht.
- **Einbau:**
  - Kachel: `compact`, unter dem Raumnamen.
  - Raumansicht: volle Box unter den Termin-Infos.
  - Raumliste (Smartphone): kleines ⚠ mit `sr-only`-Text neben dem Raumnamen.
  - Pills: ⚠ mit `sr-only`-Text in der Pill.
- [ ] **Step 1:** `problemTexts`-Tests schreiben (FAIL), dann implementieren (PASS).
- [ ] **Step 2:** Einbauen. `npm test`, `tsc -b` und `check:i18n` müssen grün sein.
- [ ] **Step 3:** Commit `feat(frontend): Hinweis bei Problemen der letzten Aufzeichnung`.

### Task 5: Spec und Doku

- [ ] **Spec:** neuer Abschnitt „§6b Letzte Aufzeichnung“. Er beschreibt die zwei Quellen, die Problemarten mit der 30-Minuten-Regel und den Rückblick von 7 Tagen. Dazu der Hinweis, dass die Vorfälle der Anfang des Protokolls aus §7.5 sind; die Alarme bleiben Stufe 3. In §7.1 kurz darauf verweisen.
- [ ] **KONFIGURATION:** `OPENCAST_LOOKBACK_DAYS` und die Bedeutung des Hinweises.
- [ ] **README:** die Variablentabelle ergänzen.
- [ ] Alle Checks laufen lassen. Commit `docs: Hinweis zur letzten Aufzeichnung`.
