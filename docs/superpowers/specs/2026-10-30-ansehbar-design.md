# ansehBAR — Design

Stand: 2026-10-30 · Status: Entwurf zur Freigabe

ansehBAR ersetzt den alten Live-Stream-Monitor (`alt/streaming-monitor/`) der
Uni Osnabrück: eine statische Seite mit Video.js-Grid und fest kodierter
Rekorderliste. Das neue Tool ist ein virtUOS-„-bar“-Tool auf Basis von
basicbar und wächst in Stufen zu einem Kontroll- und Alarmwerkzeug für die
Hörsaal-Aufzeichnungen.

## 1. Warum

- Die Hörsaal-Medientechnik nutzt den alten Monitor noch immer, um nach
  Installation oder Wartung zu prüfen, ob ein Raum sauber läuft: Dreht die
  Kamera zum Vortragenden zurück? Ist das PC-Bild ungestört? Stimmt der Ton?
  Neue Rekorder sollen sofort drin sein. Heute heißt das: Code ändern.
- Die Abteilung des Auftraggebers ist dafür zuständig, dass alle geplanten
  Aufzeichnungen laufen. Für ständiges Hinschauen gibt es kein Personal mehr,
  deshalb gibt es heute nur Stichproben, vor allem bei wichtigen
  Veranstaltungen. Ein Alarm ohne Hinschauen schließt diese Lücke.
- Bei wichtigen Veranstaltungen ist oft ein Techniker in der Nähe und will
  nebenbei auf dem Smartphone prüfen, ob alles läuft.
- Der alte Monitor zeigt bei fehlendem Stream nur einen schwarzen oder
  fehlerhaften Player. Er ist unauthentifiziert, und seine Rekorderlisten
  sind schon auseinandergelaufen (`index.html` gegenüber `neu/index.html`).

Fachlicher Hintergrund:
- Opencast plant die Aufzeichnungen. Die Rekorder (Capture Agents) starten
  zur gebuchten Zeit selbst.
- **Aufzeichnung und Live-Stream sind bei den Rekordern fest gekoppelt.**
  Fehlt der Stream während eines Termins, ist die Aufzeichnung praktisch kaputt.
- Ein Stream enthält Kamerabild und Bildschirmbild zusammen in einem Video.
- Gestreamt wird derzeit über einen HLS-Streaming-Server:
  `https://streaming.example.org/live/<stream>/playlist.m3u8` (HLS).
  Mittelfristig wird der Streaming-Server durch eine andere Streaming-Technik ersetzt.
- Die Mediensteuerung hat eine Funktion „Stumm für 10 Minuten“.
  Bis zu 10 Minuten Stille im Raum sind also gewollt.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**
- Am PC: Übersicht aller Räume, in denen gerade gestreamt wird oder werden
  sollte, plus Ausblick auf den Rest des Tages.
- Am Smartphone: einen Raum groß kontrollieren.
- Ein unmissverständlicher Hinweis, wenn in einem Raum kein Video läuft, und
  warum (kein Termin oder Stream fehlt).
- Bild und Ton prüfen: Pegelanzeige auch bei stummem Video, Ton pro Stream
  gezielt einschaltbar.
- Rekorderdaten aus Opencast: Welche Rekorder gibt es, welche sollten gerade
  aufzeichnen, ist der Stream wirklich da?
- Alarm, wenn ein Stream laut Opencast-Termin fehlt oder abbricht, und
  zurückhaltender, wenn der Ton sicher ausfällt.
- Ein Protokoll der Ausfälle, im Kalender pro Raum mit den Opencast-Terminen
  abgleichbar.
- Barrierefrei (Ziel WCAG 2.1 AA), voll nutzbar auf Smartphones.
- Erweiterbar: Das Tool soll später weitere Ideen aufnehmen, eventuell sogar
  die Basis eines neuen Live-Streamings werden. Der Streaming-Server darf deshalb nicht
  quer durch den Code verdrahtet sein.

**Nicht-Ziele (vorerst)**
- Streaming für jedermann. ansehBAR ist ein Kontrollwerkzeug für einen
  kleinen Kreis.
- Probleme beheben: Rekorder, Opencast oder Mediensteuerung werden nicht
  gesteuert. Ein Alarm ist nur eine Meldung, behoben wird woanders.
