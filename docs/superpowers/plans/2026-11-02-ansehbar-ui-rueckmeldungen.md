# ansehBAR Rückmeldungen nach Stufe 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Rückmeldungen nach dem ersten Betrieb mit dem echten Opencast umsetzen:
- Opencast-Fehler verständlich melden und einen Abgleich auf Knopfdruck anbieten.
- Rekorder löschen können.
- Kennzeichnen, welche Rekorder aus Opencast stammen.
- Header-Menü wie in den anderen -bar-Tools.
- Die ruhigen Räume auffälliger darstellen.
- Den Knopf „Pegel aktivieren“ überall zeigen.
- Icon-Knöpfe in der Verwaltung und ein verständlicher Schwellwert.

**Architecture:**
- Der Monitor-Prozess bleibt allein für den Abgleich zuständig.
- Ein Knopfdruck setzt nur `OpencastSyncState.requested_at`. Der Sync-Thread im Monitor sieht das im nächsten Zyklus und gleicht sofort ab.
- Fehler bekommen eine feste Kategorie (`error_kind`). Der Herzschlag liefert sie an die SPA, ohne Fehlertext und ohne URL.
- Gelöschte Opencast-Rekorder landen als `IgnoredAgent` auf einer Liste. Der Abgleich legt sie nicht wieder an.

**Tech Stack:** wie Stufe 2.

**Spec:** `docs/superpowers/specs/2026-10-30-ansehbar-design.md`. Neu ist Abschnitt 6a „Nachträge 2026-11-02“ (Task 1).

**Erkundet am echten Opencast (2026-11-02):**
- Die External API filtert `/api/events` nach den Zugriffsrechten der Events. Ohne `ROLE_ADMIN` sah das Konto nur 4 alte Events; ein Fehler kam dabei nicht.
- Für Seiten ohne Berechtigung liefert Opencast **HTTP 200** mit einer HTML-Seite, deren Titel `Opencast :: Forbidden` lautet. Bei manchen Pfaden ist der Content-Type sogar `application/json`.
- Mit `ROLE_ADMIN` liefert das Fenster 98 Events, davon 94 mit `scheduling`.
- Die Kollegen prüfen noch eine engere Rolle.
- Docker Compose interpoliert `$` in `.env`-Werten. Passwörter mit `$` müssen als `$$` geschrieben werden.

## Global Constraints

- SPDX-Header in jeder neuen Quelldatei. UI-Texte sind englische i18n-Keys mit deutscher Übersetzung; Backend-Texte laufen über gettext mit `.po`/`.mo`.
- **ansehBAR schreibt nie nach Opencast.** Der Knopf löst nur einen lesenden Abgleich aus.
- Fehlerkategorien und Meldungen enthalten nie Zugangsdaten, URLs oder Hostnamen.
- Status immer mit Text **und** Symbol; brand ist nie Statusfarbe; Dark-Mode-Text mindestens `slate-300`.
- Icon-Knöpfe haben ein sprechendes `aria-label` mit Raumnamen und einen `title`.
- Nie Browser-Dialoge; zum Bestätigen `ConfirmDialog`.
- Stream-Namen und Agent-IDs sind case-sensitiv.
- Keine Infrastrukturdetails im Repo; Fixtures sind fiktiv.
- Prettier nicht auf ganze Dateien anwenden; der bestehende Stil mit langen Zeilen bleibt.
- Befehle im Container; Commits enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Branch `feature/ui-feedback`; am Ende ein PR gegen `main`.

## Review Focus

1. **Aktiver Rekorder:** Er lässt sich nie löschen. Die API antwortet mit 409, und das Frontend zeigt dafür keinen Knopf. Test in Task 3.
2. **Gelöschter Opencast-Rekorder:** Er kommt beim nächsten Abgleich nicht wieder. Nach „Wieder zulassen“ erscheint er erneut als „Neu – bitte prüfen“. Test in Task 3.
3. **„Forbidden“-Seite mit HTTP 200:** Sie wird als Fehler `forbidden` erkannt, nie als leere Liste. Test in Task 2.
4. **Abgleich-Knopf während eines laufenden Abgleichs:** Es läuft kein zweiter Abgleich parallel. Die Anforderung wird nach dem laufenden Abgleich erfüllt. Test in Task 2.
5. **Agents ja, aber 0 Termine im Fenster:** Es gibt einen Hinweis `no_events` („Rechte prüfen“), aber keinen Fehlerzustand; die Daten werden trotzdem übernommen. Test in Task 2.

