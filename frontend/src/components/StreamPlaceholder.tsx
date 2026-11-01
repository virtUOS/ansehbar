// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Presentation } from "../recorders";

/** Striped stand-in for the player when there is nothing to play. "unknown"
 *  never claims "not sending": we simply do not know. */
export function StreamPlaceholder({
  kind,
  children,
}: {
  kind: Exclude<Presentation, "live" | "live-unknown">;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  // Literal t() calls so the i18n check sees every key.
  const text =
    kind === "unknown"
      ? t("Status unknown – check not possible")
      : kind === "inactive"
        ? t("Recorder inactive")
        : t("No stream – the recorder is not sending right now");
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-sm font-medium text-slate-800 dark:text-slate-100"
      style={{
        backgroundImage:
          "repeating-linear-gradient(135deg, rgb(148 163 184 / 0.35) 0 10px, rgb(148 163 184 / 0.15) 10px 20px)",
      }}
    >
      <span className="rounded bg-white/80 px-2 py-1 dark:bg-slate-900/80">{text}</span>
      {children}
    </div>
  );
}