- Rollen und Rechtestufen: Alle, die sich anmelden dürfen, dürfen alles.
- Paging und Favoriten. Erst wenn andere Hochschulen mit viel mehr Räumen
  einsteigen.
- Zugriffsschutz der Stream-URLs selbst (Sache des Streaming-Servers).
- Pünktlichkeit lernen (siehe Stufe 4; Daten werden aber ab Stufe 3 gesammelt).

**Anti-Ziele: Das wäre ein Fehlschlag, selbst wenn es technisch läuft**
- **Alarmfluten.** Pausen, Stillarbeit, „Stumm 10 min“ oder ein flackernder
  Stream dürfen keine Serie von Meldungen auslösen. Wer zu viele Fehlalarme
  bekommt, ignoriert irgendwann alle.
- Ein schwarzer Player ohne Erklärung.
- Schreibende Eingriffe in Keycloak. **ansehBAR ändert dort nie etwas.**
- Status nur über Farbe (Barrierefreiheit).

## 3. Aufbau und Technik

**Entschieden:**
- Ein „-bar“-Tool: erzeugt aus dem basicbar-Copier-Template
  (`~/dev/basicbar`, `pipx run copier copy --vcs-ref HEAD …`).
  - Stack: Django, DRF, `basicbar-auth` (OIDC über Keycloak), React mit Vite
    und Tailwind, `@basicbar/ui`, Postgres, Docker Compose, Caddy.
  - `project_slug: ansehbar`, `project_title: ansehBAR`, `use_lti: false`.
  - Die Konventionen der Geschwister-Tools gelten: SPDX-Header, kein
    Django-Admin (jede Pflegemaske im Frontend), UI-Texte englisch als
    i18n-Key mit deutscher Übersetzung.
- **Postgres wird genutzt.** `basicbar-auth` braucht sie ohnehin (User,
  Session-Index für Back-Channel-Logout). Rekorderliste, Einladungen,
  Alarm-Empfänger, Vorfälle und Messwerte liegen dort.
- **Akzentfarbe „Signal-Magenta“**, `brand_hue: 335`, `neutral_hue: 220`.
  Rot, Grün und Gelb bleiben frei für den Status (läuft, fehlt, still).
  Die Farbtöne der anderen Tools: ausleihBAR 91, abstimmBAR 150,
  kalkulierBAR 195, erkennBAR 260.

**Ports** (kollisionsfrei, *meine Wahl*, prüfen gegen die Liste in
`basicbar/copier.yml` und die Geschwister): Frontend 5179, Backend 8007,
Keycloak 8086, Postgres 5438.

**Prozesse** (*meine Wahl*):
- `backend` (Django/DRF)
- `frontend`
- `monitor`: derselbe Backend-Code, Startbefehl `manage.py run_monitor`.
  Eine Dauerschleife prüft Streams, gleicht mit Opencast ab und erzeugt
  Vorfälle und Alarme.
- Kein Celery und kein Redis. Die Last ist klein, und Zustand liegt in Postgres.

**Streaming-Abstraktion:** Ein kleines Backend-Interface „Stream-Quelle“
liefert pro Rekorder:
- die Wiedergabe-URL,
- „ist der Stream live?“.

Die erste Implementierung ist „HLS“. Sie bekommt eine URL-Vorlage
(Standard `https://streaming.example.org/live/{stream}/playlist.m3u8`),
die in den Einstellungen änderbar ist. Ein späteres Streaming-System ist eine
weitere Implementierung.

**Live-Erkennung** (Details beim Builder): HLS-Playlist und Chunklist abrufen.
„Live“ heißt: Die Chunklist existiert, und ihre Media-Sequence oder ihr neuestes
Segment ist frischer als ein Schwellwert (Größenordnung 3 Segmentdauern).
Ein bloßes HTTP 200 auf die Master-Playlist reicht nicht.

## 4. Zugang

- Anmeldung über OIDC (Keycloak) mit `basicbar-auth`.
- Zugang hat, wer
  1. in der konfigurierten **IdP-Gruppe** ist (Gruppen-Claim im Token,
     Gruppenname per Env, z. B. `ansehbar-users`), **oder**
  2. auf der **Einladungsliste von ansehBAR** steht.
