import { useI18n } from "./i18n";
import { useState } from "react";
import { type EvalRecord, type EvaluationResult } from "./api";

function Outcome({ record }: { record?: EvalRecord }) {
  const { t, locale, tag, ms, pct } = useI18n();
  if (!record) return <span>{t("Sonuç yok")}</span>;
  return (
    <div
      className={
        "case-outcome " + (record.correct ? "is-correct" : "is-incorrect")
      }
    >
      <strong>
        {record.correct ? t("Doğru") : t("İncelenmeli")} · {record.decision}
      </strong>
      <code>{record.intent_id || "—"}</code>
      <small>
        {record.error ? t(record.error) : record.message || record.reason_code}
      </small>
      <small>{ms(record.total_ms)}</small>
    </div>
  );
}

export function CaseComparison({
  results,
  labels,
}: {
  results: Record<string, EvaluationResult>;
  labels: Record<string, string>;
}) {
  const { t, locale, tag, ms, pct } = useI18n();
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [onlyDifferent, setOnlyDifferent] = useState(false);
  const keys = Object.keys(results);
  const leftId = results[left] ? left : keys[0];
  const rightId =
    results[right] && right !== leftId
      ? right
      : keys.find((key) => key !== leftId)!;
  const rightRecords = new Map(
    results[rightId].records.map((record) => [record.case_id, record]),
  );
  const rows = results[leftId].records.filter((record) => {
    const other = rightRecords.get(record.case_id);
    return (
      !onlyDifferent ||
      !other ||
      record.decision !== other.decision ||
      record.intent_id !== other.intent_id
    );
  });
  return (
    <details className="panel case-comparison">
      <summary>{t("İki kombinasyonu vaka bazında karşılaştır")}</summary>
      <div className="case-compare-controls">
        <label>
          {t("Birinci kombinasyon")}
          <select
            value={leftId}
            onChange={(event) => setLeft(event.target.value)}
          >
            {keys.map((key) => (
              <option key={key} value={key}>
                {labels[key]}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("İkinci kombinasyon")}
          <select
            value={rightId}
            onChange={(event) => setRight(event.target.value)}
          >
            {keys
              .filter((key) => key !== leftId)
              .map((key) => (
                <option key={key} value={key}>
                  {labels[key]}
                </option>
              ))}
          </select>
        </label>
        <label className="difference-filter">
          <input
            type="checkbox"
            checked={onlyDifferent}
            onChange={(event) => setOnlyDifferent(event.target.checked)}
          />
          {t("Yalnız farklı kararlar (")}
          {rows.length})
        </label>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("Vaka / beklenen")}</th>
              <th>{labels[leftId]}</th>
              <th>{labels[rightId]}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((record) => (
              <tr key={record.case_id}>
                <td className="result-question">
                  {record.question}
                  <code>
                    {record.expected_intent_id || record.expected_decision}
                  </code>
                </td>
                <td>
                  <Outcome record={record} />
                </td>
                <td>
                  <Outcome record={rightRecords.get(record.case_id)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <p className="no-differences">
            {t("Seçili kombinasyonlar aynı kararları üretmiş.")}
          </p>
        )}
      </div>
    </details>
  );
}
