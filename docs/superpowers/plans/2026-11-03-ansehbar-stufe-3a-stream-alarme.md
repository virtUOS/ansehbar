# Stufe 3a: Stream-Alarme, E-Mail und /metrics – Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fehlt während eines Termins der Stream, geht ein Alarm per E-Mail an die
Alarm-Empfänger und ein Alarmzustand an Prometheus (`/metrics`). Kommt der
Stream stabil zurück, folgt eine Entwarnung per E-Mail.

**Architecture:** Die bestehenden `Incident`-Zeilen (Stufe 2) bleiben das
Protokoll. Ein neues Modul entscheidet, wann ein Vorfall alarmwürdig ist
(Alarmmodus pro Raum: `exact`/`grid`/`off`). Eine neue App `alarms` hält
Empfänger und Zustellprotokoll und stellt im Monitor-Zyklus zu. Die Metriken
liest Prometheus pull-basiert. Die Alarmregeln liegen als Datei im Repo und
werden den Betreibern geschickt.

**Tech Stack:** Django 5.1, DRF, Postgres, Django-Mail (SMTP), React/Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`, Abschnitte
7.1, 7.2 und 7.4. Außerdem 5.4 für Empfänger und Kanäle.

**Zuschnitt von Stufe 3** (*meine Entscheidung*):
- **3a (dieser Plan):** Alarme „Stream fehlt“, Kanäle E-Mail und
  Monitoring-Dienst, Empfänger, Raster-Einstellungen.
- **3b:** Pegelmessung im Backend (ffmpeg), Alarm „Ton fehlt“,
  Backend-Pegel in der Oberfläche, „erster Ton“ pro Termin (Stufe 4
  vorbereiten).
- **3c:** Raumkalender und Protokoll (7.5) mit Aufbewahrungsfristen und
  Zeitleiste in der Raumansicht.

Jeder Teil ist für sich nutzbar.

## Global Constraints

- **SPDX-Header:** Apache-2.0-Header in jeder neuen Quelldatei, auch in
  Migrationen: `# SPDX-License-Identifier: Apache-2.0` und
  `# Copyright 2026 Universität Osnabrück (virtUOS)`.
- **Texte im Backend:** englische msgids mit `gettext`, Deutsch in
  `backend/locale/de/LC_MESSAGES/django.po`; `.po` und `.mo` einchecken.
- **Texte im Frontend:** Englisch als i18n-Key, Deutsch in
  `frontend/src/locales/de/translation.json`; `npm run check:i18n` muss grün sein.
- **Nur fiktive Werte:** Keine Infrastrukturdetails der Einrichtung im Repo
  (Hostnamen, Raumnamen, interne URLs, auch nicht die der Monitoring-Konfiguration).
- **Kein Django-Admin, keine Browser-Dialoge:** Keine Pflegemasken im
  Django-Admin; nie `window.confirm`, stattdessen `ConfirmDialog`.
- **Status sichtbar:** Status immer mit Text und Symbol; die Akzentfarbe
  (brand) ist nie eine Statusfarbe.
- **Stream-Namen:** case-sensitiv, nie kleinschreiben.
- **Nur lesen:** ansehBAR schreibt nie nach Opencast und nie nach Keycloak.
- **Alarm nur während Terminen** (7.4): außerhalb ist „kein Stream“ normal.
- **Keine Entwarnung über den Monitoring-Dienst** (7.4): Entwarnungen gibt es
  nur per E-Mail.
- **Labels:** `severity` mit den Werten `warning` und `critical`.
  Metrik-Präfix `ansehbar_`, Raum-Labels `room` und `stream`.
- **Zustellung idempotent:** genau eine Meldung pro Vorfall-Ereignis, Kanal
  und Empfänger, auch über Neustarts des Monitors hinweg (`SentNotification.key`).
- **Schreiben ohne Verlust:** Der Monitor schreibt mit
  `save(update_fields=[…])`, nie die ganze Zeile.
- **Neustart des Monitors:** Nach Code-Änderungen den Monitor neu starten
  (`docker compose restart monitor`).
- **Prüfbefehle:**
  - `docker compose exec backend python manage.py test`
  - `docker compose exec frontend npx tsc -b`
  - `docker compose exec frontend npm test`
  - `docker compose exec frontend npm run check:i18n`
  - `docker compose exec backend sh -c "pip install -q ruff && ruff check ."`

## Entscheidungen, die dieser Plan festlegt

