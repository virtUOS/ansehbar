// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** App shell: header (navigation, preferences, login/logout) and the access
 *  gate (Landing / NoAccess / app). */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useOutletContext } from "react-router-dom";
import { LogIn, LogOut } from "lucide-react";
import {
  PreferencesMenu,
  setDefaultContentLang,
  setTranslationEnabled,
} from "@basicbar/ui";
import i18n from "./i18n";
import Landing from "./pages/Landing";
import NoAccess from "./pages/NoAccess";
import { api, loginUrl, logoutUrl, type Whoami } from "./api";

export interface AppContext {
  whoami: Whoami;
  /** Re-fetch whoami (e.g. after a 403 from the API). */
  refreshWhoami: () => void;
}

export function useAppContext() {
  return useOutletContext<AppContext>();
}

export default function App() {
  const { t } = useTranslation();
  const [whoami, setWhoami] = useState<Whoami | null>(null);

  const load = useCallback(() => {
    api
      .whoami()
      .then((data) => {
        setWhoami(data);
        // Content-i18n config for @basicbar/ui's contentLang helpers.
        setDefaultContentLang(data.content_default_language);
        setTranslationEnabled(data.content_translation_enabled);
        if (data.language) void i18n.changeLanguage(data.language);
      })
      .catch(() => setWhoami(null));
  }, []);

  useEffect(load, [load]);

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `rounded-full px-3 py-1 text-sm font-medium transition-colors hover:bg-slate-100 dark:hover:bg-slate-800 ${
      isActive ? "bg-slate-100 dark:bg-slate-800" : ""
    }`;

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        {t("Skip to content")}
      </a>
      <header className="border-b border-slate-100 dark:border-slate-900">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <span className="text-lg font-bold">ansehBAR</span>
            {whoami?.authenticated && whoami.has_access ? (
              <nav aria-label={t("Main")} className="flex items-center gap-1">
                <NavLink to="/" end className={navClass}>
                  {t("Overview")}
                </NavLink>
                <NavLink to="/verwaltung/rekorder" className={navClass}>
                  {t("Administration")}
                </NavLink>
              </nav>
            ) : null}
          </div>
          <div className="flex items-center gap-1">
            {/* Language + appearance from @basicbar/ui. Once the tool has an
                account menu for signed-in users, move LanguageOptions and
                AppearanceControl in there (see the @basicbar/ui README). */}
            <PreferencesMenu
              onLanguageChange={(lang) => {
                if (whoami?.authenticated) void api.setLanguage(lang).catch(() => {});
              }}
            />
            {whoami?.authenticated ? (
              <a
                href={logoutUrl}
                aria-label={t("Sign out")}
                className="flex items-center rounded-full p-2 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <LogOut aria-hidden className="h-5 w-5 text-slate-500 dark:text-slate-400" />
              </a>
            ) : (
              <a
                href={loginUrl}
                aria-label={t("Sign in")}
                className="flex items-center rounded-full p-2 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <LogIn aria-hidden className="h-5 w-5 text-slate-500 dark:text-slate-400" />
              </a>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="w-full flex-1 px-4 py-8">
        {!whoami?.authenticated ? (
          <Landing />
        ) : !whoami.has_access ? (
          <NoAccess contact={whoami.access_contact} />
        ) : (
          <Outlet context={{ whoami, refreshWhoami: load } satisfies AppContext} />
        )}
      </main>
    </div>
  );
}
