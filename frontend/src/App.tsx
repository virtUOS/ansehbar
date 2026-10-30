// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** App shell: header (preferences, login/logout), landing page.
 *  Deliberately small — the tool grows from here. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Outlet, useOutletContext } from "react-router-dom";
import { LogIn, LogOut } from "lucide-react";
import {
  PreferencesMenu,
  setDefaultContentLang,
  setTranslationEnabled,
} from "@basicbar/ui";
import i18n from "./i18n";
import { api, loginUrl, logoutUrl, type Whoami } from "./api";

export function Home() {
  const { t } = useTranslation();
  const whoami = useOutletContext<Whoami | null>();
  return (
    <div className="mx-auto max-w-xl rounded-2xl border border-slate-200 p-8 text-center dark:border-slate-800">
      <h1 className="text-3xl font-bold">
        {"ansehBAR"}
      </h1>
      <p className="mt-3 text-slate-500 dark:text-slate-400">
        {"Kontrolle der Live-Streams aus den Aufzeichnungsr\u00e4umen"}
      </p>
      {whoami?.authenticated ? (
        <p className="mt-6 text-sm text-slate-600 dark:text-slate-300">
          {t("Signed in as")} <span className="font-medium">{whoami.username}</span>
        </p>
      ) : (
        <a
          href={loginUrl}
          className="mt-6 inline-block rounded-full bg-brand-400 px-5 py-2 text-sm font-bold text-slate-900 transition-colors hover:bg-brand-500"
        >
          {t("Sign in")}
        </a>
      )}
    </div>
  );
}

export default function App() {
  const { t } = useTranslation();
  const [whoami, setWhoami] = useState<Whoami | null>(null);

  useEffect(() => {
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

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        {t("Skip to content")}
      </a>
      <header className="border-b border-slate-100 dark:border-slate-900">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <span className="text-lg font-bold">
            {"ansehBAR"}
          </span>
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
      <main id="main" className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">
        <Outlet context={whoami} />
      </main>
    </div>
  );
}
