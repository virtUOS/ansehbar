// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Minimal API client: session state + CSRF, ready to grow with the tool. */

// Same origin in production (the SPA is served next to the API behind Caddy);
// only the Vite dev server needs the backend container's host port.
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "http://localhost:8007" : "");

export const loginUrl = `${API_BASE}/oidc/authenticate/`;
export const silentLoginUrl = `${API_BASE}/oidc/silent/`;
export const logoutUrl = `${API_BASE}/oidc/logout-redirect/`;

export interface Whoami {
  authenticated: boolean;
  username?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  subject?: string;
  is_staff?: boolean;
  language?: string;
  csrf_token: string;
  ai_enabled: boolean;
  content_default_language: string;
  content_translation_enabled: boolean;
  has_access: boolean;
  access_contact: string;
}

export type RecorderState = "live" | "offline" | "unknown";

/** An Opencast event (ISO datetimes). */
export interface EventBrief {
  id: number;
  title: string;
  series: string;
  presenters: string;
  start: string;
  end: string;
}

export type IncidentKind = "stream_missing" | "audio_silent";

export interface IncidentEntry {
  id: number;
  kind: IncidentKind;
  started_at: string;
  ended_at: string | null;
  recovered: boolean;
  alerted_at: string | null;
  all_clear_at: string | null;
  silent_until: string | null;
}

export interface CalendarEvent {
  id: number;
  recorder_id: number;
  title: string;
  series: string;
  start: string;
  end: string;
  opencast_status: string;
  first_audio_at: string | null;
  incidents: IncidentEntry[];
  problems: RecordingProblem[];
}

export interface CalendarResponse {
  from: string;
  to: string;
  recorders: { id: number; room_name: string; stream_name: string; active: boolean }[];
  events: CalendarEvent[];
}

export interface LevelSample {
  t: string;
  db: number | null;
}

export interface EventDetail {
  id: number;
  recorder_id: number;
  title: string;
  series: string;
  start: string;
  end: string;
  opencast_status: string;
  first_audio_at: string | null;
  /** Current silence threshold (dBFS). */
  threshold_db: number;
  incidents: IncidentEntry[];
  samples: LevelSample[];
}

export type RecordingProblemKind =
  | "stream_missing"
  | "audio_silent"
  | "processing_failed"
  | "recording_failed"
  | "not_started"
  | "not_finished";

export interface RecordingProblem {
  kind: RecordingProblemKind;
  /** Only on "stream_missing" and "audio_silent". */
  from?: string;
  to?: string;
  minutes?: number;
}

/** The room's most recent finished recording and what went wrong with it. */
export interface LastRecording {
  title: string;
  presenters: string;
  start: string;
  end: string;
  opencast_status: string;
  problems: RecordingProblem[];
}

/** "exact": alarm from the Opencast start; "grid": from the slot start + c.t.;
 *  "off": incidents are only logged. */
export type AlarmMode = "exact" | "grid" | "off";

export interface Recorder {
  id: number;
  room_name: string;
  stream_name: string;
  agent_id: string | null;
  active: boolean;
  needs_review: boolean;
  alarm_mode: AlarmMode;
  playback_url: string;
  status: {
    state: RecorderState;
    live_since: string | null;
    checked_at: string | null;
    /** "" = never seen. */
    agent_state: string;
    agent_updated_at: string | null;
  };
  current_event: EventBrief | null;
  next_event: EventBrief | null;
  /** First event of the next local day. */
  next_event_tomorrow: EventBrief | null;
  /** All events starting later today / tomorrow (local), soonest first. */
  upcoming_today: EventBrief[];
  upcoming_tomorrow: EventBrief[];
  missing_since: string | null;
  last_recording: LastRecording | null;
  /** Server-measured level (dBFS, ≥ −91); null without a measurement of the last 120 s. */
  audio_level_db: number | null;
  /** Start of the open silence in the running event; null otherwise. */
  silent_since: string | null;
}

/** Monitor heartbeat; `now` is the server clock (compare against it, not the browser's). */
export interface MonitorHealth {
  last_check: string | null;
  now: string;
  interval_seconds: number;
  /** Recording slots: `minutes` long, starting `offset_minutes` after local midnight. */
  slots: SlotConfig;
  opencast: {
    enabled: boolean;
    /** OPENCAST_URL is set but refused (plain http:// in production). */
    insecure_url: boolean;
    last_success: string | null;
    sync_seconds: number;
    last_attempt: string | null;
    /** "" | "unreachable" | "auth" | "forbidden" | "timeout" | "server" | "invalid" | "internal" | "no_events" */
    error_kind: string;
    /** A manual sync was requested and has not run yet. */
    requested: boolean;
  };
}

export interface Invitation {
  id: number;
  identifier: string;
  note: string;
  created_by_name: string;
  created_at: string;
}

export interface SlotConfig {
  minutes: number;
  offset_minutes: number;
}

