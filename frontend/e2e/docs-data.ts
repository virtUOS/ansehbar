// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Synthetic API answers for the website screenshots (docs-screenshots.spec.ts).
 *
 *  Every room, title, address and stream here is made up; the screenshot run
 *  answers all /api/ requests from this module and never touches the dev
 *  database, so no real infrastructure name can end up in a picture. The
 *  types come from the app's API client, so a changed API breaks this file
 *  at compile time instead of silently producing wrong pictures. */
import type {
  AlarmRecipient,
  CalendarEvent,
  CalendarResponse,
  EventBrief,
  EventDetail,
  IgnoredAgent,
  IncidentEntry,
  Invitation,
  LastRecording,
  MonitorHealth,
  MonitorSettings,
  Recorder,
  Whoami,
} from "../src/api";

export type Lang = "de" | "en";

/** The frozen clock of all screenshots: Tuesday, 10 Nov 2026, 10:47 (CET). */
export const NOW = at(0, 10, 47);
/** Host of the fake streams; the spec serves them from generated files. */
export const STREAM_HOST = "https://streams.example.org";

/** ISO time `day` days after the screenshot day at hh:mm local (CET, +01:00). */
export function at(day: number, h: number, m: number, s = 0): string {
  return new Date(Date.UTC(2026, 10, 10 + day, h - 1, m, s)).toISOString();
}

export function playbackUrl(stream: string): string {
  return `${STREAM_HOST}/live/${stream}/playlist.m3u8`;
}

interface Room {
  id: number;
  name: Record<Lang, string>;
  stream: string;
  agent: string | null;
}

const ROOMS: Room[] = [
  { id: 1, name: { de: "Hörsaal A", en: "Lecture Hall A" }, stream: "cap-hs-a", agent: "ca-hs-a" },
  { id: 2, name: { de: "Hörsaal B", en: "Lecture Hall B" }, stream: "cap-hs-b", agent: "ca-hs-b" },
  { id: 3, name: { de: "Seminarraum 1.12", en: "Seminar Room 1.12" }, stream: "cap-sr-112", agent: "ca-sr-112" },
  { id: 4, name: { de: "Aula", en: "Auditorium" }, stream: "cap-aula", agent: "ca-aula" },
  { id: 5, name: { de: "Seminarraum 2.05", en: "Seminar Room 2.05" }, stream: "cap-sr-205", agent: "ca-sr-205" },
  { id: 6, name: { de: "Labor 0.04", en: "Lab 0.04" }, stream: "cap-lab-004", agent: "ca-lab-004" },
  { id: 7, name: { de: "Hörsaal C", en: "Lecture Hall C" }, stream: "cap-hs-c", agent: "ca-hs-c" },
  { id: 8, name: { de: "Seminarraum 3.01", en: "Seminar Room 3.01" }, stream: "cap-sr-301", agent: null },
  // Newly taken over from Opencast: no room name yet.
  { id: 9, name: { de: "", en: "" }, stream: "cap-neu-01", agent: "ca-neu-01" },
];

/** Room id of the room shown in room view, calendar and day view. */
export const MAIN_ROOM = 1;

function tr(lang: Lang, de: string, en: string): string {
  return lang === "de" ? de : en;
}

function event(id: number, title: string, series: string, start: string, end: string): EventBrief {
  return { id, title, series, presenters: "", start, end };
}

/** Events per room id (today and later today). */
function schedule(lang: Lang) {
  const stat = tr(lang, "Einführung in die Statistik", "Introduction to Statistics");
  return {
    current: {
      1: event(101, stat, stat, at(0, 10, 0), at(0, 12, 0)),
      2: event(102, tr(lang, "Organische Chemie I", "Organic Chemistry I"), "", at(0, 10, 0), at(0, 12, 0)),
      3: event(103, tr(lang, "Europäische Geschichte", "European History"), "", at(0, 10, 0), at(0, 12, 0)),
    } as Record<number, EventBrief>,
    upcoming: {
      1: [event(111, tr(lang, "Lineare Algebra", "Linear Algebra"), "", at(0, 14, 0), at(0, 16, 0))],
      2: [event(112, tr(lang, "Biochemie", "Biochemistry"), "", at(0, 12, 0), at(0, 14, 0))],
      4: [event(114, tr(lang, "Ringvorlesung Nachhaltigkeit", "Lecture series: Sustainability"), "", at(0, 18, 0), at(0, 20, 0))],
      5: [
        event(115, tr(lang, "Mikroökonomie", "Microeconomics"), "", at(0, 12, 0), at(0, 14, 0)),
        event(116, tr(lang, "Statistik-Tutorium", "Statistics tutorial"), "", at(0, 16, 0), at(0, 18, 0)),
      ],
      6: [event(117, tr(lang, "Physikalisches Praktikum", "Physics lab course"), "", at(0, 14, 0), at(0, 16, 0))],
    } as Record<number, EventBrief[]>,
  };
}

