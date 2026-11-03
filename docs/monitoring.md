<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Universität Osnabrück (virtUOS)

Betriebsanleitung: Prometheus-Endpoint und Alarmregeln.
Bei neuen Kennzahlen (backend/common/views.py, render_prometheus) die
Tabelle unten mitpflegen.
-->

# Monitoring mit Prometheus

ansehBAR stellt Alarm- und Betriebskennzahlen als **Prometheus-Endpoint**
bereit. Ein vorhandener Prometheus sammelt sie und löst über Alertmanager
Meldungen aus (Stufe 3a: Alarm „Stream fehlt“, zusätzlich zur E-Mail).

Diese Anleitung richtet sich an die Betreuung des Servers.

> **Zuständigkeit:** Die Betreiber des Monitorings spielen `monitoring/alerts.yml`
> und den Scrape-Eintrag ein. **Entwarnungen gibt es dort nicht:** der
> Monitoring-Dienst meldet nur den Alarm, die Entwarnung („Stream wieder da“)
> kommt ausschließlich per E-Mail von ansehBAR. Die Regeln allein können
> Alertmanager nicht davon abhalten, beim Ende eines Alarms eine
> „resolved“-Meldung zu schicken: Im Receiver (bzw. der Route) für ansehBAR
> deshalb `send_resolved: false` setzen.

## Überblick

| | |
|---|---|
| **URL** | `https://<ihre-domain>/metrics` |
| **Format** | Prometheus-Textformat (`text/plain; version=0.0.4`) |
| **Schutz** | Bearer-Token: Header `Authorization: Bearer <METRICS_TOKEN>` |
| **Standard** | **aus** — ohne gesetztes `METRICS_TOKEN` antwortet der Endpoint mit `404` |
| **Falsches Token** | `401` |
| **Inhalt** | Raum-/Stream-Namen (Label), Zeitstempel und Zähler — keine Personendaten |

## 1. Endpoint aktivieren

1. Ein langes Zufalls-Token erzeugen:

   ```bash
   openssl rand -hex 32
   ```

2. In der `.env.prod` auf dem Server eintragen (die Vorlage
   `.env.prod.example` enthält die Zeile auskommentiert):

   ```bash
   METRICS_TOKEN=<das erzeugte Token>
   ```

   `docker-compose.prod.yml` reicht die Variable an den `app`-Container durch.

3. Den App-Container neu erstellen:

   ```bash
   sudo docker compose -f docker-compose.prod.yml up -d app
   ```

4. Die Caddy-Konfiguration muss `/metrics` an die App weiterleiten. Das
   mitgelieferte `Caddyfile` enthält dafür den Block

   ```caddy
   handle /metrics {
   	reverse_proxy app:8000
   }
   ```

   Bei einem eigenen Reverse-Proxy die Weiterleitung dort ergänzen. Danach
   Caddy neu laden:

   ```bash
   sudo docker compose -f docker-compose.prod.yml restart caddy
   ```

   Fehlt der Block, liefert `/metrics` die Startseite der Web-App (HTML) statt
   der Kennzahlen, und Prometheus meldet einen Parse-Fehler.

5. Testen:

   ```bash
   curl -s -H "Authorization: Bearer <token>" https://<ihre-domain>/metrics | head
   ```

   Erwartet wird Text wie `# TYPE ansehbar_stream_missing_alarm gauge`. Ohne
   Header muss `401` kommen:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://<ihre-domain>/metrics
   ```

## 2. Prometheus konfigurieren

Scrape-Eintrag für die `prometheus.yml` (Vorlage:
`monitoring/scrape.example.yml`):

```yaml
scrape_configs:
  - job_name: ansehbar
    scheme: https
    metrics_path: /metrics
    scrape_interval: 1m
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/ansehbar.token   # enthält nur das Token
    static_configs:
      - targets: ["ansehbar.example.org"]