- Einladungen werden in ansehBAR gepflegt (eigene Tabelle) und lassen sich
  entfernen.
  - Eingeladen werden kann nur, wer ein Konto in eurem Keycloak hat oder
    haben wird.
  - Abgleich bei der Anmeldung über `preferred_username` oder E-Mail (*meine
    Wahl*: beides; ein Eintrag passt, wenn einer der beiden übereinstimmt,
    jeweils ohne Groß/Klein-Unterscheidung).
  - Wird ein Eintrag entfernt, verliert die Person den Zugang bei der nächsten
    Anfrage. Der Zugangscheck läuft pro Anfrage, nicht nur beim Login.
- Wer sich anmeldet, aber keinen Zugang hat, sieht eine freundliche Seite
  „Kein Zugang – wende dich an …“. Die Kontaktadresse ist einstellbar.
  Es entsteht dabei kein nutzbares Konto.
- Die Gruppe wird wie bei den anderen Tools von der IDM-Gruppe angelegt und
  per Gruppen-Claim (`OIDC_GROUPS_CLAIM` aus `basicbar-auth`) übermittelt.
- Zusätzlich gibt es eine Liste von Personen, die **per Konfiguration** (Env,
  z. B. `ANSEHBAR_BOOTSTRAP_USERS`, Benutzernamen/E-Mails) immer Zugang haben.
  Sie dient für den ersten Start und als Notzugang, falls der Gruppen-Claim
  fehlt.
- Alle mit Zugang haben dieselben Rechte, auch für Einstellungen,
  Einladungen und Alarm-Empfänger.
- Die Demo-Konten im Dev-Keycloak (`demo`, `admin-demo`) bekommen die Gruppe.
  Ein zusätzliches Konto ohne Gruppe dient zum Testen der „Kein Zugang“-Seite.

## 5. Oberflächen

Freigegebene Entwürfe: `.superpowers/brainstorm/*/content/uebersicht-v2.html`
(PC) und `uebersicht.html` (Smartphone-Teil).

### 5.0 Rekorder und Raum

- **Technischer Anker ist der Rekorder** (Opencast Capture Agent bzw.
  Stream-Name). An ihm hängen Termine, Vorfälle, Kalender und Alarmmodus.
- **Die Menschen sprechen von Räumen.** Jeder Rekorder hat einen Raumnamen
  (z. B. „20/R06 (Hall)“). Er ist überall die Hauptbezeichnung: Kacheln,
  Suche, Meldungen, Kalender. Die Rekorder-ID steht nur klein als Zusatz.
- Wo im Dokument „pro Raum“ oder `/raum/<id>` steht, ist technisch der
  Rekorder gemeint. Die URL nutzt die interne Rekorder-ID.
- Ein Rekorder ohne Raumnamen (z. B. ein neu aus Opencast übernommener) wird
  mit seiner ID angezeigt und als „Raumname fehlt“ markiert.
- *Meine Wahl:* Wird ein Rekorder ausgetauscht, bleibt die Historie beim
  alten Rekorder. Der Kalender lässt sich nach Raumnamen filtern und zeigt
  dann alte und neue Rekorder desselben Raums gemeinsam.

### 5.1 PC-Übersicht (Startseite)

- Kopfzeile: Logo „ansehBAR“, Filter-Chips **Jetzt · Heute · Alle Räume**
  (mit Anzahl) und eine Suche nach Raum.
- **Kacheln nur für Räume, die gerade streamen oder streamen sollten.**
  Reihenfolge: Probleme zuerst (Stream fehlt, dann Stille), dann nach Raum.
- Eine Kachel enthält:
  - Player (16:9), rechts eine senkrechte Pegelanzeige.
  - Status-Badge oben links, immer mit **Text und Symbol**: `● LIVE`,
    `◐ STILL seit 10:11`, `⚠ Stream fehlt`.
  - Darunter groß der Raum.
  - **Deutlich hervorgehoben die Zeit:** „seit 10:00“ (läuft) bzw. „ab 10:00“
    (fehlt), daneben klein „bis 12:00“.
  - Titel des Opencast-Termins.
  - Ton-Knopf (🔇/🔊) pro Kachel.
  - Bei „fehlt“: gestreifte Fläche statt Player, Text „Stream fehlt – seit
    17 min“, roter Rahmen, Hinweis „Alarm 10:03 gesendet“.
- **„Heute noch geplant“:** Liste unter den Kacheln, keine Kacheln.
  Pro Zeile: Zeitfenster hervorgehoben in Akzentfarbe, Raum, Titel,
  „in 1 h 43 min“.
