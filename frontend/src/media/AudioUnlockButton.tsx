// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Volume2 } from "lucide-react";
import { useAudio } from "./AudioContextProvider";

export function AudioUnlockButton() {
  const { t } = useTranslation();
  const { needsUnlock, unlock } = useAudio();
  if (!needsUnlock) return null;
  return (
    <button
      type="button"
      onClick={() => void unlock().catch(() => {})}
      className="flex items-center gap-2 rounded-full bg-brand-400 px-4 py-2 text-sm font-bold text-slate-900 transition-colors hover:bg-brand-500"
    >
      <Volume2 aria-hidden className="h-4 w-4" />
      {t("Enable level & sound")}
    </button>
  );
}
