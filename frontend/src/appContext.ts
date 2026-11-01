// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** App-wide context (whoami + refresh), independent of router nesting. */
import { createContext, useContext } from "react";
import type { Whoami } from "./api";

export interface AppContextValue {
  whoami: Whoami;
  /** Re-fetch whoami (e.g. after a 403 from the API). */
  refreshWhoami: () => void;
}

export const AppContext = createContext<AppContextValue | undefined>(undefined);

export function useAppContext(): AppContextValue | undefined {
  return useContext(AppContext);
}
