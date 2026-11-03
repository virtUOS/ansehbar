// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import type { Recorder } from "../api";
import { hasLastRecordingProblems, lastRecordingRef } from "../recorders";
import { problemText } from "../problemTexts";

/** Amber note that the room's last recording had problems (text and symbol,
 *  never colour only). `compact`: one line, details in the title tooltip. */
export function LastRecordingWarning({ recorder, compact = false }: { recorder: Recorder; compact?: boolean }) {
  const { t, i18n } = useTranslation();
  const lr = recorder.last_recording;
  if (!lr || !hasLastRecordingProblems(recorder)) return null;
  const lang = i18n.language;
  // Unknown kinds yield no line; the heading still shows (problems exist).
  const lines = lr.problems.map((p) => problemText(t, p, lang)).filter((l) => l !== "");
  const ref = t("{{title}}, {{day}} {{from}}–{{to}}", lastRecordingRef(lr, lang));
  if (compact) {
    return (
      <p
        role="note"
        title={[ref, ...lines].join("\n")}
        className="mt-1 flex items-center gap-1.5 rounded-md bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-950 dark:bg-amber-950 dark:text-amber-100"
      >
        <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
        <span className="truncate">{t("Last recording had problems")}</span>
      </p>
    );
  }
  return (
    <div
      role="note"
      className="flex items-start gap-2 rounded-lg bg-amber-100 px-3 py-2 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100"
    >
      <AlertTriangle aria-hidden className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0">
        <p className="font-semibold">{t("Last recording had problems")}</p>
        <p className="break-words">{ref}</p>
        {lines.length > 0 && (
          <ul className="list-disc pl-5">
            {lines.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