---

### Task 1: Spec-Nachtrag

**Files:** Modify `docs/superpowers/specs/2026-10-30-ansehbar-design.md`, nach Abschnitt 6.

- [ ] **Step 1:** Einen Abschnitt „### 6a Nachträge 2026-11-02“ mit genau diesen Punkten einfügen:
  - Abgleich auf Knopfdruck (Verwaltung → Rekorder und im Fehlerbanner). Er ist nur lesend.
  - Verständliche Meldung bei Problemen mit Opencast. Kategorien:
    - nicht erreichbar,
    - Anmeldung abgelehnt,
    - keine Berechtigung,
    - Zeitüberschreitung,
    - Serverfehler,
    - unerwartete Antwort,
    - Hinweis „keine Termine sichtbar“.
  - Deaktivierte Rekorder lassen sich endgültig löschen. Die Termine des Rekorders werden mitgelöscht. Opencast-Rekorder kommen dann auf eine Ignorierliste, die sich rückgängig machen lässt.
  - Rekorder aus Opencast tragen das Opencast-Logo (ECL-2.0, Quelle `opencast/opencast`, Datei `opencast-icon.svg`).
  - Rechte des API-Kontos: Ohne Leserecht auf die Events bleibt die Terminliste leer. Übergangsweise gilt `ROLE_ADMIN`; eine engere Rolle ist offen (siehe 10).
  - In Abschnitt 10 „Offen“ ergänzen: „Engere Opencast-Rolle für das ansehBAR-Konto (Kollegen klären)“.
- [ ] **Step 2:** Commit `docs(spec): Nachträge nach erstem Betrieb mit Opencast`.

### Task 2: Opencast-Fehlerkategorien und Abgleich auf Knopfdruck (Backend)

**Files:**
- Modify: `backend/opencast/client.py`, `sync.py`, `models.py` (+ Migration), `views.py` (neu), `tests.py`
- Modify: `backend/config/api_urls.py`, `backend/recorders/management/commands/run_monitor.py`, `backend/recorders/views.py` (`MonitorHealthView`), `backend/recorders/tests.py`

**Interfaces:**
- Produces:
  - `OpencastError(message: str, kind: str)`. `kind` ist eines von `"unreachable"` (Connect/DNS), `"auth"` (401), `"forbidden"` (403 oder eine HTML-Seite mit `Opencast :: Forbidden`), `"timeout"` (auch die Gesamtfrist), `"server"` (5xx), `"invalid"` (kein JSON, falsche Form, `max_pages`).
  - Im Client gilt eine Antwort, deren Body mit `<` beginnt (nach Whitespace) oder `Opencast :: Forbidden` enthält, als `forbidden`, und zwar vor dem JSON-Parsen und unabhängig vom Status.
  - `OpencastSyncState` bekommt zwei Felder:
    - `requested_at: DateTimeField(null=True)`
    - `last_error_kind: CharField(20, blank=True)`. Das ist eine der Kategorien von oben oder `"no_events"`. `no_events` heißt: Der Abgleich war erfolgreich, Agents > 0, aber 0 Events im Fenster.
  - `run_opencast_sync` setzt bei Erfolg `last_error_kind=""` oder `"no_events"` und bei `OpencastError` `last_error_kind=exc.kind`.
  - `POST /api/opencast/sync/` (Permission `HasAccess`):
    - Setzt `requested_at=now` und antwortet 202 mit `{"requested_at": iso}`.
    - Ist Opencast nicht konfiguriert, antwortet es 409 mit `{"detail": _("Opencast is not configured.")}`.
  - `GET /api/monitor/health/`: Der Block `opencast` bekommt `last_attempt` (iso|null), `error_kind` (string, `""` = ok) und `requested` (bool: `requested_at` gesetzt und neuer als `last_attempt_at`). Weiterhin gibt es keinen Fehlertext.
  - Im Monitor-Loop wird zusätzlich zum Intervall synchronisiert, wenn `requested_at > last_attempt_at` (oder `last_attempt_at` leer) gilt. Single-Flight bleibt erhalten. Läuft gerade ein Abgleich, wird die Anforderung danach erfüllt.

