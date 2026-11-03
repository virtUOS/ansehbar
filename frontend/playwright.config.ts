// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { defineConfig, devices } from "@playwright/test";

// Website screenshots (`npm run docs:shots`) are the only Playwright run so
// far: not a test — the project exists only when DOCS_SHOTS is set. Installed
// Google Chrome (channel "chrome") instead of Playwright's Chromium, which
// lacks the H.264/AAC codecs of the HLS streams.
export default defineConfig({
  testDir: "./e2e",
  reporter: "list",
  timeout: 120_000,
  use: {
    baseURL: process.env.DOCS_SHOTS_BASE_URL ?? "http://localhost:5179",
  },
  projects: process.env.DOCS_SHOTS
    ? [
        {
          name: "docs-shots",
          testMatch: /docs-screenshots\.spec\.ts$/,
          use: { ...devices["Desktop Chrome"], channel: "chrome", colorScheme: "light" as const },
        },
      ]
    : [],
});