- **Puffer = vorhandene Wartezeit:** Der „technische Puffer“ aus 7.2
  (Standard 3 min) ist die vorhandene Einstellung `missing_grace_minutes`.
  Es gibt kein zweites Feld.
- **Raster = vorhandene Slots:** Das Raster aus 7.2 sind die vorhandenen
  Slots (`slot_minutes`, `slot_offset_minutes`). Neu kommen c.t.-Versatz
  (Standard 15 min) und Toleranz nach c.t. (Standard 5 min) dazu.
- **Stabile Rückkehr = feste 60 s:** Die Konstante `STABLE_SECONDS = 60` wird
  keine Einstellung (YAGNI). Fällt der Stream innerhalb dieser Zeit wieder aus,
  wird der vorherige Vorfall wieder geöffnet; es entsteht kein neuer.
- **Ende-Toleranz:** Endet der Stream innerhalb der Toleranz vor dem
  geplanten Ende (Standard 5 min), ist das kein Vorfall. Das gilt in
  `missing_since`, also auch für die Anzeige „Stream fehlt“ in der Oberfläche.
- **`alerted_at` = Alarmzustand:** Das Feld sagt „alarmwürdig geworden“,
  unabhängig vom Kanal. E-Mail und `/metrics` lesen beide daraus.
- **Entwarnung nur nach Rückkehr:** Entwarnung nur für Vorfälle, die
  geendet haben, weil der Stream zurückkam (`recovered=True`). Endet der
  Termin bei fehlendem Stream, gibt es keine Entwarnung.
- **Kein Alarm-Schwall:** Es werden nur Vorfälle alarmiert, deren Termin noch
  läuft. Alte offene Vorfälle (etwa nach einem Deploy) lösen nichts aus.
- **Sprache der E-Mails:** Die Setting `ALARM_LANGUAGE` (Env, Standard
  `de`) gilt für alle Empfänger gleich.
- **Wiederholversuche:** E-Mail höchstens 5 Versuche pro Meldung, danach
  bleibt sie mit `last_error` liegen. Ein SMTP-Fehler hält den Zyklus nie an.

## Review Focus

1. **Neustart mitten im Vorfall:** Der Monitor startet während eines offenen,
   schon alarmierten Vorfalls neu. Erwartung: keine zweite Alarm-E-Mail.
   Test: `test_restart_does_not_resend` (Task 5).
2. **SMTP nicht erreichbar:** Erwartung: Der Zyklus läuft weiter, der Versuch
   wird gezählt, der nächste Zyklus versucht es erneut, nach 5 Versuchen ist
   Schluss. Test: `test_smtp_failure_is_retried_and_capped` (Task 5).
3. **Termin endet bei fehlendem Stream:** Erwartung: keine Entwarnung.
   Test: `test_no_all_clear_when_event_ends_missing` (Task 5).
4. **Kurzes Flackern:** Der Stream kommt für 30 s zurück und fällt wieder aus.
   Erwartung: ein Vorfall, ein Alarm, keine Entwarnung.
   Test: `test_flicker_reopens_incident` (Task 2) und
   `test_flicker_sends_single_alarm` (Task 5).
5. **Alarmmodus „off“ oder Rekorder deaktiviert vor Fälligkeit:**
   Erwartung: kein Alarm, der Vorfall bleibt protokolliert.
   Test: `test_mode_off_never_alarms` (Task 3) und
   `test_deactivated_recorder_not_alarmed` (Task 5).

---

### Task 1: Einstellungen und Alarmmodus im Backend

**Files:**
- Modify: `backend/recorders/models.py` (`Recorder`, `MonitorSettings`)
- Modify: `backend/recorders/serializers.py` (`RecorderSerializer.Meta.fields`, `MonitorSettingsSerializer`)
- Create: `backend/recorders/migrations/0006_alarm_settings.py`
- Test: `backend/recorders/tests.py`

**Interfaces:**
- **Produces:**
  - `Recorder.alarm_mode` (`"exact" | "grid" | "off"`, Standard `"exact"`).
  - Konstanten `Recorder.ALARM_EXACT`, `ALARM_GRID`, `ALARM_OFF`.
  - Neue Felder in `MonitorSettings`, alle Integer in Minuten bzw. Bool:
    - `ct_minutes` (15, 0–60);
    - `ct_tolerance_minutes` (5, 0–30);
    - `end_tolerance_minutes` (5, 0–30);
    - `alarm_email_enabled` (True);
    - `alarm_metrics_enabled` (True).
  - Alle neuen Felder stehen in `GET`/`PUT /api/settings/monitor/` und in
    `GET`/`PATCH /api/recorders/`.