- [ ] **Step 1: Failing tests:**
  - `test_html_forbidden_with_200_is_forbidden_error`: Body `<!DOCTYPE html>…<title>Opencast :: Forbidden</title>`, Status 200, `Content-Type: application/json`. Ergebnis: `OpencastError.kind == "forbidden"`.
  - Je ein Test für `auth` (401), `server` (503), `unreachable` (ConnectError), `timeout` (Gesamtfrist) und `invalid` (`"{"`).
  - `test_sync_sets_no_events_hint`: 2 Agents, 0 Events. Ergebnis: `last_success_at` gesetzt, `last_error_kind == "no_events"`, die Agents sind übernommen.
  - `test_sync_error_kind_recorded`: Bei einem `OpencastError("…", "auth")` gilt `last_error_kind == "auth"`, und nichts wird übernommen.
  - `test_sync_request_endpoint`: Ergebnis 202, und `requested_at` ist gesetzt. Ohne `OPENCAST_URL` kommt 409. `outsider` bekommt 403.
  - `test_health_reports_request_and_error_kind`
  - `test_requested_sync_runs_before_interval`: Loop-Modus, Intervall 3600 s, `requested_at` neuer als `last_attempt_at`. Der Sync läuft im nächsten Zyklus.
  - `test_request_during_running_sync_is_served_after`: Der Sync blockiert, eine Anforderung kommt hinzu. Es gibt keinen zweiten parallelen Thread; nach dem Ende läuft genau ein weiterer Abgleich.
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** Implementieren. Die Migration erzeugt `makemigrations opencast`. Die neue Meldung kommt in `django.po` mit der deutschen Übersetzung „Opencast ist nicht konfiguriert.“; `.mo` kompilieren.
- [ ] **Step 4:** Backend-Suite, ruff und `makemigrations --check` grün.
- [ ] **Step 5:** Commit `feat(opencast): Fehlerkategorien, Hinweis ohne Termine, Abgleich auf Knopfdruck`.

### Task 3: Rekorder löschen und ignorierte Agents (Backend)

**Files:**
- Modify: `backend/opencast/models.py` (+ Migration), `sync.py`, `tests.py`
- Modify: `backend/recorders/views.py`, `serializers.py`, `tests.py`, `backend/config/api_urls.py`, `backend/locale/de/…`

**Interfaces:**
- Produces:
  - `opencast.models.IgnoredAgent`: `agent_id: CharField(100, unique)`, `created_at: auto_now_add`, `created_by: CharField(150, blank)` (Anzeigename oder Benutzername der löschenden Person). Ordering `agent_id`.
  - `DELETE /api/recorders/{id}/`:
    - Nur erlaubt, wenn `active=False`. Sonst 409 mit `{"detail": _("Only deactivated recorders can be deleted.")}`.
    - Hat der Rekorder eine `agent_id`, wird in derselben Transaktion `IgnoredAgent` per `get_or_create` angelegt.
    - Antwort 204. Status und Termine werden per CASCADE mitgelöscht.
  - `sync_agents` überspringt Agents, deren ID in `IgnoredAgent` steht: kein Anlegen, kein Verknüpfen, kein WARNING-Log.
  - `GET /api/ignored-agents/` liefert die Liste `[{id, agent_id, created_at, created_by}]`. `DELETE /api/ignored-agents/{id}/` antwortet 204. Beide mit Permission `HasAccess`.
