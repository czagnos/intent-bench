import { useId } from "react";
import type { EvaluationExecutionOptions, ExecutionLimits } from "../api";

export type ExecutionControlValues = {
  repetitions: string;
  maxProviderRequests: string;
  maxDurationSeconds: string;
  maxReportedCostUsd: string;
};

export type ExecutionControlErrors = {
  repetitions?: string;
  maxProviderRequests?: string;
  maxDurationSeconds?: string;
  maxReportedCostUsd?: string;
  plannedCount?: string;
};

export type ExecutionControlValidation =
  | { valid: true; payload: EvaluationExecutionOptions; plannedCount: number }
  | { valid: false; errors: ExecutionControlErrors; plannedCount: number | null };

function decimalValue(value: string): number {
  const text = value.trim();
  return /^(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text) ? Number(text) : NaN;
}

function integerValue(value: string): number {
  return /^\d+$/.test(value.trim()) ? Number(value) : NaN;
}

export function validateExecutionControls(
  value: ExecutionControlValues,
  baseExecutionCount: number | null,
): ExecutionControlValidation {
  const errors: ExecutionControlErrors = {};
  const repetitions = integerValue(value.repetitions);
  if (!Number.isInteger(repetitions) || repetitions < 1 || repetitions > 5)
    errors.repetitions = "Enter an integer from 1 to 5.";
  const limits: ExecutionLimits = {};
  if (value.maxProviderRequests.trim()) {
    const requests = integerValue(value.maxProviderRequests);
    if (!Number.isInteger(requests) || requests < 0 || requests > 100000)
      errors.maxProviderRequests = "Enter an integer from 0 to 100,000, or leave empty.";
    else limits.max_provider_requests = requests;
  }
  if (value.maxDurationSeconds.trim()) {
    const duration = decimalValue(value.maxDurationSeconds);
    if (!Number.isFinite(duration) || duration < 1 || duration > 86400)
      errors.maxDurationSeconds = "Enter a finite number from 1 to 86,400, or leave empty.";
    else limits.max_duration_seconds = duration;
  }
  if (value.maxReportedCostUsd.trim()) {
    const cost = decimalValue(value.maxReportedCostUsd);
    if (!Number.isFinite(cost) || cost <= 0 || cost > 10000)
      errors.maxReportedCostUsd = "Enter a finite amount greater than 0 and at most 10,000, or leave empty.";
    else limits.max_reported_cost_usd = cost;
  }
  let plannedCount: number | null = null;
  if (baseExecutionCount === null || !Number.isSafeInteger(baseExecutionCount) || baseExecutionCount < 0) {
    errors.plannedCount = "Select a valid case and variant combination to calculate the planned count.";
  } else if (!errors.repetitions) {
    plannedCount = baseExecutionCount * repetitions;
    if (plannedCount > 100000)
      errors.plannedCount = "Planned case executions exceed 100,000. Reduce cases, variants, or repetitions.";
  }
  if (Object.keys(errors).length || plannedCount === null)
    return { valid: false, errors, plannedCount };
  return {
    valid: true,
    payload: {
      repetitions,
      ...(Object.keys(limits).length ? { execution_limits: limits } : {}),
    },
    plannedCount,
  };
}

const fields: { key: keyof ExecutionControlValues; label: string; hint: string; inputMode: "numeric" | "decimal" }[] = [
  { key: "repetitions", label: "Repetitions", hint: "Integer from 1 to 5.", inputMode: "numeric" },
  { key: "maxProviderRequests", label: "Maximum provider requests", hint: "Optional integer from 0 to 100,000.", inputMode: "numeric" },
  { key: "maxDurationSeconds", label: "Maximum duration in seconds", hint: "Optional number from 1 to 86,400.", inputMode: "decimal" },
  { key: "maxReportedCostUsd", label: "Reported USD threshold", hint: "Optional amount greater than 0, up to 10,000.", inputMode: "decimal" },
];

export type ExecutionControlsProps = {
  value: ExecutionControlValues;
  baseExecutionCount: number | null;
  disabled?: boolean;
  onChange: (value: ExecutionControlValues) => void;
};

export function ExecutionControls({ value, baseExecutionCount, disabled, onChange }: ExecutionControlsProps) {
  const id = useId();
  const validation = validateExecutionControls(value, baseExecutionCount);
  const errors = validation.valid ? {} : validation.errors;
  return (
    <fieldset className="execution-controls" disabled={disabled}>
      <legend>Execution controls</legend>
      <div className="execution-fields">
        {fields.map((field) => (
          <label key={field.key}>
            {field.label}
            <input
              type="text"
              inputMode={field.inputMode}
              aria-label={field.label}
              aria-describedby={`${id}-${field.key}-hint${errors[field.key] ? ` ${id}-${field.key}-error` : ""}`}
              aria-invalid={Boolean(errors[field.key])}
              value={value[field.key]}
              onChange={(event) => onChange({ ...value, [field.key]: event.target.value })}
            />
            <small id={`${id}-${field.key}-hint`}>{field.hint}</small>
            {errors[field.key] ? (
              <small id={`${id}-${field.key}-error`} className="selection-warning" role="alert">
                {errors[field.key]}
              </small>
            ) : null}
          </label>
        ))}
      </div>
      <p className="execution-preview" aria-live="polite">
        {validation.plannedCount === null
          ? "Planned case executions unavailable."
          : `${baseExecutionCount?.toLocaleString("en-US")} × ${Number(value.repetitions)} = ${validation.plannedCount.toLocaleString("en-US")} planned case executions`}
      </p>
      {errors.plannedCount ? <p className="selection-warning" role="alert">{errors.plannedCount}</p> : null}
      <p className="execution-note">
        Limits apply across all variants and repeats. Leave optional limits empty for no limit.
        USD is a soft stop threshold; an in-flight request may exceed it. Unknown cost stops further requests when a USD threshold is set.
        In-flight HTTP or local work may finish. Duration starts when work begins and excludes queue time.
      </p>
    </fieldset>
  );
}