- [ ] **Step 1: Write the failing tests** in `MonitorSettingsApiTests` and `RecorderApiTests`

```python
def test_alarm_settings_defaults_and_bounds(self):
    body = self.client.get("/api/settings/monitor/").json()
    self.assertEqual(
        [body[k] for k in ["ct_minutes", "ct_tolerance_minutes", "end_tolerance_minutes",
                           "alarm_email_enabled", "alarm_metrics_enabled"]],
        [15, 5, 5, True, True],
    )
    base = {"url_template": body["url_template"], "stale_factor": 3}
    for field, value, code in [("ct_minutes", 61, 400), ("ct_minutes", 0, 200),
                               ("ct_tolerance_minutes", 31, 400),
                               ("end_tolerance_minutes", 30, 200)]:
        with self.subTest(field=field, value=value):
            self.assertEqual(self.put({**base, field: value}).status_code, code)

def test_recorder_alarm_mode(self):
    rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
    url = f"/api/recorders/{rec.pk}/"
    self.assertEqual(self.client.get(url).json()["alarm_mode"], "exact")
    ok = self.client.patch(url, {"alarm_mode": "grid"}, content_type="application/json")
    self.assertEqual(ok.status_code, 200)
    bad = self.client.patch(url, {"alarm_mode": "loud"}, content_type="application/json")
    self.assertEqual(bad.status_code, 400)
```

- [ ] **Step 2: Run, expect FAIL** (`KeyError`/400 vs 200)

Run: `docker compose exec backend python manage.py test recorders`

- [ ] **Step 3: Add the fields, choices, serializer fields and the migration** (`makemigrations recorders -n alarm_settings`, then add the SPDX header)

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit** `feat: alarm mode per recorder and alarm settings`

---

### Task 2: Vorfall-Regel – Ende-Toleranz, Rückkehr, Flackern

**Files:**
- Modify: `backend/recorders/missing.py` (`missing_since`)
- Modify: `backend/recorders/incidents.py` (`update_incidents`)
- Modify: `backend/recorders/models.py` (`Incident`), `backend/recorders/serializers.py` (call site of `missing_since`)
- Create: `backend/recorders/migrations/0007_incident_alarm_fields.py`
- Test: `backend/recorders/tests.py` (`UpdateIncidentsTests`, a new `MissingSinceTests`)

**Interfaces:**
- **Consumes:** `MonitorSettings.end_tolerance_minutes` (Task 1).
- **Produces:**
  - `missing_since(active, state, offline_since, current_event, now, grace, end_tolerance=timedelta(0)) -> datetime | None`.
    Neu: Gibt `None` zurück, wenn `offline_since` gesetzt ist und
    `offline_since >= current_event.end - end_tolerance`.
  - Neue Felder an `Incident`, alle null/False als Standard:
    - `recovered: bool` (geschlossen, weil der Stream zurückkam);
    - `alerted_at: datetime | None`;
    - `all_clear_at: datetime | None`.
  - `recorders.incidents.STABLE_SECONDS = 60`.
  - Beide Aufrufer von `missing_since` (Serializer und `update_incidents`)
    übergeben `end_tolerance` aus den Einstellungen.

- [ ] **Step 1: Write the failing tests**