```

Das Token besser per `credentials_file` als direkt in der YAML hinterlegen
(Datei nur für den Prometheus-Benutzer lesbar). Nach der Änderung Prometheus
neu laden und unter *Status → Targets* prüfen, dass das Ziel `UP` ist.

## 3. Die Kennzahlen

Alle Werte sind **Gauges**.

| Kennzahl | Labels | Bedeutung |
|---|---|---|
| `ansehbar_stream_missing_alarm` | `room`, `stream` | `1`, wenn für den Rekorder ein offener, alarmierter Vorfall besteht, sonst `0`. Gemeldet für alle aktiven Rekorder, deren Alarmmodus nicht „aus“ ist. Entfällt ganz, wenn der Kanal „Metriken“ (Alarm-Einstellung `alarm_metrics_enabled`) aus ist. |
| `ansehbar_audio_silent_alarm` | `room`, `stream` | `1`, wenn für den Rekorder ein offener, alarmierter Ton-Vorfall („Ton fehlt“) besteht, sonst `0`. Gleiche Rekorderauswahl und gleicher Kanal „Metriken“ wie bei `ansehbar_stream_missing_alarm`. |
| `ansehbar_monitor_last_check_timestamp_seconds` | — | Unix-Zeit der letzten Prüfung eines aktiven Rekorders; fehlt, solange noch nie geprüft wurde. |
| `ansehbar_opencast_enabled` | — | `1`, wenn die Opencast-Anbindung aktiv ist, sonst `0`. |
| `ansehbar_opencast_last_success_timestamp_seconds` | — | Unix-Zeit des letzten erfolgreichen Opencast-Abgleichs; nur bei aktiver Anbindung und nach einem ersten Erfolg. |
| `ansehbar_recorders` | `state` | Anzahl aktiver Rekorder je Status: `live`, `offline`, `unknown`. |

Label-Werte werden maskiert (`\\`, `\"`, `\n`). `room` ist der Raumname, ohne
Namen die Agent-ID, sonst der Stream-Name (wie in der Oberfläche).

## 4. Alarmregeln

`monitoring/alerts.yml` enthält die Regelgruppe `ansehbar`. Alle Regeln tragen
das Label `service: ansehbar` (für das Routing in den eigenen Matrix-Raum) und
ein `severity`-Label.

| Regel | Bedingung | Dauer | Severity |
|---|---|---|---|
| `AnsehbarStreamMissing` | `ansehbar_stream_missing_alarm == 1` | 2 min | `critical` |
| `AnsehbarAudioSilent` | `ansehbar_audio_silent_alarm == 1` | 1 min | `warning` |
| `AnsehbarMonitorStale` | `time() - ansehbar_monitor_last_check_timestamp_seconds > 300` | 5 min | `warning` |
| `AnsehbarOpencastSyncStale` | `ansehbar_opencast_enabled == 1 and time() - ansehbar_opencast_last_success_timestamp_seconds > 900` | 10 min | `warning` |

Die Regel `AnsehbarAudioSilent` ist neu (Stufe 3b): Die Betreiber müssen die
aktualisierte `monitoring/alerts.yml` erneut erhalten und einbinden, sonst
bleibt „Ton fehlt“ ohne Prometheus-Alarm.

Einbinden: Datei auf den Prometheus-Server legen, unter `rule_files:` in der
`prometheus.yml` eintragen, Prometheus neu laden. Die Prüfung der Syntax:

```bash
promtool check rules monitoring/alerts.yml
```

Der Alarm „Stream fehlt“ entsteht nur während eines Aufzeichnungstermins
(Alarmmodus und Karenzzeit stellen Sie in den Alarm-Einstellungen ein).
Außerhalb von Terminen ist „kein Stream“ normal und bleibt `0`.

## Fehlersuche

| Symptom | Ursache / Lösung |
|---|---|
| `404` | `METRICS_TOKEN` nicht gesetzt oder App-Container nicht neu erstellt (Schritt 1.3) |
| `401` | Token falsch, oder Header fehlt (`Authorization: Bearer …`, mit Leerzeichen) |
| HTML statt Kennzahlen / Parse-Fehler in Prometheus | `handle /metrics` fehlt im `Caddyfile` (Schritt 1.4) |
| `ansehbar_stream_missing_alarm` / `ansehbar_audio_silent_alarm` fehlt | Kanal „Metriken“ (`alarm_metrics_enabled`) ist aus, oder kein aktiver Rekorder mit Alarmmodus ungleich „aus“ |
| Target `DOWN`, TLS-Fehler | Domain/Zertifikat prüfen; `scheme: https` gesetzt? |
