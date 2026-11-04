# Installation und Betrieb (Produktivserver)

Diese Anleitung richtet ansehBAR auf einem **Rocky-Linux-10-Server** ein
(Rocky Linux 9 geht genauso). Sie ist so geschrieben, dass Sie ihr ohne
Linux-Vorerfahrung folgen können: Kopieren Sie jeden Befehl genau so, wie er
dasteht.

ansehBAR läuft als Docker-Compose-Stack aus vier Containern:

```
Browser ── https ──> Caddy ──> /api, /oidc, /metrics → App (Django/uvicorn)
                       │        /static, /media       → Volumes (direkt ausgeliefert)
                       │        alles andere          → Oberfläche (SPA, Volume frontend_data)
                       └── HTTPS-Zertifikat automatisch (Let's Encrypt) oder eigenes (HARICA)

Monitor ── prüft die Streams, gleicht Opencast ab, misst den Ton, verschickt Alarme
```

- **db**: PostgreSQL 16, Daten im Volume `postgres_data`.
- **app**: das ansehBAR-Image von GitHub (`ghcr.io/virtuos/ansehbar`). Es
  enthält Django und die fertig gebaute Oberfläche. Beim Start führt es die
  Datenbank-Migrationen aus, sammelt die statischen Dateien und kopiert die
  Oberfläche in ein Volume.
- **monitor**: dasselbe Image als Hintergrundprozess (`run_monitor`). Er
  prüft die Streams, gleicht Opencast ab, misst den Ton mit ffmpeg,
  verschickt Alarm-E-Mails und räumt alte Daten auf. Einen Cron-Job braucht
  ansehBAR nicht.
- **caddy**: Webserver mit HTTPS. Caddy holt und erneuert das Zertifikat selbst.

Die Anmeldung läuft über den **Identity Provider der Einrichtung** (OIDC,
z. B. Keycloak). Ein eigenes Keycloak gibt es auf dem Server nicht.

Diese Anleitung beschreibt den **Server**. Was ansehBAR selbst braucht
(Streaming-Server, OIDC-Client, Standortkonfiguration, Opencast, Alarme,
Aufbewahrung), steht in der [Konfigurationsanleitung](KONFIGURATION.md); auf
sie wird an den passenden Stellen verwiesen.

> **Platzhalter:** `ansehbar.example.org`, `admin@example.org` und alles in
> spitzen Klammern (`<…>`) ersetzen Sie durch Ihre Werte. Die spitzen Klammern
> selbst schreiben Sie nicht mit.

## Inhalt

