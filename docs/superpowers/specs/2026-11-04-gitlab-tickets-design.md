# GitLab-Tickets aus der Übersicht — Design

Stand: 2026-11-04 · Ergänzung zu `2026-10-30-ansehbar-design.md`

## Absicht

Wer in der Übersicht eine Störung an einem Rekorder sieht (z. B. ein
gestörtes Bild), soll mit wenigen Klicks ein GitLab-Ticket für die
Medientechnik anlegen können. Die Medientechnik muss danach vor Ort handeln
(z. B. Kabel prüfen) und braucht dafür im Ticket alles, was ansehBAR in
diesem Moment weiß: Raum, Rekorder, laufender Opencast-Termin, Status und ein
Bild der Vorschau. Vorbild ist die Defekt-Ticket-Anbindung von ausleihBAR
(`backend/lending/gitlab_service.py` dort).

## Ziele

- Kleiner Button an **jeder Kachel der Übersicht** (`RecorderTile`), sichtbar
  für alle mit Zugang zu ansehBAR (faktisch Admins).
- Klick öffnet einen Dialog: Freitextfeld „Fehlermeldung“ (Pflicht),
  Vorschau des Screenshots, Absenden. Danach zeigt der Dialog einmal den Link
  auf das neue Ticket.
- Das Ticket enthält:
  - **Titel:** `<Raum> (<Stream-Name>): <Fehlermeldung, gekürzt>`,
    z. B. „Hörsaal A (cap-hs-a): Bild gestört“; insgesamt höchstens 255 Zeichen.
  - **Beschreibung (Markdown):**
    - die Fehlermeldung;
    - Raum, Stream-Name, Capture-Agent-ID;
    - Zeitpunkt der Meldung (Europe/Berlin);
    - ansehBAR-Status: live/offline, live seit (`RecorderStatus.live_since`),
      offline seit, Ton/Stille seit, Pegel, Agent-Status aus Opencast;
    - der aktuell laufende Opencast-Termin, falls vorhanden: Titel, Serie,
      Vortragende (Presenter), geplante Zeit, Opencast-Status;
    - „aufgezeichnet seit“ = `live_since`, wenn der Stream live ist;
    - Ersteller (Name/E-Mail des angemeldeten Users);
    - Link auf die Raumansicht in ansehBAR.
  - **Screenshot** des aktuellen Vorschaubilds, eingebettet im Ticket.
- Konfiguration in **Verwaltung → Einstellungen**: GitLab-Projekt-URL und
  Access-Token, wie in ausleihBAR (Token write-only, verschlüsselt
  gespeichert, Hinweis auf Project Access Token mit Rolle „Reporter“ und
  Scope `api`). Ist nichts konfiguriert, erscheint kein Button.

## Nicht-Ziele

- Keine Speicherung des Tickets in ansehBAR, keine Anzeige offener Tickets,
  keine Dubletten-Erkennung.
- Keine Labels, keine Zuweisung, kein Fälligkeitsdatum.
- Kein Button in der Raumansicht oder im Kalender (später möglich).
- Kein automatisches Ticket durch den Monitor/Alarme.

## Anti-Ziele

- Das GitLab-Token darf nie an den Browser zurückgehen, nie im Log stehen
  und nie an einen anderen Host als den konfigurierten gesendet werden
  (keine Redirects folgen, wie ausleihBAR).
- Ein Fehler beim Screenshot darf das Ticket nicht verhindern; ein
  GitLab-Fehler muss im Dialog verständlich gemeldet werden (nicht still).
- Weiterhin keine Schreibzugriffe auf Opencast oder Keycloak.
- Keine Infrastrukturdaten im Repo (Beispiel-URLs nur `gitlab.example.com`).

## Entscheidungen

Vom Nutzer entschieden:
- Button an der Kachel der Übersicht; alle mit Zugang dürfen ihn benutzen.
- Inhalt wie oben, ohne Labels; nach dem Erstellen genügt der Link.
- Vortragende kommen aus Opencast (Presenter des Termins).

Meine Festlegungen (für den Builder bindend, aber beim Review prüfen):
- **Ein** GitLab-Projekt für die ganze Instanz (ansehBAR hat keine Pools).
  Felder `gitlab_url` und `gitlab_token` am bestehenden Singleton
  `MonitorSettings`; Token verschlüsselt mit Fernet (`cryptography`), Schlüssel
  aus `TOKEN_ENCRYPTION_KEY`, sonst aus `SECRET_KEY` abgeleitet — wie
  ausleihBAR `catalog/encryption.py`. `TOKEN_ENCRYPTION_KEY` kommt in
  `.env.prod.example`, `docker-compose.prod.yml` und die Doku.
- **Presenter:** neues Feld `ScheduledEvent.presenters` (Text, Namen mit
  „, “ verbunden), befüllt beim Opencast-Sync aus dem Event-Feld `presenter`
  (Liste von Strings). Wird nur gelesen, Opencast bleibt unverändert.
- **Ablauf:** Der Browser macht den Screenshot und schickt ihn mit der
  Meldung an `POST /api/recorders/<id>/ticket/` (multipart: `message`,
  optional `screenshot` als PNG/JPEG, max. 5 MB). Das Backend sammelt die
  Daten serverseitig (nicht vom Client übernommen), lädt den Screenshot über
  `POST /api/v4/projects/<projekt>/uploads` hoch, bettet das zurückgegebene
  Markdown ein und legt das Issue mit `POST /api/v4/projects/<projekt>/issues`
  an. Antwort: `{ "web_url": … }` (nur wenn auf dem konfigurierten Host).
  Schlägt der Upload fehl, wird das Ticket ohne Bild mit einem Hinweis
  angelegt. GitLab-Fehler → HTTP 502 mit verständlicher Meldung.
  stdlib `urllib` wie ausleihBAR, kein neues HTTP-Paket.
