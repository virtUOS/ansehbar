// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Fails if a literal `t("…")` key used in src/ has no German translation.
 *  Unused catalog keys are only reported as warnings (some come from
 *  @basicbar/ui). Dynamic keys (variables) are not checked. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/", import.meta.url).pathname;
const de = JSON.parse(readFileSync(join(root, "locales/de/translation.json"), "utf8"));

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) yield path;
  }
}

// t("key"), t('key'), t(`key`) — also i18n.t(...); stops at the closing quote.
const re = /\bt\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`([^`$]*)`)/g;
const used = new Map();
for (const file of walk(root)) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(re)) {
    const key = (m[1] ?? m[2] ?? m[3]).replace(/\\(["'])/g, "$1");
    if (!used.has(key)) used.set(key, file.replace(root, "src/"));
  }
}

// Plural forms: key_one / key_other count as translating `key`.
const has = (k) => k in de || `${k}_one` in de || `${k}_other` in de;
const missing = [...used].filter(([k]) => !has(k));
const unused = Object.keys(de).filter(
  (k) => !used.has(k) && !used.has(k.replace(/_(one|other|few|many|zero|two)$/, "")),
);

for (const k of unused) console.warn(`warning: unused key in de catalog: "${k}"`);
if (missing.length) {
  for (const [k, f] of missing) console.error(`missing German translation: "${k}" (${f})`);
  process.exit(1);
}
console.log(`i18n ok: ${used.size} keys used, all translated.`);
