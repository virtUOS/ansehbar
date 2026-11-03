---
title: Installation
description: ansehBAR selbst betreiben — Aufbau, Voraussetzungen, Systemanforderungen und die ausführliche Konfigurationsanleitung.
---

# Installation

ansehBAR läuft als Docker-Compose-Stack auf einem eigenen Linux-Server. Das
Repository enthält keine Angaben zu einer bestimmten Einrichtung:
Streaming-Server, Rekorder, Anmeldedienst und Domain richtet jeder Standort
selbst ein.

Die Schritt-für-Schritt-Anleitung steht im Repository:

- [Konfigurationsanleitung (docs/KONFIGURATION.md)](https://github.com/virtUOS/ansehbar/blob/main/docs/KONFIGURATION.md)
  — Streaming-Server, Anmeldung, Server, Standortkonfiguration, Opencast,
  Alarme, Aufbewahrung, Fehlersuche, Aktualisieren.
- [Monitoring-Dienst (docs/monitoring.md)](https://github.com/virtUOS/ansehbar/blob/main/docs/monitoring.md)
  — `/metrics` für Prometheus und die mitgelieferten Alarmregeln.
- [README](https://github.com/virtUOS/ansehbar#readme) — Überblick,
  Entwicklung und Betrieb.

## Aufbau

| Dienst | Aufgabe |
|---|---|
| `db` | PostgreSQL 16 |
| `app` | Django mit der Oberfläche und der API |
| `monitor` | prüft die Streams, gleicht Opencast ab, misst den Ton (ffmpeg), verschickt Alarme |
| `caddy` | Reverse-Proxy mit automatischem HTTPS |

Das fertige Image steht unter `ghcr.io/virtuos/ansehbar` bereit.

## Voraussetzungen

- **Streaming-Server** mit HLS-Streams pro Rekorder, per HTTPS erreichbar und
  mit CORS-Freigabe für die ansehBAR-Domain (die Videos lädt der Browser
  direkt vom Streaming-Server).
- **Identity Provider** mit OIDC, z. B. Keycloak, und eine Gruppe für den
  Zugang.
- Optional **Opencast** (External API, nur lesend) für geplante Termine,
  „Stream fehlt“ und Alarme.
- Optional ein **SMTP-Server** für Alarm-E-Mails und **Prometheus** mit
  Alertmanager für den Monitoring-Dienst.

## Systemanforderungen

Richtwerte für einen Standort mit etwa 40 Räumen, von denen bis zu 10
gleichzeitig aufzeichnen:

| | Empfehlung |
|---|---|
| CPU | 2 vCPU |
| Arbeitsspeicher | 4 GB |
| Festplatte | 20–30 GB (Images, Datenbank, Logs) |
| System | Linux mit Docker und Docker Compose |

- **Netz:** Die Videos laufen nicht über den ansehBAR-Server. Die
  Ton-Messung lädt aber pro laufendem Raum etwa alle 30 Sekunden 10 Sekunden
  des Streams. Bei 10 gleichzeitigen Räumen sind das im Schnitt rund
  10 Mbit/s aus dem Streaming-Netz.
- **Erreichbarkeit:** Port 443 von außen für die Nutzerinnen und Nutzer und
  für den Abruf durch Prometheus; ausgehend der Streaming-Server, Opencast,
  der Identity Provider und der SMTP-Server.
- Die Datenbank bleibt klein: Pegelmessungen über 30 Tage brauchen bei 10
  Räumen unter 100 MB.
