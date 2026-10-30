// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { loginUrl } from "../api";

export default function Landing() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl rounded-2xl border border-slate-200 p-8 text-center dark:border-slate-800">
      <h1 className="text-3xl font-bold">ansehBAR</h1>
      <p className="mt-3 text-slate-500 dark:text-slate-400">
        {t("Monitoring the live streams from the recording rooms")}
      </p>
      <a
        href={loginUrl}
        className="mt-6 inline-block rounded-full bg-brand-400 px-5 py-2 text-sm font-bold text-slate-900 transition-colors hover:bg-brand-500"
      >
        {t("Sign in")}
      </a>
    </div>
  );
}
