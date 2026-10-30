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
}

let csrfToken = "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      // FormData bodies get their multipart boundary from the browser.
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
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
};
