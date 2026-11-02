// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { knownAgentState } from "../recorders";

/** Opencast agent state as text; "" (never seen) reads "unknown", other values
 *  are shown raw. */
export function AgentStateText({ state }: { state: string }) {
  const { t } = useTranslation();
  // Literal t() calls so the i18n check sees every key.
  switch (knownAgentState(state)) {
    case "idle":
      return <>{t("idle")}</>;
    case "capturing":
      return <>{t("capturing")}</>;
    case "uploading":
      return <>{t("uploading")}</>;
    case "offline":
      return <>{t("offline")}</>;
    case "unknown":
      return <>{t("unknown")}</>;
    default:
      return <>{state === "" ? t("unknown") : state}</>;
  }
}
