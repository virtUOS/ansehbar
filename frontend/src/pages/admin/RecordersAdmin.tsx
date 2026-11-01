// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { splitErrors, type FormErrors } from "../../admin";
import { ApiError, api, type Recorder } from "../../api";
import { useAppContext } from "../../appContext";
import { Field, FormErrorSummary, inputCls } from "../../components/FormParts";
import { StatusBadge } from "../../components/StatusBadge";
import { RoomName } from "../../components/RoomName";
import { AgentStateText } from "../../components/AgentStateText";
import { displayName, sortForAdmin } from "../../recorders";

const FIELDS = ["room_name", "stream_name", "agent_id", "active"];
const NO_ERRORS: FormErrors = { fields: {}, general: [] };

/** Recorder id being edited, "new", or null when the form is closed. */
type Editing = number | "new" | null;

export function RecordersAdmin() {
  const { t } = useTranslation();
  const refreshWhoami = useAppContext()?.refreshWhoami;
  const [recorders, setRecorders] = useState<Recorder[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [message, setMessage] = useState("");
  const [rowError, setRowError] = useState("");
  const addBtn = useRef<HTMLButtonElement>(null);

  const reload = useCallback(async () => {
    try {
      setRecorders(await api.recorders.list());
      setLoadError(null);
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

  const toggleActive = async (r: Recorder) => {
    setRowError("");
    try {
      await api.recorders.update(r.id, { active: !r.active });
      setMessage(t("Saved."));
      await reload();
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
    }
  };

  const closeForm = () => {
    setEditing(null);
    // Return focus to the control that opened the form.
    setTimeout(() => addBtn.current?.focus(), 0);
  };

  const current = typeof editing === "number" ? recorders.find((r) => r.id === editing) : undefined;

  return (
    <section aria-labelledby="rec-h" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="rec-h" className="text-xl font-bold">
          {t("Recorders")}
        </h2>
        <button ref={addBtn} type="button" className="btn-primary" onClick={() => { setMessage(""); setEditing("new"); }}>
          {t("Add recorder")}
        </button>
      </div>
      <p role="status" className="min-h-5 text-sm text-slate-700 dark:text-slate-300">
        {message}
      </p>

      {editing !== null ? (
        <RecorderForm
          key={editing}
          recorder={current}
          onCancel={closeForm}
          onSaved={async () => {
            setMessage(t("Saved."));
            await reload();
            closeForm();
          }}
        />
      ) : null}

      {loadError ? <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {loadError}</p> : null}
      {rowError ? <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {rowError}</p> : null}

      {loading ? (
        <p>{t("Loading…")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <caption className="sr-only">{t("Recorders")}</caption>
            <thead className="bg-slate-100 dark:bg-slate-800">
              <tr>
                <th scope="col" className="px-3 py-2">{t("Room name")}</th>
                <th scope="col" className="px-3 py-2">{t("Stream name")}</th>
                <th scope="col" className="px-3 py-2">{t("Opencast agent")}</th>
                <th scope="col" className="px-3 py-2">{t("Active")}</th>
                <th scope="col" className="px-3 py-2">{t("Status")}</th>
                <th scope="col" className="px-3 py-2">{t("Review")}</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">{t("Actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {sortForAdmin(recorders).map((r) => (
                <tr key={r.id} className="border-t border-slate-200 dark:border-slate-800">
                  <th scope="row" className="px-3 py-2 font-medium"><RoomName recorder={r} /></th>
                  <td className="px-3 py-2 font-mono">{r.stream_name}</td>
                  <td className="px-3 py-2 font-mono">
                    {r.agent_id ? (
                      <>
                        {r.agent_id} <span className="font-sans text-xs text-slate-600 dark:text-slate-300">· <AgentStateText state={r.status.agent_state} /></span>
                      </>
                    ) : (
                      <span className="font-sans text-slate-600 dark:text-slate-300">{t("Not linked")}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.active ? `✓ ${t("Active")}` : `– ${t("Inactive")}`}</td>
                  <td className="px-3 py-2">{r.active ? <StatusBadge state={r.status.state} /> : <span aria-hidden>–</span>}</td>
                  <td className="px-3 py-2">
                    {r.needs_review ? (
                      <span className="inline-flex rounded-full bg-amber-300 px-2.5 py-0.5 text-xs font-bold text-amber-950">⚑ {t("New – please check")}</span>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <button
                      type="button"
                      className="btn-secondary mr-2"
                      aria-label={t("Edit {{room}}", { room: displayName(r) })}
                      onClick={() => { setMessage(""); setEditing(r.id); }}
                    >
                      {t("Edit")}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      aria-label={`${r.active ? t("Deactivate") : t("Activate")}: ${displayName(r)}`}
                      onClick={() => void toggleActive(r)}
                    >
                      {r.active ? t("Deactivate") : t("Activate")}
                    </button>
                  </td>
                </tr>
              ))}
              {!recorders.length ? (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-slate-600 dark:text-slate-300">{t("No recorders yet.")}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RecorderForm({
  recorder,
  onCancel,
  onSaved,
}: {
  recorder?: Recorder;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [room, setRoom] = useState(recorder?.room_name ?? "");
  const [stream, setStream] = useState(recorder?.stream_name ?? "");
  const [agent, setAgent] = useState(recorder?.agent_id ?? "");
  const [active, setActive] = useState(recorder?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErrors(NO_ERRORS);
    // Saving counts as the review; "" unlinks the agent (server: "" -> null).
    const data = { room_name: room.trim(), stream_name: stream.trim(), agent_id: agent.trim() || null, active, needs_review: false };
    try {
      if (recorder) await api.recorders.update(recorder.id, data);
      else await api.recorders.create(data);
      await onSaved();
    } catch (err) {
      setErrors(splitErrors(err, FIELDS));
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="max-w-4xl space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800" aria-labelledby="rec-form-h">
      <h3 id="rec-form-h" className="text-lg font-bold">
        {recorder ? t("Edit recorder") : t("Add recorder")}
      </h3>
      <FormErrorSummary messages={errors.general} />
      <Field label={t("Room name")} errors={errors.fields.room_name}>
        {(p) => <input {...p} ref={first} value={room} onChange={(e) => setRoom(e.target.value)} className={inputCls} />}
      </Field>
      <Field label={t("Stream name")} errors={errors.fields.stream_name} hint={t("Case-sensitive, e.g. cap-90-R12")}>
        {(p) => <input {...p} required value={stream} onChange={(e) => setStream(e.target.value)} className={`${inputCls} font-mono`} autoCapitalize="off" autoCorrect="off" spellCheck={false} />}
      </Field>
      <Field label={t("Opencast agent")} errors={errors.fields.agent_id} hint={t("Opencast capture agent; leave empty if not linked.")}>
        {(p) => <input {...p} value={agent} onChange={(e) => setAgent(e.target.value)} className={`${inputCls} font-mono`} autoCapitalize="off" autoCorrect="off" spellCheck={false} />}
      </Field>
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4" />
        {t("Active")}
      </label>
      {errors.fields.active?.length ? (
        <p role="alert" className="text-sm font-medium text-red-800 dark:text-red-300">
          <span aria-hidden>⚠ </span>
          {errors.fields.active.join(" ")}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={saving} className="btn-primary">
          {t("Save")}
        </button>
        <button type="button" onClick={onCancel} className="btn-secondary">
          {t("Cancel")}
        </button>
      </div>
    </form>
  );
}