```python
# MissingSinceTests (event 10:00–12:00, grace 3 min, end tolerance 5 min)
def test_stream_ending_within_end_tolerance_is_not_missing(self):
    self.assertIsNone(missing_since(True, "offline", berlin(11, 56), self.ev,
                                    berlin(11, 58), GRACE, END_TOL))
def test_stream_ending_before_end_tolerance_is_missing(self):
    self.assertEqual(missing_since(True, "offline", berlin(11, 50), self.ev,
                                   berlin(11, 58), GRACE, END_TOL), berlin(11, 50))

# UpdateIncidentsTests
def test_live_closes_incident_as_recovered(self):
    # open incident, status live → ended_at == now, recovered is True
def test_event_end_closes_incident_not_recovered(self):
    # still offline at event end → ended_at == event.end, recovered is False
def test_flicker_reopens_incident(self):
    # incident recovered at 10:20:00; offline again at 10:20:30 (< 60 s):
    # update_incidents(10:20:40) → the same incident open again
    # (ended_at None, recovered False); Incident count stays 1
def test_drop_after_stable_return_opens_new_incident(self):
    # recovered at 10:20:00, offline again from 10:21:30 → second incident
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement.**
  - **`missing_since`:** Neue Bedingung wie im Interfaces-Block.
  - **Schließen in `update_incidents`:** Wird ein Vorfall geschlossen, weil der
    Status `LIVE` ist, setzt `update_incidents` `recovered=True` (mit
    `update_fields=["ended_at", "recovered"]`).
  - **Wieder öffnen:** Bevor ein neuer Vorfall für (Rekorder, Termin)
    entsteht, sucht `update_incidents` den jüngsten Vorfall desselben Paars
    mit `recovered=True` und `ended_at >= now - STABLE_SECONDS`. Gibt es ihn,
    wird er wieder geöffnet (`ended_at=None`, `recovered=False`), statt eine
    neue Zeile anzulegen. Dafür genügt eine zusätzliche Abfrage pro Lauf, über
    alle Rekorder.
  - **Migration:** `makemigrations recorders -n incident_alarm_fields`, dann
    den SPDX-Header ergänzen.

- [ ] **Step 4: Run all backend tests, expect PASS.** The existing `missing_since` and last-recording tests must stay green.

- [ ] **Step 5: Commit** `feat: end tolerance and stable return for stream incidents`

---

### Task 3: Wann ist ein Vorfall alarmwürdig?

**Files:**
- Create: `backend/recorders/alarm_rules.py`
- Test: `backend/recorders/tests.py` (`AlarmDueTests`)

**Interfaces:**
- **Consumes:** `Recorder.alarm_mode`, die Felder aus `MonitorSettings` und
  `Incident` (Tasks 1–2).
- **Produces:**
  - `slot_start(at: datetime, minutes: int, offset_minutes: int) -> datetime`
    (aware, lokale Zeit). Gleiche Regel wie `slotOf` im Frontend
    (`frontend/src/recorders.ts`): Slots beginnen `offset_minutes` nach
    Mitternacht und sind `minutes` lang. Vor dem Offset liegt man im letzten
    Slot des Vortags.
  - `alarm_threshold(event, mode: str, settings: MonitorSettings) -> datetime | None`:
    - `exact`: `event.start + grace`;
    - `grid`: `max(event.start + grace, slot_start(event.start) + ct + ct_tolerance)`;
    - `off`: `None`.
  - `alarm_due(incident, settings, now) -> bool`: Wahr, wenn alle Bedingungen gelten:
    - Der Vorfall ist offen.
    - Sein Termin existiert und läuft (`start <= now < end`).
    - Der Rekorder ist aktiv.
    - Der Modus ist nicht `off`.
    - Es gilt `now >= max(threshold, incident.started_at)`.

- [ ] **Step 1: Write the failing tests** (event 10:00–12:00, grace 3, ct 15, tolerance 5, slots 120/0)

```python
def test_exact_threshold_is_start_plus_grace(self):
    self.assertEqual(alarm_threshold(self.ev, "exact", self.s), berlin(10, 3))
def test_grid_threshold_is_ct_plus_tolerance(self):
    self.assertEqual(alarm_threshold(self.ev, "grid", self.s), berlin(10, 20))
def test_grid_does_not_shift_late_start_further(self):
    ev = self.event(berlin(10, 30), berlin(12))
    self.assertEqual(alarm_threshold(ev, "grid", self.s), berlin(10, 33))
def test_grid_uses_slot_offset(self):
    # slots 90/15, event 9:15 → slot 9:15, threshold 9:35
def test_slot_start_before_offset_is_previous_day(self):
    # 90/15, 00:05 → 22:45 previous day (same as the frontend test)
def test_mode_off_never_alarms(self):
    # alarm_due False for any now while incident open
