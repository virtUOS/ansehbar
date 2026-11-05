---
title: Live-Kontrolle der Vorlesungsaufzeichnung
description: ansehBAR zeigt auf einen Blick, welche Hörsäle gerade streamen, ob Bild und Ton da sind und welche Aufzeichnungen Probleme hatten — mit Alarmen per E-Mail und für Prometheus. Open Source von virtUOS, Universität Osnabrück.
hide:
  - navigation
  - toc
---

<div class="as-hero" markdown>

<div class="as-hero__text" markdown>

<p class="as-eyebrow">Open Source · virtUOS, Universität Osnabrück</p>

<h1 class="as-hero__title">Jeder Hörsaal auf einen Blick — <span>Bild, Ton und Termin.</span></h1>

<p class="as-hero__lead">
Die Rekorder in den Hörsälen zeichnen auf und streamen dabei live. Fehlt der
Stream, fehlt meist auch die Aufzeichnung. ansehBAR zeigt, welche Räume gerade
senden, prüft Bild und Ton und meldet sich, wenn während eines geplanten
Termins etwas fehlt — bevor die Aufzeichnung verloren ist.
</p>

<div class="as-hero__actions" markdown>
[Anleitung](anleitung/index.md){ .md-button .md-button--primary }
[:fontawesome-brands-github: Quellcode auf GitHub](https://github.com/virtUOS/ansehbar){ .md-button }
</div>

</div>

<figure class="as-shot as-shot--hero" markdown>
![ansehBAR-Übersicht: Kacheln für einen Raum mit fehlendem Stream, einen stillen und einen laufenden Raum, darunter die heute noch geplanten Aufzeichnungen](bilder/uebersicht.png)
</figure>

</div>

<ul class="as-facts">
  <li><strong>Live-Erkennung</strong><span>an der Chunklist, nicht nur am HTTP-Status</span></li>
  <li><strong>Ton-Pegel</strong><span>im Browser und vom Server gemessen</span></li>
  <li><strong>Opencast</strong><span>geplante Termine, nur lesend</span></li>
  <li><strong>Alarme</strong><span>per E-Mail und für Prometheus</span></li>
  <li><strong>GitLab-Tickets</strong><span>mit Status, Termin und Screenshot</span></li>
  <li><strong>Deutsch &amp; Englisch</strong><span>am PC und auf dem Smartphone</span></li>
</ul>

## Was ansehBAR kann { .as-section-title }

<p class="as-section-lead">Ein Kontrollwerkzeug für Medientechnik und Aufzeichnungsteams: Es beobachtet Streams und Opencast-Termine und verändert nichts an Rekordern, Opencast oder Anmeldedienst.</p>

<div class="as-features" markdown>

<div class="as-feature" markdown>
![Raumansicht mit großem Player, Zeitleiste des laufenden Termins und Pegelkurve](bilder/raumansicht.png)

### Raumansicht mit Zeitleiste

Großer Player mit Ton und Vollbild, darunter die Ereignisse des laufenden
Termins: wann der Stream fehlte, wann Alarm und Entwarnung rausgingen, ab wann
Ton da war — und der gemessene Pegelverlauf.
</div>

<div class="as-feature" markdown>
![Wochenansicht des Raumkalenders mit Terminen und Markern für fehlenden Stream, Stille und Opencast-Probleme](bilder/kalender-woche.png)

### Raumkalender

Woche und Tag eines Raums mit allen Opencast-Terminen. Marker zeigen, wo der
Stream fehlte, wo es still war, wo ein Alarm ausgelöst wurde und welche
Aufzeichnung in Opencast gescheitert ist.
</div>

<div class="as-feature as-feature--phones" markdown>
<div class="as-phonepair" markdown>
![Raumliste auf dem Smartphone mit Status „Stream fehlt“, „Still“ und „Live“](bilder/handy-uebersicht.png)
![Raumansicht auf dem Smartphone mit Player und Zeitleiste](bilder/handy-raum.png)
</div>

### Auch unterwegs

Auf dem Smartphone wird die Übersicht zur Raumliste. Ein Tipp öffnet den Raum
mit großem Player, Ton und Vollbild — praktisch bei wichtigen Veranstaltungen
direkt im Hörsaal.
</div>

<div class="as-feature" markdown>
![Verwaltung der Alarm-Empfängerinnen und -Empfänger](bilder/verwaltung-alarme.png)

### Alarme, die passen

Alarm, wenn während eines Termins der Stream fehlt oder lange Stille herrscht;
Entwarnung, wenn alles wieder läuft. Pro Raum einstellbar: pünktlich zum
Opencast-Start, nach Raster mit c.t. oder nur protokollieren.
</div>

</div>

<div class="grid cards as-more" markdown>

-   :material-traffic-light-outline: __Klare Zustände__

    Immer Text und Symbol, nie nur Farbe: Live, Still, Stream fehlt, Kein
    Stream, Status unbekannt — und ein Hinweis, wenn der Monitor selbst keine
    Daten mehr liefert.

-   :material-volume-high: __Ton prüfen__

    Pegel pro Kachel, auch bei stummem Video. Es läuft immer nur ein Ton —
    wer einen anderen Raum einschaltet, schaltet den vorigen stumm.

-   :material-alert-outline: __Letzte Aufzeichnung__

    Hatte die letzte Aufzeichnung eines Raums Probleme, steht das in Kachel
    und Raumansicht — bis zur nächsten sauberen Aufzeichnung.

-   :material-theme-light-dark: __Hell und dunkel__

    Die Oberfläche folgt dem System oder Ihrer Wahl, auf Deutsch oder
    Englisch.

</div>

## Für wen { .as-section-title }

<div class="grid cards as-audience" markdown>

-   :material-video-account: __Medientechnik und Aufzeichnungsteams__

    ---

    Am PC alle laufenden Räume im Blick, unterwegs der einzelne Raum auf dem
    Smartphone. Alarme per E-Mail an die, die eingreifen können.

    [:octicons-arrow-right-24: Zur Anleitung](anleitung/index.md)

-   :material-server-network: __Hochschulen und Rechenzentren__

    ---

    Selbst betreiben mit Docker Compose, Anmeldung über den eigenen Identity
    Provider (OIDC), Anbindung an Opencast und Prometheus.

    [:octicons-arrow-right-24: Zur Installation](installation.md)

</div>

## Beobachten, nicht eingreifen { .as-section-title }

<div class="grid cards as-trust" markdown>

-   :material-eye-outline: __Nur lesend__

    ansehBAR schreibt nie nach Opencast oder in den Anmeldedienst und steuert
    keine Rekorder. Es liest Streams und Termine — mehr nicht.

-   :material-account-lock-outline: __Kleiner Personenkreis__

    Zugang über eine Gruppe im Identity Provider oder per Einladung. Die
    Streams sind kein öffentliches Angebot.

-   :material-scale-balance: __Open Source__

    Der gesamte Quellcode steht unter der Apache-Lizenz 2.0 auf
    [GitHub](https://github.com/virtUOS/ansehbar).

-   :material-domain: __Aus der Hochschule__

    Entwickelt von virtUOS an der Universität Osnabrück, als Teil der
    BAR-Werkzeuge wie abstimmBAR und ausleihBAR.

</div>

<div class="as-cta" markdown>

<div markdown>

## Installation { .as-cta__title }

ansehBAR läuft als Docker-Compose-Stack aus PostgreSQL, Django, einem
Monitor-Prozess und Caddy auf einem eigenen Linux-Server — mit automatischem
HTTPS und Anmeldung über OIDC. Opencast, E-Mail und Prometheus sind optional.

</div>

<div class="as-cta__actions" markdown>
[Zur Installation](installation.md){ .md-button .md-button--primary }
</div>

</div>
