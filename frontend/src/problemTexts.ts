// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import type { TFunction } from "i18next";
import type { RecordingProblem } from "./api";
import { problemTextOf } from "./recorders";

/** Translated line for one recording problem; "" for a kind this client does
 *  not know. Literal t() calls, so check:i18n sees the keys. */
export function problemText(t: TFunction, problem: RecordingProblem, lang: string): string {
  const text = problemTextOf(problem, lang);
  if (!text) return "";
  const p = text.params;
  switch (text.key) {
    case "Stream missing {{from}}–{{to}} ({{minutes}} min)":
      return t("Stream missing {{from}}–{{to}} ({{minutes}} min)", p);
    case "Silent {{minutes}} min from {{from}}":
      return t("Silent {{minutes}} min from {{from}}", p);
    case "Processing in Opencast failed":
      return t("Processing in Opencast failed");
    case "Recording failed on the recorder":
      return t("Recording failed on the recorder");
    case "Recording did not start":
      return t("Recording did not start");
    case "Recording did not finish":
      return t("Recording did not finish");
    default:
      return "";
  }
}
