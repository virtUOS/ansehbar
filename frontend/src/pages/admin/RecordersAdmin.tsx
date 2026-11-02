// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Power, PowerOff, Trash2 } from "lucide-react";
import { sortIgnoredAgents, splitErrors, toggleActivePayload, type FormErrors } from "../../admin";
import { ApiError, api, type IgnoredAgent, type Recorder } from "../../api";
import { useAppContext } from "../../appContext";
import { Field, FormErrorSummary, inputCls } from "../../components/FormParts";
import { StatusBadge } from "../../components/StatusBadge";
import { OpencastIcon } from "../../components/OpencastIcon";
import { RoomName } from "../../components/RoomName";
import { AgentStateText } from "../../components/AgentStateText";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { SyncNowButton } from "../../components/SyncNowButton";
import { displayName, formatClock, opencastNotice, sortForAdmin } from "../../recorders";
import type { MonitorHealth } from "../../api";

const iconBtn =
  "inline-flex min-h-11 min-w-11 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-900 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800 dark:focus-visible:outline-slate-100";

const FIELDS = ["room_name", "stream_name", "agent_id", "active"];
const NO_ERRORS: FormErrors = { fields: {}, general: [] };

/** Recorder id being edited, "new", or null when the form is closed. */
type Editing = number | "new" | null;