- **Ruhige Räume:** eine kompakte Zeile „Heute ohne Aufzeichnung: …“. Ein Klick
  auf einen Raum öffnet ihn trotzdem (Raumansicht, Player versucht zu laden,
  klarer Hinweis, wenn nichts kommt).
- „Alle Räume“ zeigt alle Rekorder als Kacheln, ruhige Räume mit „Kein Stream
  – keine Aufzeichnung geplant · nächste: 14:00“.
- Videos starten **stumm** und automatisch. Der Ton ist pro Kachel einschaltbar.
  *Meine Wahl:* Es läuft immer nur ein Ton zur Zeit. Wer einen anderen
  einschaltet, schaltet den vorherigen stumm.
- Am Abend (ab 17 Uhr) oder wenn heute nichts mehr ansteht: zusätzlich „Morgen“
  mit den Terminen des nächsten Tages (*meine Wahl*).
- Die Statusdaten aktualisieren sich selbst (Polling alle ~5–10 s, *meine
  Wahl*). Kacheln erscheinen und verschwinden ohne Neuladen. Laufende Player
  werden dabei nicht neu gestartet.
- **Stufe 1 ohne Opencast:** Es gibt nur „läuft“ und „ruhig“. „Stream fehlt“,
  Titel, „bis“ und „Heute noch geplant“ kommen mit Stufe 2.

### 5.2 Smartphone (ein Raum)

- Raumansicht mit eigener URL (`/raum/<id>`). Auf schmalen Bildschirmen ist sie
  das primäre Ziel. Die Übersicht wird zur Raumliste mit Status
  (Live/fehlt/heute ab …).
- Kopf: zurück, Raumname, „Raum wechseln“.
- Großer Player mit Pegel, Badge mit Laufzeit („● LIVE 47:12“).
- Titel, Opencast-Zeitfenster, Rekordername.
- Große Knöpfe: **Ton an/aus**, **Vollbild**.
- Kurze Zeitleiste der Ereignisse dieses Termins, z. B. „✅ Bild seit 10:00
  stabil“, „◐ 10:31 Stille 4 min (protokolliert)“.
- Die Raumansicht gibt es auch am PC (Klick auf eine Kachel oder einen Raum).

### 5.3 Pegelanzeige

- Im Browser über die Web-Audio-API (MediaElementSource → Analyser). Der Ton
  wird abgegriffen, ohne hörbar zu sein: Das Element ist nicht `muted`, die
  Lautstärke regelt ein GainNode.
- Browser verlangen eine Nutzergeste, bevor Audio läuft. Deshalb gibt es
  einmal pro Seite den Knopf „Pegel & Ton aktivieren“. Bis dahin zeigt die
  Anzeige den **vom Monitor im Backend gemessenen Pegel** (grob, alle paar
  Sekunden; ab Stufe 3) bzw. in Stufe 1 einen klaren Zustand „Pegel nach
  Klick“.
- Wiedergabe über hls.js (MSE; auf iOS ManagedMediaSource, Fallback natives
  HLS). Bei nativem HLS kann die Web-Audio-Messung leer bleiben. Dann wird auf
  den Backend-Pegel zurückgefallen, ohne Fehlermeldung.
- CORS ist geprüft (2026-10-30). `streaming.example.org` antwortet mit
  `Access-Control-Allow-Origin: *` und ist vom Entwicklungsrechner
  erreichbar. Ein Stream ohne Sendung liefert HTTP 404 auf
  `playlist.m3u8`. Das ist ein brauchbares erstes Signal für die
  Live-Erkennung, ersetzt aber nicht die Frische-Prüfung der Chunklist.

### 5.4 Pflege und Einstellungen (Frontend, kein Django-Admin)

- **Rekorder/Räume:** Liste mit Anlegen, Bearbeiten, Deaktivieren.
  - Stufe 1: Felder Anzeigename (Raum, z. B. „40/R05“), Stream-Name, aktiv.
  - Startdaten: die Liste aus `alt/streaming-monitor/index.html` mit den
    Raumnamen aus `direct.html`/`streams-alt.html`, wo vorhanden. Der Abgleich der
    widersprüchlichen Namen (`rec-hall`/`legacy-hall` u. a.) ist eine Aufgabe
    beim Import. Was unklar ist, wird inaktiv angelegt und markiert.
  - Ab Stufe 2: Opencast-Capture-Agent, Alarmmodus pro Raum (siehe 7.2).
