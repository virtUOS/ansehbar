// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Bell, BellOff, Send } from "lucide-react";
import { identifierFor, recipientPayload, splitErrors, type FormErrors } from "../../admin";
import { ApiError, api, type AlarmRecipient, type UserHit } from "../../api";
import { useAppContext } from "../../appContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Field, FormErrorSummary, inputCls } from "../../components/FormParts";

const FIELDS = ["email", "user"];
const NO_ERRORS: FormErrors = { fields: {}, general: [] };

export function AlarmsAdmin() {
  const { t } = useTranslation();
  const refreshWhoami = useAppContext()?.refreshWhoami;
  const [items, setItems] = useState<AlarmRecipient[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [rowError, setRowError] = useState("");
  const [removing, setRemoving] = useState<AlarmRecipient | null>(null);
  const [testing, setTesting] = useState(false);

  const reload = useCallback(async () => {
    try {
      setItems(await api.alarmRecipients.list());
      setLoadError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) refreshWhoami?.();
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [refreshWhoami]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const toggle = async (r: AlarmRecipient) => {
    setRowError("");
    try {
      await api.alarmRecipients.setActive(r.id, !r.active);
      setMessage(t("Saved."));
      await reload();
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
    }
  };

  const remove = async () => {
    if (!removing) return;
    const target = removing;
    setRemoving(null);
    setRowError("");
    try {
      await api.alarmRecipients.remove(target.id);
      setMessage(t("{{email}} removed.", { email: target.email }));
      await reload();
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
      void reload();
    }
  };

  const sendTest = async () => {
    setTesting(true);
    setRowError("");
    setMessage("");
    try {
      const { queued } = await api.alarmRecipients.test();
      setMessage(t("{{count}} test e-mails queued", { count: queued }));
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
    } finally {
      setTesting(false);
    }
  };

  return (
    <section aria-labelledby="alarm-h" className="space-y-4">
      <h2 id="alarm-h" className="text-xl font-bold">
        {t("Alarm recipients")}
      </h2>
      <p className="max-w-4xl text-sm text-slate-700 dark:text-slate-300">
        {t("Active recipients get an e-mail when a stream is missing during a scheduled recording, and an all-clear when it is back.")}
      </p>

      <RecipientForm
        onAdded={async (email) => {
          setMessage(t("{{email}} added.", { email }));
          await reload();
        }}
      />

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn-secondary inline-flex items-center gap-2" disabled={testing} onClick={() => void sendTest()}>
          <Send aria-hidden className="h-4 w-4" />
          {t("Send test e-mail")}
        </button>
        <p role="status" className="min-h-5 text-sm font-medium">
          {message}
        </p>
      </div>
      {loadError ? <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {loadError}</p> : null}
      {rowError ? <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {rowError}</p> : null}

      {loading ? (
        <p>{t("Loading…")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <caption className="sr-only">{t("Alarm recipients")}</caption>
            <thead className="bg-slate-100 dark:bg-slate-800">
              <tr>
                <th scope="col" className="px-3 py-2">{t("E-mail")}</th>
                <th scope="col" className="px-3 py-2">{t("User")}</th>
                <th scope="col" className="px-3 py-2">{t("Status")}</th>
                <th scope="col" className="px-3 py-2">{t("By")}</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">{t("Actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-t border-slate-200 dark:border-slate-800">
                  <th scope="row" className="px-3 py-2 font-medium">{r.email}</th>
                  <td className="px-3 py-2">{r.display_name}</td>
                  <td className="px-3 py-2">
                    {r.active ? (
                      <span className="inline-flex items-center gap-1">
                        <Bell aria-hidden className="h-4 w-4" />
                        {t("Active")}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-slate-700 dark:text-slate-300">
                        <BellOff aria-hidden className="h-4 w-4" />
                        {t("Inactive")}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.created_by}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <span className="inline-flex gap-2">
                      <button
                        type="button"
                        className="btn-secondary"
                        aria-label={r.active ? t("Deactivate {{email}}", { email: r.email }) : t("Activate {{email}}", { email: r.email })}
                        onClick={() => void toggle(r)}
                      >
                        {r.active ? t("Deactivate") : t("Activate")}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        aria-label={t("Remove {{email}}", { email: r.email })}
                        onClick={() => setRemoving(r)}
                      >
                        {t("Remove")}
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-slate-600 dark:text-slate-300">{t("No alarm recipients yet.")}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}

      {removing ? (
        <ConfirmDialog
          title={t("Remove alarm recipient?")}
          confirmLabel={t("Remove")}
          onConfirm={() => void remove()}
          onCancel={() => setRemoving(null)}
        >
          {t("{{email}} will no longer receive alarms.", { email: removing.email })}
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

function RecipientForm({ onAdded }: { onAdded: (email: string) => Promise<void> }) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [userId, setUserId] = useState<number | null>(null);
  const [hits, setHits] = useState<UserHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const picked = useRef(""); // text set by picking a hit: do not search for it again

  // Debounced search (250 ms, at least 2 characters); only the newest request wins.
  useEffect(() => {
    const q = input.trim();
    if (q.length < 2 || q === picked.current) {
      setHits([]);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      api.users
        .search(q)
        .then((r) => !cancelled && setHits(r))
        .catch(() => !cancelled && setHits([]))
        .finally(() => !cancelled && setSearching(false));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [input]);

  const change = (value: string) => {
    setInput(value);
    // Editing the text drops a picked user: what is typed is what is sent.
    if (value.trim() !== picked.current) {
      picked.current = "";
      setUserId(null);
    }
  };

  const pick = (hit: UserHit) => {
    const text = identifierFor(hit);
    picked.current = text;
    setInput(text);
    setUserId(hit.id);
    setHits([]);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErrors(NO_ERRORS);
    try {
      const created = await api.alarmRecipients.create(recipientPayload(input, userId));
      setInput("");
      setUserId(null);
      setHits([]);
      picked.current = "";
      await onAdded(created.email);
    } catch (err) {
      const split = splitErrors(err, FIELDS);
      // Both field errors belong to the single input.
      const merged = [...(split.fields.email ?? []), ...(split.fields.user ?? [])];
      setErrors({ fields: merged.length ? { email: merged } : {}, general: split.general });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="max-w-4xl space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <FormErrorSummary messages={errors.general} />
      <Field
        label={t("E-mail address or user")}
        errors={errors.fields.email}
        hint={t("Enter an e-mail address, or type at least 2 characters to search known users.")}
      >
        {(p) => (
          <input
            {...p}
            required
            value={input}
            onChange={(e) => change(e.target.value)}
            className={inputCls}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        )}
      </Field>
      <div aria-live="polite" className="text-sm">
        {searching ? <span className="text-slate-600 dark:text-slate-300">{t("Searching…")}</span> : null}
        {!searching && hits.length ? (
          <ul aria-label={t("Matching users")} className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {hits.map((h) => (
              <li key={h.id}>
                <button type="button" onClick={() => pick(h)} className="block w-full px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
                  <span className="font-medium">{h.display_name || h.username}</span>{" "}
                  <span className="text-slate-600 dark:text-slate-300">
                    {h.username}
                    {h.email ? ` · ${h.email}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <button type="submit" disabled={saving} className="btn-primary">
        {t("Add recipient")}
      </button>
    </form>
  );
}