export function RecordersAdmin() {
  const { t, i18n } = useTranslation();
  const refreshWhoami = useAppContext()?.refreshWhoami;
  const [recorders, setRecorders] = useState<Recorder[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [message, setMessage] = useState("");
  const [rowError, setRowError] = useState("");
  const [ignored, setIgnored] = useState<IgnoredAgent[]>([]);
  const [toDelete, setToDelete] = useState<Recorder | null>(null);
  const [health, setHealth] = useState<MonitorHealth | null>(null);
  const [syncPolling, setSyncPolling] = useState(false);
  const addBtn = useRef<HTMLButtonElement>(null);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await api.monitor.health());
    } catch {
      /* the page works without the heartbeat */
    }
  }, []);
  const loadIgnored = useCallback(async () => {
    try {
      setIgnored(await api.ignoredAgents.list());
    } catch {
      /* optional section */
    }
  }, []);

  useEffect(() => {
    void loadHealth();
    void loadIgnored();
  }, [loadHealth, loadIgnored]);

  // Poll the heartbeat only while a sync is pending.
  useEffect(() => {
    if (!syncPolling) return;
    const id = window.setInterval(() => void loadHealth(), 2000);
    return () => window.clearInterval(id);
  }, [syncPolling, loadHealth]);

  const syncDone = useCallback(() => {
    setSyncPolling(false);
    void loadHealth();
    void reload();
    void loadIgnored();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadHealth, loadIgnored]);

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
      await api.recorders.update(r.id, toggleActivePayload(r));
      setMessage(t("Saved."));
      await reload();
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
    }
  };

  const confirmDelete = async () => {
    const r = toDelete;
    setToDelete(null);
    if (!r) return;
    setRowError("");
    try {
      await api.recorders.remove(r.id);
      setRecorders((list) => list.filter((x) => x.id !== r.id));
      setMessage(t("Saved."));
      await loadIgnored();
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
    }
  };

  const allowAgain = async (i: IgnoredAgent) => {
    setRowError("");
    try {
      await api.ignoredAgents.remove(i.id);
      setIgnored((list) => list.filter((x) => x.id !== i.id));
      setMessage(t("Saved."));
    } catch (e) {
      setRowError(splitErrors(e, []).general.join(" "));
    }
  };

  const closeForm = () => {
    setEditing(null);
    // Return focus to the control that opened the form.
    setTimeout(() => addBtn.current?.focus(), 0);
  };

  const notice = health ? opencastNotice(health) : { level: null, key: null };
  // Literal keys, so check:i18n sees them.
  const noticeTexts: Record<string, string> = {
    "Opencast not reachable": t("Opencast not reachable"),
    "Opencast rejected the login": t("Opencast rejected the login"),
    "No permission in Opencast": t("No permission in Opencast"),
    "Opencast did not answer in time": t("Opencast did not answer in time"),
    "Opencast server error": t("Opencast server error"),
    "Unexpected answer from Opencast": t("Unexpected answer from Opencast"),
    "Opencast shows no scheduled recordings – check the account's permissions": t(
      "Opencast shows no scheduled recordings – check the account's permissions",
    ),
  };
  const noticeText = notice.key ? noticeTexts[notice.key] : "";

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
      {health?.opencast.enabled ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          <SyncNowButton label={t("Sync Opencast now")} requested={health.opencast.requested} onStart={() => setSyncPolling(true)} onDone={syncDone} onError={() => setSyncPolling(false)} />
          <span className="text-slate-700 dark:text-slate-300">
            {health.opencast.last_success
              ? t("Last sync: {{time}}", { time: formatClock(health.opencast.last_success, i18n.language) })
              : t("No sync yet")}
          </span>
          {noticeText ? (
            <span role="status" className="font-bold text-amber-900 dark:text-amber-300">
              <span aria-hidden>⚠ </span>
              {noticeText}
            </span>
          ) : null}
        </div>
      ) : null}
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
                        <OpencastIcon className="mr-1.5" />{r.agent_id} <span className="font-sans text-xs text-slate-600 dark:text-slate-300">· <AgentStateText state={r.status.agent_state} /></span>
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
                    <span className="inline-flex gap-2">
                      <button
                        type="button"
                        className={iconBtn}
                        title={t("Edit")}
                        aria-label={t("Edit {{room}}", { room: displayName(r) })}
                        onClick={() => { setMessage(""); setEditing(r.id); }}
                      >
                        <Pencil aria-hidden className="h-5 w-5" />
                      </button>
                      <button
                        type="button"
                        className={iconBtn}
                        title={r.active ? t("Deactivate") : t("Activate")}
                        aria-label={r.active ? t("Deactivate {{room}}", { room: displayName(r) }) : t("Activate {{room}}", { room: displayName(r) })}
                        onClick={() => void toggleActive(r)}
                      >
                        {r.active ? <PowerOff aria-hidden className="h-5 w-5" /> : <Power aria-hidden className="h-5 w-5" />}
                      </button>
                      {!r.active ? (
                        <button
                          type="button"
                          className={iconBtn}
                          title={t("Delete")}
                          aria-label={t("Delete {{room}}", { room: displayName(r) })}
                          onClick={() => setToDelete(r)}
                        >
                          <Trash2 aria-hidden className="h-5 w-5" />
                        </button>
                      ) : null}
                    </span>
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

      {ignored.length ? (
        <section aria-labelledby="ign-h" className="space-y-2">
          <h3 id="ign-h" className="text-lg font-bold">{t("Ignored Opencast agents")}</h3>
          <p className="text-sm text-slate-700 dark:text-slate-300">{t("At the next sync the agent returns as “New – please check”.")}</p>
          <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <caption className="sr-only">{t("Ignored Opencast agents")}</caption>
              <thead className="bg-slate-100 dark:bg-slate-800">
                <tr>
                  <th scope="col" className="px-3 py-2">{t("Agent")}</th>
                  <th scope="col" className="px-3 py-2">{t("Date")}</th>
                  <th scope="col" className="px-3 py-2">{t("By")}</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">{t("Actions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {sortIgnoredAgents(ignored).map((i) => (
                  <tr key={i.id} className="border-t border-slate-200 dark:border-slate-800">
                    <th scope="row" className="px-3 py-2 font-mono font-medium">{i.agent_id}</th>
                    <td className="px-3 py-2">{new Date(i.created_at).toLocaleDateString(i18n.language)}</td>
                    <td className="px-3 py-2">{i.created_by}</td>
                    <td className="px-3 py-2 text-right">
                      <button type="button" className="btn-secondary min-h-11" aria-label={t("Allow {{agent}} again", { agent: i.agent_id })} onClick={() => void allowAgain(i)}>
                        {t("Allow again")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {toDelete ? (
        <ConfirmDialog title={t("Delete recorder?")} confirmLabel={t("Delete")} onConfirm={() => void confirmDelete()} onCancel={() => setToDelete(null)}>
          <p>{t("{{room}} will be permanently deleted along with its status and schedule.", { room: displayName(toDelete) })}</p>
          {toDelete.agent_id ? <p className="mt-2">{t("The Opencast agent {{agent}} will be ignored from now on.", { agent: toDelete.agent_id })}</p> : null}
        </ConfirmDialog>
      ) : null}
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
