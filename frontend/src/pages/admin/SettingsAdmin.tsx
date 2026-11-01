// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { previewUrl, splitErrors, type FormErrors } from "../../admin";
import { ApiError, api } from "../../api";
import { useAppContext } from "../../appContext";
import { Field, FormErrorSummary, inputCls } from "../../components/FormParts";

const FIELDS = ["url_template", "stale_factor", "missing_grace_minutes"];
const NO_ERRORS: FormErrors = { fields: {}, general: [] };

export function SettingsAdmin() {
  const { t } = useTranslation();
  const refreshWhoami = useAppContext()?.refreshWhoami;
  const [template, setTemplate] = useState("");
  const [stale, setStale] = useState("3");
  const [grace, setGrace] = useState("10");
  const [firstStream, setFirstStream] = useState<string | undefined>();
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.settings.get(), api.recorders.list()])
      .then(([s, recs]) => {
        if (cancelled) return;
        // Initial load only; the effect never reruns over unsaved edits.
        setTemplate(s.url_template);
        setStale(String(s.stale_factor));
        setGrace(String(s.missing_grace_minutes));
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
      });
      setTemplate(result.url_template);
      setStale(String(result.stale_factor));
      setGrace(String(result.missing_grace_minutes));
      setSaved(true);
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
        <Field label={t("Stale factor")} errors={errors.fields.stale_factor} hint={t("A stream counts as live while its playlist changed within this many target durations (2–10).")}>
          {(p) => (
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
        <div>
          <p className="text-sm font-medium">{t("Preview")}</p>
          <p className="mt-1 break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800">
            {previewUrl(template, firstStream)}
          </p>
        </div>
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
