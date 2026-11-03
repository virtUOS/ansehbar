# ansehBAR einrichten und konfigurieren

Diese Anleitung beschreibt, wie ein Standort ansehBAR mit seiner eigenen
Infrastruktur in Betrieb nimmt. Das Repository enthält bewusst keine
Angaben zu einer konkreten Einrichtung: Streaming-Server, Rekorder,
Räume, Anmeldedienst und Domain bringt jeder Standort selbst mit.

Für die lokale Entwicklung reicht `docker compose up -d` (siehe
[README](../README.md#entwicklung)). Diese Anleitung behandelt den
Produktivbetrieb.

## Überblick: Was ein Standort braucht

| Baustein | Wozu | Wo konfiguriert |
| --- | --- | --- |
| Server mit Docker und Docker Compose | Betrieb von App, Monitor, Datenbank und Reverse Proxy | – |
| Domain mit DNS-Eintrag auf den Server, Ports 80/443 | Erreichbarkeit und TLS | `.env`, `Caddyfile` |
| OIDC-Anbieter (z. B. Keycloak) mit einer Gruppe | Anmeldung und Zugangsberechtigung | `.env`, beim Anbieter |
| HLS-Streaming-Server | Live-Streams der Rekorder | Standortkonfiguration |
| Liste der Rekorder | Welche Streams überwacht werden | Standortkonfiguration |

Dabei gibt es drei Orte für Einstellungen:

1. **`.env`** auf dem Server: Secrets, Domain, OIDC, Zugang. Nicht eingecheckt.
2. **Standortkonfiguration** (`site.local.json`): Stream-URL-Vorlage und
   Rekorderliste. Nicht eingecheckt, wird einmalig oder bei Änderungen
   in die Datenbank geladen.
3. **Verwaltung im Frontend**: laufende Pflege von Rekordern,
   Einladungen und Monitor-Einstellungen. Liegt in der Datenbank.

## 1. Voraussetzungen am Streaming-Server

ansehBAR bindet jeden Rekorder über eine URL-Vorlage ein, in die der
Stream-Name eingesetzt wird, z. B.

```
https://streaming.example.org/live/{stream}/playlist.m3u8
```

Der Streaming-Server muss Folgendes erfüllen:

- **HLS:** Unter der URL liegt eine HLS-Playlist, entweder eine
  Master-Playlist mit Varianten oder direkt eine Media-Playlist.
- **Media-Sequence:** Die Media-Playlist enthält `#EXT-X-MEDIA-SEQUENCE`,
  und die Zahl steigt, solange der Stream läuft. Daran erkennt der Monitor,
  dass ein Stream wirklich live ist und nicht nur eine eingefrorene
  Playlist ausliefert.
- **Offline = 404:** Sendet ein Rekorder nicht, antwortet der Server mit
  HTTP 404 (oder 410).
- **HTTPS:** Die Vorlage muss mit `https://` beginnen. Weiterleitungen von
  HTTPS auf HTTP werden nicht befolgt.
- **CORS:** Der Browser lädt die Streams direkt vom Streaming-Server, nicht
  über ansehBAR. Der Server muss deshalb CORS-Header senden, mindestens
  `Access-Control-Allow-Origin` mit der ansehBAR-Domain oder `*`.
- **Erreichbarkeit:** Der Server muss vom ansehBAR-Server aus erreichbar sein
  (Monitor) und von den Geräten der Nutzenden (Browser).

Schnelltest von der Kommandozeile, während ein Rekorder sendet:

```bash
# Antwortet mit 200 und Playlist? Steht ein CORS-Header in der Antwort?
curl -si -H "Origin: https://ansehbar.example.org" \
  https://streaming.example.org/live/<stream>/playlist.m3u8 | head -20
```

Danach die Chunklist aus der Antwort zweimal im Abstand von einigen
Sekunden abrufen: `#EXT-X-MEDIA-SEQUENCE` muss sich erhöhen.

## 2. Anmeldung (OIDC) einrichten

ansehBAR meldet Nutzende über OpenID Connect an und **schreibt nie** etwas
beim Anbieter. Am Beispiel Keycloak:

1. **Client anlegen:** Client-ID z. B. `ansehbar`, Typ *confidential*
   (Client-Authentifizierung an), Standard-Flow (Authorization Code) an.
2. **URLs eintragen** (mit `<host>` = eure ansehBAR-Domain):
   - Valid Redirect URI: `https://<host>/oidc/callback/`
   - Valid Post Logout Redirect URI: `https://<host>/`
   - Web Origin: `https://<host>`
   - Back-Channel Logout URL: `https://<host>/oidc/backchannel-logout/`
     (Abmelden in Keycloak beendet dann auch die ansehBAR-Sitzung)
3. **Gruppe anlegen**, z. B. `ansehbar-users`, und die berechtigten
   Personen aufnehmen.
4. **Gruppen-Claim mitschicken:** einen Mapper vom Typ *Group Membership*
   mit Claim-Name `groups` anlegen. „Full group path“ aus, damit der
   Gruppenname ohne führenden `/` ankommt. Der Mapper muss für den
   **Userinfo**-Endpunkt aktiv sein, denn ansehBAR liest die Claims von dort.
5. **Client-Secret** kopieren, es kommt in die `.env`.

Andere OIDC-Anbieter funktionieren genauso, solange sie einen
Gruppen-Claim liefern. Weichen die Claim-Namen ab, lassen sie sich in der
`.env` umstellen (`OIDC_GROUPS_CLAIM`, `OIDC_CLAIM_USERNAME` usw.).

### Wer Zugang hat

Zugang hat, wer mindestens eine dieser Bedingungen erfüllt:

- Mitglied der Gruppe aus `ANSEHBAR_ACCESS_GROUP` ist (Standard
  `ansehbar-users`);
- in `ANSEHBAR_BOOTSTRAP_USERS` steht (Benutzername oder E-Mail,
  kommagetrennt), gedacht für die erste Einrichtung und als Notzugang;
- in ansehBAR unter „Verwaltung → Einladungen“ eingeladen wurde.

Alle mit Zugang haben dieselben Rechte. Wer sich anmeldet, aber keinen Zugang
hat, sieht die Seite „Kein Zugang“ mit dem Kontakt aus
`ANSEHBAR_ACCESS_CONTACT`.

Gruppenmitgliedschaften werden beim Login übernommen. Wird jemand aus der
Gruppe entfernt, gilt das ab der nächsten Anmeldung. Für ein sofortiges Ende
die Person beim OIDC-Anbieter abmelden; der Back-Channel-Logout beendet dann
auch die ansehBAR-Sitzung. Entfernte Einladungen wirken sofort.

## 3. Server einrichten

```bash
git clone <repository-url> ansehbar
cd ansehbar
cp .env.prod.example .env
```

### `.env` ausfüllen

Pflichtangaben (ohne sie startet `docker compose` nicht):

| Variable | Inhalt |
| --- | --- |
| `PUBLIC_BASE_URL` | Öffentliche Adresse, z. B. `https://ansehbar.example.org` (ohne `/` am Ende) |
| `DJANGO_SECRET_KEY` | Langer Zufallswert, z. B. aus `openssl rand -base64 48` |
| `DJANGO_ALLOWED_HOSTS` | Domain, z. B. `ansehbar.example.org` |
| `CSRF_TRUSTED_ORIGINS` | `https://` + Domain |
| `POSTGRES_PASSWORD` | Starkes Datenbankpasswort |
| `OIDC_RP_CLIENT_ID` | Client-ID aus Schritt 2 |
| `OIDC_RP_CLIENT_SECRET` | Client-Secret aus Schritt 2 |
| `OIDC_OP_ISSUER` | Issuer-URL, bei Keycloak `https://<keycloak>/realms/<realm>`; die Endpunkte werden daraus automatisch ermittelt |

ansehBAR-spezifisch:

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `ANSEHBAR_ACCESS_GROUP` | Gruppe mit Zugang | `ansehbar-users` |
| `ANSEHBAR_BOOTSTRAP_USERS` | Benutzernamen/E-Mails mit Zugang ohne Gruppe | leer |
| `ANSEHBAR_ACCESS_CONTACT` | Kontakt auf der Seite „Kein Zugang“ | leer |
| `MONITOR_INTERVAL_SECONDS` | Sekunden zwischen zwei Prüfläufen | `10` |
| `ANSEHBAR_SITE_CONFIG` | Pfad der Standortkonfiguration im Container | `/app/site.local.json` |

Die übrigen Variablen in `.env.prod.example` (KI-Funktionen,
LibreTranslate, Django-Admin-Gruppe) sind optional und für ansehBAR derzeit
nicht nötig.

### `Caddyfile` anpassen

`ansehbar.example.org` durch eure Domain ersetzen und unter `email` eine
echte Kontaktadresse für Let's Encrypt eintragen. Caddy holt und erneuert
das Zertifikat dann selbst. Für eigene Zertifikate der Einrichtung zeigt der
Kommentar im `Caddyfile`, wie sie eingebunden werden.

### Starten

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Es starten vier Container: `db` (PostgreSQL), `app` (Web und API, migriert
die Datenbank beim Start), `monitor` (prüft die Streams) und `caddy`
(HTTPS). Kontrolle:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f monitor
```

## 4. Standortkonfiguration laden

Die Standortkonfiguration ist eine JSON-Datei mit der Stream-URL-Vorlage und
der Rekorderliste. Vorlage: [`backend/site.example.json`](../backend/site.example.json).

```json
{
  "stream_url_template": "https://streaming.example.org/live/{stream}/playlist.m3u8",
  "recorders": [
    {"stream_name": "rec-10-r01", "room_name": "10/R01"},
    {"stream_name": "rec-20-hall", "room_name": "20/R06 (Hall)", "active": false}
  ]
}
```

| Feld | Pflicht | Bedeutung |
| --- | --- | --- |
| `stream_url_template` | nein | URL-Vorlage mit genau einem `{stream}`, muss mit `https://` beginnen |
| `recorders[].stream_name` | ja | Name des Streams auf dem Streaming-Server, eindeutig und **case-sensitiv**. Erlaubt sind Buchstaben, Ziffern, `.`, `_` und `-`; das erste Zeichen muss ein Buchstabe oder eine Ziffer sein |
| `recorders[].room_name` | ja | Anzeigename, so wie die Leute den Raum nennen |
| `recorders[].active` | nein | `false` legt den Rekorder deaktiviert an; Standard `true` |

Die Datei als `site.local.json` anlegen. Dateien mit der Endung
`.local.json` ignoriert Git, sie landen also nicht versehentlich im
Repository. Dann laden, im Produktivbetrieb über die Standardeingabe, damit
keine zusätzliche Datei in den Container gemountet werden muss:

```bash
# Erst prüfen, was sich ändern würde:
docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py load_site_config --path - --dry-run < site.local.json

# Dann übernehmen:
docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py load_site_config --path - < site.local.json
```

In der Entwicklung liegt die Datei unter `backend/site.local.json` und wird
ohne weitere Angaben gefunden:

```bash
docker compose exec backend python manage.py load_site_config
```

So verhält sich das Laden:

- **Erst prüfen, dann schreiben:** Die ganze Datei wird geprüft, bevor
  etwas geschrieben wird. Bei Fehlern listet der Befehl alle Probleme auf und
  ändert nichts.
- **Abgleich über den Stream-Namen:** Rekorder werden anhand des
  Stream-Namens angelegt oder aktualisiert (Raumname, Aktiv-Status).
  Gelöscht wird nie etwas.
- **`--deactivate-missing`:** deaktiviert zusätzlich alle Rekorder, die
  nicht in der Datei stehen.
- **Wiederholbar:** Mehrfaches Laden ist unschädlich; unveränderte Einträge
  werden als „unverändert“ gemeldet.
- **Vorrang der Datei:** Ein erneutes Laden überschreibt Raumname und
  Aktiv-Status der aufgeführten Rekorder sowie die URL-Vorlage, auch wenn sie
  zwischenzeitlich in der Verwaltung geändert wurden. Wer dauerhaft mit der
  Datei arbeitet, pflegt Änderungen am besten dort.

Ohne Standortkonfiguration startet ansehBAR mit leerer Rekorderliste und
der Beispiel-URL. Rekorder lassen sich dann auch direkt in der Verwaltung
anlegen.

## 5. Opencast anbinden (optional)

Mit Opencast kennt ansehBAR die geplanten Aufzeichnungen und kann zwischen
„kein Stream, weil nichts geplant ist“ und „Stream fehlt“ unterscheiden.
ansehBAR liest nur (External API, nur GET) und **schreibt nie** nach
Opencast. Ohne `OPENCAST_URL` bleibt die Anbindung aus, alles andere
funktioniert wie zuvor.

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `OPENCAST_URL` | Basisadresse von Opencast, z. B. `https://opencast.example.org`; leer = aus. Nur `https://`: bei `http://` (außer mit `DJANGO_DEBUG=1`) gleicht der Monitor nicht ab und meldet einen ERROR im Log, damit die Zugangsdaten nie unverschlüsselt übertragen werden | leer |
| `OPENCAST_USER` | Benutzer für die External API | leer |
| `OPENCAST_PASSWORD` | Passwort dieses Benutzers. Docker Compose wertet `$` in `.env`-Werten aus: ein `$` im Passwort als `$$` schreiben | leer |
| `OPENCAST_SYNC_SECONDS` | Sekunden zwischen zwei Abgleichen (der Monitor gleicht in einem eigenen Thread ab; ein langsames Opencast verzögert die Stream-Prüfung nicht) | `60` |
| `OPENCAST_LOOKAHEAD_DAYS` | Wie viele Tage Terminplan im Voraus gelesen werden | `7` |
| `OPENCAST_LOOKBACK_DAYS` | Wie viele Tage zurück nach der letzten Aufzeichnung eines Raums gesucht wird (Hinweis „Letzte Aufzeichnung hatte Probleme“, siehe unten) | `7` |


**Hinweis „Letzte Aufzeichnung hatte Probleme“:** Er bezieht sich immer auf den
zuletzt beendeten Termin des Raums innerhalb von `OPENCAST_LOOKBACK_DAYS` und
verschwindet nach der nächsten sauberen Aufzeichnung. Er erscheint als gelber
Kasten in der Raumansicht, in Kachel, Smartphone-Liste und Pillen als kompakte
Zeile bzw. ⚠-Marker. Quellen und Meldungen:

- ansehBARs eigener Monitor: „Stream fehlte HH:MM–HH:MM (N min)“, nur während
  eines Termins und nach der Karenzzeit; „Status unbekannt“ zählt nie.
- Opencast: „Verarbeitung in Opencast fehlgeschlagen“,
  „Aufzeichnung auf dem Rekorder fehlgeschlagen“.
- 30-Minuten-Regel: „Aufzeichnung wurde nicht gestartet“ (30 Minuten nach dem
  Ende noch geplant) und „Aufzeichnung wurde nicht abgeschlossen“ (30 Minuten
  nach dem Ende noch in Aufnahme oder Übernahme). Beides nur, wenn ein
  erfolgreicher Opencast-Abgleich nach diesen 30 Minuten den Status bestätigt
  hat. Laufende Verarbeitung ist kein Problem.

Nach Änderungen an der `.env` die Container neu erzeugen
(`docker compose -f docker-compose.prod.yml up -d`), denn ein bloßer Neustart
liest die Datei nicht neu ein.

### Konto in Opencast

Ein eigenes Konto nur mit Leserechten anlegen, mit den Rollen:

- `ROLE_API`
- `ROLE_API_CAPTURE_AGENTS_VIEW`
- `ROLE_API_EVENTS_VIEW`
- `ROLE_API_EVENTS_SCHEDULING_VIEW`

Außerdem muss das Konto die geplanten Events lesen dürfen. Das ist der
häufigste Stolperstein: Die External API filtert `/api/events` nach den
Event-ACLs. Fehlt dem Konto das Leserecht, antwortet die API zwar fehlerfrei,
die Terminliste ist aber leer oder zeigt nur wenige alte Termine.

- Eine Rolle des Kontos braucht Leserecht in den Event-ACLs, am einfachsten
  über die ACL-Vorlagen, mit denen die Termine angelegt werden.
- Rollen der Form `ROLE_CAPTURE_AGENT_<NAME>` helfen **nicht**: Sie stehen
  nicht in den Event-ACLs.
- Der Kalender der Capture Agents (`/recordings/calendars`) verlangt in der
  Standard-Sicherheitskonfiguration `ROLE_CAPTURE_AGENT` oder `ROLE_ADMIN`.
- Übergangsweise hat sich `ROLE_ADMIN` bewährt (ohne sie sah ein Konto nur
  vier alte Events). Das ist weitreichend; ansehBAR benutzt trotzdem nur
  lesende Aufrufe. Eine engere Rolle wird mit den Betreibern geklärt.

Ist die Rechtelage unklar, zeigt ansehBAR einen Hinweis: Sind Agents
bekannt, aber keine geplanten Termine sichtbar, steht im Banner „Opencast
zeigt keine geplanten Aufzeichnungen – Rechte des Kontos prüfen“.

Meldet Opencast eine HTML-Seite „Opencast :: Forbidden“, auch mit HTTP-Status
200, gilt das als „keine Berechtigung“ und nicht als gültige Antwort.

Prüfen von der Kommandozeile (Benutzer und Passwort werden abgefragt):

```bash
curl -u ansehbar https://<opencast>/api/agents
curl -u ansehbar "https://<opencast>/api/events?withscheduling=true"
```

Die erste Antwort muss die Capture Agents der Rekorder zeigen, die zweite
die geplanten Termine.

### Agent und Stream zuordnen

- **Standard:** Agent-ID und Stream-Name sind gleich (case-sensitiv).
- **Abweichender Name:** Die Agent-ID als `agent_id` beim Rekorder in der
  `site.local.json` eintragen oder unter **Verwaltung → Rekorder** pflegen.
- **Neue Agents:** Ein Agent ohne passenden Rekorder wird als Rekorder mit
  leerem Raumnamen angelegt und erscheint als „Neu – bitte prüfen“. Speichern
  im Bearbeiten-Formular der Verwaltung oder Deaktivieren markiert ihn als
  geprüft.
- **Doppelter Rekorder:** Heißt der Agent anders als der Stream des
  vorhandenen Rekorders, legt der Abgleich zunächst einen zweiten Rekorder
  (Stream-Name = Agent-ID) an. Dann zuerst beim automatisch angelegten
  Rekorder `agent_id` leeren und ihn deaktivieren, danach die Agent-ID beim
  richtigen Rekorder eintragen (eine Agent-ID kann nur an einem Rekorder
  stehen).

### Abgleich auf Knopfdruck

Unter **Verwaltung → Rekorder** löst „Opencast jetzt abgleichen“ sofort
einen Abgleich aus, im Fehlerbanner heißt der Knopf „Jetzt abgleichen“.
Er startet nur den lesenden Abgleich (ansehBAR schreibt nie nach Opencast),
zeigt „Abgleich läuft …“ und danach die Zeit des letzten Abgleichs. Fehler
erscheinen sofort im Banner, nicht erst nach drei Intervallen.

### Rekorder löschen und Agents ignorieren

- **Nur deaktivierte Rekorder** lassen sich löschen (Papierkorb-Knopf mit
  Bestätigung). Aktive Rekorder nicht: erst deaktivieren.
- Beim Löschen verschwinden auch Status und Termine des Rekorders.
- Stammt der Rekorder aus Opencast, kommt seine Agent-ID auf die Liste
  „Ignorierte Opencast-Agents“; der Abgleich legt ihn nicht wieder an.
  „Wieder zulassen“ nimmt sie von der Liste. Der Agent erscheint dann beim
  nächsten Abgleich als „Neu – bitte prüfen“.
- Rekorder aus Opencast tragen in der Oberfläche das Opencast-Logo.

Zum Ausprobieren eignet sich der öffentliche Opencast-Testserver; die
Demo-Zugangsdaten stehen auf seiner Startseite. Nur in die lokale `.env`
eintragen, nie ins Repository.

## 6. Erste Anmeldung und laufende Pflege

1. `https://<host>` öffnen und mit einem Konto anmelden, das in der Gruppe
   oder in `ANSEHBAR_BOOTSTRAP_USERS` steht.
2. Unter **Verwaltung → Rekorder** prüfen, ob die Liste stimmt. Neue
   Rekorder lassen sich hier anlegen, bestehende bearbeiten oder
   deaktivieren.
3. Unter **Verwaltung → Einstellungen** stehen die Stream-URL-Vorlage (mit
   Vorschau) und die „Toleranz bis „Stream beendet““. Ein Stream gilt als live, solange
   sich seine Media-Sequence innerhalb von *Toleranz × Segmentdauer* ändert;
   Standard 3, erlaubt 2 bis 10.
   Außerdem die **Aufzeichnungs-Slots**: Länge (Standard 120 Minuten, erlaubt
   15 bis 480) und Beginn nach Mitternacht (Standard 0, also Slots zu geraden
   Stunden; muss kürzer als die Länge sein). Die Übersicht gruppiert „Heute
   noch geplant“ und „Morgen“ nach diesen Slots und markiert Termine, deren
   Beginn oder Ende vom Slot abweicht.
4. Unter **Verwaltung → Einladungen** weitere Personen ohne
   Gruppenmitgliedschaft freischalten.
5. Unter **Verwaltung → Alarme** Empfänger für Alarm-E-Mails eintragen (siehe
   Abschnitt 7).
6. Sobald Gruppe und Einladungen tragen, kann `ANSEHBAR_BOOTSTRAP_USERS`
   wieder geleert werden.

## 7. Alarme, E-Mail und Metriken

ansehBAR alarmiert, wenn während eines Opencast-Termins der Stream fehlt
(nur mit Opencast-Anbindung, siehe Abschnitt 5). Außerhalb von Terminen ist
„kein Stream“ normal und löst nichts aus. Es gibt zwei Kanäle: E-Mail und die
Metrik-Schnittstelle `/metrics` für Prometheus. Letztere beschreibt
[docs/monitoring.md](monitoring.md). Entwarnungen gibt es nur per E-Mail.

### Alarmmodus pro Rekorder

Unter **Verwaltung → Rekorder** stellt jeder Rekorder seinen Modus ein:

| Modus | Verhalten |
| --- | --- |
| `exact` (Standard) | Alarm, wenn der Stream zum Opencast-Start plus Wartezeit fehlt |
| `grid` | Alarm frühestens zum Slot-Beginn plus c.t. plus Toleranz; für Einrichtungen, die anders buchen oder starten |
| `off` | Kein Alarm, der Vorfall wird nur erfasst |

Unter **Verwaltung → Einstellungen** stehen die zugehörigen Zeiten:

| Einstellung | Bedeutung | Standard |
| --- | --- | --- |
| Wartezeit („technischer Puffer“) | Minuten nach dem Terminbeginn, bevor ein fehlender Stream zählt | 3 |
| Slots (Länge, Beginn nach Mitternacht) | Raster der Veranstaltungen, siehe Abschnitt 6 | 120 / 0 |
| c.t.-Versatz | Minuten nach dem Slot-Beginn, zu denen die Veranstaltung tatsächlich beginnt | 15 |
| Toleranz nach c.t. | Zusätzliche Minuten nach c.t. im Modus `grid` | 5 |
| Toleranz am Ende | Endet der Stream so kurz vor dem geplanten Ende, ist das kein Vorfall (auch nicht in der Anzeige „Stream fehlt“) | 5 |
| Alarm per E-Mail / Metriken | Schaltet je einen Kanal global ab | an |

Im Modus `grid` gilt als Schwelle der spätere Zeitpunkt aus „Terminbeginn plus
Wartezeit“ und „Slot-Beginn plus c.t.-Versatz plus Toleranz“. Beginnt ein
Termin erst nach c.t., wird er nicht zusätzlich verschoben.

### Vorfälle und Entwarnung

- Pro Ausfall gibt es einen Vorfall; er wird alarmwürdig, sobald die
  Schwelle überschritten ist. Es werden nur Vorfälle alarmiert, deren Termin
  noch läuft: Alte offene Vorfälle (etwa nach einem Deploy) lösen nichts aus.
- Kommt der Stream zurück und fällt innerhalb von 60 Sekunden wieder aus
  (gemessen ab dem Ausfall), gilt es als derselbe Vorfall: kein neuer Alarm.
- **Entwarnung:** Bleibt der Stream mindestens 60 Sekunden stabil, geht eine
  Entwarnung an dieselben Empfänger. Endet der Termin bei fehlendem Stream,
  gibt es keine Entwarnung. Fällt der Stream nach einer Entwarnung erneut aus,
  entsteht ein neuer Vorfall mit eigenem Alarm.

### E-Mail einrichten

Der Monitor versendet die E-Mails über SMTP. In der `.env`:

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `EMAIL_HOST` | SMTP-Server | `localhost` |
| `EMAIL_PORT` | Port | `25` |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | Zugangsdaten, falls nötig (`$` in Passwörtern als `$$` schreiben) | leer |
| `EMAIL_USE_TLS` | `1` = STARTTLS, `0` = aus | `0` |
| `EMAIL_TIMEOUT` | Sekunden, bevor eine hängende Verbindung aufgegeben wird | `10` |
| `DEFAULT_FROM_EMAIL` | Absender | `ansehbar@localhost` |
| `ALARM_LANGUAGE` | Sprache der E-Mails (`de`/`en`), für alle Empfänger gleich | `de` |
| `EMAIL_BACKEND` | Nur zum Überschreiben des SMTP-Backends, z. B. für Tests | SMTP (in der Entwicklung Konsole) |

In der Entwicklung sind keine Mail-Einstellungen nötig: Die E-Mails erscheinen
im Log des Monitors. Nach Änderungen an der `.env` die Container neu erzeugen
(`docker compose -f docker-compose.prod.yml up -d`).

Empfänger pflegt man unter **Verwaltung → Alarme**. Dort lässt sich auch eine
Test-E-Mail an alle aktiven Empfänger anstoßen (der Monitor versendet sie im
nächsten Zyklus). Jede Meldung steht im Protokoll `SentNotification`. Die Zustellung ist
idempotent: Pro Vorfall-Ereignis, Kanal und Empfänger gibt es genau eine
Meldung, auch über Neustarts des Monitors hinweg. Schlägt der Versand fehl,
versucht der Monitor es im nächsten Zyklus erneut, höchstens 5-mal pro Meldung;
danach bleibt sie mit der Fehlermeldung (`last_error`) liegen. Ein SMTP-Fehler
hält den Prüfzyklus nie an.

### Metriken für Prometheus

`/metrics` ist ohne `METRICS_TOKEN` aus (404). Einrichtung, Kennzahlen,
Alarmregeln (`monitoring/alerts.yml`) und Scrape-Beispiel
(`monitoring/scrape.example.yml`) stehen in [monitoring.md](monitoring.md).

## 8. Prüfen und Fehlersuche

| Beobachtung | Ursache und Abhilfe |
| --- | --- |
| Nach der Anmeldung erscheint „Kein Zugang“ | Person ist weder in der Gruppe noch eingeladen, oder der Gruppen-Claim kommt nicht an. Mapper prüfen (Claim-Name `groups`, für Userinfo aktiv, ohne vollen Pfad) und neu anmelden. |
| Anmeldung schlägt fehl oder landet in einer Schleife | Redirect-URI beim Anbieter, `PUBLIC_BASE_URL`, `DJANGO_ALLOWED_HOSTS` und `CSRF_TRUSTED_ORIGINS` vergleichen; `OIDC_OP_ISSUER` muss vom Server aus erreichbar sein. |
| Alle Rekorder „Status unbekannt“ | Der Monitor erreicht den Streaming-Server nicht (DNS, Firewall, falsche URL-Vorlage). Mit `docker compose -f docker-compose.prod.yml logs monitor` und einem `curl` aus dem Container prüfen. |
| Alle Rekorder „Kein Stream“, obwohl gesendet wird | URL-Vorlage oder Stream-Namen falsch (Groß-/Kleinschreibung beachten). Die Vorschau unter „Einstellungen“ zeigt die erzeugte URL. |
| Kachel zeigt „live“, aber das Video bleibt schwarz oder „Wiedergabe gestört“ | Meist fehlende CORS-Header am Streaming-Server, oder das Gerät erreicht den Streaming-Server nicht. Browser-Konsole prüfen. |
| Banner „Monitor liefert keine Daten seit …“ | Der Container `monitor` läuft nicht oder hängt: `docker compose -f docker-compose.prod.yml ps` und `logs monitor`. Ohne Monitor bleibt der zuletzt bekannte Status stehen, das Banner warnt davor. |
| Pegelanzeige bleibt grau | Der Browser gibt Audio erst nach einem Klick frei: „Pegel & Ton aktivieren“ drücken. Auf Geräten, die HLS nativ abspielen, steht „Pegel nicht verfügbar“. |
| Banner „Opencast-Daten veraltet“ | Der letzte erfolgreiche Abgleich ist länger als drei Abgleich-Intervalle (`OPENCAST_SYNC_SECONDS`) her, oder es gab noch gar keinen erfolgreichen Abgleich (etwa kurz nach dem Start). Solange das Banner steht, zeigen Kachel und Raumansicht nicht „Kein Stream – keine Aufzeichnung geplant“. `docker compose -f docker-compose.prod.yml logs monitor` zeigt die Fehlerart (`opencast=error`): Adresse, Zugangsdaten und Erreichbarkeit prüfen, mit dem `curl` aus Abschnitt 5 gegenprobieren. Die Stream-Prüfung läuft unabhängig davon weiter. |
| Banner „Opencast nicht erreichbar“ | Adresse, Netz, DNS oder Firewall prüfen; mit dem `curl` aus Abschnitt 5 gegenprobieren. |
| Banner „Opencast hat die Anmeldung abgelehnt“ | Benutzer oder Passwort falsch. Enthält das Passwort ein `$`, in der `.env` `$$` schreiben, und Container neu erzeugen. |
| Banner „Keine Berechtigung in Opencast“ | Dem Konto fehlen API-Rollen oder Rechte; auch Opencasts HTML-Seite „Forbidden“ mit Status 200 wird so gemeldet. Rollen aus „Konto in Opencast“ prüfen. |
| Banner „Opencast antwortet nicht rechtzeitig“ | Opencast antwortet zu langsam; Last und Netz prüfen. Der nächste Abgleich versucht es erneut. |
| Banner „Opencast-Serverfehler“ oder „Unerwartete Antwort von Opencast“ | Fehler auf Opencast-Seite oder falsche Adresse (z. B. Proxy-Seite statt API). Logs von Opencast und Monitor prüfen. |
| Banner „Interner Fehler beim Opencast-Abgleich“ | Der Abgleich scheiterte an ansehBAR selbst (meist der Datenbank), nicht an Opencast. Log des Monitors prüfen (`docker compose -f docker-compose.prod.yml logs monitor`). |
| Banner „Opencast-Abgleich abgeschaltet – OPENCAST_URL muss https:// verwenden“ | `OPENCAST_URL` beginnt mit `http://`. Ohne TLS ginge das Passwort im Klartext über das Netz, deshalb gleicht ansehBAR nicht ab (außer mit `DJANGO_DEBUG=1`). Adresse auf `https://` umstellen und Container neu erzeugen. |
| Hinweis „Opencast zeigt keine geplanten Aufzeichnungen“ | Agents sind bekannt, aber das Konto sieht keine Termine: Event-ACL-Rechte des Kontos prüfen (siehe „Konto in Opencast“). |
| Termine fehlen, obwohl in Opencast geplant | Meist darf das Konto die Events nicht lesen: Rolle in den Event-ACLs bzw. ACL-Vorlagen ergänzen (siehe „Konto in Opencast“). Außerdem liegt der Termin vielleicht außerhalb von `OPENCAST_LOOKAHEAD_DAYS`, oder der Agent ist keinem Rekorder zugeordnet. |
| E-Mails kommen nicht an | Zuerst `docker compose -f docker-compose.prod.yml logs monitor` prüfen. Offene Meldungen zeigt das Protokoll: `docker compose -f docker-compose.prod.yml exec app python manage.py shell -c "from alarms.models import SentNotification as S; print(list(S.objects.filter(sent_at__isnull=True).values('recipient', 'attempts', 'last_error')))"`. `last_error` nennt den SMTP-Fehler (Server, Port, Zugangsdaten, `EMAIL_USE_TLS`). Ohne `EMAIL_HOST` geht die Mail an `localhost:25` und kommt meist nirgends an. Nach 5 Fehlversuchen versucht der Monitor die Meldung nicht mehr; Einstellung korrigieren und eine Test-E-Mail senden. Außerdem: Ist der Alarmmodus des Rekorders `off`, ist „Alarm per E-Mail“ abgeschaltet, oder fehlen Empfänger, wird nichts gesendet. |
| Keine Alarme trotz fehlendem Stream | Alarme gibt es nur während eines Opencast-Termins, nach Wartezeit (bei `grid` nach c.t. plus Toleranz) und nur für Vorfälle, deren Termin noch läuft. Modus, Opencast-Anbindung und Banner prüfen. |
| Agent wird übersprungen | Der Log des Monitors nennt per WARNING den Grund: Die Agent-ID ist kein gültiger Stream-Name (erlaubt sind Buchstaben, Ziffern, `.`, `_`, `-`), oder zu lang (mehr als 100 Zeichen), oder der Stream-Name gehört schon zu einem anderen Agent. `agent_id` beim passenden Rekorder setzen. |

## 9. Aktualisieren

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Datenbank-Migrationen laufen beim Start des Containers `app` automatisch.
Die Standortkonfiguration bleibt in der Datenbank erhalten und muss nur bei
Änderungen erneut geladen werden.
