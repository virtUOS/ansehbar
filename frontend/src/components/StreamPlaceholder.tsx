// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { missingMinutes, type Presentation } from "../recorders";
import { useNow } from "../useNow";

/** Own one-minute ticker: the surrounding tile does not re-render. */
function MissingText({ since }: { since: string | null }) {
  const { t } = useTranslation();
  const now = useNow(60000);
  return since ? (
    <>
      {t("Stream missing for {{minutes}} min", {
        minutes: missingMinutes(since, now),
      })}
    </>
  ) : (
    <>{t("Stream missing")}</>
  );
}

/** Striped stand-in for the player when there is nothing to play. "unknown"
 *  never claims "not sending": we simply do not know. */
export function StreamPlaceholder({
  kind,
  scheduled = true,
  missingSince = null,
  children,
}: {
  kind: Exclude<Presentation, "live" | "live-unknown" | "silent">;
  /** false: Opencast is on and nothing is scheduled today. */
  scheduled?: boolean;
  missingSince?: string | null;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  // Literal t() calls so the i18n check sees every key.
  const text =
    kind === "missing" ? (
      <MissingText since={missingSince} />
    ) : kind === "unknown" ? (
      t("Status unknown – check not possible")
    ) : kind === "inactive" ? (
      t("Recorder inactive")
    ) : scheduled ? (
      t("No stream – the recorder is not sending right now")
    ) : (
      t("No stream – no recording scheduled")
    );
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-sm font-medium text-slate-800 dark:text-slate-100"
      style={{
        backgroundImage:
          "repeating-linear-gradient(135deg, rgb(148 163 184 / 0.35) 0 10px, rgb(148 163 184 / 0.15) 10px 20px)",
      }}
    >
      <span
        className={`rounded px-2 py-1 ${
          kind === "missing"
            ? "bg-red-100 font-bold text-red-950 dark:bg-red-950 dark:text-red-100"
            : "bg-white/80 dark:bg-slate-900/80"
        }`}
      >
        {kind === "missing" ? <span aria-hidden>⚠ </span> : null}
        {text}
      </span>
      {children}
    </div>
  );
}
