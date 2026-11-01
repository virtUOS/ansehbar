// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure helpers for the admin pages. */
import { ApiError, type Recorder, type UserHit } from "./api";

export interface FormErrors {
  fields: Record<string, string[]>;
  /** Errors not tied to a field (detail, non_field_errors, network, 5xx). */
  general: string[];
}

/** Splits an API error into per-field messages and form-level messages. */
export function splitErrors(err: unknown, knownFields: string[]): FormErrors {
  if (!(err instanceof ApiError)) {
    return { fields: {}, general: [err instanceof Error ? err.message : String(err)] };
  }
  const fields: Record<string, string[]> = {};
  const general: string[] = [];
  for (const [key, msgs] of Object.entries(err.fieldErrors)) {
    if (knownFields.includes(key)) fields[key] = msgs;
    else general.push(...msgs);
  }
  if (!Object.keys(fields).length && !general.length) general.push(err.message);
  return { fields, general };
}

/** Live preview of the playback URL; the stream name is never altered. */
export function previewUrl(template: string, streamName: string | undefined): string {
  return template.replace("{stream}", streamName || "example-stream");
}

/** What picking a search hit puts into the identifier field. */
export function identifierFor(hit: UserHit): string {
  return hit.email || hit.username;
}

/** PATCH body for the Activate/Deactivate button. Deactivating is an explicit
 *  review decision, so it also clears "new – please check". */
export function toggleActivePayload(r: Pick<Recorder, "active">): Partial<Recorder> {
  return r.active ? { active: false, needs_review: false } : { active: true };
}
