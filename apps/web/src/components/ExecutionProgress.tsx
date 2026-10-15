import type { Evaluation, EvaluationStatus, EvaluationStopReason } from "../api";

export type ExecutionProgressProps = {
  evaluation: Evaluation;
  cancellationPending?: boolean;
  onCancel: () => void;
};

function reportedUsd(value: number): string {
  return `$${value.toLocaleString("en-US", { maximumSignificantDigits: 8 })}`;
}

const statusLabels: Record<EvaluationStatus, string> = {
  queued: "Queued", running: "Running", completed: "Completed", stopped: "Stopped", cancelled: "Cancelled", failed: "Failed",
};
const stopReasons: Record<EvaluationStopReason, string> = {
  request_limit: "Provider request limit reached.",
  duration_limit: "Duration limit reached.",
  reported_cost_limit: "Reported USD threshold reached.",
  reported_cost_unknown: "Reported cost unavailable.",
  user_cancelled: "Cancelled by user.",
  interrupted: "Interrupted by restart.",
};

export function isEvaluationActive(status: EvaluationStatus): boolean {
  return status === "queued" || status === "running";
}

export function ExecutionProgress({ evaluation, onCancel, cancellationPending = false }: ExecutionProgressProps) {
  const { accounting } = evaluation;
  const active = isEvaluationActive(evaluation.status);
  const cancelling = active && (cancellationPending || evaluation.cancel_requested);
  const status = cancelling
    ? `${evaluation.cancel_requested ? "Cancellation requested" : "Requesting cancellation"} (${evaluation.status})`
    : statusLabels[evaluation.status];
  return (
    <section className="execution-progress panel" aria-label="Evaluation progress">
      <div className="execution-progress-heading">
        <h2>Evaluation progress</h2>
        <span role="status">{status}</span>
        <button type="button" className="button subtle" disabled={!active || cancelling} onClick={onCancel}>
          {cancelling ? "Cancellation pending" : "Cancel evaluation"}
        </button>
      </div>
      {cancelling ? <p className="execution-note">In-flight HTTP or local work may finish before cancellation is acknowledged.</p> : null}
      {evaluation.phase ? <p className="execution-note">Phase: {evaluation.phase}</p> : null}
      {evaluation.stop_reason ? <p className="execution-stop-reason">Stop reason: {stopReasons[evaluation.stop_reason]}</p> : null}
      {!active && evaluation.progress < evaluation.total ? (
        <p className="execution-note">Incomplete evaluation. Finished case results remain available; unexecuted cases are excluded.</p>
      ) : null}
      <dl className="execution-accounting">
        <div><dt>Completed / planned</dt><dd>{evaluation.progress} / {evaluation.total}</dd></div>
        {accounting ? <>
          <div><dt>Provider requests</dt><dd>{accounting.provider_requests}</dd></div>
          <div><dt>Known reported USD subtotal</dt><dd>{reportedUsd(accounting.known_cost_usd)}</dd></div>
          <div><dt>Reported USD total</dt><dd>{accounting.reported_cost_usd === null ? "Unknown" : reportedUsd(accounting.reported_cost_usd)}</dd></div>
          <div><dt>Requests with unknown cost</dt><dd>{accounting.unknown_cost_requests}</dd></div>
        </> : null}
      </dl>
      {accounting
        ? <p className="execution-note">Reported external inference cost only; excludes self-hosting costs.</p>
        : <p className="execution-note">Provider request and cost accounting unavailable for this saved evaluation.</p>}
      <progress aria-label="Completed case executions" value={evaluation.progress} max={evaluation.total || 1} />
    </section>
  );
}
