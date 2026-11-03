// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Screenshots for the project website (`website/bilder/`), not a test.
 *
 *  Run with the frontend dev server up (`docker compose up -d frontend`):
 *  `npm run docs:shots` (German) or `DOCS_SHOTS_LANG=en npm run docs:shots`
 *  (English, into website/en/bilder with the same file names). Needs Google
 *  Chrome and ffmpeg on the host.
 *
 *  Every /api/ request is answered from e2e/docs-data.ts (synthetic rooms,
 *  events and incidents); the backend and its database are never asked, so
 *  the pictures cannot show real rooms. The live streams are short HLS videos
 *  of a generated slide (ffmpeg), served under streams.example.org. The clock
 *  is frozen at Tuesday 10 Nov 2026, 10:47, Europe/Berlin.
 *
 *  DOCS_SHOTS_DIR=<dir> writes elsewhere; DOCS_SHOTS_ONLY=<name>,<name>
 *  writes only those shots (the run is the same). */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, type BrowserContext, type Page } from "@playwright/test";
import * as data from "./docs-data";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LANG: data.Lang = process.env.DOCS_SHOTS_LANG === "en" ? "en" : "de";
const OUT = path.resolve(
  process.env.DOCS_SHOTS_DIR ?? path.join(HERE, LANG === "en" ? "../../website/en/bilder" : "../../website/bilder"),
);
const ONLY = (process.env.DOCS_SHOTS_ONLY ?? "").split(",").map((n) => n.trim()).filter(Boolean);
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };
const HLS_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "ansehbar-docs-hls-"));

test.use({
  viewport: DESKTOP,
  deviceScaleFactor: 1.5,
  locale: LANG === "en" ? "en-GB" : "de-DE",
  timezoneId: "Europe/Berlin",
});

// ---------------------------------------------------------------- streams

function slideHtml(title: string, subtitle: string): string {
  return `<!doctype html><html><body style="margin:0;width:1280px;height:720px;
    font-family:'Helvetica Neue',Arial,sans-serif;background:linear-gradient(135deg,#1e2a44,#2f4870);
    color:#fff;display:flex;flex-direction:column;justify-content:center;padding:0 110px;box-sizing:border-box">
    <div style="font-size:26px;letter-spacing:.08em;text-transform:uppercase;opacity:.7">${subtitle}</div>
    <div style="font-size:64px;font-weight:700;margin:18px 0 36px;line-height:1.1">${title}</div>
    <div style="display:flex;gap:28px;align-items:flex-end;height:180px">
      ${[60, 110, 150, 95, 170, 130].map((h) => `<div style="width:70px;height:${h}px;background:#8fb3ff;border-radius:8px 8px 0 0;opacity:.85"></div>`).join("")}
    </div></body></html>`;
}

/** One 2-minute VOD HLS stream per live room (still slide, silent audio). */
async function makeStreams(page: Page) {
  for (const id of data.LIVE_ROOMS) {
    const { title, subtitle } = data.slideFor(LANG, id);
    const dir = path.join(HLS_DIR, data.streamOf(id));
    fs.mkdirSync(dir, { recursive: true });
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.setContent(slideHtml(title, subtitle));
    const png = path.join(dir, "slide.png");
    await page.screenshot({ path: png });
    execFileSync("ffmpeg", [
      "-loglevel", "error", "-y",
      "-loop", "1", "-framerate", "5", "-i", png,
      "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
      "-t", "120", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-g", "20",
      "-c:a", "aac", "-b:a", "48k", "-shortest",
      "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
      "-hls_segment_filename", path.join(dir, "seg%03d.ts"),
      path.join(dir, "playlist.m3u8"),
    ]);
  }
}

// ------------------------------------------------------------------- mocks

function json(body: unknown) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function mockBackend(context: BrowserContext) {
  await context.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (route.request().method() !== "GET") return route.fulfill(json({}));
    if (p === "/api/whoami/") return route.fulfill(json(data.whoami(LANG)));
    if (p === "/api/recorders/") return route.fulfill(json(data.recorders(LANG)));
    if (p === "/api/monitor/health/") return route.fulfill(json(data.health()));
    if (p === "/api/settings/monitor/") return route.fulfill(json(data.settings()));
    if (p === "/api/alarm-recipients/") return route.fulfill(json(data.recipients()));
    if (p === "/api/invitations/") return route.fulfill(json(data.invitations(LANG)));
    if (p === "/api/ignored-agents/") return route.fulfill(json(data.ignoredAgents()));
    const cal = p.match(/^\/api\/recorders\/\d+\/calendar\/$/);
    if (cal) {
      const from = url.searchParams.get("from") ?? "2026-11-09";
      return route.fulfill(json(data.calendar(LANG, from, Number(url.searchParams.get("days") ?? 7))));
    }
    const rec = p.match(/^\/api\/recorders\/(\d+)\/$/);
    if (rec) return route.fulfill(json(data.recorders(LANG).find((r) => r.id === Number(rec[1]))));
    const ev = p.match(/^\/api\/events\/(\d+)\/$/);
    if (ev) return route.fulfill(json(data.eventDetail(LANG, Number(ev[1]))));
    return route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"not mocked"}' });
  });
  await context.route(`${data.STREAM_HOST}/**`, async (route) => {
    const rel = new URL(route.request().url()).pathname.replace(/^\/live\//, "");
    const file = path.join(HLS_DIR, rel);
    if (!file.startsWith(HLS_DIR) || !fs.existsSync(file)) return route.fulfill({ status: 404 });
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*" },
      contentType: file.endsWith(".m3u8") ? "application/vnd.apple.mpegurl" : "video/mp2t",
      body: fs.readFileSync(file),
    });
  });
}

