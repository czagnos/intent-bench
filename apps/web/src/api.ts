export type MethodId = "lexical" | "e5" | "hybrid_llm";
export type Method = {
  id: MethodId;
  name: string;
  available: boolean;
  description: string;
  model: string;
};
export type ModelOption = {
  registered?: boolean;
  id: string;
  name: string;
  model: string;
  description: string;
  license: string | null;
  weights_url: string | null;
  available: boolean;
  unavailable_reason: string | null;
  settings: { provider_only?: string[]; reasoning?: string; profile?: string };
};
export type ModelCatalog = {
  embedding: ModelOption[];
  llm: ModelOption[];
  reranker?: ModelOption[];
  max_variants: number;
  verified_on: string;
};
export type ConnectionProbe = {
  ok: boolean;
  model: string;
  accuracy_benchmark: false;
  error?: string;
  elapsed_ms: number;
  dimensions?: number;
};
export type SetupConnection = { id: string; model: string; configured: boolean; reason: string | null };
export type SetupStatus = {
  workspace: string;
  catalog_version: string;
  shared_openrouter_key_present: boolean;
  embedding: SetupConnection;
  llm: SetupConnection;
  index: { state: "present" | "missing" | "invalid" | "unavailable"; representation: "combined" | "separate"; reason: string | null };
  calibration: { state: "current" | "missing_or_stale" | "unavailable"; reason: string | null };
};
export type Candidate = {
  intent_id: string;
  name: string;
  domain: string;
  score: number;
  score_type: string;
  evidence: string;
  semantic_score: number | null;
  lexical_score: number | null;
};
export type Intent = {
  intent_id: string;
  name: string;
  domain: string;
  description: string;
  examples: string[];
  exclusions: string[];
  confusable_with: string[];
  workflow_id: string;
  required_slots: string[];
  slot_questions: Record<string, string>;
  kind: "information" | "transaction";
  channels: ("chat" | "voice")[];
  selection_rule?: string;
};
export type RetrievalProfile = {
  id: string;
  name: string;
  source: "hybrid" | "semantic";
  representation: "combined" | "separate";
  source_k: number;
  pool_k: number;
  candidate_k: number;
  semantic_weight: number;
  reranker_id: string | null;
};
export type RetrievalTrace = {
  executed: boolean;
  completed?: boolean;
  source?: string;
  semantic?: string[];
  lexical?: string[];
  fusion?: string[];
  pool?: string[];
  final?: string[];
  reranker_used?: boolean;
};
export type StageQuality = {
  protocol: string;
  routing_total: number;
  retrieval_completed: number;
  context_bypasses: number;
  retrieval_incomplete: number;
  stages: Record<string, { hits: number; total: number; recall: number | null }>;
  candidate_conditioned_accuracy: number | null;
  candidate_conditioned_correct: number;
  candidate_conditioned_total: number;
  categories: Record<string, number>;
  technical_stages: Record<string, number>;
};
export type ImportReport = {
  filename: string;
  dataset_version: string;
  imported: number;
  inserted?: number;
  already_present?: number;
  rows: number;
  skipped_empty_question: number;
  duplicates: number;
  valid_traces: number;
  source_flags: Record<string, number>;
  notes: string[];
};
export type Status = {
  workspace: string;
  intent_count: number;
  catalog_min_size?: number;
  case_count: number;
  customer_case_count: number;
  reviewed_customer_count: number;
  reviewed_customer_test_count: number;
  seed_case_count: number;
  catalog_version: string;
  llm_configured: boolean;
  llm_model: string;
  llm_provider: string;
  embedding_mode: string;
  embedding_model: string;
  embedding_configured: boolean;
  embedding_profile: string;
  methods: Method[];
  models: ModelCatalog;
  imports: ImportReport[];
};
export type EmbeddingMetadata = {
  model: string;
  mode: string;
  profile: string;
  query_instruction: string | null;
  provider: string;
  provider_only?: string[];
};
export type LlmMetadata = {
  model: string;
  timeout_seconds: number;
  connection_id?: string;
} & (
  | {
      provider: "openrouter" | "openai_compatible";
      reasoning: "disabled" | "low" | "none";
      max_tokens: number;
      response_format: "json_schema" | "json_object" | "prompt";
      send_temperature?: boolean;
      thinking_parameter?: "none" | "chat_template" | "top_level" | "openrouter";
      provider_only?: string[];
    }
  | {
      provider: "typesafe";
      protocol: "systemone";
      prompt_version: string;
    }
);
export type Variant = {
  group_id?: string;
  repeat_index?: number;
  model_labels?: { embedding?: string; llm?: string; reranker?: string };
  retrieval_profile?: RetrievalProfile;
  reranker?: { model: string; mode: string } | null;
  id: string;
  method: MethodId;
  name: string;
  embedding: EmbeddingMetadata | null;
  llm: LlmMetadata | null;
  catalog?: CatalogScope;
  base_variant_id?: string;
};
export type CatalogScope = {
  version: string;
  parent_version: string;
  intent_count: number;
  protected_intent_count: number;
  available_intent_count: number;
  intent_ids: string[];
  selection_seed: number;
  selection_protocol: string;
};
export type Decision = {
  decision: string;
  intent_id: string | null;
  intent_name: string | null;
  workflow_id: string | null;
  slots: Record<string, string>;
  missing_slots: string[];
  message: string;
  reason_code: string;
  candidates: Candidate[];
  clarification_options: { intent_id: string; name: string }[];
  timings_ms: Record<string, number>;
  model: string;
  embedding?: EmbeddingMetadata | null;
  llm?: LlmMetadata | null;
  variant?: Variant;
  method: string;
  catalog_version: string;
  prompt_version: string | null;
  simulation_complete: boolean;
  pending_confirmation?: boolean;
  dialogue_act?: string;
  calibration?: Rejection | null;
  rejection_score?: number | null;
  usage: Record<string, number>;
};
export type Stage = {
  id: number;
  stage: string;
  label: string;
  at?: number;
  catalog_version?: string;
  candidates?: Candidate[];
};
export type Job = {
  id: string;
  status: string;
  result?: Decision;
  error?: string;
  events: Stage[];
};
export type DataSplit = "dev" | "calibration" | "test";
export type ReviewDecision = "route" | "continue" | "cancel" | "clarify" | "out_of_scope" | "handoff";
export type PreTurnContext = {
  active_intent?: string | null;
  slots?: Record<string, string>;
  pending_slot?: string | null;
  pending_confirmation?: boolean;
  clarification_options?: string[];
  clarifications?: number;
  messages?: { role: "user" | "assistant"; content: string }[];
};
export type Case = {
  case_id: string;
  conversation_id?: string | null;
  source_dataset_id?: string | null;
  source_session_id?: string;
  source_message_id?: string;
  context?: PreTurnContext;
  question: string;
  reference_answer?: string;
  source: string;
  reviewed: boolean;
  source_flag: string | null;
  expected_decision: ReviewDecision | null;
  expected_intent_id: string | null;
  split: DataSplit;
  suggestions: Candidate[];
  historical_trace?: { action?: string; elapsed_seconds?: number };
};
export type CaseSnapshot = Omit<Case, "suggestions">;
export type CaseVersions = {
  case_id: string;
  current: CaseSnapshot;
  versions: { version: string; created: number; reason: string; case: CaseSnapshot }[];
};
export type ConversationSplitResult = { conversation_id: string; split: DataSplit; updated_count: number };
export type Metrics = {
  stage_quality?: StageQuality;
  total: number;
  correct: number;
  routing_total: number;
  routing_correct: number;
  routing_accuracy: number | null;
  decision_accuracy: number | null;
  routing_accuracy_ci95: number[] | null;
  macro_f1: number | null;
  recall_at_k: number | null;
  k: number;
  coverage: number | null;
  routed_precision: number | null;
  clarification_rate: number | null;
  oos_false_accept_rate: number | null;
  in_scope_false_reject_rate?: number | null;
  oos_total?: number;
  errors: number;
  intent_count: number;
  latency_ms: Record<string, number | null>;
  stage_latency_ms?: Record<
    string,
    { count: number; p50: number | null; p95: number | null }
  >;
  confusions: { expected: string; predicted: string; count: number }[];
};
export type EvalRecord = {
  retrieval_trace?: RetrievalTrace;
  candidates?: Candidate[];
  retrieval_candidates?: Candidate[];
  error_stage?: string | null;
  analysis?: { category: string; expected_ranks: Record<string, number | null>; error_stage?: string | null };
  case_id: string;
  question: string;
  expected_decision: string;
  expected_intent_id: string | null;
  decision: string;
  intent_id: string | null;
  correct: boolean;
  total_ms: number;
  reason_code: string;
  error: string | null;
  message?: string;
  rejection_score?: number | null;
  diagnostics?: Record<string, unknown> | null;
};
export type EvaluationResult = {
  group_id?: string;
  repeat_index?: number;
  complete?: boolean;
  completed_count?: number;
  selected_count?: number;
  model_labels?: { embedding?: string; llm?: string; reranker?: string };
  retrieval_profile?: RetrievalProfile;
  reranker?: { model: string; mode: string } | null;
  reranker_prepare_ms?: number;
  metrics: Metrics;
  records: EvalRecord[];
  model: string | null;
  method?: MethodId;
  embedding?: EmbeddingMetadata | null;
  llm?: LlmMetadata | null;
  calibration?: Rejection | null;
  index_build_ms?: number;
  index_cache_hit?: boolean;
  index_error?: string | null;
  catalog?: CatalogScope;
  base_variant_id?: string;
  calibration_build_ms?: number;
  preparation_error?: string | null;
  scaling?: {
    baseline_intent_count: number | null;
    accuracy_delta_pp: number | null;
    p95_ratio: number | null;
  };
};
export type ExecutionLimits = {
  max_provider_requests?: number | null;
  max_duration_seconds?: number | null;
  max_reported_cost_usd?: number | null;
};
export type EvaluationExecutionOptions = {
  repetitions: number;
  execution_limits?: ExecutionLimits;
};
// Saved artifacts can predate individual options; request payloads use EvaluationExecutionOptions.
export type EvaluationSavedOptions = {
  repetitions?: number;
  execution_limits?: ExecutionLimits;
  methods?: MethodId[];
  embedding_ids?: string[];
  llm_ids?: string[];
  semantic_rejection?: "calibrated" | "off";
  source?: "all" | "seed" | "customer";
  split?: "dev" | "calibration" | "test";
  limit?: number;
  catalog_sizes?: number[] | null;
  catalog_seed?: number;
  scale_calibration_source?: "seed" | "customer";
  scale_max_oos_false_accept_rate?: number;
  retrieval_profiles?: RetrievalProfile[] | null;
};
export type EvaluationStatus = "queued" | "running" | "completed" | "stopped" | "cancelled" | "failed";
export type EvaluationStopReason =
  | "request_limit"
  | "duration_limit"
  | "reported_cost_limit"
  | "reported_cost_unknown"
  | "user_cancelled"
  | "interrupted";