- [ ] **Step 1: Failing tests:**
  - `test_delete_active_recorder_refused` → 409, der Rekorder bleibt bestehen.
  - `test_delete_inactive_recorder_cascades`: Status und Events sind weg.
  - `test_delete_opencast_recorder_ignores_agent` → `IgnoredAgent` existiert; danach legt `sync_agents([…dieser Agent…])` nichts an.
  - `test_unignore_lets_agent_return`: `DELETE /api/ignored-agents/{id}/`, dann `sync_agents` → der Rekorder ist wieder da, mit `needs_review=True`.
  - `test_ignored_agents_requires_access`
  - Den bestehenden `test_delete_not_allowed` (405) an das neue Verhalten anpassen.
- [ ] **Step 2–4:** FAIL, dann implementieren (die neue Meldung kommt in `django.po` mit „Nur deaktivierte Rekorder können gelöscht werden.“), dann grün. Dazu ruff und `makemigrations --check`.
- [ ] **Step 5:** Commit `feat(recorders): deaktivierte Rekorder löschen, ignorierte Opencast-Agents`.

### Task 4: Header-Menü wie in den anderen -bar-Tools

**Files:** Modify `frontend/src/App.tsx`. Create `frontend/src/components/UserMenu.tsx`. Locales.

**Interfaces:**
- Vorbild ist `UserMenu` in `~/dev/abstimmbar/frontend/src/App.tsx`, nur lesen, nicht kopieren, was abstimmBAR-spezifisch ist:
  - Avatar-Kreis mit Initiale (`bg-brand-400`).
  - `role="menu"`; schließt bei Klick außerhalb und mit Escape.
  - Auf dem Smartphone `max-sm:fixed max-sm:left-4 max-sm:right-4`.
  - Einträge: „Signed in as {Name}“, dann `LanguageOptions`, dann `AppearanceControl`, dann „Sign out“ (`logoutUrl`). Trennlinien wie im Vorbild.
- Angemeldet: genau **ein** Knopf, das Avatar-Menü. Der bisherige `PreferencesMenu`-Knopf und das Logout-Icon entfallen. Die Sprachwahl ruft weiter `api.setLanguage(lang)` auf.
- Nicht angemeldet: **zwei** Knöpfe, „Sign in“ als Text-Knopf (`bg-brand-400 … font-semibold`, Link auf `loginUrl`) und `PreferencesMenu`.
- `LanguageOptions` und `AppearanceControl` kommen aus `@basicbar/ui`. Gibt die installierte Version sie nicht her, auf `NEEDS_CONTEXT` gehen; nicht nachbauen.
- Keys (EN → DE): `"User menu"` → „Benutzermenü“, `"Signed in as"` → „Angemeldet als“. Die übrigen Keys gibt es schon oder sie kommen aus `@basicbar/ui`.
- [ ] **Step 1:** Umsetzen. `npx tsc -b`, `npm test` und `check:i18n` sind grün.
- [ ] **Step 2:** Commit `feat(frontend): Benutzermenü wie in den anderen -bar-Tools`.

### Task 5: Übersicht und Opencast-Kennzeichnung

**Files:**
- Modify: `frontend/src/pages/Overview.tsx`, `pages/RoomView.tsx`, `components/StatusBadge.tsx`, `components/RecorderTile.tsx`, `components/RoomList.tsx`, `components/MonitorBanner.tsx`, `api.ts`, `recorders.ts` (+ Tests), `useRecorders.ts`, Locales, `NOTICE`
- Create: `frontend/src/components/OpencastIcon.tsx`, `components/RoomPills.tsx`

**Interfaces:**
- **`OpencastIcon`:**
  - Pfade aus `opencast/opencast`, Datei `modules/engage-ui/src/main/resources/ui/img/logo/opencast-icon.svg` (per `gh api repos/opencast/opencast/contents/<pfad>`, base64), reduziert auf `viewBox` und Pfade.
  - Farbe über `currentColor` oder die Originalfarben; Hauptsache in Hell und Dunkel erkennbar.
  - Props `className`. Darstellung `role="img"`, `aria-label={t("From Opencast")}` und `title`.
  - Im Dateikopf ein Kommentar zu Quelle und Lizenz (ECL-2.0). In `NOTICE` eine Zeile: „Opencast-Logo: © Apereo Foundation, ECL-2.0, aus github.com/opencast/opencast“.
  - Angezeigt bei Rekordern mit `agent_id`: in der Kachel neben dem Stream-Namen, in der Raumansicht in der Agent-Zeile, in der Verwaltungsliste und in den Pills.
