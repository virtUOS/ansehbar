---
title: Live monitoring for lecture capture
description: ansehBAR shows at a glance which lecture halls are streaming, whether picture and sound are there and which recordings had problems — with alarms by e-mail and for Prometheus. Open source by virtUOS, Osnabrück University.
hide:
  - navigation
  - toc
---

<div class="as-hero" markdown>

<div class="as-hero__text" markdown>

<p class="as-eyebrow">Open source · virtUOS, Osnabrück University</p>

<h1 class="as-hero__title">Every lecture hall at a glance — <span>picture, sound and schedule.</span></h1>

<p class="as-hero__lead">
The recorders in the lecture halls record and stream live at the same time.
When the stream is missing, the recording usually is too. ansehBAR shows which
rooms are on air, checks picture and sound and speaks up when something is
missing during a scheduled event — before the recording is lost.
</p>

<div class="as-hero__actions" markdown>
[Guide](guide/index.md){ .md-button .md-button--primary }
[:fontawesome-brands-github: Source code on GitHub](https://github.com/virtUOS/ansehbar){ .md-button }
</div>

</div>

<figure class="as-shot as-shot--hero" markdown>
![ansehBAR overview: tiles for a room with a missing stream, a silent room and a live room, below them the recordings still scheduled today](bilder/uebersicht.png)
</figure>

</div>

<ul class="as-facts">
  <li><strong>Live detection</strong><span>from the chunklist, not just the HTTP status</span></li>
  <li><strong>Sound level</strong><span>measured in the browser and on the server</span></li>
  <li><strong>Opencast</strong><span>scheduled events, read-only</span></li>
  <li><strong>Alarms</strong><span>by e-mail and for Prometheus</span></li>
  <li><strong>GitLab tickets</strong><span>with status, event and screenshot</span></li>
  <li><strong>German &amp; English</strong><span>on desktop and phone</span></li>
</ul>

## What ansehBAR does { .as-section-title }

<p class="as-section-lead">A monitoring tool for media services and lecture capture teams: it watches streams and Opencast schedules and changes nothing on recorders, Opencast or the identity provider.</p>

<div class="as-features" markdown>

<div class="as-feature" markdown>
![Room view with a large player, the timeline of the running event and the level curve](bilder/raumansicht.png)

### Room view with timeline

A large player with sound and full screen, below it the events of the running
recording: when the stream was missing, when alarm and all-clear went out,
when sound started — and the measured level curve.
</div>

<div class="as-feature" markdown>
![Week view of the room calendar with events and markers for missing stream, silence and Opencast problems](bilder/kalender-woche.png)

### Room calendar

The week and the day of a room with all Opencast events. Markers show where
the stream was missing, where it was silent, where an alarm was raised and
which recording failed in Opencast.
</div>

<div class="as-feature as-feature--phones" markdown>
<div class="as-phonepair" markdown>
![Room list on a phone with the states “Stream missing”, “Silent” and “Live”](bilder/handy-uebersicht.png)
![Room view on a phone with player and timeline](bilder/handy-raum.png)
</div>

### On the go

On a phone the overview becomes a room list. A tap opens the room with a large
player, sound and full screen — handy for important events right in the
lecture hall.
</div>

<div class="as-feature" markdown>
![Managing the alarm recipients](bilder/verwaltung-alarme.png)

### Alarms that fit

An alarm when the stream is missing during an event or when it stays silent
for long; an all-clear when everything runs again. Per room: on time from the
Opencast start, by grid with c.t., or log only.
</div>

</div>

<div class="grid cards as-more" markdown>

-   :material-traffic-light-outline: __Clear states__

    Always text and symbol, never colour alone: Live, Silent, Stream missing,
    No stream, Status unknown — and a notice when the monitor itself stops
    delivering data.

-   :material-volume-high: __Check the sound__

    A level meter per tile, even with muted video. Only one room plays sound
    at a time — switching another one on mutes the previous one.

-   :material-alert-outline: __Last recording__

    If a room's last recording had problems, tile and room view say so — until
    the next clean recording.

-   :material-theme-light-dark: __Light and dark__

    The interface follows your system or your choice, in German or English.

</div>

## Who it is for { .as-section-title }

<div class="grid cards as-audience" markdown>

-   :material-video-account: __Media services and lecture capture teams__

    ---

    All running rooms on the desktop, a single room on the phone. Alarms by
    e-mail to the people who can act.

    [:octicons-arrow-right-24: To the guide](guide/index.md)

-   :material-server-network: __Universities and IT centres__

    ---

    Self-hosted with Docker Compose, sign-in through your own identity
    provider (OIDC), connected to Opencast and Prometheus.

    [:octicons-arrow-right-24: To the installation](installation.md)

</div>

## Watch, don't touch { .as-section-title }

<div class="grid cards as-trust" markdown>

-   :material-eye-outline: __Read-only__

    ansehBAR never writes to Opencast or the identity provider and controls no
    recorders. It reads streams and schedules — nothing more.

-   :material-account-lock-outline: __Small group of users__

    Access through a group in the identity provider or by invitation. The
    streams are not a public service.

-   :material-scale-balance: __Open source__

    All source code is available under the Apache License 2.0 on
    [GitHub](https://github.com/virtUOS/ansehbar).

-   :material-domain: __Made at a university__

    Developed by virtUOS at Osnabrück University, as one of the BAR tools
    alongside abstimmBAR and ausleihBAR.

</div>

<div class="as-cta" markdown>

<div markdown>

## Installation { .as-cta__title }

ansehBAR runs as a Docker Compose stack of PostgreSQL, Django, a monitor
process and Caddy on your own Linux server — with automatic HTTPS and sign-in
via OIDC. Opencast, e-mail and Prometheus are optional.

</div>

<div class="as-cta__actions" markdown>
[To the installation](installation.md){ .md-button .md-button--primary }
</div>

</div>
