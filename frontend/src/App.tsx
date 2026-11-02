// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** App shell: header (navigation, account menu / login) and the access
 *  gate (Landing / NoAccess / app). */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";
import {
  PreferencesMenu,
  setDefaultContentLang,
  setTranslationEnabled,
} from "@basicbar/ui";
import i18n from "./i18n";
import { AppContext } from "./appContext";
import { AudioContextProvider } from "./media/AudioContextProvider";
import Landing from "./pages/Landing";
import NoAccess from "./pages/NoAccess";
import UserMenu from "./components/UserMenu";
import { api, loginUrl, type Whoami } from "./api";

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

  const appCtx = useMemo(() => (whoami ? { whoami, refreshWhoami: load } : null), [whoami, load]);

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `rounded-full px-2 py-1 text-sm sm:px-3 font-medium transition-colors hover:bg-slate-100 dark:hover:bg-slate-800 ${
      isActive ? "bg-slate-100 dark:bg-slate-800" : ""
    }`;

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        {t("Skip to content")}
      </a>
      <header className="border-b border-slate-100 dark:border-slate-900">
        <div className="flex flex-wrap items-center justify-between gap-x-2 px-2 py-2 sm:px-4 sm:py-3">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 sm:gap-x-4">
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
            {whoami?.authenticated ? (
              <UserMenu whoami={whoami} />
            ) : (
              <>
                <a
                  href={loginUrl}
                  className="rounded-full bg-brand-400 px-4 py-1.5 text-sm font-semibold text-slate-900 transition-colors hover:bg-brand-300"
                >
                  {t("Sign in")}
                </a>
                <PreferencesMenu />
              </>
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
          <AppContext.Provider value={appCtx!}>
            <AudioContextProvider>
              <Outlet />
            </AudioContextProvider>
          </AppContext.Provider>
        )}
      </main>
    </div>
  );
}
