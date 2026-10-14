import { useCallback, useEffect, useState } from "react";
import { ArrowDownToLine, LoaderCircle, SlidersHorizontal } from "lucide-react";
import {
  api,
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
        ? t("Kalibre edilmiş · eşik {threshold}", {
            threshold: value.threshold.toFixed(4),
          })
        : t("OOS reddetme kapalı")}
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
        {t("Semantik OOS reddetme")}
        <select
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value as "calibrated" | "off")}
        >
          <option value="calibrated">{t("Kalibre edilmiş eşik")}</option>
          <option value="off">{t("Kapalı · önceki referans")}</option>
        </select>
      </label>
      <p className="field-hint">
        {value === "calibrated"
          ? experiment
            ? t(
                "Her katalog büyüklüğü ve embedding modeli için eşik ayrı kalibrasyon verisiyle bu deneyde hesaplanır. Hazırlık süresi p95'e dahil edilmez.",
              )
            : t(
                "Önce Kalibrasyon ekranında seçili embedding modelleri için eşik hesaplayın. Ek LLM çağrısı yapılmaz.",
              )
          : t(
              "En yakın aday seçilir; semantik benzerlik için OOS eşiği uygulanmaz.",
            )}
      </p>
    </div>
  );
}
export default function Calibration({ status }: { status: Status }) {
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
          <p className="eyebrow">{t("KALİBRASYON")}</p>
          <h1>{t("Her embedding için ölçülmüş bir reddetme eşiği.")}</h1>
          <p>
            {t(
              "Ayrı etiketli veriyle OOS yanlış kabulünü ve geçerli taleplerin kaybını dengele.",
            )}
          </p>
        </div>
      </div>
      <section className="panel experiment-setup">
        <div className="experiment-controls">
          <label>
            {t("Kalibrasyon kümesi")}
            <select
              value={source}
              disabled={busy}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="seed">{t("Demo kalibrasyon vakaları")}</option>
              <option value="customer">
                {t("Doğrulanmış müşteri kalibrasyon vakaları")}
              </option>
            </select>
          </label>
          <label>
            {t("En fazla OOS yanlış kabul (%)")}
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
            {t("Eşikleri hesapla")}
          </button>
        </div>
        <ModelChecklist
          label={t("Embedding modelleri")}
          options={status.models.embedding}
          selected={models}
          disabled={busy}
          onChange={setModels}
        />
        <p className="field-hint">
          {counts &&
            t(
              "{inside} kapsam içi · {outside} kapsam dışı · {total} kalibrasyon vakası",
              {
                inside: counts.in_scope,
                outside: counts.oos,
                total: counts.total,
              },
            )}
        </p>
        <p className="field-hint">
          {t(
            "En az 10 kapsam içi ve 10 kapsam dışı doğrulanmış vaka gerekir. Müşteri vakalarını Vakalar ekranında Kalibrasyon bölümüne atayın.",
          )}
        </p>
        <p className="field-hint">
          {t(
            "İndeks hazırlığı ve her vaka için embedding çağrısı yapılır. LLM kullanılmaz. Modeller sırayla çalışır.",
          )}
        </p>
      </section>
      <div className="notice">
        {t(
          "Bu oran kalibrasyon kümesindeki hedeftir; yeni istekler için garanti değildir. Demo kümesi elle yazılmıştır. Sonuçları ayrı test vakalarında Deneyler ekranından doğrulayın.",
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
              {t("{done} / {total} vaka işlendi", {
                done: job.progress,
                total: job.total,
              })}
              <small className="active-variant">
                {job.active_model || t("Sırada")}
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
            {r.status === "failed" ? t(r.error) : t("Kalibrasyon kaydedildi")}
          </div>
        ))}
      <section className="panel">
        <div className="panel-heading">
          <h2>{t("Aktif katalog için kalibrasyonlar")}</h2>
          <button
            className="button"
            disabled={!data}
            onClick={() => download("calibration-profiles.json", data)}
          >
            <ArrowDownToLine size={16} />
            {t("Dışa aktar")}
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("Embedding modeli")}</th>
                <th>{t("Durum / kaynak")}</th>
                <th>{t("Cosine eşiği")}</th>
                <th>{t("Kapsam içi kabul")}</th>
                <th>{t("Kapsam içi yanlış ret")}</th>
                <th>{t("OOS yanlış kabul")}</th>
                <th>{t("Vaka sayısı")}</th>
              </tr>
            </thead>
            <tbody>
              {data?.profiles.map((p) => (
                <tr key={p.embedding_id}>
                  <td>{p.model}</td>
                  <td>
                    {p.calibration ? (
                      <>
                        <span className="badge green">{t("Hazır")}</span>
                        <div className="field-hint">
                          {p.calibration.source === "seed"
                            ? t("Demo")
                            : t("Müşteri")}{" "}
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
                          ? t("Model bağlantısı gerekli")
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
          "Tablodaki oranlar eşik seçilen kalibrasyon verisine aittir; intent doğruluğu değildir. Turuncu değer, kapsam içi vakaların %10’dan fazlasının reddedildiğini gösterir.",
        )}
      </p>
      <p className="field-hint">
        {t(
          "Model, sağlayıcı, embedding ayarları, katalog veya etiketler değişirse eşik yeniden hesaplanmalıdır. Test ifadeleri ve katalog örnekleri kalibrasyonda kullanılamaz.",
        )}
      </p>
    </div>
  );
}
