// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/verwaltung/rekorder", label: "Recorders" },
  { to: "/verwaltung/einladungen", label: "Invitations" },
  { to: "/verwaltung/alarme", label: "Alarms" },
  { to: "/verwaltung/einstellungen", label: "Settings" },
];

export function AdminLayout() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      <h1 className="text-2xl font-bold">{t("Administration")}</h1>
      <nav aria-label={t("Administration")} className="flex flex-wrap gap-1 border-b border-slate-200 pb-2 dark:border-slate-800">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              `rounded-full px-3 py-1.5 text-sm font-medium transition-colors hover:bg-slate-100 dark:hover:bg-slate-800 ${
                isActive ? "bg-slate-100 font-bold dark:bg-slate-800" : ""
              }`
            }
          >
            {t(tab.label)}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
