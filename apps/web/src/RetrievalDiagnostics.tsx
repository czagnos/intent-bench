import type { EvalRecord, EvaluationResult } from "./api";
import { useI18n } from "./i18n";

export const failureNames: Record<string, string> = {
  correct: "Doğru", retrieval_miss: "Kaynak aramada bulunamadı", fusion_cutoff: "Birleştirme / bağlamda elendi",
  reranker_cutoff: "Reranker sonrasında elendi", candidate_cutoff: "LLM aday sınırında elendi",
  selection_error: "Yanlış intent seçildi", unnecessary_clarification: "Gereksiz netleştirme", false_rejection: "Kapsam içi yanlış ret",
  policy_decision: "Workflow / politika kararı", technical_error: "Teknik hata", context_decision: "Konuşma bağlamı kararı",
  oos_false_accept: "OOS yanlış kabul", decision_error: "Diğer karar hatası", untracked: "Aşama kaydı yok",
};
const stageNames: Record<string, string> = { semantic: "Semantik kaynak", lexical: "Sözcüksel kaynak", fusion: "Birleştirme sırası", pool: "Aday havuzu", final: "Son aday listesi" };

export function RetrievalDiagnostics({ result }: { result: EvaluationResult }) {
  const { t, pct, ms } = useI18n();
  const q = result.metrics.stage_quality;
  if (!q) return null;
  const stageK = (stage: string) => stage === "final" ? result.metrics.k : stage === "pool"
    ? result.retrieval_profile?.pool_k ?? result.metrics.k : result.retrieval_profile?.source_k ?? 40;
  return <section className="panel retrieval-diagnostics">
    <div className="panel-heading"><h2>{t("Doğruluk nerede kayboluyor?")}</h2><span className="badge blue">{t("Aşama analizi")}</span></div>
    <p className="field-hint">{t("Aşama recall oranları, beklenen kararı route olan ve araması tamamlanan vakaları kullanır. Teknik hatalar genel accuracy hesabında başarısız kalır.")}</p>
    <div className="quality-cards">
      {Object.entries(q.stages).map(([id, value]) => <div key={id}><span>{t(stageNames[id])} Recall@{stageK(id)}</span><strong>{pct(value.recall)}</strong><small>{value.hits} / {value.total}</small></div>)}
      <div><span>{t("Doğru aday varken doğruluk")}</span><strong>{pct(q.candidate_conditioned_accuracy)}</strong><small>{q.candidate_conditioned_correct} / {q.candidate_conditioned_total}</small></div>
    </div>
    <p className="field-hint">{t("Son aday listesinde doğru intent olan vakalarda doğru route oranı; hata, ret ve netleştirme de paydada kalır.")}</p>
    <p className="field-hint">{t("Araması tamamlanan: {completed} · bağlamdan çözülen: {context} · araması tamamlanamayan: {incomplete}", { completed: q.retrieval_completed, context: q.context_bypasses, incomplete: q.retrieval_incomplete })}</p>
    <div className="quality-breakdown">{Object.entries(q.categories).filter(([id]) => id !== "correct").map(([id, count]) => <div key={id}><span>{t(failureNames[id] || id)}</span><strong>{count}</strong></div>)}</div>
    <p className="field-hint">{t("Her başarısız vaka bir hata grubunda sayılır. Katalog çakışmaları ayrıca insan incelemesi gerektirir; bu gruplar etiketi değiştirmez.")}</p>
    {result.reranker && <p className="field-hint">{t("Reranker p95: {latency} · model hazırlığı: {preparation}", { latency: ms(result.metrics.stage_latency_ms?.reranking?.p95), preparation: ms(result.reranker_prepare_ms) })}</p>}
  </section>;
}

export function CandidateTrace({ record }: { record: EvalRecord }) {
  const { t } = useI18n();
  if (!record.analysis) return null;
  return <div className="candidate-trace">
    <strong>{t(failureNames[record.analysis.category] || record.analysis.category)}</strong>
    <details><summary>{t("Aday izini göster")}</summary>
      <p className="field-hint">{t("Beklenen intentin sırası; — listede yok veya bu aşama çalışmadı.")}</p>
      <dl>{Object.entries(record.analysis.expected_ranks).map(([stage, rank]) => <div key={stage}><dt>{t(stageNames[stage] || stage)}</dt><dd>{rank ?? "—"}</dd></div>)}</dl>
      {record.error_stage && <p>{t("Hata aşaması")}: {record.error_stage}</p>}
      {!!record.candidates?.length && <ol>{record.candidates.map(c => <li key={c.intent_id} className={c.intent_id === record.expected_intent_id ? "trace-expected" : ""}><span>{c.name}</span><small>{c.intent_id} · {c.score.toFixed(4)} ({c.score_type})</small></li>)}</ol>}
    </details>
  </div>;
}