1. [Servergröße](#1-servergröße)
2. [Was Sie vorher brauchen](#2-was-sie-vorher-brauchen)
3. [Installation Schritt für Schritt](#3-installation-schritt-für-schritt)
4. [Nach dem ersten Start](#4-nach-dem-ersten-start)
5. [Alltagskommandos](#5-alltagskommandos)
6. [Aktualisieren](#6-aktualisieren)
7. [Sicherung und Wiederherstellung](#7-sicherung-und-wiederherstellung)
8. [Eigenes Zertifikat (HARICA)](#8-eigenes-zertifikat-harica)
9. [Fehlersuche](#9-fehlersuche)
10. [Checkliste](#10-checkliste)

---

## 1. Servergröße

| CPU | RAM | Festplatte |
|---|---|---|
| 2 vCPU | 4 GB | 30–40 GB |

Das reicht für einen Standort mit etwa 40 Räumen, von denen bis zu 10
gleichzeitig aufzeichnen:

- **RAM:** PostgreSQL, Django, Monitor und Caddy brauchen zusammen etwa 1 GB.
  Dazu kommen bis zu vier ffmpeg-Prozesse der Tonmessung (je rund 50 MB) und
  das Betriebssystem.
- **CPU:** ffmpeg dekodiert nur die Tonspur; vier parallele Messungen
  brauchen zusammen weniger als einen Kern.
- **Festplatte:** Die Datenbank bleibt klein (Pegelmessungen über 30 Tage bei
  10 Räumen unter 100 MB). Platz brauchen die Images (nach Updates liegen alte
  daneben), die Logs und die nächtlichen Sicherungen (Abschnitt 7).
- **Netz:** Die Videos schaut der Browser direkt vom Streaming-Server, sie
  laufen nicht über diesen Server. Die Tonmessung lädt aber pro laufendem Raum
  etwa alle 30 Sekunden 10 Sekunden des Streams: bei 10 gleichzeitigen Räumen
  im Schnitt rund 10 Mbit/s aus dem Streaming-Netz, über einen Vorlesungstag
  grob 30–40 GB. Weniger wird es mit einem höheren `AUDIO_INTERVAL_SECONDS`.

## 2. Was Sie vorher brauchen

- Einen frischen Server mit **Rocky Linux 10** (oder 9) und ein Konto mit
  `sudo`-Rechten (als `root` lassen Sie das `sudo` weg). Docker ist auf einer
  frischen Installation **nicht** vorhanden; Sie installieren es in Schritt 3.
- Einen **DNS-Namen** (z. B. `ansehbar.example.org`), der auf die IP des
  Servers zeigt. Für Let's Encrypt müssen die Ports 80 und 443 aus dem
  Internet erreichbar sein; sonst brauchen Sie ein HARICA-Zertifikat
  (Abschnitt 8).
- Einen **OIDC-Client** beim Identity Provider und eine Gruppe für den
  Zugang ([Konfigurationsanleitung, Abschnitt 2](KONFIGURATION.md#2-anmeldung-oidc-einrichten)).
  Der Stack startet auch ohne funktionierenden Login, Sie können ihn also
  nachreichen.
- Einen **Streaming-Server**, den der Server per HTTPS erreicht, mit
  CORS-Freigabe für die ansehBAR-Adresse ([Abschnitt 1](KONFIGURATION.md#1-voraussetzungen-am-streaming-server)).
- Optional: ein **Opencast-Konto** mit Leserechten ([Abschnitt 5](KONFIGURATION.md#5-opencast-anbinden-optional)),
  einen **SMTP-Server** mit Absenderadresse für Alarm-E-Mails und
  **Prometheus** für den Monitoring-Dienst ([docs/monitoring.md](monitoring.md)).
- Die **Standortkonfiguration** `site.local.json` mit Ihren Rekordern
  ([Abschnitt 4](KONFIGURATION.md#4-standortkonfiguration-laden)), falls Sie
  die Rekorder nicht von Hand in der Verwaltung anlegen.

Ausgehend muss der Server erreichen: den Streaming-Server, den Identity
Provider, Opencast, den SMTP-Server und `ghcr.io` (Images).

> Notation: Alle Befehle laufen im Terminal des Servers. Im Editor `nano`
> speichern Sie mit **Strg+O** und **Enter** und beenden mit **Strg+X**.

---

## 3. Installation Schritt für Schritt

### Schritt 1: Am Server anmelden

Von Ihrem Rechner aus:

```bash
ssh <benutzer>@<server-ip>
```

### Schritt 2: System aktualisieren

```bash
sudo dnf -y update
sudo dnf -y install git nano bind-utils cronie
sudo systemctl enable --now crond
```

`cronie` brauchen Sie für die nächtliche Sicherung (Abschnitt 7).

Hat `dnf update` einen **neuen Kernel** installiert (bei einer frischen VM
fast immer), starten Sie den Server **jetzt** einmal neu. Sonst passen der
laufende Kernel und seine Module nicht zusammen, und Docker kann seine
Netzwerkregeln nicht anlegen (Abschnitt 9):

```bash
sudo reboot
```

Danach wieder anmelden (Schritt 1).

### Schritt 3: Docker installieren

Ein frisches Rocky Linux bringt Docker nicht mit. Docker stellt dafür ein
eigenes Paketverzeichnis bereit:

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world      # muss "Hello from Docker!" ausgeben
```

Prüfen:

```bash
sudo docker compose version           # Docker Compose version v2.…
sudo systemctl is-enabled docker      # enabled (Docker startet beim Booten)
```

Falls etwas nicht klappt:

- `dnf config-manager --add-repo` wird als unbekannte Option abgelehnt (neuere
  dnf-Version): Dann lautet der Befehl
  `sudo dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/rhel/docker-ce.repo`.
- `podman-docker`, `podman` oder `runc` melden einen Konflikt: Entfernen Sie sie
  vorher mit `sudo dnf -y remove podman-docker podman runc`.
- Das RHEL-Verzeichnis liefert für Ihre Version keine Pakete: Unter Rocky
  Linux 9 funktioniert auch das CentOS-Verzeichnis
  (`https://download.docker.com/linux/centos/docker-ce.repo`); sonst hilft die
  aktuelle Anleitung unter <https://docs.docker.com/engine/install/rhel/>.
- Ist Docker schon installiert, zeigt `sudo docker version` bei **Server**
  `Docker Engine - Community`; dann überspringen Sie die Installation. Steht
  dort `podman`, ist nur der Podman-Ersatz installiert: Entfernen Sie ihn wie
  oben und installieren Sie Docker.

### Schritt 4: Firewall öffnen

Caddy braucht Port **80** (Zertifikat und Umleitung auf HTTPS) und **443**
(HTTPS). Rocky nutzt **firewalld**:

```bash
sudo dnf -y install firewalld
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
sudo firewall-cmd --list-services      # muss http und https enthalten
```

Steht der Server hinter einer Netz-Firewall des Rechenzentrums oder einer
Security-Group (Cloud-VM), lassen Sie dort ebenfalls TCP 80 und 443 eingehend
freischalten. Für Prometheus reicht 443: Es fragt `/metrics` über die
öffentliche Adresse ab.

### Schritt 5: DNS prüfen

```bash
dig +short ansehbar.example.org      # muss die IP des Servers ausgeben
```

Machen Sie erst weiter, wenn hier die richtige IP erscheint. Let's Encrypt
prüft genau das.

### Schritt 6: Anwendung herunterladen

Das Repository ist öffentlich; Zugangsdaten brauchen Sie nicht.

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/virtUOS/ansehbar.git
cd /opt/ansehbar
```

Der Ordner muss `/opt/ansehbar` heißen: Docker benennt die Volumes nach dem
Ordner (`ansehbar_postgres_data` …), und die Sicherung in Abschnitt 7
verlässt sich darauf. Alle weiteren Befehle führen Sie **in diesem Ordner**
aus.

### Schritt 7: Konfiguration anlegen

```bash
cd /opt/ansehbar
sudo cp .env.prod.example .env
sudo chmod 600 .env
```

Erzeugen Sie die Zufallswerte, einen für Django, einen für die Datenbank und
(wenn Sie Prometheus anbinden) einen für den Metrik-Endpunkt:

```bash
openssl rand -base64 48      # → DJANGO_SECRET_KEY
openssl rand -hex 24         # → POSTGRES_PASSWORD
openssl rand -hex 32         # → METRICS_TOKEN (optional)
```

> **Wichtig:** Der Platzhalter `change-me-to-a-long-random-string` aus der
> Vorlage ist öffentlich bekannt. ansehBAR verweigert mit ihm (wie mit dem
> Entwicklungsschlüssel) den Start. Tragen Sie also Ihren eigenen Wert ein.

Öffnen Sie die Datei:

```bash
sudo nano .env
```

Setzen Sie mindestens diese Werte (Zeilen mit `#` sind Kommentare):

```dotenv
# Öffentliche Adresse: nur Schema und Host, kein Pfad, kein "/" am Ende.
# Caddy holt für diesen Host das Zertifikat.
PUBLIC_BASE_URL=https://ansehbar.example.org
# Kontakt für Let's Encrypt (Hinweise zum Ablauf des Zertifikats)
ACME_EMAIL=<funktionsadresse>@example.org

# Django
DJANGO_SECRET_KEY=<ausgabe von openssl rand -base64 48>
DJANGO_ALLOWED_HOSTS=ansehbar.example.org
CSRF_TRUSTED_ORIGINS=https://ansehbar.example.org

# Datenbank
POSTGRES_PASSWORD=<ausgabe von openssl rand -hex 24>

# Image-Version = Release-Tag (mit oder ohne "v", z. B. 1.0.0)
ANSEHBAR_VERSION=<version>

# Anmeldung (OIDC-Client, siehe KONFIGURATION.md Abschnitt 2)
OIDC_RP_CLIENT_ID=<client-id>
OIDC_RP_CLIENT_SECRET=<client-secret>
OIDC_OP_ISSUER=https://<keycloak-host>/realms/<realm>
OIDC_GROUPS_CLAIM=groups

# Zugang: Gruppe im Identity Provider, erste Konten ohne Gruppe, Kontakt
ANSEHBAR_ACCESS_GROUP=<gruppe>
ANSEHBAR_BOOTSTRAP_USERS=<ihr-benutzername>
ANSEHBAR_ACCESS_CONTACT=<funktionsadresse>@example.org
```

Je nach Ausbau kommen dazu (die Zeilen stehen auskommentiert in der Vorlage;
`#` am Anfang entfernen):

```dotenv
# Opencast (nur lesend; KONFIGURATION.md Abschnitt 5). Ein "$" im Passwort als "$$" schreiben.
OPENCAST_URL=https://<opencast-host>
OPENCAST_USER=<benutzer>
OPENCAST_PASSWORD=<passwort>

# Alarm-E-Mails (KONFIGURATION.md Abschnitt 7)
EMAIL_HOST=<smtp-host>
EMAIL_PORT=25
EMAIL_USE_TLS=0
DEFAULT_FROM_EMAIL=ansehbar@example.org

# Prometheus (docs/monitoring.md)
METRICS_TOKEN=<ausgabe von openssl rand -hex 32>
```

Welche Releases es gibt, sehen Sie auf GitHub unter
[Releases](https://github.com/virtUOS/ansehbar/releases) bzw. unter
**Packages → ansehbar**. Lassen Sie `ANSEHBAR_VERSION` leer, gilt `latest` (das
jeweils neueste Release); für einen nachvollziehbaren Betrieb pinnen Sie
lieber eine Version.

Speichern mit **Strg+O**, **Enter**, beenden mit **Strg+X**. Die übrigen
Variablen der Vorlage (Tonmessung, Monitor-Intervall, Claim-Namen) können
bleiben, wie sie sind; sie sind in der README und der Konfigurationsanleitung
erklärt.

### Schritt 8: Webserver (Caddy)

Am `Caddyfile` ändern Sie **nichts**. Es gehört zum Repository und liest seine
Werte aus der `.env`, die `docker-compose.prod.yml` an den Caddy-Container
weitergibt:

| Variable | Bedeutung |
|---|---|
| `PUBLIC_BASE_URL` | Site-Adresse, für die Caddy das Zertifikat holt (derselbe Wert wie für die App). `https://` macht die Seite HTTPS-only, HTTP leitet Caddy um. |
| `ACME_EMAIL` | Kontaktadresse für Let's Encrypt. Pflicht; fehlt sie, startet Compose nicht. |

Caddy leitet `/api/`, `/oidc/`, `/admin/` und `/metrics` an Django weiter,
liefert `/static/` und `/media/` aus den Volumes und alles andere aus der
Oberfläche. Außerdem setzt Caddy Sicherheitsheader: ansehBAR darf nicht in
fremde Seiten eingebettet werden (`Content-Security-Policy: frame-ancestors
'none'`, `X-Frame-Options: DENY`), dazu `X-Content-Type-Options: nosniff` und
eine sparsame `Referrer-Policy`.

Weil das `Caddyfile` unverändert bleibt, läuft `git pull` bei Updates ohne
Konflikte. Geänderte Werte in der `.env` übernehmen Sie mit `up -d` (Schritt 10);
ein bloßes `restart` liest die `.env` nicht neu ein.

### Schritt 9: SELinux-Freigabe

Rocky Linux hat SELinux eingeschaltet. Ein Container darf vom Host
eingebundene Dateien nur lesen, wenn sie das passende Label tragen. Caddy
bindet das `Caddyfile` ein:

```bash
cd /opt/ansehbar
sudo chcon -t container_file_t Caddyfile
ls -Z Caddyfile                 # muss container_file_t enthalten
```

`git pull` kann die Datei ersetzen und das Label verlieren. Führen Sie den
`chcon`-Befehl deshalb nach jedem Update erneut aus (Abschnitt 6). Die Volumes
brauchen keine Freigabe.

### Schritt 10: Image laden und starten

```bash
cd /opt/ansehbar
sudo docker compose -f docker-compose.prod.yml pull
sudo docker compose -f docker-compose.prod.yml up -d --no-build
```

`--no-build` verhindert, dass Docker das Image aus dem Quellcode baut, falls
das Laden scheitert. Meldet `pull` einen Fehler (`unauthorized`, `not found`),
siehe Abschnitt 9.

> **Ohne Release-Image** (oder zum Testen eines Standes, der noch kein
> Release ist) baut der Server das Image aus dem Checkout selbst:
> `sudo docker compose -f docker-compose.prod.yml up -d --build`. Das dauert
> einige Minuten.

Prüfen Sie, dass die gewünschte Version läuft. In der Spalte `TAG` muss die
Version aus `ANSEHBAR_VERSION` stehen, nicht `latest` (dann ist die Zeile in
der `.env` noch leer oder auskommentiert):

```bash
sudo docker compose -f docker-compose.prod.yml images app monitor
```

Beobachten Sie den Start:

```bash
sudo docker compose -f docker-compose.prod.yml logs -f app      # Strg+C beendet die Anzeige
```

Bereit ist die App, sobald `Application startup complete` erscheint. Caddy
holt das Zertifikat in der ersten Minute:

```bash
sudo docker compose -f docker-compose.prod.yml logs caddy | grep -i "certificate obtained"
```

Prüfen Sie, dass alles läuft:

```bash
sudo docker compose -f docker-compose.prod.yml ps       # db, app, monitor, caddy: "Up"
```

Öffnen Sie danach `https://ansehbar.example.org` im Browser. Die Startseite
mit „Anmelden“ erscheint.

---

## 4. Nach dem ersten Start

### 4.1 Anmelden

Melden Sie sich mit dem Konto aus `ANSEHBAR_BOOTSTRAP_USERS` an. Klappt das
nicht, helfen die Hinweise zum Login in Abschnitt 9 und die Tabelle in der
[Konfigurationsanleitung, Abschnitt 8](KONFIGURATION.md#8-prüfen-und-fehlersuche).

### 4.2 Rekorder laden

Mit einer Standortkonfiguration (`site.local.json`, Aufbau in der
[Konfigurationsanleitung, Abschnitt 4](KONFIGURATION.md#4-standortkonfiguration-laden)):
Legen Sie die Datei auf dem Server ab, z. B. als `/opt/ansehbar/site.local.json`
(Git ignoriert sie, und die Sicherung nimmt sie mit), und laden Sie sie über
die Standardeingabe:

```bash
cd /opt/ansehbar
sudo chmod 600 site.local.json
# erst prüfen, was sich ändern würde:
sudo docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py load_site_config --path - --dry-run < site.local.json
# dann übernehmen:
sudo docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py load_site_config --path - < site.local.json
```

Ohne Datei legen Sie die Rekorder unter **Verwaltung → Rekorder** an und
tragen die Stream-URL-Vorlage unter **Verwaltung → Einstellungen** ein. Mit
Opencast-Anbindung legt ansehBAR die Capture Agents zusätzlich selbst an.

### 4.3 Monitor prüfen

```bash
sudo docker compose -f docker-compose.prod.yml logs monitor --tail 30
```

Der Monitor schreibt regelmäßig eine Zusammenfassung (wie viele Rekorder live,
offline, unbekannt). Stehen alle auf „Status unbekannt“ oder „Kein Stream“,
obwohl gesendet wird, prüfen Sie URL-Vorlage, Stream-Namen und die
Erreichbarkeit des Streaming-Servers ([Konfigurationsanleitung, Abschnitt 8](KONFIGURATION.md#8-prüfen-und-fehlersuche)).
Ein einzelner Stream lässt sich von Hand messen:

```bash
sudo docker compose -f docker-compose.prod.yml exec app python manage.py measure_audio <stream-name>
```

### 4.4 Zugang übergeben

Sobald die Gruppe im Identity Provider trägt und weitere Personen eingeladen
sind (**Verwaltung → Einladungen**), leeren Sie `ANSEHBAR_BOOTSTRAP_USERS` in
der `.env` und legen die Container neu an:

```bash
sudo docker compose -f docker-compose.prod.yml up -d --no-build
```

### 4.5 Mail

Tragen Sie unter **Verwaltung → Alarme** mindestens einen Empfänger ein und
drücken Sie **Test-E-Mail senden**. Der Monitor verschickt sie beim nächsten
Durchlauf (wenige Sekunden). Kommt nichts an, siehe Abschnitt 9.

### 4.6 Monitoring-Dienst (optional)

Mit gesetztem `METRICS_TOKEN` antwortet `/metrics`:

```bash
cd /opt/ansehbar
curl -s -H "Authorization: Bearer $(sudo grep '^METRICS_TOKEN=' .env | cut -d= -f2-)" \
  https://ansehbar.example.org/metrics | head
```

Scrape-Eintrag und Alarmregeln für Prometheus stehen in
[docs/monitoring.md](monitoring.md).

### 4.7 Sicherung einrichten

Richten Sie jetzt die nächtliche Sicherung ein (Abschnitt 7).

### 4.8 Übersteht das einen Neustart?

Ja. Docker startet beim Booten, alle Dienste haben `restart: unless-stopped`,
alle Daten liegen in Volumes, und die Firewall-Regeln sind dauerhaft
gespeichert. Prüfen Sie es einmal:

```bash
sudo reboot
# nach dem Neustart wieder anmelden, dann:
cd /opt/ansehbar
sudo docker compose -f docker-compose.prod.yml ps
```

---

## 5. Alltagskommandos

Alle im Ordner `/opt/ansehbar`. Damit die Zeilen kürzer werden, legen Sie
pro Sitzung eine Abkürzung an:

```bash
cd /opt/ansehbar
P="sudo docker compose -f docker-compose.prod.yml"
$P ps                          # was läuft
$P logs -f                     # Live-Logs aller Dienste (Strg+C beendet)
$P logs app --tail 100         # letzte 100 Zeilen der App
$P logs monitor --tail 100     # letzte 100 Zeilen des Monitors
$P restart monitor             # Monitor neu starten
$P up -d --no-build            # starten bzw. geänderte .env übernehmen
$P down                        # alles stoppen (Daten bleiben erhalten)
$P exec app python manage.py run_monitor --once   # ein Prüflauf von Hand
```

`$P down -v` würde auch die Volumes und damit **alle Daten löschen**. Nutzen
Sie es nie auf dem Server.

Welche Werte im Container ankommen (ohne die Geheimnisse anzuzeigen):

```bash
$P exec app env | grep -oE "^(DJANGO_|OIDC_|POSTGRES_|ANSEHBAR_|OPENCAST_|AUDIO_|EMAIL_|METRICS_|CSRF|FRONTEND)[A-Z_]*" | sort
```

---

## 6. Aktualisieren

Ein neues Release entsteht, wenn auf GitHub ein Tag `vX.Y.Z` gesetzt wird:
Der Workflow `release.yml` baut dann das Image und legt es als `vX.Y.Z`,
`X.Y.Z` und `latest` in die Registry. So aktualisieren Sie den Server:

1. Die Release-Hinweise auf GitHub lesen (neue Einstellungen, Hinweise zur
   Migration).

2. Neue Version in der `.env` eintragen:

   ```bash
   cd /opt/ansehbar
   sudo nano .env               # ANSEHBAR_VERSION=<neue version>
   ```

3. Vorher sichern (Abschnitt 7):

   ```bash
   sudo /usr/local/sbin/ansehbar-backup
   ```

4. Compose-Datei und `Caddyfile` aktualisieren, Image laden, neu starten:

   ```bash
   cd /opt/ansehbar
   sudo git pull
   sudo chcon -t container_file_t Caddyfile
   sudo docker compose -f docker-compose.prod.yml pull
   sudo docker compose -f docker-compose.prod.yml up -d --no-build
   sudo docker compose -f docker-compose.prod.yml logs app --tail 60
   ```

   Migrationen und `collectstatic` laufen beim Start von selbst. Bereit ist
   die App, sobald `Application startup complete` erscheint. Der Monitor
   startet mit der neuen Version neu.

5. Offene Browser-Tabs zeigen die alte Oberfläche, bis sie neu geladen werden
   (**Strg+Umschalt+R**, am Mac **Cmd+Umschalt+R**).

6. Alte Images aufräumen, damit die Platte nicht voll läuft:

   ```bash
   sudo docker image prune -f
   ```

**Zurück auf die vorige Version:** alte Version in die `.env` eintragen, dann
`pull` und `up -d --no-build` wie oben. Hat die neue Version Migrationen
mitgebracht, passt die Datenbank nicht mehr zur alten Version; dann spielen Sie
die Sicherung von vor dem Update zurück (Abschnitt 7).

**Wenn `git pull` wegen lokaler Änderungen abbricht:** Auf dem Server werden
`Caddyfile` und `docker-compose.prod.yml` nicht bearbeitet. Ausnahme sind die
Zeilen für ein eigenes Zertifikat (Abschnitt 8). Die nehmen Sie so mit:

```bash
sudo git stash && sudo git pull && sudo git stash pop
```

Meldet `git stash pop` einen Konflikt, behalten Sie die neue Fassung aus git,
fügen Ihre `tls`- bzw. Mount-Zeile wieder ein und verwerfen den Stash mit
`sudo git stash drop`.

**Neue Variable in einem Release:** `docker-compose.prod.yml` reicht jede
Variable einzeln an die Container weiter. Bringt ein Release eine neue
Einstellung mit, steht sie in `.env.prod.example`; übernehmen Sie sie bei
Bedarf in Ihre `.env` und starten mit `up -d --no-build`. Vergleichen:

```bash
diff <(grep -oE "^#?[A-Z_]+=" .env.prod.example | tr -d '#' | sort -u) <(sudo grep -oE "^[A-Z_]+=" .env | sort -u)
```

Zeilen mit `<` gibt es nur in der Vorlage (meist optional).

---

## 7. Sicherung und Wiederherstellung

### Was gesichert wird

| Daten | Ort | Sicherung |
|---|---|---|
| Datenbank (Rekorder, Einstellungen, Termine, Vorfälle, Pegelmessungen, Empfänger, Einladungen) | Volume `ansehbar_postgres_data` | `pg_dump` |
| Konfiguration | `/opt/ansehbar/.env` | Datei kopieren (enthält Geheimnisse) |
| Standortkonfiguration | `/opt/ansehbar/site.local.json`, falls vorhanden | Datei kopieren |
| Zertifikate | Volume `ansehbar_caddy_data` | verzichtbar, Caddy stellt neu aus |

`static_data`, `media_data` und `frontend_data` entstehen bei jedem Start neu
bzw. sind leer; sie brauchen Sie nicht zu sichern. Termine holt ansehBAR
ohnehin aus Opencast; unersetzlich sind vor allem Vorfälle, Einstellungen,
Empfänger und Einladungen.

### Sicherungsskript

```bash
sudo tee /usr/local/sbin/ansehbar-backup > /dev/null <<'EOF'
#!/bin/sh
# Nächtliche Sicherung von ansehBAR: Datenbank, .env, Standortkonfiguration.
set -eu
DIR=/var/backups/ansehbar
KEEP_DAYS=14
STAMP=$(date +%F-%H%M)
cd /opt/ansehbar
mkdir -p "$DIR"
chmod 700 "$DIR"
C="docker compose -f docker-compose.prod.yml"
$C exec -T db pg_dump -U ansehbar -d ansehbar --clean --if-exists | gzip > "$DIR/db-$STAMP.sql.gz"
cp .env "$DIR/env-$STAMP"
[ -f site.local.json ] && cp site.local.json "$DIR/site-$STAMP.json"
chmod 600 "$DIR"/*
find "$DIR" -type f -mtime +"$KEEP_DAYS" -delete
EOF
sudo chmod 700 /usr/local/sbin/ansehbar-backup
sudo /usr/local/sbin/ansehbar-backup
sudo ls -lh /var/backups/ansehbar
```

Die Dateien entstehen auf dem Host (der Container schreibt nur in die
Ausgabe), deshalb braucht die Sicherung keine SELinux-Freigabe. Haben Sie
`POSTGRES_USER` oder `POSTGRES_DB` in der `.env` geändert, passen Sie
`-U ansehbar -d ansehbar` an.

Nächtlich um 2:30 Uhr ausführen:

```bash
sudo tee /etc/cron.d/ansehbar-backup > /dev/null <<'EOF'
30 2 * * * root /usr/local/sbin/ansehbar-backup >> /var/log/ansehbar-backup.log 2>&1
EOF
sudo chmod 644 /etc/cron.d/ansehbar-backup
```

Das Skript behält 14 Tage. **Eine Sicherung auf demselben Server schützt nicht
vor dem Verlust des Servers.** Lassen Sie `/var/backups/ansehbar` von der
zentralen Datensicherung des Rechenzentrums mitnehmen oder kopieren Sie die
Dateien regelmäßig auf ein anderes System. Die Sicherungen enthalten
personenbezogene Daten (Namen und E-Mail-Adressen) und die `.env` mit allen
Geheimnissen; behandeln Sie sie entsprechend.

### Wiederherstellen

Wählen Sie den Zeitpunkt (`<stempel>`, z. B. `2026-11-03-0230`):

```bash
cd /opt/ansehbar
B=/var/backups/ansehbar
T=<stempel>
sudo docker compose -f docker-compose.prod.yml stop app monitor caddy

# Datenbank: die Sicherung löscht und ersetzt die Tabellen (--clean)
gunzip -c "$B/db-$T.sql.gz" | sudo docker compose -f docker-compose.prod.yml exec -T db \
  psql -U ansehbar -d ansehbar -v ON_ERROR_STOP=1 -q > /dev/null

sudo docker compose -f docker-compose.prod.yml up -d --no-build
```

Auf einem **neuen Server** richten Sie zuerst alles nach Abschnitt 3 ein
(dieselbe `ANSEHBAR_VERSION` wie zum Zeitpunkt der Sicherung, die `.env` aus
der Sicherung), starten einmal, spielen dann wie oben zurück und lassen das
Laden der Standortkonfiguration weg.

---

## 8. Eigenes Zertifikat (HARICA)

Ist der Server nicht aus dem Internet erreichbar oder soll ein
Hochschul-Zertifikat genutzt werden, verwendet Caddy die Dateien statt Let's
Encrypt. Diese Änderung am `Caddyfile` und an `docker-compose.prod.yml` ist
die einzige vorgesehene lokale Anpassung.

1. Die Dateien außerhalb des Repositorys ablegen, damit der private Schlüssel
   nie in git landet:

   ```bash
   sudo mkdir -p /etc/ansehbar/certs
   sudo chmod 700 /etc/ansehbar/certs
   ```

   - `/etc/ansehbar/certs/ansehbar.pem`: Serverzertifikat **mit
     Zwischenzertifikaten** (zuerst das Serverzertifikat, dann die Kette), PEM.
   - `/etc/ansehbar/certs/ansehbar.key`: der private Schlüssel, PEM,
     **ohne Passphrase**.

2. Für SELinux freigeben:

   ```bash
   sudo chcon -Rt container_file_t /etc/ansehbar/certs
   ```

3. In `docker-compose.prod.yml` beim Dienst `caddy` die vorbereitete Zeile
   einkommentieren (das `#` am Anfang entfernen):

   ```yaml
         - /etc/ansehbar/certs:/etc/caddy/certs:ro
   ```

4. Im `Caddyfile` direkt unter der Zeile `{$PUBLIC_BASE_URL} {` einfügen:

   ```
   	tls /etc/caddy/certs/ansehbar.pem /etc/caddy/certs/ansehbar.key
   ```

   Der Host in `PUBLIC_BASE_URL` muss im Zertifikat stehen. `ACME_EMAIL` wird
   dann nicht genutzt, muss aber gesetzt bleiben.

5. Übernehmen:

   ```bash
   cd /opt/ansehbar
   sudo chcon -t container_file_t Caddyfile
   sudo docker compose -f docker-compose.prod.yml up -d --no-build
   sudo docker compose -f docker-compose.prod.yml logs caddy --tail 30
   ```

Die Erneuerung ist in diesem Fall **Handarbeit**: Dateien vor Ablauf ersetzen,
dann `sudo docker compose -f docker-compose.prod.yml restart caddy`. Tragen Sie
sich das Ablaufdatum in den Kalender ein. Bei Updates nehmen Sie die beiden
Zeilen mit `git stash` mit (Abschnitt 6).

Ohne öffentlich erreichbaren Port 80 kann Prometheus `/metrics` trotzdem über
443 abfragen; es muss dem Zertifikat aber vertrauen (HARICA ist in den
üblichen CA-Listen enthalten).

---

## 9. Fehlersuche

Der erste Blick geht immer in die Logs:

```bash
cd /opt/ansehbar
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml logs app --tail 100
sudo docker compose -f docker-compose.prod.yml logs monitor --tail 100
sudo docker compose -f docker-compose.prod.yml logs caddy --tail 100
sudo docker compose -f docker-compose.prod.yml logs db --tail 50
```

Probleme mit Streams, Opencast, Ton, Alarmen und Zugang (alles, was die App
selbst anzeigt) beschreibt die Tabelle in der
[Konfigurationsanleitung, Abschnitt 8](KONFIGURATION.md#8-prüfen-und-fehlersuche).
Hier geht es um den Server.

### Compose startet nicht: `required variable … is missing a value`

Eine Pflichtvariable fehlt in der `.env` (z. B. `ACME_EMAIL`,
`DJANGO_SECRET_KEY`, `OIDC_RP_CLIENT_SECRET`). Ergänzen Sie sie nach dem Muster
in `.env.prod.example` und starten Sie mit `up -d --no-build`.

### App oder Monitor starten nicht

- `ImproperlyConfigured: DJANGO_SECRET_KEY must be set …`: Es ist der
  Entwicklungsschlüssel oder der Platzhalter aus der Vorlage aktiv. Eigenen
  Schlüssel eintragen (Schritt 7).
- `OIDC_OP_ISSUER=… is set, but the OIDC endpoints could not be …`: Der Server
  erreicht das Discovery-Dokument des Identity Providers nicht. Prüfen:
  `curl -s https://<keycloak-host>/realms/<realm>/.well-known/openid-configuration | head -c 200`.
- App oder Monitor starten ständig neu und warten auf die Datenbank: Hat sich
  `POSTGRES_PASSWORD` nach dem ersten Start geändert, passt es nicht mehr zur
  bestehenden Datenbank (PostgreSQL übernimmt das Passwort nur beim
  allerersten Start). Altes Passwort wieder eintragen.

### `pull` scheitert: `unauthorized`, `denied` oder `manifest unknown`

- `manifest unknown`/`not found`: Diese `ANSEHBAR_VERSION` gibt es nicht. Auf
  GitHub unter *Releases* bzw. *Packages* nachsehen. Gibt es noch gar kein
  Release, bauen Sie aus dem Checkout (`up -d --build`, Schritt 10).
- `unauthorized`/`denied`: Das Image ist (noch) nicht öffentlich. Entweder in
  den Einstellungen des Pakets auf GitHub die Sichtbarkeit auf *Public*
  stellen lassen, oder am Server mit einem GitHub-Token (Recht
  `read:packages`) anmelden:
  `sudo docker login ghcr.io -u <github-benutzer>` und bei `Password:` das
  Token eingeben.

### Login: Fehlermeldungen des Identity Providers

- **„Invalid parameter: redirect_uri“**: Die Redirect-URI im Client stimmt
  nicht genau mit `https://ansehbar.example.org/oidc/callback/` überein
  (Schema, Host, Schrägstrich am Ende). Prüfen Sie auch `PUBLIC_BASE_URL`.
- **Abmelden endet mit „Invalid redirect uri“**: `Valid post logout redirect
  URIs` fehlt oder lautet anders als `https://ansehbar.example.org/`.
- **Nach der Anmeldung wieder auf der Startseite, nicht angemeldet**: Die
  Anmeldung ist gescheitert; im App-Log steht der Grund. Häufig: falsches
  `OIDC_RP_CLIENT_SECRET`, Client nicht vertraulich, oder die Uhrzeit des
  Servers stimmt nicht (`timedatectl` muss `System clock synchronized: yes`
  zeigen).
- **„Kein Zugang“ nach der Anmeldung**: Gruppe oder Gruppen-Claim fehlt
  ([Konfigurationsanleitung, Abschnitt 2](KONFIGURATION.md#wer-zugang-hat)).
- **CSRF-Fehler (403)** beim Speichern: `CSRF_TRUSTED_ORIGINS` muss genau
  `https://ansehbar.example.org` lauten.
- **„Bad Request (400)“** beim Aufruf: `DJANGO_ALLOWED_HOSTS` enthält den Host
  nicht.

### SELinux verweigert den Zugriff

Symptom: Caddy startet nicht und meldet `permission denied` beim Lesen von
`/etc/caddy/Caddyfile` oder den Zertifikaten. Prüfen:

```bash
sudo ausearch -m avc -ts recent | tail -20      # Einträge mit "denied" und "container_t"
ls -Z /opt/ansehbar/Caddyfile
```

Beheben: Label setzen (Schritt 9 bzw. Abschnitt 8), dann neu starten:

```bash
cd /opt/ansehbar
sudo chcon -t container_file_t Caddyfile
sudo docker compose -f docker-compose.prod.yml up -d --no-build
```

Schalten Sie SELinux dafür **nicht** ab.

### Kein HTTPS bzw. Zertifikatsfehler

```bash
sudo docker compose -f docker-compose.prod.yml logs caddy | grep -iE "challenge|obtain|error"
```

- `Timeout during connect (likely firewall problem)`: Port 80 oder 443 ist von
  außen gesperrt (firewalld, Netz-Firewall, Security-Group). Freischalten
  lassen (Schritt 4) oder ein HARICA-Zertifikat nutzen (Abschnitt 8).
- `NXDOMAIN` oder falsche IP: DNS stimmt nicht (Schritt 5).
- `rateLimited`: zu viele Fehlversuche bei Let's Encrypt. Ursache beheben und
  etwa eine Stunde warten, Caddy nicht in einer Schleife neu starten.
- Der Browser meldet ein unbekanntes Zertifikat bei HARICA: Die Kette fehlt in
  der `.pem`-Datei (Zwischenzertifikate anhängen, Abschnitt 8).

Nach der Behebung `sudo docker compose -f docker-compose.prod.yml restart caddy`
und mitlesen, bis `certificate obtained successfully` erscheint.

### Monitor erreicht Streaming-Server oder Opencast nicht

Der Monitor läuft im Container; er braucht ausgehend HTTPS zum
Streaming-Server und zu Opencast. Aus dem Container prüfen:

```bash
sudo docker compose -f docker-compose.prod.yml exec monitor \
  python -c "import httpx; print(httpx.get('https://<streaming-host>/', timeout=10).status_code)"
```

Ein Timeout heißt meist: Firewall des Rechenzentrums oder ein Proxy, den der
Container nicht kennt. Eine Statuszahl (auch 404) heißt: Die Verbindung steht.

### Docker startet nicht: fehlende Kernel-Module

Symptom: `systemctl enable --now docker` scheitert, `sudo journalctl -u docker`
zeigt Zeilen wie `missing kernel module?` oder
`failed to start daemon: Error initializing network controller`. Meist läuft
nach `dnf update` noch der alte Kernel. Neu starten:

```bash
sudo reboot
```

Hilft das nicht, fehlen auf Minimal-Images die Module:

```bash
sudo dnf -y install "kernel-modules-$(uname -r)"
sudo reboot
```

Danach `sudo systemctl reset-failed docker && sudo systemctl enable --now docker`.

### Keine Mails

Test-E-Mail unter **Verwaltung → Alarme** senden und das Monitor-Log lesen
(`logs monitor`). Typisch: `Connection refused` (falscher Host/Port oder keine
Freigabe der Server-IP am Mailserver), `STARTTLS extension not supported`
(`EMAIL_USE_TLS=0` setzen) oder Anmeldefehler
(`EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD`). Wie Sie offene Meldungen
einsehen, steht in der [Konfigurationsanleitung, Abschnitt 8](KONFIGURATION.md#8-prüfen-und-fehlersuche).

---

## 10. Checkliste

- [ ] Eigener `DJANGO_SECRET_KEY` (nicht der Platzhalter) und starkes
      `POSTGRES_PASSWORD`; `.env` mit `chmod 600`.
- [ ] `PUBLIC_BASE_URL`, `DJANGO_ALLOWED_HOSTS` und `CSRF_TRUSTED_ORIGINS`
      zeigen auf die echte Adresse (ohne Pfad, ohne `/` am Ende).
- [ ] `ACME_EMAIL` ist eine Funktionsadresse, die jemand liest.
- [ ] `ANSEHBAR_VERSION` ist auf ein Release gepinnt.
- [ ] OIDC-Client mit Redirect-, Post-Logout- und Backchannel-URL;
      Group-Membership-Mapper `groups`; Login getestet.
- [ ] Rekorder geladen oder angelegt; der Monitor meldet „live“ für einen
      laufenden Stream; Video und Pegel erscheinen im Browser.
- [ ] Optional: Opencast-Abgleich ohne Banner; Termine erscheinen unter
      „Heute noch geplant“.
- [ ] Alarm-Empfänger eingetragen; eine Test-E-Mail kam an.
- [ ] Optional: `METRICS_TOKEN` gesetzt, `/metrics` antwortet, Scrape-Eintrag
      und Alarmregeln an den Monitoring-Dienst übergeben.
- [ ] `ANSEHBAR_BOOTSTRAP_USERS` nach der Übergabe geleert.
- [ ] Cron für die Sicherung angelegt; Sicherungen landen außerhalb des
      Servers; eine Wiederherstellung wurde einmal geprobt.
- [ ] Nur Ports 80/443 (und SSH) offen; `db` und `app` sind nicht nach außen
      veröffentlicht (`expose` statt `ports`).
- [ ] Nach `sudo reboot` kommt der Stack von selbst wieder.