// ----------------------------------------------------------------- helpers

const HIDE_TRANSIENT = `*, *::before, *::after { caret-color: transparent !important; transition: none !important; }`;

async function open(page: Page, url: string) {
  await page.clock.setFixedTime(new Date(data.NOW));
  await page.goto(url);
  await page.addStyleTag({ content: HIDE_TRANSIENT });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

/** Every video on the page shows a frame (or there is none). */
async function videosReady(page: Page) {
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll("video")).every((v) => v.readyState >= 2),
    undefined,
    { timeout: 30_000 },
  );
  await page.waitForTimeout(800);
}

async function shot(page: Page, name: string, fullPage = false) {
  if (ONLY.length && !ONLY.includes(name)) return;
  fs.mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });
}

// ------------------------------------------------------------------- shots

test("website screenshots", async ({ browser }) => {
  const setup = await browser.newPage();
  await makeStreams(setup);
  await setup.close();

  // Desktop, light.
  const desktop = await browser.newContext({
    viewport: DESKTOP, deviceScaleFactor: 1.5, locale: LANG === "en" ? "en-GB" : "de-DE",
    timezoneId: "Europe/Berlin", colorScheme: "light",
  });
  await mockBackend(desktop);
  const page = await desktop.newPage();

  await open(page, "/");
  await page.getByRole("heading", { level: 2 }).first().waitFor();
  await videosReady(page);
  await shot(page, "uebersicht");

  await open(page, `/raum/${data.MAIN_ROOM}`);
  await page.locator("ol").first().waitFor();
  await videosReady(page);
  await shot(page, "raumansicht", true);

  await open(page, `/raum/${data.MAIN_ROOM}/kalender?ansicht=woche&datum=2026-11-10`);
  await page.locator("[aria-live]").first().waitFor();
  await page.waitForTimeout(800);
  await shot(page, "kalender-woche");

  await open(page, `/raum/${data.MAIN_ROOM}/kalender?ansicht=tag&datum=2026-11-10`);
  await page.locator("svg[role=img]").first().waitFor();
  await shot(page, "kalender-tag", true);

  for (const [name, url] of [
    ["verwaltung-rekorder", "/verwaltung/rekorder"],
    ["verwaltung-einladungen", "/verwaltung/einladungen"],
    ["verwaltung-alarme", "/verwaltung/alarme"],
    ["verwaltung-einstellungen", "/verwaltung/einstellungen"],
  ] as const) {
    await open(page, url);
    await page.locator("main h2, main table, main form").first().waitFor();
    await page.waitForTimeout(500);
    await shot(page, name, name === "verwaltung-einstellungen");
  }
  await desktop.close();

  // Desktop, dark: the overview once more.
  const dark = await browser.newContext({
    viewport: DESKTOP, deviceScaleFactor: 1.5, locale: LANG === "en" ? "en-GB" : "de-DE",
    timezoneId: "Europe/Berlin", colorScheme: "dark",
  });
  await mockBackend(dark);
  const darkPage = await dark.newPage();
  await open(darkPage, "/");
  await darkPage.getByRole("heading", { level: 2 }).first().waitFor();
  await videosReady(darkPage);
  await shot(darkPage, "uebersicht-dunkel");
  await dark.close();

  // Phone.
  const phone = await browser.newContext({
    viewport: PHONE, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    locale: LANG === "en" ? "en-GB" : "de-DE", timezoneId: "Europe/Berlin", colorScheme: "light",
  });
  await mockBackend(phone);
  const phonePage = await phone.newPage();
  await open(phonePage, "/");
  await phonePage.waitForTimeout(1500);
  await shot(phonePage, "handy-uebersicht");
  await open(phonePage, `/raum/${data.MAIN_ROOM}`);
  await videosReady(phonePage);
  await shot(phonePage, "handy-raum");
  await phone.close();

  fs.rmSync(HLS_DIR, { recursive: true, force: true });
});
