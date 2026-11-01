// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import type { Recorder } from "../api";
import { displayName, roomNameMissing } from "../recorders";

/** Room name (or its fallback) plus, when the room name is empty, a hint in
 *  text and symbol. */
export function RoomName({ recorder }: { recorder: Recorder }) {
  const { t } = useTranslation();
  return (
    <>
      {displayName(recorder)}
      {roomNameMissing(recorder) ? (
        <span className="ml-2 whitespace-nowrap text-xs font-semibold text-amber-900 dark:text-amber-200">
          <span aria-hidden>⚠ </span>
          {t("Room name missing")}
        </span>
      ) : null}
    </>
  );
}
