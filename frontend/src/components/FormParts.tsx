// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Small form building blocks shared by the admin pages. */
import { useId, type ReactNode } from "react";

export const inputCls =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm aria-[invalid=true]:border-red-700 dark:border-slate-700 dark:bg-slate-900 dark:aria-[invalid=true]:border-red-400";

/** Label + control + field errors wired via aria-describedby / aria-invalid. */
export function Field({
  label,
  errors,
  hint,
  children,
}: {
  label: string;
  errors?: string[];
  hint?: string;
  children: (p: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const errId = `${id}-err`;
  const hintId = `${id}-hint`;
  const has = !!errors?.length;
  const described = [has ? errId : "", hint ? hintId : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      {children({ id, "aria-describedby": described, "aria-invalid": has || undefined })}
      {hint ? (
        <p id={hintId} className="mt-1 text-xs text-slate-600 dark:text-slate-400">
          {hint}
        </p>
      ) : null}
      {has ? (
        <p id={errId} className="mt-1 text-sm font-medium text-red-800 dark:text-red-300">
          <span aria-hidden>⚠ </span>
          {errors!.join(" ")}
        </p>
      ) : null}
    </div>
  );
}

/** Form-level errors (non-field) shown at the top of a form. */
export function FormErrorSummary({ messages }: { messages: string[] }) {
  if (!messages.length) return null;
  return (
    <div role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm font-medium text-red-900">
      <span aria-hidden>⚠ </span>
      {messages.join(" ")}
    </div>
  );
}