- **Screenshot:** Canvas `drawImage` aus dem `<video>` der Kachel, im Moment
  des Klicks auf den Button (das ist das Bild mit der Störung), als JPEG
  (Qualität ~0,9). Damit der Canvas im nativen HLS-Pfad (Safari) nicht
  „tainted“ ist, bekommt das `<video>` `crossOrigin="anonymous"`; der
  Streaming-Server gibt CORS schon frei. Gelingt die Aufnahme nicht (kein
  Bild, Canvas gesperrt), zeigt der Dialog „Kein Screenshot möglich“ und
  sendet ohne.
- **Sprache des Tickets:** die Sprache der Anfrage (gettext,
  `Accept-Language`), wie alle Backend-Texte.
- **Konfiguration prüfen:** Ein Button „Verbindung testen“ ist nicht Teil
  dieser Stufe; die Einstellungsseite zeigt nur „Token gesetzt“.
- **Sichtbarkeit des Buttons:** Die Recorder-API bzw. ein Settings-Endpunkt
  liefert `tickets_enabled: bool` (URL und Token gesetzt).
- **Kachel-Button:** kleines Symbol mit Tooltip/aria-label „Ticket
  erstellen“, nur wenn `tickets_enabled`; neben den vorhandenen Buttons der
  Kachel; Dialog als Variante des vorhandenen Dialog-Musters (kein
  `window.prompt`).

## Rahmen

- Django-App: Code in `recorders/` (`tickets.py` für den GitLab-Client und
  die Ticket-Zusammenstellung), View-Action am `RecorderViewSet`.
- Tests: GitLab-Aufrufe gemockt (Payload, kein Redirect, URL-Prüfung,
  Upload-Fehler → Ticket ohne Bild, Token nie in der Antwort);
  Settings-Serializer (Token write-only); Sync übernimmt Presenter;
  Frontend: Dialog (Pflichtfeld, Erfolg mit Link, Fehlermeldung).
- Doku: `docs/KONFIGURATION.md` (GitLab-Abschnitt), Website-Anleitung
  (Übersicht + Einstellungen, DE/EN), ggf. Screenshot des Dialogs.
- i18n: neue Texte Englisch als Key, Deutsch in den Übersetzungen;
  Backend-Texte in `django.po`.

### Nach dem Builder-Check ergänzt (meine Festlegungen)

- **Rechte:** Ticket-Endpunkt und Einstellungen bleiben bei `HasAccess` wie
  der Rest der Einstellungen. Gegen Token-Abfluss gilt: Wer die GitLab-URL
  ändert, muss im selben Speichervorgang ein neues Token angeben, sonst wird
  das gespeicherte Token gelöscht (ein geändertes Ziel bekommt nie das alte
  Token). Leere URL schaltet die Funktion ab.
- **URL-Format:** vollständige Projekt-URL wie in ausleihBAR,
  `https://gitlab.example.com/gruppe/untergruppe/projekt` (Subgruppen
  erlaubt, angehängtes `/-/…` wird abgeschnitten). Projektpfad wird für
  `/api/v4/projects/<id>` URL-kodiert. Nur `https`; `http` nur bei
  `DEBUG=1` (lokale Tests).
- **Link zur Raumansicht:** aus dem vorhandenen Setting `FRONTEND_BASE_URL`
  (in Produktion = `PUBLIC_BASE_URL`): `<FRONTEND_BASE_URL>/raum/<id>`.
- **CORS:** hls.js lädt Playlists und Segmente schon heute per XHR, der
  Streaming-Server muss also bereits für alle Dateien CORS senden
  (`docs/KONFIGURATION.md` §1). `crossOrigin="anonymous"` am `<video>`
  (vor dem Setzen von `src`) ändert daher für den hls.js-Pfad nichts und
  macht den nativen Pfad screenshotfähig. Gilt für beide Pfade.
- **Kachel ohne Video** (offline, kein Stream, inaktiv): Ticket ohne
  Screenshot; der Dialog sagt das. Die Aufnahme ist ein einzelnes Bild im
  Moment des Button-Klicks und bleibt im Dialog-Zustand.
- **Presenter:** Das Feld `presenter` (Liste) ist Teil der normalen
  Antwort von `/api/events/`; kein Zusatzparameter. Bestehende Termine
  bekommen den Wert beim nächsten Abgleich (Upsert), kein Extra-Lauf.
- **Upload-Prüfung:** nur `image/jpeg` oder `image/png`, geprüft über die
  Magic Bytes, max. 5 MB; sonst 400. Kein eigenes Rate-Limit (Nutzerkreis
  sind Admins).
- **Datenschutz:** Der Screenshot kann Personen im Hörsaal zeigen und liegt
  danach in GitLab. Die Doku empfiehlt ein privates GitLab-Projekt mit
  kleinem Personenkreis.

## Dem Builder überlassen

Icon-Wahl, genaue Formulierung der Ticket-Abschnitte, Aufteilung der
Frontend-Komponenten, Kürzungsregel für den Titel, Markdown-Formatierung.