- **Einladungen** (siehe 4).
- **Alarm-Empfänger:** E-Mail-Adressen frei eintragen oder bekannte Nutzer
  (bereits angemeldet) per Suche auswählen. Einzeln an- und abschaltbar.
- **Alarm-Kanäle:** E-Mail, Weitergabe an den Monitoring-Dienst (siehe 7.4),
  jeweils an/aus.
- **Zeitraster und Schwellen** (siehe 7.2, 7.3).
- **Streaming:** URL-Vorlage, Live-Schwellwert.
- Sprache Deutsch und Englisch, über `@basicbar/ui` i18n.

### 5.5 Barrierefreiheit (verbindlich)

- Status immer mit Text und Symbol, nie nur mit Farbe. Die Kontraste der
  Badges gelten in Hell- und Dunkelmodus.
- Volle Tastaturbedienung. Kacheln sind fokussierbar, Ton-Knöpfe haben
  sprechende Labels („Ton für 40/R05 einschalten“).
- Neue Alarme werden über eine `aria-live`-Region angesagt („Stream fehlt in
  95/R05“). Wiederkehrende Aktualisierungen ohne Statuswechsel werden nicht
  angesagt.
- `prefers-reduced-motion` wird respektiert (keine pulsierenden Badges).
- Die Pegelanzeige hat eine Textalternative („Pegel normal“/„still seit …“).

## 6. Stufe 2: Opencast

- Lesender Zugriff auf Opencast über die External API mit einem eigenen
  API-Konto. Es braucht nur Leserechte: Capture Agents sowie geplante und
  laufende Events. Die genauen Rollen und Endpunkte bestimmt der Builder.
  Zugangsdaten per Env.
- Der Monitor synchronisiert regelmäßig:
  - **Capture Agents** → Rekorderliste. Neue Agents erscheinen automatisch
    (als „neu, prüfen“ markiert, *meine Wahl*: direkt aktiv).
  - **Termine** des aktuellen Tages, plus Vorlauf für „Heute noch geplant“ und
    für den Kalender: Start, Ende, Titel, Serie, Capture Agent.
- **Zuordnung Rekorder ↔ Stream:** Standard ist Stream-Name = Capture-Agent-Name
  (bei der Uni Osnabrück 1:1). Pro Rekorder lässt sich ein abweichender
  Stream-Name eintragen.
- Opencast-Status des Agents (idle/capturing/offline) wird angezeigt, wo
  hilfreich. Er ist aber nicht die Wahrheit über den Stream. Die Wahrheit ist
  die Live-Erkennung.

### 6a Nachträge 2026-11-02

Nachträge aus dem ersten Betrieb mit Opencast.

- **Abgleich auf Knopfdruck:** unter Verwaltung → Rekorder und im Fehlerbanner.
  Er ist nur lesend.
- **Verständliche Meldung bei Problemen mit Opencast.** Kategorien:
  - nicht erreichbar,
  - Anmeldung abgelehnt,
  - keine Berechtigung,
  - Zeitüberschreitung,
  - Serverfehler,
  - unerwartete Antwort,
  - Hinweis „keine Termine sichtbar“.
  Meldungen nennen nie Zugangsdaten, URLs oder Hostnamen.
- **Deaktivierte Rekorder endgültig löschen.** Die Termine des Rekorders werden
  mitgelöscht. Opencast-Rekorder kommen dann auf eine Ignorierliste, die sich
  rückgängig machen lässt.
- **Logo:** Rekorder aus Opencast tragen das Opencast-Logo (ECL-2.0, Quelle
  `opencast/opencast`, Datei `opencast-icon.svg`).
- **Rechte des API-Kontos:** Ohne Leserecht auf die Events bleibt die Terminliste
  leer. Übergangsweise gilt `ROLE_ADMIN`; eine engere Rolle ist offen (siehe 10).

### 6b Letzte Aufzeichnung

Hinweis „Letzte Aufzeichnung hatte Probleme“: Er bezieht sich immer auf den
zuletzt beendeten Termin des Raums innerhalb von `OPENCAST_LOOKBACK_DAYS`
(Standard 7). Nach der nächsten sauberen Aufzeichnung verschwindet er.

