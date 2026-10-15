import { useWorkspaceApi } from "./workspace";
import { useCallback, useEffect, useState } from "react";
import { ArrowDownToLine, LoaderCircle, SlidersHorizontal } from "lucide-react";
import {
  download,
  type CalibrationStatus,
  type CalibrationJob,
  type Rejection,
  type Status,
} from "./api";
import { ModelChecklist, initialModelIds } from "./ModelPicker";
import { useI18n } from "./i18n";

export function RejectionSummary({ value }: { value?: Rejection | null }) {
  const { t } = useI18n();
  if (!value) return null;
  return (
    <small className="rejection-summary">
      {value.calibrated
        ? t("Calibrated · threshold {threshold}", {
            threshold: value.threshold.toFixed(4),
          })
        : t("OOS rejection off")}
      {value.calibrated && (
        <span title={value.id}> · {value.id.slice(0, 8)}</span>
      )}
    </small>
  );
}
export function RejectionControl({
  value,
  disabled,
  onChange,
  experiment = false,
}: {
  value: "calibrated" | "off";
  disabled: boolean;
  onChange: (mode: "calibrated" | "off") => void;
  experiment?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="rejection-control">
      <label>
        {t("Semantic OOS rejection")}
        <select
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value as "calibrated" | "off")}
        >
          <option value="calibrated">{t("Calibrated threshold")}</option>
          <option value="off">{t("Off · previous baseline")}</option>
        </select>
      </label>
      <p className="field-hint">
        {value === "calibrated"
          ? experiment
            ? t(
                "Each catalog size and embedding model gets a threshold fitted on separate calibration data within this experiment. Preparation time is excluded from p95.",
              )
            : t(
                "First fit thresholds for the selected embedding models on the Calibration page. No additional LLM call is made.",
              )
          : t(
              "The nearest candidate is selected without an OOS similarity threshold.",
            )}
      </p>
    </div>
  );
}
export default function Calibration({ status }: { status: Status }) {
  const { api } = useWorkspaceApi();
  const { t, pct, tag } = useI18n();
  const [data, setData] = useState<CalibrationStatus>();
  const [models, setModels] = useState(() =>
    initialModelIds(status.models.embedding),
  );
  const [source, setSource] = useState("seed");
  const [target, setTarget] = useState(5);
  const [job, setJob] = useState<CalibrationJob>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const busy =
    starting || (!!job && ["queued", "running"].includes(job.status));
  const refresh = useCallback(
    () =>
      api<CalibrationStatus>("/calibrations")
        .then(setData)
        .catch((e) => setError(e.message)),
    [],
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = setInterval(() => {
      api<CalibrationJob>("/requests/" + job.id)
        .then((value) => {
          if (!active) return;
          setJob(value);
          if (!["queued", "running"].includes(value.status)) void refresh();
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 800);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [job?.id, job?.status, refresh]);
  async function run() {
    setStarting(true);
    setError("");
    try {
      const created = await api<{ id: string }>("/calibrations", {
        method: "POST",
        body: JSON.stringify({
          embedding_ids: models,
          source,
          max_oos_false_accept_rate: target / 100,
        }),
      });
      setJob(await api<CalibrationJob>("/requests/" + created.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }
  const counts = data?.datasets[source];
  const insufficient = !counts || counts.in_scope < 10 || counts.oos < 10;
  return (
    <div className="page-pad">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("CALIBRATION")}</p>
          <h1>{t("A measured rejection threshold for every embedding model.")}</h1>
          <p>
            {t(
              "Balance OOS false acceptance and rejection of valid requests using a separate labelled dataset.",
            )}
          </p>
        </div>
      </div>
      <section className="panel experiment-setup">
        <div className="experiment-controls">
          <label>
            {t("Calibration set")}
            <select
              value={source}
              disabled={busy}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="seed">{t("Demo calibration cases")}</option>
              <option value="customer">
                {t("Reviewed customer calibration cases")}
              </option>
            </select>
          </label>
          <label>
            {t("Maximum OOS false acceptance (%)")}
            <input
              type="number"
              min={0}
              max={50}
              step={1}
              value={Number.isFinite(target) ? target : ""}
              disabled={busy}
              onChange={(e) =>
                setTarget(e.target.value === "" ? NaN : Number(e.target.value))
              }
            />
          </label>
          <button
            className="button primary"
            disabled={
              busy ||
              !models.length ||
              insufficient ||
              !Number.isFinite(target) ||
              target < 0 ||
              target > 50
            }
            onClick={() => void run()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <SlidersHorizontal size={17} />
            )}
            {t("Fit thresholds")}
          </button>
        </div>
        <ModelChecklist
          label={t("Embedding models")}
          options={status.models.embedding}
          selected={models}
          disabled={busy}
          onChange={setModels}
        />
        <p className="field-hint">
          {counts &&
            t(
              "{inside} in scope · {outside} out of scope · {total} calibration cases",
              {
                inside: counts.in_scope,
                outside: counts.oos,
                total: counts.total,
              },
            )}
        </p>
        <p className="field-hint">
          {t(
            "At least 10 reviewed in-scope and 10 OOS cases are required. Assign customer cases to the Calibration split on the Cases page.",
          )}
        </p>
        <p className="field-hint">
          {t(
            "This prepares the index and makes an embedding call for each case. No LLM is used. Models run sequentially.",
          )}
        </p>
      </section>
      <div className="notice">
        {t(
          "This is a target on the calibration set, not a guarantee for new requests. The demo set is handwritten. Validate results on separate test cases on the Experiments page.",
        )}
      </div>
      {error && (
        <div className="notice error" role="alert">
          {t(error)}
        </div>
      )}
      {job?.error && (
        <div className="notice error" role="alert">
          {t(job.error)}
        </div>
      )}
      {busy && job && (
        <div className="evaluation-progress">
          <div>
            <LoaderCircle className="spin" size={17} />
            <span>
              {t("{done} / {total} cases processed", {
                done: job.progress,
                total: job.total,
              })}
              <small className="active-variant">
                {job.active_model || t("Queued")}
              </small>
            </span>
          </div>
          <progress value={job.progress} max={job.total} />
        </div>
      )}
      {job &&
        Object.values(job.results || {}).map((r) => (
          <div
            className={
              "notice " + (r.status === "failed" ? "error" : "success")
            }
            key={r.model}
          >
            {r.model} ·{" "}
            {r.status === "failed" ? t(r.error) : t("Calibration saved")}
          </div>
        ))}
      <section className="panel">
        <div className="panel-heading">
          <h2>{t("Calibrations for the active catalog")}</h2>
          <button
            className="button"
            disabled={!data}
            onClick={() => download("calibration-profiles.json", data)}
          >
            <ArrowDownToLine size={16} />
            {t("Export")}
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("Embedding model")}</th>
                <th>{t("Status / source")}</th>
                <th>{t("Cosine threshold")}</th>
                <th>{t("In-scope retention")}</th>
                <th>{t("In-scope false rejection")}</th>
                <th>{t("OOS false acceptance")}</th>
                <th>{t("Case count")}</th>
              </tr>
            </thead>
            <tbody>
              {data?.profiles.map((p) => (
                <tr key={p.embedding_id}>
                  <td>{p.model}</td>
                  <td>
                    {p.calibration ? (
                      <>
                        <span className="badge green">{t("Ready")}</span>
                        <div className="field-hint">
                          {p.calibration.source === "seed"
                            ? t("Demo")
                            : t("Customer")}{" "}
                          ·{" "}
                          {new Date(
                            p.calibration.created * 1000,
                          ).toLocaleString(tag)}
                        </div>
                        <code title={p.calibration.id}>
                          {p.calibration.id.slice(0, 8)}
                        </code>
                      </>
                    ) : (
                      <span className="field-hint">
                        {!p.available
                          ? t("Model connection required")
                          : t(p.reason)}
                      </span>
                    )}
                  </td>
                  <td>{p.calibration?.threshold.toFixed(4) || "—"}</td>
                  <td>{pct(p.calibration?.metrics.in_scope_accept_rate)}</td>
                  <td
                    className={
                      p.calibration?.metrics.low_retention
                        ? "selection-warning"
                        : ""
                    }
                  >
                    {pct(p.calibration?.metrics.in_scope_false_reject_rate)}
                  </td>
                  <td>{pct(p.calibration?.metrics.oos_false_accept_rate)}</td>
                  <td>{p.calibration?.sample_count || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className="field-hint">
        {t(
          "These rates describe the threshold on its calibration data, not intent accuracy. Orange indicates rejection of more than 10% of in-scope cases.",
        )}
      </p>
      <p className="field-hint">
        {t(
          "Refit when the model, provider, embedding settings, catalog or labels change. Test utterances and catalog examples cannot be used for calibration.",
        )}
      </p>
    </div>
  );
}
