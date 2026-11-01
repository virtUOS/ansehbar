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

## 5. Erste Anmeldung und laufende Pflege

1. `https://<host>` öffnen und mit einem Konto anmelden, das in der Gruppe
   oder in `ANSEHBAR_BOOTSTRAP_USERS` steht.
2. Unter **Verwaltung → Rekorder** prüfen, ob die Liste stimmt. Neue
   Rekorder lassen sich hier anlegen, bestehende bearbeiten oder
   deaktivieren.
3. Unter **Verwaltung → Einstellungen** stehen die Stream-URL-Vorlage (mit
   Vorschau) und der Frische-Faktor. Ein Stream gilt als live, solange
   sich seine Media-Sequence innerhalb von *Faktor × Segmentdauer* ändert;
   Standard 3, erlaubt 2 bis 10.
4. Unter **Verwaltung → Einladungen** weitere Personen ohne
   Gruppenmitgliedschaft freischalten.
5. Sobald Gruppe und Einladungen tragen, kann `ANSEHBAR_BOOTSTRAP_USERS`
   wieder geleert werden.

## 6. Prüfen und Fehlersuche

| Beobachtung | Ursache und Abhilfe |
| --- | --- |
| Nach der Anmeldung erscheint „Kein Zugang“ | Person ist weder in der Gruppe noch eingeladen, oder der Gruppen-Claim kommt nicht an. Mapper prüfen (Claim-Name `groups`, für Userinfo aktiv, ohne vollen Pfad) und neu anmelden. |
| Anmeldung schlägt fehl oder landet in einer Schleife | Redirect-URI beim Anbieter, `PUBLIC_BASE_URL`, `DJANGO_ALLOWED_HOSTS` und `CSRF_TRUSTED_ORIGINS` vergleichen; `OIDC_OP_ISSUER` muss vom Server aus erreichbar sein. |
| Alle Rekorder „Status unbekannt“ | Der Monitor erreicht den Streaming-Server nicht (DNS, Firewall, falsche URL-Vorlage). Mit `docker compose -f docker-compose.prod.yml logs monitor` und einem `curl` aus dem Container prüfen. |
| Alle Rekorder „Kein Stream“, obwohl gesendet wird | URL-Vorlage oder Stream-Namen falsch (Groß-/Kleinschreibung beachten). Die Vorschau unter „Einstellungen“ zeigt die erzeugte URL. |
| Kachel zeigt „live“, aber das Video bleibt schwarz oder „Wiedergabe gestört“ | Meist fehlende CORS-Header am Streaming-Server, oder das Gerät erreicht den Streaming-Server nicht. Browser-Konsole prüfen. |
| Banner „Monitor liefert keine Daten seit …“ | Der Container `monitor` läuft nicht oder hängt: `docker compose -f docker-compose.prod.yml ps` und `logs monitor`. Ohne Monitor bleibt der zuletzt bekannte Status stehen, das Banner warnt davor. |
| Pegelanzeige bleibt grau | Der Browser gibt Audio erst nach einem Klick frei: „Pegel & Ton aktivieren“ drücken. Auf Geräten, die HLS nativ abspielen, steht „Pegel nicht verfügbar“. |

## 7. Aktualisieren

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Datenbank-Migrationen laufen beim Start des Containers `app` automatisch.
Die Standortkonfiguration bleibt in der Datenbank erhalten und muss nur bei
Änderungen erneut geladen werden.
