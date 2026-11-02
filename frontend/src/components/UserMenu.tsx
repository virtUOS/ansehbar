// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Account menu for signed-in users (like the sibling -bar tools): name,
 *  language, appearance, sign out — behind a single avatar button. */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AppearanceControl, LanguageOptions } from "@basicbar/ui";
import { api, logoutUrl, type Whoami } from "../api";

const divider = <div className="my-1 border-t border-slate-100 dark:border-slate-800" />;

export default function UserMenu({ whoami }: { whoami: Whoami }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const initial = (whoami.first_name || whoami.username || "?")[0].toUpperCase();
  const displayName = [whoami.first_name, whoami.last_name].filter(Boolean).join(" ") || whoami.username;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("User menu")}
        className="flex items-center rounded-full p-1 transition-colors duration-150 hover:bg-slate-100 dark:hover:bg-slate-800"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-400 text-sm font-bold text-slate-900">
          {initial}
        </span>
      </button>
      {open && (
        <div
          role="menu"
          // Phones: the header wraps, so span the viewport instead of hanging off the button.
          className="absolute right-0 z-30 mt-2 w-56 overflow-hidden max-sm:fixed max-sm:left-4 max-sm:right-4 max-sm:w-auto rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900"
        >
          <div className="px-3 py-2 text-xs text-slate-500 dark:text-slate-300">
            <p className="truncate">
              {t("Signed in as")}{" "}
              <span className="font-medium text-slate-700 dark:text-slate-200">{displayName}</span>
            </p>
          </div>
          {divider}
          <LanguageOptions onChange={(lang) => void api.setLanguage(lang).catch(() => {})} />
          {divider}
          <AppearanceControl />
          {divider}
          <a
            href={logoutUrl}
            role="menuitem"
            className="block w-full px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {t("Sign out")}
          </a>
        </div>
      )}
    </div>
  );
}