- **Zwei Quellen:**
  - ansehBARs eigener Monitor: Lücken im Stream, nur während eines Termins und
    nach der Karenzzeit. „Status unbekannt“ zählt nie als Lücke.
  - Opencast: der Status des Events (Aufnahme und Verarbeitung).
- **Problemarten:**
  - „Stream fehlte HH:MM–HH:MM (N min)“ (eigener Monitor),
  - „Verarbeitung in Opencast fehlgeschlagen“ (`PROCESSING_FAILURE`),
  - „Aufzeichnung auf dem Rekorder fehlgeschlagen“ (`RECORDING_FAILURE`),
  - „Aufzeichnung wurde nicht gestartet“ (30 Minuten nach dem Ende noch
    `SCHEDULED`),
  - „Aufzeichnung wurde nicht abgeschlossen“ (30 Minuten nach dem Ende noch
    `RECORDING` oder `INGESTING`).
  Laufende Verarbeitung ist kein Problem.
- **Zuordnung:** Verarbeitete Events, die ihre Planungsdaten verloren haben,
  bleiben über Opencasts Ort plus Start und Dauer dem Raum zugeordnet.
- **Darstellung:** gelber Kasten in der Raumansicht; kompakte Zeile bzw.
  ⚠-Marker in Kachel, Smartphone-Liste und Pillen.
- **Vorfälle:** Stream-Lücken werden als Vorfälle gespeichert. Das ist der
  Anfang des Protokolls aus 7.5. Die Alarme bleiben Stufe 3.

## 7. Stufe 3: Vorfälle, Alarme, Protokoll

### 7.1 Begriffe

- **Termin:** ein Opencast-Event mit Rekorder, Start und Ende.
- **Vorfall:** etwas Auffälliges während eines Termins.
  - Typ `stream_missing`: Der Stream fehlt zu Beginn oder bricht ab.
  - Typ `audio_silent`: Der Ton fehlt.
  - Ein Vorfall hat Beginn und Ende. Er wird immer protokolliert, egal ob ein
    Alarm rausgeht.
  - Stream-Lücken werden schon in Stufe 2 als Vorfälle gespeichert (siehe 6b).

### 7.2 Alarm „Stream fehlt“

- **Alarmmodus pro Raum einstellbar:**
  - `exact` (Standard): Alarm, wenn der Stream zum Opencast-Start plus
    technischem Puffer (Standard 3 min, *meine Wahl*, global einstellbar)
    nicht da ist.
  - `grid`: Alarm frühestens zum Rasterbeginn plus c.t. plus Toleranz (siehe
    unten). Für Einrichtungen, die anders buchen oder starten.
  - `off`: nur Protokoll.
  - Später denkbar: `confirm`, wenn die Mediensteuerung eine
    „Aufzeichnung bestätigen“-Funktion bekommt. Nicht bauen, aber den Modus
    nicht verbauen.
- **Raster** (global in den Einstellungen):
  - Länge (Standard 120 min), Startzeitpunkte (Standard gerade Stunden),
    c.t.-Versatz (Standard 15 min), Toleranz nach c.t. (Standard 5 min,
    *meine Wahl*).
  - Ein Termin, dessen Opencast-Start schon auf oder nach c.t. liegt, wird
    nicht zusätzlich verschoben. Maßgeblich ist der spätere Zeitpunkt aus
    „Opencast-Start + Puffer“ und „Raster-c.t. + Toleranz“.
- **Ende:** Endet der Stream innerhalb einer Toleranz vor dem geplanten Ende
  (Standard 5 min, *meine Wahl*), ist das kein Vorfall.
- **Wiederholung:** Pro Termin geht beim ersten Ausfall ein Alarm raus. Kommt
  der Stream wieder (stabil, Standard ≥ 1 min, *meine Wahl*) und bricht
  erneut ab, geht **ein weiterer Alarm** raus.
- **Entwarnung:** Wenn der Stream wiederkommt, geht eine Entwarnung an
  dieselben Kanäle.
- Kurzes Flackern (unter dem Live-Schwellwert) ist kein Ausfall.

### 7.3 Alarm „Ton fehlt“

- Der Monitor misst während laufender Termine den Pegel im Backend. *Meine
  Wahl:* ffmpeg liest nur die Audiospur des HLS-Streams und gibt Pegelwerte
  (z. B. `ebur128`/`astats`) aus, die zu Werten pro Sekunde bzw. Minute
  verdichtet werden.