export type ExecutionUsageTotals = {
  provider_requests: number;
  known_prompt_tokens: number;
  known_completion_tokens: number;
  known_total_tokens: number;
  unknown_prompt_token_requests: number;
  unknown_completion_token_requests: number;
  unknown_total_token_requests: number;
  known_cost_usd: number;
  unknown_cost_requests: number;
  reported_cost_usd: number | null;
};
export type ServiceStageAccounting = ExecutionUsageTotals & {
  service: "embedding" | "llm" | "typesafe" | "reranker";
  stage: "evaluation" | "index" | "calibration" | "cases";
};
export type ExecutionAccounting = ExecutionUsageTotals & {
  by_service_stage: ServiceStageAccounting[];
};
export type RepeatMetricSummary = {
  count: number;
  mean: number | null;
  sample_sd: number | null;
  min: number | null;
  max: number | null;
};
export type RepeatGroupMetrics = {
  routing_accuracy: RepeatMetricSummary;
  decision_accuracy: RepeatMetricSummary;
  macro_f1: RepeatMetricSummary;
  recall_at_k: RepeatMetricSummary;
  latency_p95_ms: RepeatMetricSummary;
  technical_error_rate: RepeatMetricSummary;
};
export type RepeatCaseDisagreement = {
  case_id: string;
  distinct_outcome_count: number;
  disagrees: boolean;
};
export type RepeatDisagreementSummary = {
  compared_repeat_count: number;
  eligible_case_count: number;
  excluded_technical_error_case_count: number;
  disagreeing_case_count: number;
  disagreement_rate: number | null;
  cases: RepeatCaseDisagreement[];
};
export type RepeatGroupSummary = {
  group_id: string;
  planned_count: number;
  complete_count: number;
  partial_count: number;
  missing_count: number;
  metrics: RepeatGroupMetrics;
  latency_label: string;
  disagreement: RepeatDisagreementSummary;
};
export type Evaluation = {
  id: string;
  status: EvaluationStatus;
  options?: EvaluationSavedOptions;
  cancel_requested?: boolean;
  stop_reason?: EvaluationStopReason | null;
  accounting?: ExecutionAccounting;
  started?: number;
  elapsed_ms?: number;
  group_summaries?: RepeatGroupSummary[];
  created: number;
  selected_count: number;
  unreviewed_excluded: number;
  progress: number;
  total: number;
  dataset_fingerprint: string;
  catalog_version: string;
  catalog_scopes?: CatalogScope[];
  source_counts: Record<string, number>;
  variants?: Variant[];
  active_variant?: string;
  phase?: string;
  latency_protocol?: string;
  error?: string;
  results?: Record<string, EvaluationResult>;
};