- **`RoomPills({ title, icon, recorders })`:**
  - Eine Überschrift `h2` (`text-lg font-bold`), darunter `ul` mit `flex flex-wrap gap-2`.
  - Pro Raum ein Link-Pill `rounded-full border px-3 py-1.5` mit Icon, `displayName`, gegebenenfalls `OpencastIcon` und dem Hinweis „Raumname fehlt“.
  - Ersetzt die Fließtext-Zeilen „Heute ohne Aufzeichnung“ (Icon `CalendarX2`), „Status unbekannt“ (Icon `HelpCircle`) und „Derzeit ohne Stream“ (ohne Opencast; Icon `VideoOff`). Die Inhalte bleiben gleich (Regel R5: unbekannte Räume nur in „Status unbekannt“).
- **Pegel-Knopf:** `AudioUnlockButton` erscheint auch auf schmalen Bildschirmen in der Übersicht, über der Liste, und in der Raumansicht über dem Player, solange der Ton nicht freigeschaltet ist.
- **`StatusBadge`:** `whitespace-nowrap`, damit „Kein Stream“ einzeilig bleibt; das gilt für alle Zustände.
- **Opencast-Meldung:**
  - `api.ts` `MonitorHealth.opencast` bekommt `last_attempt`, `error_kind` und `requested`.
  - `useRecorders` liefert zusätzlich `opencastErrorKind: string` und `opencastRequested: boolean`.
  - `MonitorBanner` zeigt bei `error_kind ∉ {"", "no_events"}` sofort eine Fehlermeldung, also nicht erst bei „veraltet“.
  - Bei `no_events` zeigt er einen Hinweis.
  - Neben der Meldung steht jeweils der Knopf „Jetzt abgleichen“: `POST /api/opencast/sync/`, deaktiviert solange `requested`, Text „Abgleich läuft …“.
  - Texte als Keys (EN → DE), Literal-`t()` über eine Map in `recorders.ts` oder im Banner:
    - `"Opencast not reachable"` → „Opencast nicht erreichbar“
    - `"Opencast rejected the login"` → „Opencast hat die Anmeldung abgelehnt“
    - `"No permission in Opencast"` → „Keine Berechtigung in Opencast“
    - `"Opencast did not answer in time"` → „Opencast antwortet nicht rechtzeitig“
    - `"Opencast server error"` → „Opencast-Serverfehler“
    - `"Unexpected answer from Opencast"` → „Unerwartete Antwort von Opencast“
    - `"Opencast shows no scheduled recordings – check the account's permissions"` → „Opencast zeigt keine geplanten Aufzeichnungen – Rechte des Kontos prüfen“
    - `"Sync now"` → „Jetzt abgleichen“
    - `"Sync running…"` → „Abgleich läuft …“
    - `"From Opencast"` → „aus Opencast“
    - `"Currently without stream"` → bestehender Key
  - Ein reiner Helfer `opencastNotice(health): {level: "error"|"hint"|null, key}` in `recorders.ts` mit vitest-Tests für jede Kategorie und für `""`.
- [ ] **Step 1:** Tests für `opencastNotice` schreiben → FAIL; implementieren → PASS.
- [ ] **Step 2:** Alles Übrige umsetzen. `npm test`, `tsc -b` und `check:i18n` sind grün.
- [ ] **Step 3:** Commit `feat(frontend): Raum-Pills, Opencast-Logo, Opencast-Meldungen, Pegel-Knopf überall`.

### Task 6: Verwaltung: Icon-Knöpfe, Löschen, ignorierte Agents, Abgleich, Schwellwert