def test_due_only_while_event_runs(self):
    # True at 10:04 (exact), False at 12:00 and with ended_at set
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError`)

- [ ] **Step 3: Implement the three functions in `recorders/alarm_rules.py`.** Compute `slot_start` with `timezone.localtime`. Build the result from local midnight plus a `timedelta`, then `make_aware`, so DST days come out right.

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit** `feat: alarm thresholds for exact and grid mode`

---

### Task 4: App `alarms` – Empfänger, Zustellprotokoll, API

**Files:**
- Create: `backend/alarms/__init__.py`, `apps.py`, `models.py`, `serializers.py`, `views.py`, `tests.py`, `migrations/0001_initial.py`
- Modify: `backend/config/settings.py` (`INSTALLED_APPS`, E-Mail-Settings), `backend/config/api_urls.py`
- Modify: `docker-compose.yml`, `docker-compose.prod.yml`, `.env.prod.example`

**Interfaces:**
- **Produces:**
  - `AlarmRecipient` mit den Feldern:
    - `email` (EmailField, unique);
    - `user` (FK, null, SET_NULL);
    - `active` (Standard True);
    - `created_at`;
    - `created_by` (CharField 150).
  - `SentNotification` mit den Feldern:
    - `key` (CharField 200, unique);
    - `channel` (`"email"`);
    - `kind` (`"alarm" | "all_clear" | "test"`);
    - `incident` (FK `recorders.Incident`, null, SET_NULL);
    - `recipient` (EmailField);
    - `subject`, `body`;
    - `created_at`, `sent_at` (null);
    - `attempts` (Standard 0);
    - `last_error`.
  - API (`HasAccess`):
    - `GET`/`POST /api/alarm-recipients/`. `POST` nimmt
      `{"email": "…"}` oder `{"user": <id>}`; mit `user` wird die
      E-Mail-Adresse des Benutzers übernommen. 400, wenn der Benutzer keine
      E-Mail-Adresse hat oder die Adresse schon eingetragen ist.
    - `PATCH /api/alarm-recipients/<id>/` mit `{"active": bool}`.
    - `DELETE /api/alarm-recipients/<id>/`.
    - `POST /api/alarm-recipients/test/` erzeugt pro aktivem Empfänger eine
      `SentNotification` mit `kind="test"` und antwortet `202` mit
      `{"queued": n}`. Der nächste Zyklus des Monitors stellt sie zu.
  - Settings aus Env, mit Standardwerten wie in kalkulierBAR:
    - `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
      `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`;
    - `EMAIL_TIMEOUT` (10);
    - `DEFAULT_FROM_EMAIL` (`ansehbar@localhost`);
    - `ALARM_LANGUAGE` (`de`).
  - In der Entwicklungsumgebung (`docker-compose.yml`) steht
    `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`.

- [ ] **Step 1: Write the failing API tests** in `alarms/tests.py`:
  - `test_add_by_email`
  - `test_add_by_user_takes_their_email`
  - `test_user_without_email_is_400`
  - `test_duplicate_is_400`
  - `test_toggle_and_delete`
  - `test_requires_access` (a user without access gets 403)
  - `test_test_endpoint_queues_one_per_active_recipient` (2 active, 1 inactive → `queued == 2`)

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement the app.** Register the viewset as `alarm-recipients` and the `test` route as an `@action(detail=False, methods=["post"])`.
  - **Key of a test notification:** `test:<uuid4>:email:<address>`.
  - **New env variables:** Each one goes into both compose files and `.env.prod.example`, every value commented in `.env.prod.example` with fictitious values.

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit** `feat: alarm recipients and notification log`

---

### Task 5: Zustellung im Monitor-Zyklus

**Files:**
- Create: `backend/alarms/delivery.py`, `backend/alarms/templates/alarms/` (Text-Templates)
- Modify: `backend/recorders/management/commands/run_monitor.py` (`_cycle`: nach `update_incidents`)
- Modify: `backend/locale/de/LC_MESSAGES/django.po` (+ `.mo`)
- Test: `backend/alarms/tests.py` (`DeliveryTests`)

**Interfaces:**
- **Consumes:**
  - `alarm_due` (Task 3);
  - `Incident.alerted_at`, `all_clear_at`, `recovered`;
  - `STABLE_SECONDS` (Task 2);
  - `AlarmRecipient`, `SentNotification` (Task 4);
  - `settings.FRONTEND_BASE_URL` für den Link.
