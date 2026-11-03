---
title: Installation
description: Running ansehBAR yourself — architecture, prerequisites, system requirements and the detailed configuration guide.
---

# Installation

ansehBAR runs as a Docker Compose stack on your own Linux server. The
repository contains no details of a particular institution: each site sets up
its own streaming server, recorders, identity provider and domain.

The step-by-step guide is in the repository (in German):

- [Configuration guide (docs/KONFIGURATION.md)](https://github.com/virtUOS/ansehbar/blob/main/docs/KONFIGURATION.md)
  — streaming server, sign-in, server, site configuration, Opencast, alarms,
  retention, troubleshooting, updating.
- [Monitoring service (docs/monitoring.md)](https://github.com/virtUOS/ansehbar/blob/main/docs/monitoring.md)
  — `/metrics` for Prometheus and the bundled alerting rules.
- [README](https://github.com/virtUOS/ansehbar#readme) — overview,
  development and operation.

## Architecture

| Service | Task |
|---|---|
| `db` | PostgreSQL 16 |
| `app` | Django with the web interface and the API |
| `monitor` | checks the streams, syncs Opencast, measures the sound (ffmpeg), sends alarms |
| `caddy` | reverse proxy with automatic HTTPS |

The ready-made image is available as `ghcr.io/virtuos/ansehbar`.

## Prerequisites

- A **streaming server** with one HLS stream per recorder, reachable via HTTPS
  and with CORS allowed for the ansehBAR domain (the browser loads the videos
  directly from the streaming server).
- An **identity provider** with OIDC, e.g. Keycloak, and a group for access.
- Optionally **Opencast** (External API, read-only) for scheduled events,
  “stream missing” and alarms.
- Optionally an **SMTP server** for alarm e-mails and **Prometheus** with
  Alertmanager for the monitoring service.

## System requirements

Guide values for a site with about 40 rooms, up to 10 of which record at the
same time:

| | Recommendation |
|---|---|
| CPU | 2 vCPU |
| Memory | 4 GB |
| Disk | 20–30 GB (images, database, logs) |
| System | Linux with Docker and Docker Compose |

- **Network:** the videos do not pass through the ansehBAR server. The sound
  measurement, however, loads 10 seconds of the stream about every 30 seconds
  per running room. With 10 rooms at the same time that is around 10 Mbit/s
  on average from the streaming network.
- **Reachability:** port 443 from outside for the users and for Prometheus;
  outgoing to the streaming server, Opencast, the identity provider and the
  SMTP server.
- The database stays small: level measurements over 30 days need less than
  100 MB for 10 rooms.
