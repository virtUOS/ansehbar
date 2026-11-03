# Stufe 3b: Backend-Pegel und Alarm „Ton fehlt“ – Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Monitor misst während laufender Termine den Tonpegel jedes live
streamenden Raums. Längere Stille wird als Vorfall `audio_silent`
protokolliert. Der erste lange Ton-Ausfall eines Termins löst einen Alarm per
E-Mail und über `/metrics` aus. Die Oberfläche zeigt den Backend-Pegel, solange
der Browser selbst keinen messen kann, und markiert stille Räume.

**Architecture:** Ein reines Python-Modul (`streams/audio.py`) startet ffmpeg
für einen Stream und liest den mittleren Pegel aus `volumedetect`. Ein
Django-Modul (`recorders/audio_monitor.py`) wählt die Räume aus, misst sie
begrenzt parallel und führt Stille-Zustand und Vorfälle. Es läuft in
`run_monitor` in einem eigenen Thread, wie der Opencast-Abgleich. So bremst
eine langsame Messung nie die Stream-Prüfung. Alarm, Entwarnung und
`/metrics` nutzen die Wege aus Stufe 3a. Dazu kommt eine zweite Alarmregel
pro Vorfallart.

**Tech Stack:** Django 5.1, DRF, Postgres, ffmpeg (Debian-Paket im Image),
React/Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`. Maßgeblich
sind 7.1, 7.3 und 7.4. Dazu kommen 5.1 (Badge „◐ STILL seit …“, Sortierung),
5.3 (Backend-Pegel als Rückfall) und 8 („erster Ton“ pro Termin).

## Global Constraints

Es gelten alle Global Constraints aus
`docs/superpowers/plans/2026-11-03-ansehbar-stufe-3a-stream-alarme.md`, unverändert.
Die wichtigsten sind:
- SPDX-Header in jeder neuen Datei, auch in Migrationen.
- Texte:
  - Backend: gettext, die `.po`- und `.mo`-Dateien einchecken.
  - Frontend: i18n-Key auf Englisch, Deutsch in `translation.json`.
- Nur fiktive Werte im Repo. Ein Status hat immer Text und Symbol.
- Der Monitor schreibt nur mit `save(update_fields=[…])`.
- Prüfbefehle wie in `CLAUDE.md`.

Für 3b kommt hinzu:
- **Getrennte Status-Felder:** Der Audio-Thread schreibt nur die Felder
  `audio_*` und `silent_since`. Der Stream-Zyklus schreibt nur `CYCLE_FIELDS`
  und der Opencast-Abgleich nur `agent_*`. Keiner überschreibt die Felder der
  anderen.
- **ffmpeg ohne Shell:** Den Befehl immer als Argumentliste übergeben, nie mit
  `shell=True`. Nur die Protokolle `http,https,tls,tcp,crypto,hls` sind
  erlaubt, also kein `file:`.
- **Gemessen wird nur bei Live-Stream und laufendem Termin** (7.3). Sonst
  gibt es keine Messung und keinen Stille-Zustand.
- **Ein Messfehler ist keine Stille:** Bei Timeout, Netzfehler oder fehlendem
  ffmpeg bleibt der Stille-Zustand unverändert. Ein Fehler verlängert keine
  Stille.

## Entscheidungen, die dieser Plan festlegt

- **Pegelmaß:** `mean_volume` aus ffmpeg-`volumedetect`. Das ist der
  RMS-Wert in dBFS über ein Fenster von 10 s.
  - Startwert der Schwelle: −50 dBFS. Das passt zur Browser-Anzeige, wo
    „silent“ unter −50 liegt.
  - Die Schwelle ist einstellbar und wird an echten Streams kalibriert.
  - Zum Kalibrieren gibt es den Befehl `manage.py measure_audio <stream>`.
- **Kein Tonkanal:** Ein Stream ohne Audiospur zählt als still (`level_db=None`).
- **Stille-Dauer:** Gezählt wird vom ersten stillen Messwert (`silent_since`)
  bis zum letzten stillen Messwert. Gemessen wird bis zum letzten Messwert,
  nicht bis „jetzt“. Ohne frische Messung wächst die Stille also nicht.
- **Einstellungen** (in `MonitorSettings`, über die Oberfläche):

  | Feld | Standard | Bereich |
  |---|---|---|
  | `silence_threshold_db` | −50 | −90 bis −20 |
  | `silence_log_minutes` | 2 | 1 bis 30 |
  | `silence_alarm_minutes` | 15 | 5 bis 120 |

  `silence_alarm_minutes` muss mindestens so groß sein wie `silence_log_minutes`.
- **Betriebswerte** (Env, nur im Compose):

  | Variable | Standard | Bedeutung |
  |---|---|---|
  | `AUDIO_MONITOR_ENABLED` | `1` | Pegelmessung an |
  | `AUDIO_MAX_PARALLEL` | `4` | gleichzeitige Messungen |
  | `AUDIO_SAMPLE_SECONDS` | `10` | Länge eines Messfensters |
  | `AUDIO_INTERVAL_SECONDS` | `30` | Mindestabstand zwischen den Starts zweier Durchläufe |

  Sind mehr Räume dran als parallel gemessen werden können, misst der Pool
  sie nacheinander. Das ist die Rotation aus 7.3.
- **Vorfall `audio_silent`:**
  - **Öffnen:** sobald die Stille im laufenden Termin mindestens
    `silence_log_minutes` dauert, mit `started_at = max(silent_since, event.start)`.
  - **Schließen:**
    - wenn Ton gemessen wird (`recovered=True`, Ende = Zeitpunkt dieser Messung);
    - zum Termin-Ende (`ended_at = event.end`);
    - wenn der Stream nicht mehr live oder der Rekorder inaktiv ist
      (`ended_at = now`, nicht recovered).
  - Das neue Feld `silent_until` hält den letzten stillen Messwert fest.
- **Nur der erste Ton-Alarm pro Termin** (7.3): Ein `audio_silent`-Vorfall wird
  alarmwürdig, wenn `silent_until − started_at ≥ silence_alarm_minutes` gilt.
  Er alarmiert nur, wenn im selben Termin noch kein `audio_silent`-Vorfall
  alarmiert hat.
- **Alarmmodus:** `off` unterdrückt auch den Ton-Alarm, denn `off` heißt
  „nur Protokoll“. `exact` und `grid` spielen für den Ton keine Rolle.
- **Entwarnung per E-Mail auch für Ton:** Kommt der Ton nach einem Alarm
  zurück, geht eine Entwarnung („Ton wieder da“) raus.
  - Das ist *meine Wahl*: Ohne Entwarnung geht jemand umsonst in den Raum.
  - Es gilt dieselbe Stabilität wie in 3a: Die Entwarnung kommt frühestens
    60 s nach dem Schließen des Vorfalls.
  - Über `/metrics` gibt es keine Entwarnung, wie in 3a.
- **Kein Wiederöffnen bei Ton-Vorfällen:** Fällt der Ton nach dem Ende einer
  Stille wieder aus, entsteht ab `silence_log_minutes` ein neuer Vorfall.
  Ein Alarm folgt dann nicht mehr.
- **Erster Ton:** `ScheduledEvent.first_audio_at` ist der Zeitpunkt der
  ersten Messung über der Schwelle innerhalb des Termins (8). Der
  Opencast-Abgleich fasst das Feld nie an.
- **Keine Pegel-Historie in 3b:** Gespeichert werden nur der aktuelle Pegel am
  Status, die Vorfälle und `first_audio_at`. Verdichtete Minutenwerte und
  Aufbewahrungsfristen gehören zu 3c.
- **Frischer Pegel:** Die API liefert `audio_level_db` nur, wenn die letzte
  erfolgreiche Messung höchstens 120 s alt ist. Sonst kommt `null`.
- **Zeitleiste der Raumansicht** (5.2) mit den protokollierten Stillen kommt
  in 3c. In 3b zeigen Kachel und Raumansicht den Badge „◐ Still seit HH:MM“.

## Review Focus

1. **Stream ohne Audiospur:** Er zählt als still. ffmpeg meldet „matches no
   streams“, daraus wird `AudioMeasurement(ok=True, level_db=None)`. Den Test
   dafür hat Task 1.
2. **Messung scheitert über längere Zeit:** Es darf keine Stille wachsen und
   kein Alarm aus alten Daten entstehen. Den Test dafür hat Task 3.
3. **`update_incidents` aus 3a und Ton-Vorfälle:** Die Funktion darf keine
   `audio_silent`-Vorfälle schließen, auch nicht wenn der Stream live ist.
   Die Metrik „Stream fehlt“ zählt nur `stream_missing`. Die Tests dafür
   hat Task 2.
4. **Stille über zwei direkt aufeinanderfolgende Termine:**
   - Der Vorfall des ersten Termins endet an dessen Ende.
   - Der zweite Termin bekommt einen eigenen Vorfall ab seinem Start.
   - Auch er darf einmal alarmieren.
   - Den Test dafür hat Task 3.
5. **Hängendes ffmpeg:** `subprocess.run(timeout=…)` beendet den Prozess. Ein
   Durchlauf, der länger läuft als das Intervall, wird übersprungen, nicht
   doppelt gestartet. Den Stream-Zyklus bremst er nie. Die Tests dafür haben
   Task 1 (Timeout) und Task 3 (Überspringen).

---

### Task 1: Messung mit ffmpeg

**Files:**
- Create: `backend/streams/audio.py`
- Create: `backend/recorders/management/commands/measure_audio.py`
- Modify: `Dockerfile`, `backend/Dockerfile` (`ffmpeg` zu `apt-get install` hinzufügen)
- Test: `backend/streams/tests.py`

**Interfaces:**
- Produces:
  - ```python
    @dataclass(frozen=True)
    class AudioMeasurement:
        ok: bool                 # False: ffmpeg failed (network, timeout, no samples, missing)
        level_db: float | None   # mean dBFS; None with ok=True = no audio track
        detail: str = ""
    ```
  - `ffmpeg_command(url: str, seconds: int) -> list[str]`
  - `parse_volumedetect(stderr: str) -> float | None`
  - `measure_audio(url: str, seconds: int = 10, runner=subprocess.run) -> AudioMeasurement`
  - `ffmpeg_available() -> bool` (`shutil.which("ffmpeg")`)

- [ ] **Step 1: Tests schreiben** (in `streams/tests.py`, ohne echtes ffmpeg, `runner` gefälscht):
  - `test_command_is_argument_list`:
    - Das Ergebnis enthält in dieser Reihenfolge `"-protocol_whitelist", "http,https,tls,tcp,crypto,hls"`, `"-i", url`, `"-map", "0:a:0"`, `"-t", "10"`, `"-af", "volumedetect"` und `"-f", "null"`.
    - Es endet mit `"-"`.
    - Die URL mit `cap-90-R12` bleibt unverändert, die Großschreibung bleibt erhalten.
  - `test_parse_mean_volume`: Bei Stderr mit `[Parsed_volumedetect_0 @ 0x1] mean_volume: -23.4 dB` liefert die Funktion `-23.4`. Ohne diese Zeile liefert sie `None`.
  - `test_measure_level`: Der Runner liefert returncode 0 und Stderr mit `mean_volume: -61.0 dB`. Ergebnis: `AudioMeasurement(True, -61.0)`.
  - `test_measure_no_audio_track`: Der Runner liefert returncode 1 und Stderr mit `Stream map '0:a:0' matches no streams.`. Ergebnis: `ok=True, level_db=None`, `detail` enthält `"no audio"`.
  - `test_measure_timeout`: Der Runner wirft `subprocess.TimeoutExpired`. Ergebnis: `ok=False`.
  - `test_measure_failure`: Der Runner liefert returncode 1 und Stderr mit `HTTP error 404`. Ergebnis: `ok=False`, `detail` ist höchstens 200 Zeichen lang.
  - `test_measure_missing_ffmpeg`: Der Runner wirft `FileNotFoundError`. Ergebnis: `ok=False`.
  - `test_real_ffmpeg_sine` mit `@skipUnless(ffmpeg_available())`:
    - Rufe ffmpeg direkt mit `-f lavfi -i sine=frequency=440:duration=2 -af volumedetect -f null -` auf.
    - Nimm dafür nicht `ffmpeg_command`: `lavfi` steht nicht auf der Whitelist.
    - Prüfe, dass `parse_volumedetect` auf dem echten Stderr einen Wert zwischen −40 und 0 liefert.
    - So bricht ein ffmpeg-Update mit geändertem Ausgabeformat den Parser nicht unbemerkt.
- [ ] **Step 2:** `docker compose exec backend python manage.py test streams` muss mit ImportError fehlschlagen.
- [ ] **Step 3: `streams/audio.py` umsetzen.**
  - Ohne Django-Imports, wie `sources.py`.
  - `ffmpeg_command` setzt `-nostdin -hide_banner -nostats -loglevel info -rw_timeout 10000000` vor `-i`.
  - `measure_audio` ruft `runner(cmd, capture_output=True, text=True, timeout=seconds + 30)` auf.
  - Ein Ergebnis mit Pegel zählt vor dem returncode.
- [ ] **Step 4:** Im Dockerfile `ffmpeg` in die `apt-get install`-Zeile beider Stufen aufnehmen.
  - Dann `docker compose build backend && docker compose up -d backend monitor` ausführen.
  - `docker compose exec backend ffmpeg -version` muss eine Version ausgeben.
- [ ] **Step 5: `manage.py measure_audio <stream> [--seconds N]` umsetzen.**
  - Der Befehl baut die URL über `HlsStreamSource(MonitorSettings.load().url_template, client).playback_url(stream)`.
  - Er gibt `level: -42.1 dBFS`, `level: no audio track` oder `failed: <detail>` aus.
  - Ein Test ruft `call_command` mit gepatchtem `measure_audio` auf und prüft die Ausgabe.
- [ ] **Step 6:** Tests grün, ruff grün.
- [ ] **Step 7: Commit** `feat(streams): measure audio level with ffmpeg`

### Task 2: Datenmodell und Einstellungen

**Files:**
- Modify: `backend/recorders/models.py`, `backend/opencast/models.py`, `backend/recorders/serializers.py` (nur `MonitorSettingsSerializer`)
- Modify: `backend/recorders/incidents.py` (Filter auf `kind`)
- Modify: `backend/common/views.py` (Filter auf `kind` in `ansehbar_stream_missing_alarm`)
- Create: Migrationen `recorders/0009_audio.py`, `opencast/0006_event_first_audio_at.py`
- Test: `backend/recorders/tests.py`, `backend/opencast/tests.py`, `backend/common/tests.py` (oder dort, wo die Metrik-Tests aus 3a liegen)

**Interfaces:**
- Produces:
  - `RecorderStatus`:
    - `audio_level_db = FloatField(null=True, blank=True)`
    - `audio_checked_at = DateTimeField(null=True, blank=True)` (letzte *erfolgreiche* Messung)
    - `audio_detail = CharField(max_length=200, blank=True)`
    - `silent_since = DateTimeField(null=True, blank=True)`
  - `Incident`:
    - `AUDIO_SILENT = "audio_silent"`; `KIND_CHOICES` bekommt `(AUDIO_SILENT, "audio silent")`.
    - `silent_until = DateTimeField(null=True, blank=True)`
  - `ScheduledEvent.first_audio_at = DateTimeField(null=True, blank=True)`
  - `MonitorSettings` (Werte siehe Entscheidungen):
    - `silence_threshold_db = SmallIntegerField(default=-50, validators=[Min(-90), Max(-20)])`
    - `silence_log_minutes` (2, 1–30)
    - `silence_alarm_minutes` (15, 5–120)

- [ ] **Step 1: Tests schreiben.**
  - `test_settings_defaults_audio`: Die Standardwerte sind −50, 2 und 15.
  - `test_settings_alarm_shorter_than_log_rejected`:
    - Ein PUT mit `silence_log_minutes=10, silence_alarm_minutes=5` liefert 400 mit Fehler an `silence_alarm_minutes`.
    - Der Text ist „Must not be shorter than the minimum logged silence.“
  - `test_update_incidents_ignores_audio_incidents`:
    - Ausgangslage: ein offener `audio_silent`-Vorfall in einem laufenden Termin, der Status ist `live`.
    - Nach `update_incidents(now)` ist der Vorfall noch offen und `recovered=False`.
    - Dazu ein zweiter Fall: Status `offline`, keine Wiederöffnung des Ton-Vorfalls als Flackern.
  - `test_metrics_stream_gauge_ignores_audio`: Ein offener alarmierter `audio_silent`-Vorfall setzt `ansehbar_stream_missing_alarm` nicht auf 1.
  - `test_sync_keeps_first_audio_at` (opencast):
    - Ausgangslage: `first_audio_at` ist gesetzt, dann läuft der Abgleich mit demselben Termin und geändertem Titel.
    - Danach ist `first_audio_at` unverändert und der Titel neu.
- [ ] **Step 2:** Die Tests müssen fehlschlagen.
- [ ] **Step 3: Modelle und Migrationen umsetzen.**
  - `makemigrations` ausführen.
  - In die Migrationen die SPDX-Header nachtragen.
- [ ] **Step 4: Serializer anpassen.**
  - Die drei Felder in `MonitorSettingsSerializer.fields` aufnehmen.
  - Die Prüfung in `validate` ergänzen, nach dem Muster von `slot_offset_minutes`.
- [ ] **Step 5: Filter auf `kind` setzen.**
  - In `incidents.py` beide Abfragen auf `kind=Incident.STREAM_MISSING` filtern: die offenen und die kürzlich zurückgekehrten Vorfälle.
  - Ebenso das `alarmed`-Set in `render_prometheus`.
  - In `views.py` ist `incidents_by_event` schon gefiltert; Task 6 erweitert das.
- [ ] **Step 6:** `makemessages -l de` ausführen, Deutsch eintragen, `compilemessages` ausführen.
  - Prüfen: Tests grün, `makemigrations --check` grün, ruff grün.
- [ ] **Step 7: Commit** `feat: audio fields, silence settings, audio_silent incident kind`

### Task 3: Audio-Durchlauf im Monitor

**Files:**
- Create: `backend/recorders/audio_monitor.py`
- Modify: `backend/recorders/management/commands/run_monitor.py`
- Modify: `backend/config/settings.py`, `docker-compose.yml`, `docker-compose.prod.yml`, `.env.prod.example` (die vier `AUDIO_*`-Variablen)
- Test: `backend/recorders/tests.py`

**Interfaces:**
- Consumes:
  - `AudioMeasurement` und `measure_audio` (Task 1)
  - die Felder aus Task 2
  - `HlsStreamSource.playback_url`
- Produces:
  - `run_audio_pass(measure: Callable[[str], AudioMeasurement], source: StreamSource, now_fn: Callable[[], datetime] = timezone.now, max_workers: int = 4) -> int`.
    - Gibt die Zahl der gemessenen Räume zurück.
    - Nur Schritt 1 (Ziele wählen) und Schritt 2 (messen) laufen ohne ORM-Zugriff in Worker-Threads.
    - Danach werden die Ergebnisse geschrieben, alles mit einem `now = now_fn()`, das *nach* den Messungen genommen wird.
  - `update_audio_incidents(now: datetime) -> None` (öffentlich für die Tests)

Ablauf von `run_audio_pass`:
1. **Ziele:** aktive Rekorder mit `status.state == LIVE` und einem laufenden Termin (`start <= now < end`, der früheste).
   - Sortiert nach `audio_checked_at` (leer zuerst), damit die Rotation fair bleibt.
2. Alle Ziele mit `ThreadPoolExecutor(max_workers)` messen.
   - Die URL kommt aus `source.playback_url(stream_name)`.
   - Ausnahmen im Worker ergeben `AudioMeasurement(False, None, "<Typ>: <msg>")`.
3. **Pro Ergebnis schreiben** (`save(update_fields=…)`, ein gelöschter Rekorder bricht nichts ab, wie `_save` in `monitor.py`):
   - **`ok=False`:**
     - nur `audio_detail` setzen;
     - `silent_since`, `audio_checked_at` und `audio_level_db` bleiben.
   - **still** (`level_db is None` oder `< silence_threshold_db`):
     - `silent_since = silent_since or now`
     - `audio_level_db = level_db`, `audio_checked_at = now`, `audio_detail = ""`
       (bei fehlender Audiospur: `audio_detail = "no audio track"`).
   - **Ton:**
     - `silent_since = None`, Pegel und Zeit setzen;
     - am Termin `first_audio_at = now`, wenn noch leer (bedingtes `update`).
4. **Alle Nicht-Ziele mit `silent_since` oder `audio_level_db`:** beide auf `None` setzen.
   - Das gilt für Status `offline`/`unknown`, kein Termin und inaktiv.
5. `update_audio_incidents(now)` aufrufen.

`update_audio_incidents(now)`:
- **Für jeden offenen `audio_silent`-Vorfall**, in dieser Reihenfolge:
  - Termin weg oder vorbei → `ended_at = min(event.end, now)`.
  - Rekorder inaktiv oder Status nicht live → `ended_at = now`.
  - `silent_since is None` (Ton zurück) → `ended_at = audio_checked_at`, `recovered = True`.
  - Sonst `silent_until = audio_checked_at`.
- **Für jedes Ziel mit `silent_since`** und ohne offenen Ton-Vorfall für (Rekorder, laufender Termin):
  - `start = max(silent_since, event.start)`.
  - Wenn `audio_checked_at − start ≥ silence_log_minutes`: Vorfall anlegen mit `kind=AUDIO_SILENT`, `started_at=start` und `silent_until=audio_checked_at`.

- [ ] **Step 1: Tests schreiben.**
  - `measure` ist eine Fake-Funktion, die pro Stream-Name ein vorgegebenes `AudioMeasurement` liefert.
  - `now_fn` liefert feste Zeiten.
  - **`test_only_live_with_running_event_measured`:**
    - Vier Rekorder: live mit Termin, live ohne Termin, offline mit Termin, inaktiv mit Termin.
    - Nur der erste wird gemessen, Rückgabe 1.
  - **`test_silence_starts_and_sound_clears`:**
    - Eine stille Messung setzt `silent_since`.
    - Eine Messung mit Ton setzt es auf `None` und setzt `first_audio_at` am Termin.
    - Eine zweite Messung mit Ton ändert `first_audio_at` nicht.
  - **`test_no_audio_track_is_silent`:** `level_db=None, ok=True` setzt `silent_since`, und `audio_detail` ist `"no audio track"`.
  - **`test_failed_measurement_keeps_state`:**
    - Ausgangslage: still seit 10:00, letzte stille Messung 10:03.
    - Danach scheitern die Messungen bis 10:30.
    - Erwartet:
      - `silent_since` bleibt 10:00, `audio_checked_at` bleibt 10:03.
      - Kein Vorfall wächst über `silent_until=10:03` hinaus.
      - Mit `silence_alarm_minutes=15` ist `audio_alarm_due` (Task 4) `False`; das prüft Task 4.
  - **`test_incident_opens_after_log_minutes`:**
    - Termin 10:00–12:00, Messungen still um 10:20, 10:21 und 10:22:30.
    - Vor 10:22 gibt es keinen Vorfall.
    - Danach gibt es genau einen, mit `started_at=10:20` und `silent_until=10:22:30`.
  - **`test_incident_recovers_on_sound`:**
    - Bei Ton um 10:40 ist der Vorfall geschlossen, mit `ended_at=10:40` und `recovered=True`.
  - **`test_incident_closed_when_stream_drops`:**
    - Status `offline`.
    - Der Vorfall endet mit `now`, `recovered=False`, und `silent_since` ist `None`.
  - **`test_silence_across_back_to_back_events`:**
    - Termine A 10:00–12:00 und B 12:00–14:00, still durchgehend ab 11:50.
    - Der Vorfall von A endet um 12:00.
    - B bekommt ab 12:02 einen eigenen Vorfall mit `started_at=12:00`.
  - **`test_status_fields_not_clobbered`:**
    - Nach dem Durchlauf sind `state`, `media_sequence` und `agent_state` unverändert.
    - Das gilt auch, wenn sie zwischen Laden und Schreiben in der DB geändert wurden.
  - **`test_pass_skipped_while_previous_runs`** (in `run_monitor`):
    - `_start_audio` startet keinen zweiten Thread, solange der erste lebt.
    - Es startet keinen neuen, bevor `AUDIO_INTERVAL_SECONDS` seit dem letzten Start vergangen ist.
- [ ] **Step 2:** Die Tests müssen fehlschlagen.
- [ ] **Step 3: `audio_monitor.py` umsetzen.**
- [ ] **Step 4: In `run_monitor` einbinden.**
  - `_start_audio()` ist nach dem Muster von `_start_sync` gebaut:
    - eigener Daemon-Thread `audio-monitor`;
    - `close_old_connections()` am Anfang;
    - `connections.close_all()` am Ende;
    - fängt jede Ausnahme mit `logger.exception`.
  - Es wird in der Schleife direkt nach `_start_sync` aufgerufen.
  - `--once` führt den Durchlauf inline nach `_cycle` aus.
  - Beim Beenden höchstens `SYNC_JOIN_SECONDS` auf den Thread warten.
  - Die Messfunktion ist `partial(measure_audio, seconds=settings.AUDIO_SAMPLE_SECONDS)`.
  - `source` ist `HlsStreamSource(MonitorSettings.load().url_template, client)`, pro Durchlauf neu geladen.
    - Der Durchlauf nutzt davon nur `playback_url`.
    - Der httpx-Client wird im Audio-Thread nie benutzt.
  - Abschalten:
    - `AUDIO_MONITOR_ENABLED=0` schaltet die Messung ab.
    - Fehlt ffmpeg, gibt es einmal `logger.error("ffmpeg not found; audio monitoring disabled")` und dann keine Messung mehr.
- [ ] **Step 5: Settings und Env eintragen.**
  - In `config/settings.py` die vier Werte mit `_int_or_default` lesen.
  - `AUDIO_MONITOR_ENABLED` mit demselben Bool-Muster wie andere `0`/`1`-Variablen.
  - Die Variablen in beide Compose-Dateien (Anker `app-env`) und in `.env.prod.example` aufnehmen.
- [ ] **Step 6: Gegen den Dev-Stack prüfen.**
  - Tests grün.
  - `docker compose restart monitor`, danach `docker compose exec backend python manage.py run_monitor --once`: Das Log zeigt keinen Fehler.
- [ ] **Step 7: Commit** `feat(recorders): audio pass in the monitor, silence incidents`

### Task 4: Alarm und Entwarnung „Ton fehlt“

**Files:**
- Modify: `backend/recorders/alarm_rules.py`, `backend/alarms/delivery.py`, `backend/alarms/templates/alarms/incident.txt`
- Modify: `backend/locale/de/LC_MESSAGES/django.po` (+ `.mo`)
- Test: `backend/recorders/tests.py`, `backend/alarms/tests.py`

**Interfaces:**
- Consumes: `Incident.AUDIO_SILENT`, `silent_until` und `silence_alarm_minutes` (Task 2).
- Produces:
  - `audio_alarm_due(incident, settings, now, alerted_events: set[int]) -> bool`: rein, ohne I/O.
    - Bedingungen: Vorfall offen, Termin läuft, Rekorder aktiv, `alarm_mode != off`, `event_id not in alerted_events`, `silent_until − started_at ≥ silence_alarm_minutes`.
  - `alarm_due(...)` bleibt für `stream_missing` unverändert.

- [ ] **Step 1: Tests schreiben.**
  - `audio_alarm_due` liefert `True` bei genau 15 min und `False` bei 14:59.
  - `False` bei `alarm_mode=off`.
  - `False`, wenn der Termin in `alerted_events` steht.
  - `False`, wenn `silent_until` fehlt.
  - Fortsetzung des Tests aus Task 3: Nach Messfehlern bleibt es `False`, auch wenn `now` 10:30 ist.
  - `test_queue_audio_alarm_once_per_event`:
    - Zwei `audio_silent`-Vorfälle im selben Termin, beide ≥ 15 min.
    - Der erste ist geschlossen und hat schon `alerted_at`, der zweite ist offen.
    - Nach `deliver_alarms` gibt es keinen weiteren Alarm.
    - Ohne den ersten Vorfall gibt es genau eine `SentNotification` pro Empfänger, mit `kind=alarm`.
  - `test_audio_alarm_mail_text`:
    - Betreff `[ansehBAR] Ton fehlt: <Raum>` (DE).
    - Der Text enthält `Still seit: HH:MM` und den Link `/raum/<id>`.
  - `test_audio_all_clear`:
    - Ein alarmierter Vorfall wird mit `recovered=True` geschlossen.
    - Nach 60 s gibt es eine Entwarnung mit Betreff `[ansehBAR] Ton wieder da: <Raum>`.
  - `test_stream_alarm_unchanged`: Die vorhandenen 3a-Tests bleiben grün.
- [ ] **Step 2:** Die Tests müssen fehlschlagen.
- [ ] **Step 3: `_queue_alarms` anpassen.**
  - Vor der Schleife einmal `alerted_events` laden: Termin-IDs aller `audio_silent`-Vorfälle mit `alerted_at`.
  - Pro Vorfall nach `kind` verzweigen.
  - Nach dem Markieren eines Ton-Alarms die `event_id` sofort in die Menge aufnehmen.
- [ ] **Step 4: `_render_incident` und `incident.txt` nach Art unterscheiden.**
  - Neue msgids:
    - `"[ansehBAR] Sound missing: %(room)s"` / „[ansehBAR] Ton fehlt: %(room)s“
    - `"[ansehBAR] Sound back: %(room)s"` / „[ansehBAR] Ton wieder da: %(room)s“
    - `"Sound missing"` / „Ton fehlt“
    - `"Sound back"` / „Ton wieder da“
    - `"Silent since"` / „Still seit“
  - Der Kontext bekommt `audio` (bool).
- [ ] **Step 5:** `makemessages`/`compilemessages` ausführen, Tests und ruff grün.
- [ ] **Step 6: Commit** `feat(alarms): sound-missing alarm and all-clear`

### Task 5: `/metrics` und Alarmregel

**Files:**
- Modify: `backend/common/views.py`, `monitoring/alerts.yml`, `docs/monitoring.md`
- Test: die Metrik-Tests aus 3a; der YAML-Test läuft in CI

**Interfaces:**
- Produces: Gauge `ansehbar_audio_silent_alarm{room,stream}`.
  - Wert 1, solange ein alarmierter `audio_silent`-Vorfall offen ist.
  - Gleiche Raumauswahl wie `ansehbar_stream_missing_alarm`: aktiv und nicht `off`.
  - Nur bei `alarm_metrics_enabled`.

- [ ] **Step 1: Tests schreiben.**
  - Die Gauge zeigt 1 für den Raum mit offenem alarmiertem Ton-Vorfall und 0 für andere.
  - Bei `alarm_metrics_enabled=False` fehlt sie.
  - Der Alerts-Test prüft die neue Regel `AnsehbarAudioSilent` mit `severity: warning` und `service: ansehbar`.
- [ ] **Step 2:** Die Tests müssen fehlschlagen.
- [ ] **Step 3: Gauge umsetzen.**
  - Gauge in `render_prometheus` bauen.
  - Regel in `alerts.yml`:
    - `expr: ansehbar_audio_silent_alarm == 1`, `for: 1m`.
    - `summary: "Sound missing in {{ $labels.room }}"`.
    - `description: "No sound for over 15 minutes during a scheduled recording (stream {{ $labels.stream }})."`
- [ ] **Step 4:** In `docs/monitoring.md` die Metrik und die Regel ergänzen und vermerken, dass die Datei den Betreibern neu geschickt werden muss.
- [ ] **Step 5:** Tests und ruff grün.
- [ ] **Step 6: Commit** `feat(metrics): audio silent alarm gauge and rule`

### Task 6: API und Oberfläche

**Files:**
- Modify: `backend/recorders/serializers.py`, `backend/recorders/views.py`
- Modify: `frontend/src/api.ts`, `frontend/src/recorders.ts`, `frontend/src/components/StatusBadge.tsx`, `frontend/src/components/RecorderTile.tsx`, `frontend/src/pages/RoomView.tsx`, `frontend/src/media/LevelMeter.tsx`, `frontend/src/components/LastRecordingWarning.tsx`, `frontend/src/pages/admin/SettingsAdmin.tsx`
- Modify: `frontend/src/locales/de/translation.json`
- Test: `backend/recorders/tests.py`, `frontend/src/recorders.test.ts`, `frontend/src/media/level.test.ts`

**Interfaces:**
- Produces (API, `Recorder`):
  - `audio_level_db: number | null`:
    - nur, wenn `status.audio_checked_at` höchstens 120 s vor `now` liegt;
    - als Konstante `AUDIO_FRESH_SECONDS = 120` in `serializers.py`.
  - `silent_since: string | null`: `started_at` des offenen `audio_silent`-Vorfalls im laufenden Termin.
    - Eine einzige Abfrage in `views.py`, im Kontext als `open_silences: dict[recorder_id, datetime]`.
  - `last_recording.problems[]` enthält auch `kind: "audio_silent"` mit `from`, `to` und `minutes`.
    - Die Abfrage in `views.py` filtert auf beide Arten.
    - Der Serializer übernimmt `incident.kind`.
- Produces (Frontend):
  - `Presentation` bekommt `"silent"`: live und `silent_since` gesetzt.
    - `keepsPlayer` ist dafür `true`.
  - `sortForOverview`: zuerst `missing`, dann `silent`, dann Player, dann der Rest.
  - `StatusBadge`-State `silent`: Symbol `◐`, Label `"Silent"`.
    - Gleiche Farben wie `unknown` sind *nicht* erlaubt (Bernstein bedeutet „unbekannt“).
    - Stattdessen `bg-amber-100 text-amber-950 ring-1 ring-amber-700 dark:bg-amber-950 dark:text-amber-100`.
  - In Kachel und Raumansicht neben dem Badge: `t("since {{time}}", …)` mit `formatClock(silent_since)`.
    - Muster wie bei „fehlt“.
  - `LevelMeter` bekommt die Prop `serverLevelDb?: number | null`.
    - Sie gilt, solange der Browser keinen Pegel liefert: nicht freigeschaltet, force-muted oder `analyserUnavailable`.
    - Ist sie nicht `null`, zeigt der Balken `dbfsToMeter(serverLevelDb)`.
    - Label: `t("Server level: {{level}}", { level: t(describeLevel(db)) })`.
    - Ohne Server-Pegel bleibt das bisherige Verhalten.
  - In der Einstellungsseite ein `fieldset` „Sound“ mit den drei Feldern aus Task 2.
    - `silence_threshold_db` hat `step={1}` und Bereich −90 bis −20; Hinweis: „Mean level in dBFS over 10 s below which a room counts as silent.“
    - Die Minutenfelder haben die Bereiche aus Task 2.
  - `LastRecordingWarning`: neue Zeile für `audio_silent`, „Silent {{minutes}} min from {{from}}“, mit Plural.

- [ ] **Step 1: Backend-Tests schreiben.**
  - `audio_level_db` ist `null` bei einer Messung älter als 120 s und der Wert bei einer frischen.
  - `silent_since` ist nur im laufenden Termin gesetzt.
  - `last_recording` listet einen `audio_silent`-Vorfall.
  - Die Zahl der Abfragen für die Liste steigt um höchstens 1 (`assertNumQueries` wie in den vorhandenen Listen-Tests).
- [ ] **Step 2: Frontend-Tests schreiben.**
  - `presentation()` liefert `"silent"`.
  - Die Sortierung ist missing, silent, live, offline.
  - `describeLevel` mit Server-dB, falls ein Helfer dafür entsteht.
- [ ] **Step 3:** Die Tests müssen fehlschlagen. Dann umsetzen.
- [ ] **Step 4:** Prüfen: `tsc -b`, `npm test`, `check:i18n`, Backend-Tests, ruff.
- [ ] **Step 5: Im Browser prüfen.**
  - Per Django-Shell einen Status mit frischem `audio_level_db = -35` und einen offenen `audio_silent`-Vorfall in einem laufenden Testtermin anlegen.
  - Danach müssen sichtbar sein:
    - die Kachel mit „◐ Still“ und „seit HH:MM“;
    - die Sortierung hinter „fehlt“;
    - die Pegelanzeige vor dem Freischalten mit dem Label „Serverpegel: …“;
    - die Einstellungsseite, auf der Speichern und Validierung funktionieren.
- [ ] **Step 6: Commit** `feat(ui): server level, silent badge, sound settings`

### Task 7: Doku

**Files:**
- Modify: `docs/KONFIGURATION.md` (Abschnitt 7 um Ton ergänzen: die vier Env-Variablen, die drei Einstellungen, Kalibrieren mit `measure_audio`, Bandbreite)
- Modify: `README.md`, `CLAUDE.md`
  - `audio_monitor.py` und `streams/audio.py` im Aufbau nennen.
  - `measure_audio` bei den Befehlen nennen.
  - ffmpeg im Image erwähnen.
- Modify: Spec §9: 3b als umgesetzt markieren. Die Kalibrierung der Schwelle bleibt als offener Punkt in §10.

- [ ] **Step 1:** Texte schreiben. Keine echten Host- oder Raumnamen.
- [ ] **Step 2:** Alle Prüfbefehle grün.
- [ ] **Step 3: Commit** `docs: sound monitoring (stage 3b)`
