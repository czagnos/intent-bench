import type { EvalRecord, EvaluationResult } from "./api";
import { useI18n } from "./i18n";

export const failureNames: Record<string, string> = {
  correct: "Correct", retrieval_miss: "Retrieval miss", fusion_cutoff: "Fusion / context cutoff",
  reranker_cutoff: "Reranker cutoff", candidate_cutoff: "LLM candidate cutoff",
  selection_error: "Wrong intent selection", unnecessary_clarification: "Unnecessary clarification", false_rejection: "In-scope false rejection",
  policy_decision: "Workflow / policy decision", technical_error: "Technical errors", context_decision: "Conversation context decision",
  oos_false_accept: "OOS false acceptance", decision_error: "Other decision error", untracked: "No stage trace",
};
const stageNames: Record<string, string> = { semantic: "Semantic source", lexical: "Lexical source", fusion: "Fusion rank", pool: "Candidate pool", final: "Final candidate list" };

export function RetrievalDiagnostics({ result }: { result: EvaluationResult }) {
  const { t, pct, ms } = useI18n();
  const q = result.metrics.stage_quality;
  if (!q) return null;
  const stageK = (stage: string) => stage === "final" ? result.metrics.k : stage === "pool"
    ? result.retrieval_profile?.pool_k ?? result.metrics.k : result.retrieval_profile?.source_k ?? 40;
  return <section className="panel retrieval-diagnostics">
    <div className="panel-heading"><h2>{t("Where is accuracy lost?")}</h2><span className="badge blue">{t("Stage analysis")}</span></div>
    <p className="field-hint">{t("Stage recall uses expected-route cases whose retrieval completed. Technical errors remain failures in overall accuracy.")}</p>
    <div className="quality-cards">
      {Object.entries(q.stages).map(([id, value]) => <div key={id}><span>{t(stageNames[id])} Recall@{stageK(id)}</span><strong>{pct(value.recall)}</strong><small>{value.hits} / {value.total}</small></div>)}
      <div><span>{t("Accuracy when candidate is present")}</span><strong>{pct(q.candidate_conditioned_accuracy)}</strong><small>{q.candidate_conditioned_correct} / {q.candidate_conditioned_total}</small></div>
    </div>
    <p className="field-hint">{t("Correct routing among cases with the expected intent in the final list; errors, rejections and clarifications remain in the denominator.")}</p>
    <p className="field-hint">{t("Retrieval completed: {completed} · context bypasses: {context} · incomplete retrieval: {incomplete}", { completed: q.retrieval_completed, context: q.context_bypasses, incomplete: q.retrieval_incomplete })}</p>
    <div className="quality-breakdown">{Object.entries(q.categories).filter(([id]) => id !== "correct").map(([id, count]) => <div key={id}><span>{t(failureNames[id] || id)}</span><strong>{count}</strong></div>)}</div>
    <p className="field-hint">{t("Each failed case belongs to one error group. Catalog overlaps need separate human review; these groups do not change labels.")}</p>
    {result.reranker && <p className="field-hint">{t("Reranker p95: {latency} · model preparation: {preparation}", { latency: ms(result.metrics.stage_latency_ms?.reranking?.p95), preparation: ms(result.reranker_prepare_ms) })}</p>}
  </section>;
}

export function CandidateTrace({ record }: { record: EvalRecord }) {
  const { t } = useI18n();
  if (!record.analysis) return null;
  return <div className="candidate-trace">
    <strong>{t(failureNames[record.analysis.category] || record.analysis.category)}</strong>
    <details><summary>{t("Show candidate trace")}</summary>
      <p className="field-hint">{t("Rank of the expected intent; — means absent or the stage did not run.")}</p>
      <dl>{Object.entries(record.analysis.expected_ranks).map(([stage, rank]) => <div key={stage}><dt>{t(stageNames[stage] || stage)}</dt><dd>{rank ?? "—"}</dd></div>)}</dl>
      {record.error_stage && <p>{t("Error stage")}: {record.error_stage}</p>}
      {!!record.candidates?.length && <ol>{record.candidates.map(c => <li key={c.intent_id} className={c.intent_id === record.expected_intent_id ? "trace-expected" : ""}><span>{c.name}</span><small>{c.intent_id} · {c.score.toFixed(4)} ({c.score_type})</small></li>)}</ol>}
    </details>
  </div>;
}
