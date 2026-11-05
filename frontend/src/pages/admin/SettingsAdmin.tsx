// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { previewUrl, splitErrors, type FormErrors } from "../../admin";
import { ApiError, api, type MonitorSettings } from "../../api";
import { useAppContext } from "../../appContext";
import { Field, FormErrorSummary, inputCls } from "../../components/FormParts";

const FIELDS = [
  "url_template", "stale_factor", "missing_grace_minutes", "slot_minutes", "slot_offset_minutes",
  "ct_minutes", "ct_tolerance_minutes", "end_tolerance_minutes", "alarm_email_enabled", "alarm_metrics_enabled",
  "silence_threshold_db", "silence_log_minutes", "silence_alarm_minutes",
  "sample_retention_days", "history_retention_days", "gitlab_url", "gitlab_token",
];
const NO_ERRORS: FormErrors = { fields: {}, general: [] };

export function SettingsAdmin() {
  const { t } = useTranslation();
  const refreshWhoami = useAppContext()?.refreshWhoami;
  const [template, setTemplate] = useState("");
  const [stale, setStale] = useState("3");
  const [grace, setGrace] = useState("10");
  const [slotMinutes, setSlotMinutes] = useState("120");
  const [slotOffset, setSlotOffset] = useState("0");
  const [ct, setCt] = useState("15");
  const [ctTolerance, setCtTolerance] = useState("5");
  const [endTolerance, setEndTolerance] = useState("5");
  const [alarmEmail, setAlarmEmail] = useState(true);
  const [alarmMetrics, setAlarmMetrics] = useState(true);
  const [silenceThreshold, setSilenceThreshold] = useState("-50");
  const [silenceLog, setSilenceLog] = useState("2");
  const [silenceAlarm, setSilenceAlarm] = useState("15");
  const [sampleDays, setSampleDays] = useState("30");
  const [historyDays, setHistoryDays] = useState("400");
  const [gitlabUrl, setGitlabUrl] = useState("");
  const [gitlabToken, setGitlabToken] = useState("");
  const [tokenSet, setTokenSet] = useState(false);
  const [removeToken, setRemoveToken] = useState(false);
  const [firstStream, setFirstStream] = useState<string | undefined>();
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const apply = (s: MonitorSettings) => {
    setTemplate(s.url_template);
    setStale(String(s.stale_factor));
    setGrace(String(s.missing_grace_minutes));
    setSlotMinutes(String(s.slot_minutes));
    setSlotOffset(String(s.slot_offset_minutes));
    setCt(String(s.ct_minutes));
    setCtTolerance(String(s.ct_tolerance_minutes));
    setEndTolerance(String(s.end_tolerance_minutes));
    setAlarmEmail(s.alarm_email_enabled);
    setAlarmMetrics(s.alarm_metrics_enabled);
    setSilenceThreshold(String(s.silence_threshold_db));
    setSilenceLog(String(s.silence_log_minutes));
    setSilenceAlarm(String(s.silence_alarm_minutes));
    setSampleDays(String(s.sample_retention_days));
    setHistoryDays(String(s.history_retention_days));
    setGitlabUrl(s.gitlab_url);
    setTokenSet(s.gitlab_token_set);
    setGitlabToken("");
    setRemoveToken(false);
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.settings.get(), api.recorders.list()])
      .then(([s, recs]) => {
        if (cancelled) return;
        // Initial load only; the effect never reruns over unsaved edits.
        apply(s);
        setFirstStream(recs[0]?.stream_name);
        setLoaded(true);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 403) refreshWhoami?.();
        setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshWhoami]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setErrors(NO_ERRORS);
    try {
      const result = await api.settings.put({ url_template: template.trim(), stale_factor: Number(stale),
        missing_grace_minutes: Number(grace),
        slot_minutes: Number(slotMinutes),
        slot_offset_minutes: Number(slotOffset),
        ct_minutes: Number(ct),
        ct_tolerance_minutes: Number(ctTolerance),
        end_tolerance_minutes: Number(endTolerance),
        alarm_email_enabled: alarmEmail,
        alarm_metrics_enabled: alarmMetrics,
        silence_threshold_db: Number(silenceThreshold),
        silence_log_minutes: Number(silenceLog),
        silence_alarm_minutes: Number(silenceAlarm),
        sample_retention_days: Number(sampleDays),
        history_retention_days: Number(historyDays),
        gitlab_url: gitlabUrl.trim(),
        // Only sent when entered ("" removes); omitted keeps the stored token.
        ...(removeToken ? { gitlab_token: "" } : gitlabToken ? { gitlab_token: gitlabToken } : {}),
      });
      apply(result);
      setSaved(true);
      // Tile buttons depend on whoami.tickets_enabled.
      refreshWhoami?.();
    } catch (err) {
      setErrors(splitErrors(err, FIELDS));
    } finally {
      setSaving(false);
    }
  };

  if (loadError) return <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">⚠ {loadError}</p>;
  if (!loaded) return <p>{t("Loading…")}</p>;

  return (
    <section aria-labelledby="set-h" className="max-w-4xl space-y-4">
      <h2 id="set-h" className="text-xl font-bold">
        {t("Settings")}
      </h2>
      <form onSubmit={submit} className="space-y-4">
        <FormErrorSummary messages={errors.general} />
        <Field label={t("URL template")} errors={errors.fields.url_template} hint={t("Must contain {stream} exactly once.")}>
          {(p) => (
            <input
              {...p}
              required
              value={template}
              onChange={(e) => { setTemplate(e.target.value); setSaved(false); }}
              className={`${inputCls} font-mono`}
              spellCheck={false}
            />
          )}
        </Field>
        <Field
          label={t("Tolerance until “stream ended”")}
          errors={errors.fields.stale_factor}
          hint={t("A live stream delivers a new piece of video every few seconds (usually every 6 s). This many piece lengths may pass without a new one before the stream counts as ended. Default 3 ≈ 18 seconds.")}
        >
          {(p) => (
            <span className="flex items-center gap-2">
            <input
              {...p}
              required
              type="number"
              min={2}
              max={10}
              step={1}
              value={stale}
              onChange={(e) => { setStale(e.target.value); setSaved(false); }}
              className={`${inputCls} max-w-32`}
            />
            <span className="text-sm">{t("× segment duration")}</span>
            </span>
          )}
        </Field>
        <Field label={t("Grace period before “stream missing” (minutes)")} errors={errors.fields.missing_grace_minutes}>
          {(p) => (
            <input
              {...p}
              required
              type="number"
              min={0}
              max={30}
              step={1}
              value={grace}
              onChange={(e) => { setGrace(e.target.value); setSaved(false); }}
              className={`${inputCls} max-w-32`}
            />
          )}
        </Field>
        <Field
          label={t("Recording slot length (minutes)")}
          errors={errors.fields.slot_minutes}
          hint={t("Groups the upcoming recordings; times that differ from their slot are marked.")}
        >
          {(p) => (
            <input
              {...p}
              required
              type="number"
              min={15}
              max={480}
              step={5}
              value={slotMinutes}
              onChange={(e) => { setSlotMinutes(e.target.value); setSaved(false); }}
              className={`${inputCls} max-w-32`}
            />
          )}
        </Field>
        <Field
          label={t("First slot starts after midnight (minutes)")}
          errors={errors.fields.slot_offset_minutes}
          hint={t("0 with 120-minute slots: slots start at even hours (8:00, 10:00, …); 60: at odd hours.")}
        >
          {(p) => (
            <input
              {...p}
              required
              type="number"
              min={0}
              max={479}
              step={5}
              value={slotOffset}
              onChange={(e) => { setSlotOffset(e.target.value); setSaved(false); }}
              className={`${inputCls} max-w-32`}
            />
          )}
        </Field>
        <div>
          <p className="text-sm font-medium">{t("Preview")}</p>
          <p className="mt-1 break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800">
            {previewUrl(template, firstStream)}
          </p>
        </div>
        <fieldset className="space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <legend className="px-1 text-lg font-bold">{t("Alarms")}</legend>
          <Checkbox
            label={t("Alarms by e-mail")}
            checked={alarmEmail}
            errors={errors.fields.alarm_email_enabled}
            onChange={(v) => { setAlarmEmail(v); setSaved(false); }}
          />
          <Checkbox
            label={t("Alarms to the monitoring service")}
            checked={alarmMetrics}
            errors={errors.fields.alarm_metrics_enabled}
            onChange={(v) => { setAlarmMetrics(v); setSaved(false); }}
          />
          <Field
            label={t("c.t. offset (minutes)")}
            errors={errors.fields.ct_minutes}
            hint={t("Only for rooms with alarm mode “Grid (c.t.)”: recordings start this long after the slot start.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={0}
                max={60}
                step={1}
                value={ct}
                onChange={(e) => { setCt(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
          <Field
            label={t("Tolerance after c.t. (minutes)")}
            errors={errors.fields.ct_tolerance_minutes}
            hint={t("Grid mode: a missing stream raises an alarm this long after slot start + c.t.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={0}
                max={30}
                step={1}
                value={ctTolerance}
                onChange={(e) => { setCtTolerance(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
          <Field
            label={t("End tolerance (minutes)")}
            errors={errors.fields.end_tolerance_minutes}
            hint={t("A stream that ends this long before the scheduled end is not an incident.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={0}
                max={30}
                step={1}
                value={endTolerance}
                onChange={(e) => { setEndTolerance(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
        </fieldset>
        <fieldset className="space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <legend className="px-1 text-lg font-bold">{t("Sound")}</legend>
          <Field
            label={t("Silence threshold (dBFS)")}
            errors={errors.fields.silence_threshold_db}
            hint={t("Mean level in dBFS over 10 s below which a room counts as silent.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={-90}
                max={-20}
                step={1}
                value={silenceThreshold}
                onChange={(e) => { setSilenceThreshold(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
          <Field
            label={t("Log silence after (minutes)")}
            errors={errors.fields.silence_log_minutes}
            hint={t("A silence during a recording is logged once it lasts this long.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={1}
                max={30}
                step={1}
                value={silenceLog}
                onChange={(e) => { setSilenceLog(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
          <Field
            label={t("Alarm for silence after (minutes)")}
            errors={errors.fields.silence_alarm_minutes}
            hint={t("Only the first silence of a recording raises an alarm, once it lasts this long. At least the logging time.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={5}
                max={120}
                step={1}
                value={silenceAlarm}
                onChange={(e) => { setSilenceAlarm(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
        </fieldset>
        <fieldset className="space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <legend className="px-1 text-lg font-bold">{t("Retention")}</legend>
          <Field
            label={t("Keep level measurements (days)")}
            errors={errors.fields.sample_retention_days}
            hint={t("Level measurements are deleted after this many days.")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={1}
                max={365}
                step={1}
                value={sampleDays}
                onChange={(e) => { setSampleDays(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
          <Field
            label={t("Keep history (days)")}
            errors={errors.fields.history_retention_days}
            hint={t("Incidents, events and sent notifications are deleted after this many days (at least one semester).")}
          >
            {(p) => (
              <input
                {...p}
                required
                type="number"
                min={183}
                max={3650}
                step={1}
                value={historyDays}
                onChange={(e) => { setHistoryDays(e.target.value); setSaved(false); }}
                className={`${inputCls} max-w-32`}
              />
            )}
          </Field>
        </fieldset>
        <fieldset className="space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <legend className="px-1 text-lg font-bold">{t("GitLab tickets")}</legend>
          <Field
            label={t("GitLab project URL")}
            errors={errors.fields.gitlab_url}
            hint={t("Use a project access token with role “Reporter” and only the scope “api”, and set an expiry date. Changing the URL requires entering a new token, otherwise the stored token is deleted. A private project is recommended: screenshots can show people.")}
          >
            {(p) => (
              <input
                {...p}
                type="url"
                value={gitlabUrl}
                placeholder="https://gitlab.example.com/group/project"
                onChange={(e) => { setGitlabUrl(e.target.value); setSaved(false); }}
                className={`${inputCls} font-mono`}
                spellCheck={false}
              />
            )}
          </Field>
          <Field
            label={t("Access token")}
            errors={errors.fields.gitlab_token}
            hint={tokenSet ? `✓ ${t("Token set")}` : t("No token set")}
          >
            {(p) => (
              <input
                {...p}
                type="password"
                autoComplete="off"
                value={gitlabToken}
                disabled={removeToken}
                onChange={(e) => { setGitlabToken(e.target.value); setSaved(false); }}
                className={`${inputCls} font-mono`}
              />
            )}
          </Field>
          {tokenSet ? (
            <Checkbox
              label={t("Remove token")}
              checked={removeToken}
              onChange={(v) => { setRemoveToken(v); if (v) setGitlabToken(""); setSaved(false); }}
            />
          ) : null}
        </fieldset>
        <div className="flex items-center gap-3">
          <button type="submit" disabled={saving} className="btn-primary">
            {t("Save")}
          </button>
          <p role="status" className="text-sm font-medium">
            {saved ? `✓ ${t("Saved.")}` : ""}
          </p>
        </div>
      </form>
    </section>
  );
}

function Checkbox({ label, checked, errors, onChange }: { label: string; checked: boolean; errors?: string[]; onChange: (v: boolean) => void }) {
  return (
    <div>
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4" />
        {label}
      </label>
      {errors?.length ? (
        <p role="alert" className="mt-1 text-sm font-medium text-red-800 dark:text-red-300">
          <span aria-hidden>⚠ </span>
          {errors.join(" ")}
        </p>
      ) : null}
    </div>
  );
}
