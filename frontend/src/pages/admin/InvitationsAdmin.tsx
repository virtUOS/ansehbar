// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
import { identifierFor, splitErrors, type FormErrors } from "../../admin";
import { ApiError, api, type Invitation, type UserHit } from "../../api";
import { useAppContext } from "../../appContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Field, FormErrorSummary, inputCls } from "../../components/FormParts";

const FIELDS = ["identifier", "note"];
const NO_ERRORS: FormErrors = { fields: {}, general: [] };

export function InvitationsAdmin() {
  const { t } = useTranslation();
  const ctx = useAppContext();
  const [items, setItems] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [removing, setRemoving] = useState<Invitation | null>(null);
  const [removeError, setRemoveError] = useState("");

  const reload = useCallback(async () => {
    try {
      setItems(await api.invitations.list());
      setLoadError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) ctx?.refreshWhoami();
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const remove = async () => {
    if (!removing) return;
    const target = removing;
    setRemoving(null);
    setRemoveError("");
    try {
      await api.invitations.remove(target.id);
      setMessage(t("Invitation for {{id}} removed.", { id: target.identifier }));
      await reload();
    } catch (e) {
      setRemoveError(splitErrors(e, []).general.join(" "));
    }
  };

  const fmt = (iso: string) => new Date(iso).toLocaleDateString(i18n.language, { dateStyle: "medium" });

  return (
    <section aria-labelledby="inv-h" className="space-y-4">
      <h2 id="inv-h" className="text-xl font-bold">
        {t("Invitations")}
      </h2>
      <p className="max-w-4xl text-sm text-slate-700 dark:text-slate-300">
        {t("Members of the IdP group don't need an invitation.")}
      </p>

      <InviteForm
        onInvited={async (identifier) => {
          setMessage(t("{{id}} invited.", { id: identifier }));
          await reload();
        }}
      />

      <p role="status" className="min-h-5 text-sm font-medium">
        {message}
      </p>
      {loadError ? <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {loadError}</p> : null}
      {removeError ? <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {removeError}</p> : null}

      {loading ? (
        <p>{t("Loading…")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <caption className="sr-only">{t("Invitations")}</caption>
            <thead className="bg-slate-100 dark:bg-slate-800">
              <tr>
                <th scope="col" className="px-3 py-2">{t("Identifier")}</th>
                <th scope="col" className="px-3 py-2">{t("Note")}</th>
                <th scope="col" className="px-3 py-2">{t("Invited by")}</th>
                <th scope="col" className="px-3 py-2">{t("Date")}</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">{t("Actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((inv) => (
                <tr key={inv.id} className="border-t border-slate-200 dark:border-slate-800">
                  <th scope="row" className="px-3 py-2 font-medium">{inv.identifier}</th>
                  <td className="px-3 py-2">{inv.note}</td>
                  <td className="px-3 py-2">{inv.created_by_name}</td>
                  <td className="whitespace-nowrap px-3 py-2">{fmt(inv.created_at)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <button
                      type="button"
                      className="btn-secondary"
                      aria-label={t("Remove invitation for {{id}}", { id: inv.identifier })}
                      onClick={() => setRemoving(inv)}
                    >
                      {t("Remove")}
                    </button>
                  </td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-slate-600 dark:text-slate-400">{t("No invitations yet.")}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}

      {removing ? (
        <ConfirmDialog
          title={t("Remove invitation?")}
          confirmLabel={t("Remove")}
          onConfirm={() => void remove()}
          onCancel={() => setRemoving(null)}
        >
          {t("{{id}} will lose access unless they are in the IdP group.", { id: removing.identifier })}
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

function InviteForm({ onInvited }: { onInvited: (identifier: string) => Promise<void> }) {
  const { t } = useTranslation();
  const [identifier, setIdentifier] = useState("");
  const [note, setNote] = useState("");
  const [hits, setHits] = useState<UserHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const picked = useRef(""); // identifier set by picking a hit: do not search for it again

  // Debounced search (250 ms, at least 2 characters); only the newest request wins.
  useEffect(() => {
    const q = identifier.trim();
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
  }, [identifier]);

  const pick = (hit: UserHit) => {
    const id = identifierFor(hit);
    picked.current = id;
    setIdentifier(id);
    setHits([]);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErrors(NO_ERRORS);
    const id = identifier.trim();
    try {
      await api.invitations.create({ identifier: id, note: note.trim() });
      setIdentifier("");
      setNote("");
      setHits([]);
      picked.current = "";
      await onInvited(id);
    } catch (err) {
      setErrors(splitErrors(err, FIELDS));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="max-w-4xl space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <FormErrorSummary messages={errors.general} />
      <Field
        label={t("Username or email")}
        errors={errors.fields.identifier}
        hint={t("Type at least 2 characters to search known users.")}
      >
        {(p) => (
          <input
            {...p}
            required
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            className={inputCls}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        )}
      </Field>
      <div aria-live="polite" className="text-sm">
        {searching ? <span className="text-slate-600 dark:text-slate-400">{t("Searching…")}</span> : null}
        {!searching && hits.length ? (
          <ul aria-label={t("Matching users")} className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {hits.map((h) => (
              <li key={h.id}>
                <button type="button" onClick={() => pick(h)} className="block w-full px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
                  <span className="font-medium">{h.display_name || h.username}</span>{" "}
                  <span className="text-slate-600 dark:text-slate-400">
                    {h.username}
                    {h.email ? ` · ${h.email}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <Field label={t("Note (optional)")} errors={errors.fields.note}>
        {(p) => <input {...p} value={note} onChange={(e) => setNote(e.target.value)} className={inputCls} />}
      </Field>
      <button type="submit" disabled={saving} className="btn-primary">
        {t("Invite")}
      </button>
    </form>
  );
}
