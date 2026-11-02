// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

// Opencast logo: © Apereo Foundation, ECL-2.0, from
// github.com/opencast/opencast
// (modules/engage-ui/src/main/resources/ui/img/logo/opencast-icon.svg),
// reduced to viewBox and paths. The dark-blue part follows the text colour in
// dark mode so it stays legible.
import { useTranslation } from "react-i18next";

export function OpencastIcon({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  const label = t("From Opencast");
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox="0 0 110.58004 79.275291"
      className={`inline-block h-3.5 w-auto shrink-0 align-[-0.125em] text-[#24425d] dark:text-slate-200 ${className}`}
    >
      <title>{label}</title>
      <g transform="matrix(0.70993861,0,0,0.70993861,-57.202594,-168.60403)">
        <path fill="#4bb07b" d="m 136.273,237.491 55.7,55.678 -55.638,55.658 -0.025,-26.009 29.651,-29.651 -29.651,-29.649 z" />
        <path fill="currentColor" d="m 106.587,293.167 29.723,-29.649 -0.037,-26.027 -55.699,55.678 55.761,55.658 -0.025,-26.009 z" />
        <path fill="#4bb07b" d="m 180.697,349.156 -0.025,-26.01 29.651,-29.651 -29.651,-29.649 -0.036,-26.027 55.698,55.678 z" />
      </g>
    </svg>
  );
}