- Bandbreite (*meine Wahl*):
  - HLS-Segmente enthalten Video und Audio. Jede Messung lädt deshalb den
    ganzen Stream, ca. 2–4 Mbit/s.
  - Gemessen wird nur, solange ein Termin läuft. Bei euch sind es selten mehr
    als etwa 10 Räume gleichzeitig, also im Campusnetz unkritisch.
  - Die Zahl paralleler Messungen ist begrenzt (einstellbar). Darüber hinaus
    rotiert die Messung zwischen den Räumen. Bei einer Rotation verlängert sich
    die Zeit bis zu einer „sicheren“ Stille-Erkennung entsprechend.
- **Still** heißt: Pegel unter einer Schwelle (einstellbar; der Startwert wird
  in Stufe 3 an echten Streams kalibriert).
- **Alarm nur, wenn es sehr sicher ist:** durchgehend still länger als
  15 min (einstellbar; bewusst länger als „Stumm für 10 Minuten“).
- **Nur der erste Ton-Ausfall pro Termin löst einen Alarm aus.** Kommt der Ton
  wieder und fällt erneut aus, entsteht nur ein Protokolleintrag.
- Kürzere Stillephasen (Pausen, Stillarbeit) werden protokolliert, wenn sie
  über einer Mindestdauer liegen (Standard 2 min, *meine Wahl*), und in der
  Zeitleiste der Raumansicht gezeigt.

### 7.4 Kanäle

- Die Zustellung ist eine kleine Kanal-Schnittstelle. Jeder Kanal ist in den
  Einstellungen an- und abschaltbar.
- **E-Mail (Pflicht in Stufe 3)** an die Alarm-Empfänger, über Django-Mail
  mit SMTP-Konfiguration per Env.
- **Monitoring-Dienst (in Stufe 3).** Keine eigene Matrix-Anbindung: Die
  Kollegen wollen keine direkten Matrix-Nachrichten aus ansehBAR. Es gibt einen
  bestehenden Monitoring-Dienst (Prometheus + Alertmanager mit vorhandener
  Matrix-Weiterleitung). ansehBAR bietet wie abstimmBAR und ausleihBAR einen
  tokengeschützten `/metrics`-Endpunkt im Prometheus-Textformat an
  (Bearer-Token `METRICS_TOKEN`, außerhalb von `/api/`). Alarmregeln (mit
  `for:`-Verzögerung) liegen in Prometheus, nicht in ansehBAR. Der Kanal wird
  so gebaut, dass er sich ohne Umbau der Vorfall-Logik anpassen lässt.
- **Festgelegt (Rückfragen 2026-11-03):**
  - Endpunkt, Token und Scrape exakt wie bei abstimmBAR (dort von Timo schon
    angebunden): `GET /metrics` außerhalb von `/api/`, Bearer `METRICS_TOKEN`,
    ohne Token `404`, `text/plain; version=0.0.4`; Prometheus fragt über
    HTTPS die öffentliche URL ab, Token per `credentials_file`. Das
    Reverse-Proxy-Setup muss `/metrics` an die App weiterreichen. Doku analog
    zu abstimmBARs `docs/monitoring.md`.
  - Scrape-Intervall 1 min.
  - Namen und Labels wie bei abstimmBAR: Präfix `ansehbar_`, Gauges; pro Raum
    Labels `room` und `stream` (etwa 40 Räume, Kardinalität unkritisch).
  - Die Alarmregeln pflegen wir selbst: als Datei im Repo (z. B.
    `monitoring/alerts.yml`), die wir den Betreibern zusammen mit dem
    Scrape-Eintrag schicken; sie spielen sie ein.
  - Schweregrade über das Label `severity` mit den Werten `critical` (Stream
    fehlt während eines Termins) und `warning` (Opencast-Abgleich gestört,
    Monitor liefert keine Daten, Ton fehlt länger als 15 min).
  - Der Monitoring-Dienst verschickt **keine Entwarnungen** (resolved), um die
    Zahl der Nachrichten klein zu halten. Entwarnungen aus 7.2 gibt es daher
    nur per E-Mail.
  - Alarme nur während geplanter Termine; außerhalb ist „kein Stream“ normal.
  - Großzügige `for:`-Dauern sind in Ordnung: Niemand kann sofort eingreifen,
    meist geht es darum, Probleme in Folgeveranstaltungen zu vermeiden.
  - ansehBAR bekommt einen **eigenen Matrix-Raum** (nicht Warning/Critical
    des virtUOS-Space).
  - Inhibition (übergeordneter Alarm statt einer Meldung pro Raum, wenn der
    Streaming-Server ganz weg ist) vorerst weglassen; die Gruppierung im
    Alertmanager fasst gleichartige Alarme ohnehin zusammen.
  - Kein eigener Heartbeat für Container/Host nötig (`up` reicht).
  - Produktiv läuft ansehBAR auf einer eigenen VM.
