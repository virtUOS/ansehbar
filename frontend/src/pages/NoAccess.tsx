// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { logoutUrl } from "../api";

export default function NoAccess({ contact }: { contact?: string }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl rounded-2xl border border-slate-200 p-8 text-center dark:border-slate-800">
      <h1 className="text-2xl font-bold">{t("No access")}</h1>
      <p className="mt-3 text-slate-500 dark:text-slate-400">
        {t("Your account has not been granted access to ansehBAR yet.")}
      </p>
      {contact ? (
        <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
          {t("Please contact")} <span className="font-medium">{contact}</span>
        </p>
      ) : null}
      <a
        href={logoutUrl}
        className="mt-6 inline-block rounded-full border border-slate-300 px-5 py-2 text-sm font-bold transition-colors hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
      >
        {t("Sign out")}
      </a>
    </div>
  );
}