- **Produces:** `deliver_alarms(now: datetime) -> None`. Die Funktion wirft
  nie; Fehler gehen ins Log. Sie arbeitet in drei Phasen.
  1. **Alarm fällig:** Offene Vorfälle mit `alerted_at` null werden geprüft.
     Wenn `alarm_due` gilt, setzt die Funktion `alerted_at=now` und legt pro
     aktivem Empfänger eine Alarm-Meldung an, sofern `alarm_email_enabled` gilt.
     Schlüssel: `incident:<id>:alarm:email:<address>`.
  2. **Entwarnung fällig:** Betroffen sind Vorfälle mit `alerted_at` gesetzt,
     `all_clear_at` null, `recovered=True` und
     `ended_at <= now - STABLE_SECONDS`. Die Funktion setzt `all_clear_at=now`
     und legt Entwarnungen mit dem Schlüssel
     `incident:<id>:all_clear:email:<address>` an.
  3. **Senden:** Alle `SentNotification` mit `sent_at` null und `attempts < 5`
     werden einzeln mit `send_mail` verschickt. Bei Erfolg setzt die Funktion
     `sent_at`. Bei einem Fehler zählt sie `attempts` hoch und setzt
     `last_error`, ohne zu werfen.
- **Inhalt einer Meldung (7.4):**
  - Raum (`displayName`-Regel: Raumname, sonst Agent, sonst Stream-Name);
  - Stream-Name;
  - Art („Stream fehlt“ bzw. „Stream wieder da“);
  - Termin: Titel, Serie, geplante Zeit;
  - fehlt seit (`started_at`), bei der Entwarnung zusätzlich „wieder da seit“;
  - Link `FRONTEND_BASE_URL/raum/<id>`.

  Betreff:
  - Alarm: `[ansehBAR] Stream missing: <room>`;
  - Entwarnung: `[ansehBAR] Stream back: <room>`;
  - Test: `[ansehBAR] Test alarm`.

  Gerendert wird in `translation.override(settings.ALARM_LANGUAGE)`. Uhrzeiten
  stehen in lokaler Zeit.

- [ ] **Step 1: Write the failing tests** (locmem backend: `mail.outbox`)

```python
def test_alarm_sent_once_to_each_active_recipient(self): ...
def test_restart_does_not_resend(self):
    # deliver_alarms twice (simulates a restart: no in-memory state) → outbox 1 per recipient
def test_grid_mode_waits_for_ct(self): ...
def test_email_channel_off_sets_alerted_but_sends_nothing(self): ...
def test_all_clear_after_stable_return(self):
    # recovered at 10:20 → nothing at 10:20:30, all-clear at 10:21:01
def test_no_all_clear_when_event_ends_missing(self): ...
def test_flicker_sends_single_alarm(self):
    # alarm, return 30 s, drop again (update_incidents reopens) → still 1 alarm, 0 all-clear
def test_deactivated_recorder_not_alarmed(self): ...
def test_past_event_incident_not_alarmed(self):
    # open incident whose event ended (deploy after downtime) → no mail
def test_smtp_failure_is_retried_and_capped(self):
    # patch send_mail to raise SMTPException: attempts 1..5 over 6 calls, then untouched, no raise
def test_message_content(self):
    # subject "[ansehBAR] Stream fehlt: Hörsaal A" (ALARM_LANGUAGE="de"),
    # body contains title, series, "10:00–12:00", "/raum/<id>"
def test_test_notification_is_sent(self): ...
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `deliver_alarms`.**
  - **Einbindung:** `run_monitor._cycle` ruft die Funktion nach
    `update_incidents` auf, mit eigenem `try/except` und
    `logger.exception` wie beim Aufruf von `update_incidents`.
  - **Anlegen und Markieren:** Das Anlegen der Meldungen erfolgt per
    `get_or_create(key=…)`. Das Setzen von `alerted_at` und `all_clear_at`
    erfolgt per `filter(pk=…, alerted_at__isnull=True).update(...)`. So legt
    ein paralleler Lauf nichts doppelt an.
  - **Übersetzung:** Die Betreff- und Textbausteine kommen in die `.po`
    (`makemessages -l de`, `compilemessages`).

- [ ] **Step 4: Run all backend tests, expect PASS;** dann `docker compose restart monitor` und im Log (`docker compose logs monitor`) prüfen, dass der Zyklus fehlerfrei läuft

- [ ] **Step 5: Commit** `feat: deliver stream alarms and all-clears by e-mail`

---

### Task 6: `/metrics`, Alarmregeln, Betriebsdoku

**Files:**
- Create: `backend/common/metrics.py` (`render_prometheus`), `backend/common/views.py` (`MetricsView`)
- Modify: `backend/config/urls.py` (`path("metrics", MetricsView.as_view())`), `backend/config/settings.py` (`METRICS_TOKEN`)
- Modify: `Caddyfile` (`handle /metrics { reverse_proxy app:8000 }`), Compose-Dateien und `.env.prod.example` (`METRICS_TOKEN`)
- Create: `monitoring/alerts.yml`, `monitoring/scrape.example.yml`, `docs/monitoring.md`
- Test: `backend/common/tests.py`

**Interfaces:**
- **Consumes:**
  - `Incident.alerted_at` (Task 2);
  - `MonitorSettings.alarm_metrics_enabled` (Task 1);
  - `RecorderStatus.checked_at`;
  - `OpencastSyncState`;
  - `opencast_sync_enabled()`.
- **Produces:** `GET /metrics`, exakt wie `MetricsView` in abstimmBAR:
  - ohne `METRICS_TOKEN` 404;
  - falscher Header 401 (`hmac.compare_digest`);
  - `text/plain; version=0.0.4; charset=utf-8`;
  - keine DRF-Authentifizierung.

  Gauges:
  - `ansehbar_stream_missing_alarm{room,stream}`: 1 für jeden Rekorder mit
    offenem Vorfall, bei dem `alerted_at` gesetzt ist, sonst 0. Das gilt für
    alle aktiven Rekorder mit Modus ungleich `off`. Mit
    `alarm_metrics_enabled=False` wird die Metrik gar nicht ausgegeben.
  - `ansehbar_monitor_last_check_timestamp_seconds`: Unix-Zeit des letzten
    Checks aktiver Rekorder; entfällt, wenn es keinen gibt.
  - `ansehbar_opencast_last_success_timestamp_seconds`: nur, wenn Opencast
    aktiviert ist und es einen Erfolg gab.
  - `ansehbar_opencast_enabled`: 0 oder 1.
  - `ansehbar_recorders{state}`: Anzahl aktiver Rekorder pro Status
    (`live`, `offline`, `unknown`).

  Label-Werte werden escaped wie in abstimmBAR (`\\`, `"`, `\n`).