**Files:** Modify `frontend/src/pages/admin/RecordersAdmin.tsx`, `pages/admin/SettingsAdmin.tsx`, `api.ts`, `admin.ts` (+ Tests), Locales.

**Interfaces:**
- Consumes: Task 2, 3 und 5 (`OpencastIcon`, die Endpunkte).
- **Zeilen-Knöpfe als Icon-Knöpfe** (lucide), jeweils mit `aria-label` inklusive Raum und `title`:
  - `Pencil`: „Bearbeiten“.
  - `PowerOff`: „Deaktivieren“ bei aktiven Rekordern; `Power`: „Aktivieren“ bei inaktiven.
  - `Trash2`: „Löschen“, **nur** bei inaktiven Rekordern.
- **Löschen** fragt per `ConfirmDialog`: Titel „Rekorder löschen?“. Text: „{{room}} wird mit Status und Terminen endgültig gelöscht.“ Bei Opencast-Rekordern zusätzlich: „Der Opencast-Agent {{agent}} wird künftig ignoriert.“ Bestätigen-Knopf „Löschen“. Ein 409 wird als Fehlermeldung angezeigt.
- **Abschnitt „Ignorierte Opencast-Agents“** unter der Liste, nur wenn nicht leer: Liste mit Agent-ID, Datum und Person; Knopf „Wieder zulassen“ mit dem Hinweis, dass der Agent beim nächsten Abgleich als „Neu – bitte prüfen“ zurückkommt.
- **Oben auf der Seite** neben „Rekorder hinzufügen“ der Knopf „Opencast jetzt abgleichen“, nur wenn Opencast an ist. Daneben „Letzter Abgleich: HH:MM“ und gegebenenfalls die Fehlermeldung aus `opencastNotice`. Nach dem Klick wird der Herzschlag alle 2 s abgefragt, bis `requested` false ist; dann wird die Liste neu geladen.
- **Einstellungen:** `stale_factor` wird umbenannt in „Toleranz bis „Stream beendet““ mit der Einheit „× Segmentdauer“. Hilfetext: „Ein Live-Stream liefert alle paar Sekunden ein neues Videostück (meist alle 6 s). So viele Stück-Längen darf kein neues kommen, bevor der Stream als beendet gilt. Standard 3 ≈ 18 Sekunden.“
- Alle neuen Texte als Keys mit deutscher Übersetzung. Reine Helfer (Payloads, Sortierung) in `admin.ts` mit Tests.
- [ ] **Step 1:** Helfer-Tests → FAIL → PASS.
- [ ] **Step 2:** UI umsetzen. `npm test`, `tsc -b` und `check:i18n` sind grün.
- [ ] **Step 3:** Commit `feat(frontend): Verwaltung mit Icon-Knöpfen, Löschen, Ignorierliste, Abgleich-Knopf`.

### Task 7: Doku und Abnahme

**Files:** `docs/KONFIGURATION.md`, `README.md`, `.env.prod.example`.

- [ ] **Step 1: `KONFIGURATION.md`:**
  - Abschnitt Opencast: Die Event-Liste wird nach Rechten gefiltert. Übergangsweise `ROLE_ADMIN`; eine engere Lösung wird geklärt.
  - Erklären, dass HTML-„Forbidden“ mit Status 200 als „Keine Berechtigung“ gemeldet wird.
  - Den Knopf „Jetzt abgleichen“ beschreiben.
  - Die Fehlerkategorien in der Fehlersuche-Tabelle aufführen.
  - Hinweis: In `.env` muss `$` als `$$` geschrieben werden.
  - Löschen und ignorierte Agents beschreiben.
- [ ] **Step 2:** `.env.prod.example`: Kommentar zu `$$` bei `OPENCAST_PASSWORD`. README: Variablentabelle unverändert, Stand-Zeile ergänzen.
- [ ] **Step 3:** Alle Checks laufen lassen: Backend-Tests, ruff, `makemigrations --check`, `npm test`, `tsc -b`, `check:i18n`.
- [ ] **Step 4:** Commit `docs: Opencast-Rechte, Fehlermeldungen, Löschen`.
