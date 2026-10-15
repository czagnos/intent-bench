import type { RepeatGroupMetrics, RepeatGroupSummary } from "../api";

export type RepeatSummaryProps = {
  summary?: RepeatGroupSummary;
  label?: string;
};

const percentage = (value: number) => `${(value * 100).toFixed(1)}%`;
const percentagePoints = (value: number) => `${(value * 100).toFixed(1)} pp`;
const milliseconds = (value: number) => `${value.toLocaleString("en-US", { maximumFractionDigits: 2 })} ms`;
const metricRows: {
  key: keyof RepeatGroupMetrics;
  label: string;
  format: (value: number) => string;
  formatDeviation: (value: number) => string;
}[] = [
  { key: "routing_accuracy", label: "Routing accuracy", format: percentage, formatDeviation: percentagePoints },
  { key: "decision_accuracy", label: "Decision accuracy", format: percentage, formatDeviation: percentagePoints },
  { key: "macro_f1", label: "Macro-F1", format: percentage, formatDeviation: percentagePoints },
  { key: "recall_at_k", label: "Recall@K", format: percentage, formatDeviation: percentagePoints },
  { key: "latency_p95_ms", label: "Mean of per-run p95 latency (ms)", format: milliseconds, formatDeviation: milliseconds },
  { key: "technical_error_rate", label: "Technical error rate", format: percentage, formatDeviation: percentagePoints },
];

function metricValue(value: number | null, format: (value: number) => string): string {
  return value === null ? "Unavailable" : format(value);
}

export function RepeatSummary({ summary, label }: RepeatSummaryProps) {
  if (!summary) return (
    <section className="repeat-summary panel" aria-label="Repeat variability">
      <h2>Repeat variability</h2>
      <p className="execution-note">Repeat summary unavailable for this saved evaluation.</p>
    </section>
  );
  const { disagreement } = summary;
  return (
    <section className="repeat-summary panel" aria-label={`Repeat variability: ${label ?? summary.group_id}`}>
      <h2>Repeat variability · {label ?? summary.group_id}</h2>
      <dl className="execution-accounting">
        <div><dt>Planned repeats</dt><dd>{summary.planned_count}</dd></div>
        <div><dt>Complete repeats</dt><dd>{summary.complete_count}</dd></div>
        <div><dt>Partial repeats</dt><dd>{summary.partial_count}</dd></div>
        <div><dt>Missing repeats</dt><dd>{summary.missing_count}</dd></div>
      </dl>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Repeat metric statistics">
        <table>
          <caption>Statistics across complete repeats</caption>
          <thead><tr>
            <th scope="col">Metric</th><th scope="col">Count</th><th scope="col">Mean</th>
            <th scope="col">Sample SD</th><th scope="col">Min</th><th scope="col">Max</th>
          </tr></thead>
          <tbody>{metricRows.map((row) => {
            const metric = summary.metrics[row.key];
            return <tr key={row.key}>
              <th scope="row">{row.label}</th>
              <td>{metric.count}</td>
              <td>{metricValue(metric.mean, row.format)}</td>
              <td>{metric.count < 2 ? "Unavailable (n < 2)" : metricValue(metric.sample_sd, row.formatDeviation)}</td>
              <td>{metricValue(metric.min, row.format)}</td>
              <td>{metricValue(metric.max, row.format)}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <p className="execution-note">Partial and missing repeats are excluded from these statistics. Each metric count includes only defined values from complete cohorts. Percentage SD uses percentage points (pp).</p>
      <p className="execution-note">Completed runs with technical errors remain included in accuracy and error statistics.</p>
      <div className="repeat-disagreement">
        <h3>Decision / intent disagreement</h3>
        {disagreement.compared_repeat_count < 2 ? (
          <p>At least two complete repeats are required for decision/intent disagreement.</p>
        ) : disagreement.eligible_case_count === 0 ? (
          <p>No eligible cases. Disagreement is unavailable across {disagreement.compared_repeat_count} complete repeats.</p>
        ) : (
          <p>
            {disagreement.disagreeing_case_count} of {disagreement.eligible_case_count} eligible cases disagree
            {` (${metricValue(disagreement.disagreement_rate, percentage)}) across ${disagreement.compared_repeat_count} complete repeats.`}
          </p>
        )}
        <p className="execution-note">
          {disagreement.excluded_technical_error_case_count} case(s) excluded because of a technical error in at least one compared repeat.
          Intent identity is compared for route, continue, and cancel decisions.
        </p>
      </div>
      <p className="execution-note">
        Repetitions measure observed variability of the same cases, including provider and caching effects,
        and do not guarantee determinism. Repeated records are not additional held-out observations.
        No pooled confidence interval is calculated.
      </p>
    </section>
  );
}