- **`monitoring/alerts.yml`** (Prometheus-Regelgruppe `ansehbar`) mit drei
  Regeln:
  - `AnsehbarStreamMissing`: `ansehbar_stream_missing_alarm == 1`,
    `for: 2m`, `severity: critical`. Die Annotation `summary` nennt
    `{{ $labels.room }}`.
  - `AnsehbarMonitorStale`:
    `time() - ansehbar_monitor_last_check_timestamp_seconds > 300`,
    `for: 5m`, `severity: warning`.
  - `AnsehbarOpencastSyncStale`:
    `ansehbar_opencast_enabled == 1 and time() - ansehbar_opencast_last_success_timestamp_seconds > 900`,
    `for: 10m`, `severity: warning`.

  Alle Regeln tragen zusätzlich das Label `service: ansehbar` für das
  Routing in den eigenen Matrix-Raum.
- **`monitoring/scrape.example.yml`** wie abstimmBARs Beispiel:
  - `job_name: ansehbar`;
  - `scrape_interval: 1m`;
  - Bearer per `credentials_file`;
  - Ziel `ansehbar.example.org`.
- **`docs/monitoring.md`:** Aufbau wie abstimmBARs `docs/monitoring.md`
  (Token erzeugen, Caddy-Block, `curl`-Prüfung, Kennzahlen-Tabelle,
  Alarmregeln). Dazu der Hinweis: Die Betreiber spielen `alerts.yml` und den
  Scrape-Eintrag ein; Entwarnungen gibt es dort nicht.

- [ ] **Step 1: Write the failing tests** in `common/tests.py`:
  - `test_metrics_404_without_token`
  - `test_metrics_401_with_wrong_token`
  - `test_metrics_content_type`
  - `test_stream_missing_alarm_gauge`: Raum mit alarmiertem offenem Vorfall
    → `1`, anderer aktiver Raum → `0`, Raum im Modus off → fehlt.
  - `test_metrics_channel_off_hides_alarm_gauge`
  - `test_label_values_are_escaped`: Raumname mit `"`.
  - `test_recorder_state_counts`
  - `test_alerts_file_is_valid_yaml_with_severity`: lädt
    `monitoring/alerts.yml` mit `yaml.safe_load`. Jede Regel hat
    `labels.severity` in `{"warning", "critical"}` und
    `labels.service == "ansehbar"`. Wenn `pyyaml` nicht installiert ist,
    gehört es in die Backend-Requirements.

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement endpoint, renderer, files and docs.** Read abstimmBAR's `backend/common/views.py` (`render_prometheus`, `MetricsView`) and `docs/monitoring.md` and mirror them.