- **Später:** Browser-Benachrichtigungen (Web Push), allgemeine Webhooks.
- **Inhalt einer Meldung** (alles, was man zum Weiterleiten braucht): Raum,
  Rekorder, Typ, Termin (Titel, Serie, geplante Zeit), seit wann, Link zur
  Raumansicht in ansehBAR.
- **Zustellung idempotent:** Eine Meldung pro Vorfall-Ereignis und Kanal, auch
  wenn der Monitor neu startet. Das Vorbild ist kalkulierBAR mit
  `SentNotification.key`.

### 7.5 Protokoll und Kalender pro Raum

- Raumkalender (Woche/Tag) mit den Opencast-Terminen und den Vorfällen darauf
  (Stream fehlt, Ton still, Alarm gesendet, Entwarnung).
- Später soll sich abgleichen lassen, welche Aufzeichnungen fehlen oder
  lückenhaft sein dürften.
- Messwerte: Rohdaten (Pegel pro Sekunde) nur kurz aufbewahren. Verdichtete
  Werte pro Minute, Vorfälle und Termin-Zusammenfassungen länger. Die Fristen
  sind einstellbar; die Standards setzt der Builder, Vorfälle mindestens ein
  Semester.

## 8. Stufe 4: Pünktlichkeit lernen (nicht bauen, nur vorbereiten)

- Ab Stufe 3 wird pro Termin festgehalten, wann **zum ersten Mal Ton im Raum**
  war (erste Minute über der Schwelle nach Start), verknüpft mit der
  Opencast-Serie.
- Später können daraus pro Serie oder Dozent typische Startzeiten gelernt
  werden, um Ton-Alarme zu Beginn eines Termins treffsicherer zu machen.

## 9. Stufen

1. **Monitor mit fester Liste.**
   - Gerüst aus basicbar, Zugang (Gruppe und Einladungen), Rekorderpflege mit
     Import der alten Liste.
   - PC-Übersicht (läuft/ruhig) und Smartphone-Raumansicht.
   - Ton pro Kachel, Pegel im Browser.
   - Monitor-Prozess mit Live-Erkennung.
   - Damit ist der alte Monitor ersetzbar.
2. **Opencast.** Capture Agents und Termine, „Stream fehlt“ in der Oberfläche,
   „Heute noch geplant“, Zuordnung Agent ↔ Stream.
3. **Vorfälle und Alarme.** Vorfall-Logik, Backend-Pegelmessung, Kanäle
   E-Mail und Monitoring-Dienst, Empfänger, Raster-Einstellungen, Raumkalender.
4. **Pünktlichkeit lernen.**

Jede Stufe ist für sich nutzbar und wird einzeln geplant und gebaut.

## 10. Offen

- **Anbindung an den Monitoring-Dienst** (7.4): geklärt am 2026-11-03.
  Beim Einreichen der Regeldatei mit den Betreibern abstimmen, wie Alarme von
  ansehBAR in den eigenen Matrix-Raum geroutet werden (Receiver/Matcher in
  deren Alertmanager-Konfiguration).
- Engere Opencast-Rolle für das ansehBAR-Konto (Kollegen klären).

## 11. Dem Builder überlassen

- Datenmodell im Detail, API-Form, Polling-Intervalle innerhalb der genannten
  Größenordnung.
- Genaue Opencast-Endpunkte und Rollen, genaue Live-Erkennung.
- Wahl des Pegelmaßes und die Kalibrierung der Schwelle.
- Komponentenstruktur im Frontend, Player-Lebenszyklus bei vielen Kacheln.
- Aufbewahrungsfristen-Standards (Rahmen siehe 7.5).