export function createWorkspaceClient(workspace: string) {
  function url(path: string) {
    return (
      "/v1" + path + (path.includes("?") ? "&" : "?") + "workspace=" + encodeURIComponent(workspace)
    );
  }
  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url(path), {
      ...init,
      headers: {
        ...(init?.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(" ")
            : "The request could not be completed.",
      );
    }
    return data;
  }
  function waitForRoute(
    id: string,
    onStage: (stage: Stage) => void,
    signal: AbortSignal,
  ): Promise<Job> {
    return new Promise((resolve, reject) => {
      const source = new EventSource(url("/requests/" + id + "/events"));
      let poll: ReturnType<typeof setInterval> | undefined;
      let inactivity: ReturnType<typeof setTimeout> | undefined;
      let timeout: ReturnType<typeof setTimeout> | undefined;
      let settled = false;
      let polling = false;
      const cleanup = () => {
        settled = true;
        source.close();
        clearInterval(poll);
        clearTimeout(inactivity);
        clearTimeout(timeout);
        signal.removeEventListener("abort", aborted);
      };
      const done = (job: Job) => {
        if (settled) return;
        cleanup();
        resolve(job);
      };
      const aborted = () => {
        if (settled) return;
        cleanup();
        reject(new DOMException("Aborted", "AbortError"));
      };
      const watchResponse = () => {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
          cleanup();
          reject(
            new Error(
              "The response timed out. The request status is preserved on the server.",
            ),
          );
        }, 120000);
      };
      watchResponse();
      signal.addEventListener("abort", aborted);
      if (signal.aborted) {
        aborted();
        return;
      }
      const startPolling = () => {
        if (settled) return;
        clearTimeout(inactivity);
        source.close();
        if (!poll)
          poll = setInterval(() => {
            if (settled || polling) return;
            polling = true;
            api<Job>("/requests/" + id, { signal })
              .then((job) => {
                if (settled) return;
                job.events.forEach(onStage);
                if (["completed", "failed", "superseded"].includes(job.status))
                  done(job);
                else watchResponse();
              })
              .catch((error) => {
                if (settled) return;
                cleanup();
                reject(error);
              })
              .finally(() => { polling = false; });
          }, 750);
      };
      const watchStream = () => {
        clearTimeout(inactivity);
        if (!settled && !poll) inactivity = setTimeout(startPolling, 5000);
      };
      source.addEventListener("stage", (e) => {
        if (settled) return;
        watchResponse();
        watchStream();
        onStage(JSON.parse((e as MessageEvent).data));
      });
      source.addEventListener("result", (e) =>
        done(JSON.parse((e as MessageEvent).data)),
      );
      source.onerror = startPolling;
      watchStream();
    });
  }
  return { workspace, api, waitForRoute };
}