- [ ] **Step 4: Run tests, expect PASS.**
  - Set `METRICS_TOKEN=dev-token` in the local `.env`, recreate the backend
    container, then
    `curl -s -H "Authorization: Bearer dev-token" http://localhost:8007/metrics`.
    Expected: lines `# TYPE ansehbar_stream_missing_alarm gauge` and so on.
  - Remove the token from `.env` again.

- [ ] **Step 5: Commit** `feat: Prometheus metrics and alert rules`

---

### Task 7: Oberfläche – Alarm-Empfänger, Einstellungen, Alarmmodus

**Files:**
- Create: `frontend/src/pages/admin/AlarmsAdmin.tsx`
- Modify:
  - `frontend/src/api.ts` (Typen und `api.alarmRecipients`)
  - `frontend/src/pages/admin/AdminLayout.tsx` (Tab „Alarme“ → `/verwaltung/alarme`)
  - `frontend/src/App.tsx` (Route)
  - `frontend/src/pages/admin/SettingsAdmin.tsx` (Abschnitt „Alarme“)
  - `frontend/src/pages/admin/RecordersAdmin.tsx` (Formular und Liste)
  - `frontend/src/locales/de/translation.json`
- Test: `frontend/src/admin.test.ts` (reine Helfer)

**Interfaces:**
- **Consumes:** die API aus Task 1 und Task 4.
- **Produces:**
  - **Seite „Alarme“:**
    - Hinzufügen per E-Mail-Feld oder per Benutzersuche. Die Suche nutzt
      `/api/users/?search=` wie `InvitationsAdmin`.
    - Tabelle der Empfänger mit Schalter aktiv/inaktiv (Text und Symbol) und
      Löschen über `ConfirmDialog`.
    - Knopf „Test-E-Mail senden“ mit Statusmeldung
      „{{n}} Test-E-Mails in der Warteschlange“.
  - **Einstellungen, Abschnitt „Alarme“:**
    - Checkboxen „Alarme per E-Mail“ und „Alarme an den Monitoring-Dienst“;
    - Zahlenfelder c.t.-Versatz, Toleranz nach c.t. und Ende-Toleranz, mit
      Hinweistexten zum Raster-Modus.
  - **Rekorder-Formular:** Auswahl „Alarm“ mit den Optionen „Pünktlich
    (Opencast-Start)“, „Raster (c.t.)“ und „Aus (nur protokollieren)“.
  - **Rekorder-Liste:** Ein Raum mit Modus `off` zeigt ein BellOff-Symbol mit
    dem Text „Alarm aus“.
  - `recipientPayload(input: string, userId: number | null): { email: string } | { user: number }`
    in `frontend/src/admin.ts`.

- [ ] **Step 1: Write the failing test** for `recipientPayload`
  - trimmed e-mail → `{email}`;
  - a user ID wins over text → `{user}`.

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement the page, form fields and translations.** Mirror the layout and patterns of `InvitationsAdmin.tsx` and `SettingsAdmin.tsx` (`Field`, `FormErrorSummary`, `splitErrors`, `ConfirmDialog`).

- [ ] **Step 4: Run all checks** (tsc, vitest, check:i18n).
  - In the browser: add a recipient, send a test e-mail, and check that it
    appears in `docker compose logs monitor` (console backend).
  - Set and save alarm mode „Raster“ on a recorder.

- [ ] **Step 5: Commit** `feat(frontend): alarm recipients, alarm settings and mode`

---

### Task 8: Doku und Abschluss

**Files:**
- Modify:
  - `docs/KONFIGURATION.md`: E-Mail-Variablen, `METRICS_TOKEN`, Abschnitt
    Alarme mit Modi, Raster und Toleranzen; Fehlertabelle „E-Mails kommen
    nicht an“ (`SentNotification.last_error`, Log).
  - `README.md`
  - `CLAUDE.md`: App `alarms` unter „Aufbau“.
  - Spec §9: Hinweis auf die Teilung 3a/3b/3c.

- [ ] **Step 1: Update the docs.**
- [ ] **Step 2: Run the full check list from the Global Constraints, expect all green.**
- [ ] **Step 3: Commit** `docs: alarms, e-mail and monitoring`