const LAB_LAST: LastRecording = {
  title: "",
  presenters: "",
  start: at(-1, 14, 0),
  end: at(-1, 16, 0),
  opencast_status: "EVENTS.EVENTS.STATUS.PROCESSING_FAILURE",
  problems: [{ kind: "processing_failed" }],
};

export function recorders(lang: Lang): Recorder[] {
  const { current, upcoming } = schedule(lang);
  return ROOMS.map((room) => {
    const id = room.id;
    const live = id === 1 || id === 2;
    const ups = upcoming[id] ?? [];
    return {
      id,
      room_name: room.name[lang],
      stream_name: room.stream,
      agent_id: room.agent,
      active: true,
      needs_review: id === 9,
      alarm_mode: id === 4 ? "grid" : id === 8 ? "off" : "exact",
      playback_url: playbackUrl(room.stream),
      status: {
        state: live ? "live" : "offline",
        live_since: id === 1 ? at(0, 10, 7) : id === 2 ? at(0, 9, 58) : null,
        checked_at: NOW,
        agent_state: room.agent ? (live || id === 3 ? "capturing" : "idle") : "",
        agent_updated_at: NOW,
      },
      current_event: current[id] ?? null,
      next_event: ups[0] ?? null,
      next_event_tomorrow: null,
      upcoming_today: ups,
      upcoming_tomorrow: [],
      missing_since: id === 3 ? at(0, 10, 3) : null,
      last_recording:
        id === 6 ? { ...LAB_LAST, title: tr(lang, "Physikalisches Praktikum", "Physics lab course") } : null,
      audio_level_db: id === 1 ? -23.5 : id === 2 ? -63.0 : null,
      silent_since: id === 2 ? at(0, 10, 31) : null,
    } satisfies Recorder;
  });
}

export function whoami(lang: Lang): Whoami {
  return {
    authenticated: true,
    username: "amuster",
    first_name: "Alex",
    last_name: "Muster",
    email: "alex.muster@example.org",
    is_staff: false,
    language: lang,
    csrf_token: "docs",
    ai_enabled: false,
    content_default_language: lang,
    content_translation_enabled: false,
    has_access: true,
    access_contact: "",
  };
}

export function health(): MonitorHealth {
  return {
    last_check: NOW,
    now: NOW,
    interval_seconds: 10,
    slots: { minutes: 120, offset_minutes: 0 },
    opencast: {
      enabled: true,
      insecure_url: false,
      last_success: at(0, 10, 46, 20),
      sync_seconds: 60,
      last_attempt: at(0, 10, 46, 20),
      error_kind: "",
      requested: false,
    },
  };
}

export function settings(): MonitorSettings {
  return {
    url_template: `${STREAM_HOST}/live/{stream}/playlist.m3u8`,
    stale_factor: 3,
    missing_grace_minutes: 3,
    slot_minutes: 120,
    slot_offset_minutes: 0,
    ct_minutes: 15,
    ct_tolerance_minutes: 5,
    end_tolerance_minutes: 5,
    alarm_email_enabled: true,
    alarm_metrics_enabled: true,
    silence_threshold_db: -50,
    silence_log_minutes: 2,
    silence_alarm_minutes: 15,
    sample_retention_days: 30,
    history_retention_days: 400,
  };
}

export function recipients(): AlarmRecipient[] {
  return [
    { id: 1, email: "medientechnik@example.org", user: null, display_name: "", active: true, created_at: at(-30, 9, 0), created_by: "Alex Muster" },
    { id: 2, email: "kim.beispiel@example.org", user: 7, display_name: "Kim Beispiel", active: true, created_at: at(-20, 9, 0), created_by: "Alex Muster" },
    { id: 3, email: "rufbereitschaft@example.org", user: null, display_name: "", active: false, created_at: at(-12, 9, 0), created_by: "Alex Muster" },
  ];
}

export function invitations(lang: Lang): Invitation[] {
  return [
    { id: 1, identifier: "kim.beispiel@example.org", note: tr(lang, "Medientechnik, Vertretung", "Media services, deputy"), created_by_name: "Alex Muster", created_at: at(-20, 9, 0) },
    { id: 2, identifier: "jbeispiel", note: tr(lang, "Studentische Hilfskraft", "Student assistant"), created_by_name: "Alex Muster", created_at: at(-6, 14, 30) },
  ];
}

export function ignoredAgents(): IgnoredAgent[] {
  return [];
}

// ------------------------------------------------------ calendar and detail

function incident(id: number, kind: IncidentEntry["kind"], started: string, ended: string | null, extra: Partial<IncidentEntry> = {}): IncidentEntry {
  return { id, kind, started_at: started, ended_at: ended, recovered: ended !== null, alerted_at: null, all_clear_at: null, silent_until: kind === "audio_silent" ? ended : null, ...extra };
}

const PROCESSED = "EVENTS.EVENTS.STATUS.PROCESSED";
const SCHEDULED = "EVENTS.EVENTS.STATUS.SCHEDULED";