export interface MonitorSettings {
  url_template: string;
  stale_factor: number;
  missing_grace_minutes: number;
  slot_minutes: number;
  slot_offset_minutes: number;
  ct_minutes: number;
  ct_tolerance_minutes: number;
  end_tolerance_minutes: number;
  alarm_email_enabled: boolean;
  alarm_metrics_enabled: boolean;
  silence_threshold_db: number;
  silence_log_minutes: number;
  silence_alarm_minutes: number;
  sample_retention_days: number;
  history_retention_days: number;
}

export interface AlarmRecipient {
  id: number;
  email: string;
  user: number | null;
  /** "" without a linked user. */
  display_name: string;
  active: boolean;
  created_at: string;
  created_by: string;
}

export interface IgnoredAgent {
  id: number;
  agent_id: string;
  created_at: string;
  created_by: string;
}

export interface UserHit {
  id: number;
  username: string;
  email: string;
  display_name: string;
}

/** Thrown for non-2xx responses; `fieldErrors` holds DRF's `{field: [msg]}`. */
export class ApiError extends Error {
  status: number;
  fieldErrors: Record<string, string[]>;
  constructor(message: string, status: number, fieldErrors: Record<string, string[]> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

let csrfToken = "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      // FormData bodies get their multipart boundary from the browser.
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      // Django's LocaleMiddleware picks the language for server-side messages;
      // @basicbar/ui keeps <html lang> in sync with the UI language.
      "Accept-Language": (typeof document !== "undefined" && document.documentElement.lang) || "en",
      ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    const fieldErrors: Record<string, string[]> = {};
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body && typeof body === "object") {
        for (const [key, value] of Object.entries(body)) {
          if (Array.isArray(value)) fieldErrors[key] = value.map(String);
          else if (typeof value === "string") fieldErrors[key] = [value];
        }
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status, fieldErrors);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  whoami: async (): Promise<Whoami> => {
    const data = await request<Whoami>("/api/whoami/");
    csrfToken = data.csrf_token;
    return data;
  },
  setLanguage: (language: string) =>
    request<{ language: string }>("/api/whoami/language/", {
      method: "POST",
      body: JSON.stringify({ language }),
    }),
  recorders: {
    list: () => request<Recorder[]>("/api/recorders/"),
    get: (id: number) => request<Recorder>(`/api/recorders/${id}/`),
    create: (data: Partial<Recorder>) =>
      request<Recorder>("/api/recorders/", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Recorder>) =>
      request<Recorder>(`/api/recorders/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
    remove: (id: number) => request<void>(`/api/recorders/${id}/`, { method: "DELETE" }),
  },
  calendar: (recorderId: number, from: string, days: number) =>
    request<CalendarResponse>(
      `/api/recorders/${recorderId}/calendar/?from=${encodeURIComponent(from)}&days=${days}`,
    ),
  event: (id: number) => request<EventDetail>(`/api/events/${id}/`),
  ignoredAgents: {
    list: () => request<IgnoredAgent[]>("/api/ignored-agents/"),
    remove: (id: number) => request<void>(`/api/ignored-agents/${id}/`, { method: "DELETE" }),
  },
  monitor: {
    health: () => request<MonitorHealth>("/api/monitor/health/"),
  },
  opencast: {
    /** Asks the monitor for an immediate (read-only) sync. */
    sync: () => request<{ requested_at: string }>("/api/opencast/sync/", { method: "POST" }),
  },
  invitations: {
    list: () => request<Invitation[]>("/api/invitations/"),
    create: (data: { identifier: string; note: string }) =>
      request<Invitation>("/api/invitations/", { method: "POST", body: JSON.stringify(data) }),
    remove: (id: number) => request<void>(`/api/invitations/${id}/`, { method: "DELETE" }),
  },
  alarmRecipients: {
    list: () => request<AlarmRecipient[]>("/api/alarm-recipients/"),
    create: (data: { email: string } | { user: number }) =>
      request<AlarmRecipient>("/api/alarm-recipients/", { method: "POST", body: JSON.stringify(data) }),
    setActive: (id: number, active: boolean) =>
      request<AlarmRecipient>(`/api/alarm-recipients/${id}/`, { method: "PATCH", body: JSON.stringify({ active }) }),
    remove: (id: number) => request<void>(`/api/alarm-recipients/${id}/`, { method: "DELETE" }),
    /** Queues one test e-mail per active recipient; the monitor sends them. */
    test: () => request<{ queued: number }>("/api/alarm-recipients/test/", { method: "POST" }),
  },
  users: {
    search: (q: string) => request<UserHit[]>(`/api/users/?search=${encodeURIComponent(q)}`),
  },
  settings: {
    get: () => request<MonitorSettings>("/api/settings/monitor/"),
    put: (data: MonitorSettings) =>
      request<MonitorSettings>("/api/settings/monitor/", { method: "PUT", body: JSON.stringify(data) }),
  },
};
