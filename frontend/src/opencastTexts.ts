// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import type { TFunction } from "i18next";

/** Translated text of an Opencast notice key (see `opencastNotice`); literal
 *  keys, so check:i18n sees them. */
export function opencastNoticeText(t: TFunction, key: string | null): string {
  const texts: Record<string, string> = {
    "Opencast not reachable": t("Opencast not reachable"),
    "Opencast rejected the login": t("Opencast rejected the login"),
    "No permission in Opencast": t("No permission in Opencast"),
    "Opencast did not answer in time": t("Opencast did not answer in time"),
    "Opencast server error": t("Opencast server error"),
    "Unexpected answer from Opencast": t("Unexpected answer from Opencast"),
    "Internal error during the Opencast sync": t("Internal error during the Opencast sync"),
    "Opencast sync disabled – OPENCAST_URL must use https://": t(
      "Opencast sync disabled – OPENCAST_URL must use https://",
    ),
    "Opencast shows no scheduled recordings – check the account's permissions": t(
      "Opencast shows no scheduled recordings – check the account's permissions",
    ),
  };
  return key ? (texts[key] ?? "") : "";
}