export function download(filename: string, value: unknown) {
  const address = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = address;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(address);
}
export const pct = (value: number | null | undefined) =>
  value == null ? "—" : (value * 100).toFixed(1) + "%";
export const ms = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value >= 1000
      ? (value / 1000).toFixed(2) + " s"
      : Math.round(value) + " ms";

export type CalibrationMetrics = {
  threshold: number;
  in_scope_accept_rate: number;
  in_scope_false_reject_rate: number;
  oos_false_accept_rate: number;
  in_scope_total: number;
  oos_total: number;
  in_scope_accepted: number;
  oos_false_accepted: number;
  low_retention: boolean;
};
export type CalibrationFit = {
  id: string;
  mode: "calibrated";
  calibrated: true;
  model: string;
  threshold: number;
  source: string;
  created: number;
  sample_count: number;
  catalog_version: string;
  dataset_fingerprint: string;
  max_oos_false_accept_rate: number;
  metrics: CalibrationMetrics;
};
export type Rejection = CalibrationFit | { mode: "off"; calibrated: false };
export type CalibrationStatus = {
  profiles: {
    embedding_id: string;
    model: string;
    available: boolean;
    calibration: CalibrationFit | null;
    reason?: string;
  }[];
  datasets: Record<string, { total: number; in_scope: number; oos: number }>;
  catalog_version: string;
};
export type CalibrationJob = {
  id: string;
  status: string;
  progress: number;
  total: number;
  active_model?: string;
  error?: string;
  results: Record<
    string,
    {
      status: string;
      model: string;
      error?: string;
      calibration?: CalibrationFit;
    }
  >;
};