/** Week Mon 9 – Sun 15 Nov of the main room. */
function weekEvents(lang: Lang): CalendarEvent[] {
  const stat = tr(lang, "Einführung in die Statistik", "Introduction to Statistics");
  const algebra = tr(lang, "Lineare Algebra", "Linear Algebra");
  const ev = (id: number, title: string, day: number, h: number, m: number, minutes: number, status: string, rest: Partial<CalendarEvent> = {}): CalendarEvent => {
    const start = at(day, h, m);
    return {
      id, recorder_id: MAIN_ROOM, title, series: title, start,
      end: new Date(Date.parse(start) + minutes * 60_000).toISOString(),
      opencast_status: status, first_audio_at: null, incidents: [], problems: [], ...rest,
    };
  };
  return [
    ev(201, stat, -1, 10, 0, 120, PROCESSED, { first_audio_at: at(-1, 10, 17) }),
    ev(202, algebra, -1, 14, 0, 120, PROCESSED, {
      first_audio_at: at(-1, 14, 19),
      incidents: [incident(21, "audio_silent", at(-1, 14, 52), at(-1, 14, 58))],
    }),
    ev(203, tr(lang, "Kolloquium Datenanalyse", "Data analysis colloquium"), -1, 16, 0, 120, "EVENTS.EVENTS.STATUS.PROCESSING_FAILURE", {
      first_audio_at: at(-1, 16, 16),
      problems: [{ kind: "processing_failed" }],
    }),
    { ...ev(101, stat, 0, 10, 0, 120, "EVENTS.EVENTS.STATUS.RECORDING"), ...runningDetailParts() },
    ev(111, algebra, 0, 14, 0, 120, SCHEDULED),
    ev(204, tr(lang, "Statistik-Tutorium", "Statistics tutorial"), 1, 16, 0, 120, SCHEDULED),
    ev(205, stat, 2, 10, 0, 120, SCHEDULED),
    ev(206, algebra, 3, 14, 0, 120, SCHEDULED),
  ];
}

function runningDetailParts(): Pick<CalendarEvent, "first_audio_at" | "incidents"> {
  return {
    first_audio_at: at(0, 10, 16),
    incidents: [
      incident(11, "stream_missing", at(0, 10, 3), at(0, 10, 7), { alerted_at: at(0, 10, 4), all_clear_at: at(0, 10, 8) }),
      incident(12, "audio_silent", at(0, 10, 31), at(0, 10, 35)),
    ],
  };
}

export function calendar(lang: Lang, from: string, days: number): CalendarResponse {
  const start = Date.parse(`${from}T00:00:00+01:00`);
  const end = start + days * 86_400_000;
  const room = ROOMS[MAIN_ROOM - 1];
  return {
    from: new Date(start).toISOString(),
    to: new Date(end).toISOString(),
    recorders: [{ id: room.id, room_name: room.name[lang], stream_name: room.stream, active: true }],
    events: weekEvents(lang).filter((e) => Date.parse(e.start) < end && Date.parse(e.end) > start),
  };
}

/** Deterministic pseudo-random level around `base` (no Math.random: stable pictures). */
function wobble(i: number, base: number): number {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return Math.round((base + ((x - Math.floor(x)) - 0.5) * 9) * 10) / 10;
}

export function eventDetail(lang: Lang, id: number): EventDetail {
  const ev = weekEvents(lang).find((e) => e.id === id) ?? weekEvents(lang)[0];
  const samples: EventDetail["samples"] = [];
  const startMs = Date.parse(ev.first_audio_at ?? ev.start) - 120_000;
  const endMs = Math.min(Date.parse(ev.end), Date.parse(NOW));
  let i = 0;
  for (let t = startMs; t <= endMs; t += 30_000, i++) {
    const iso = new Date(t).toISOString();
    const silent = ev.incidents.some(
      (inc) => inc.kind === "audio_silent" && Date.parse(inc.started_at) <= t && t < Date.parse(inc.ended_at ?? NOW),
    );
    const beforeSound = ev.first_audio_at !== null && t < Date.parse(ev.first_audio_at);
    samples.push({ t: iso, db: silent || beforeSound ? wobble(i, -61) : wobble(i, -26) });
  }
  return {
    id: ev.id,
    recorder_id: ev.recorder_id,
    title: ev.title,
    series: ev.series,
    start: ev.start,
    end: ev.end,
    opencast_status: ev.opencast_status,
    first_audio_at: ev.first_audio_at,
    threshold_db: -50,
    incidents: ev.incidents,
    samples: Date.parse(ev.start) > Date.parse(NOW) ? [] : samples,
  };
}

/** Title shown on the fake picture of a room's stream. */
export function slideFor(lang: Lang, roomId: number): { title: string; subtitle: string } {
  const { current } = schedule(lang);
  const ev = current[roomId];
  return {
    title: ev?.title ?? ROOMS[roomId - 1].name[lang],
    subtitle: ROOMS[roomId - 1].name[lang],
  };
}

export const LIVE_ROOMS = [1, 2];
export function streamOf(roomId: number): string {
  return ROOMS[roomId - 1].stream;
}
