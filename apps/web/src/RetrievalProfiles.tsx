import type { ModelOption, RetrievalProfile } from "./api";
import { useI18n } from "./i18n";

export type ProfileDraft = RetrievalProfile & { selected: boolean };
export function initialProfiles(rerankers: ModelOption[] = []): ProfileDraft[] {
  const base: ProfileDraft = { id: "hybrid", name: "Current hybrid", source: "hybrid", representation: "combined",
    source_k: 40, pool_k: 20, candidate_k: 20, semantic_weight: .5, reranker_id: null, selected: true };
  return [base,
    { ...base, id: "semantic", name: "Semantic candidates + LLM", source: "semantic", selected: false },
    { ...base, id: "weighted", name: "Semantic-weighted hybrid", semantic_weight: .75, selected: false },
    { ...base, id: "reranked", name: "Hybrid + reranker + LLM", source_k: 60, pool_k: 40, candidate_k: 8,
      reranker_id: rerankers.find(r => r.available)?.id || "default", selected: false },
    { ...base, id: "separate", name: "Separate description and example vectors", representation: "separate", selected: false },
    { ...base, id: "semantic-shortlist", name: "Control: semantic + LLM (8 candidates)", source: "semantic", candidate_k: 8, selected: false },
    { ...base, id: "semantic-reranked", name: "Control: semantic + reranker + LLM (8 candidates)", source: "semantic", candidate_k: 8,
      reranker_id: rerankers.find(r => r.available)?.id || "default", selected: false }];
}
export const selectedProfiles = (rows: ProfileDraft[]) => rows.filter(row => row.selected).map(({ selected, ...profile }) => profile);
export function profilesValid(rows: RetrievalProfile[], rerankers: ModelOption[]) {
  return rows.length > 0 && rows.length <= 8 && rows.every(p =>
    [p.source_k, p.pool_k, p.candidate_k].every(v => Number.isInteger(v) && v >= 2) &&
    p.candidate_k <= 40 && p.candidate_k <= p.pool_k && p.pool_k <= p.source_k && p.source_k <= 100 &&
    Number.isFinite(p.semantic_weight) && p.semantic_weight > 0 && p.semantic_weight < 1 &&
    (!p.reranker_id || rerankers.some(r => r.id === p.reranker_id && r.available)));
}

export function RetrievalProfiles({ rows, onChange, rerankers, disabled }: {
  rows: ProfileDraft[]; onChange: (rows: ProfileDraft[]) => void; rerankers: ModelOption[]; disabled: boolean;
}) {
  const { t } = useI18n();
  const change = (id: string, patch: Partial<ProfileDraft>) => onChange(rows.map(p => p.id === id ? { ...p, ...patch } : p));
  const availableReranker = rerankers.find(r => r.available);
  function compareReranker() {
    const defaults = initialProfiles(rerankers);
    onChange(rows.map(row => row.id === "semantic-shortlist" || row.id === "semantic-reranked"
      ? { ...defaults.find(p => p.id === row.id)!, selected: true } : { ...row, selected: false }));
  }
  return <fieldset className="retrieval-profiles" disabled={disabled}>
    <legend>{t("Retrieval strategies")}</legend>
    <p className="field-hint">{t("Selected strategies run on the same cases for each embedding and LLM pair. Semantic search and the lexical baseline keep their own settings.")}</p>
    <div className="actions">
      <button type="button" className="button subtle" onClick={() => onChange(rows.map(p => ({ ...p, selected: ["hybrid", "semantic", "weighted"].includes(p.id) })))}>{t("Compare the first three strategies")}</button>
      <button type="button" className="button subtle" disabled={!availableReranker} onClick={compareReranker}>{t("Compare reranker on/off")}</button>
    </div>
    <p className="field-hint">{t("Reranker comparison: both strategies use semantic retrieval, 40 source candidates, a pool of 20 and 8 candidates sent to the LLM. Only the reranker changes. The button resets these two strategies.")}</p>
    {!availableReranker && <p className="field-hint">{t("Add an available reranker from Model catalog to run this comparison.")}</p>}
    {rows.map(row => <div className={"retrieval-profile " + (row.selected ? "is-selected" : "")} key={row.id}>
      <label className="profile-title"><input type="checkbox" checked={row.selected} onChange={e => change(row.id, { selected: e.target.checked })} />{t(row.name)}</label>
      {row.selected && <div className="profile-controls">
        <label>{t("Candidate source")}<select value={row.source} onChange={e => change(row.id, { source: e.target.value as RetrievalProfile["source"] })}>
          <option value="hybrid">{t("Hybrid RRF")}</option><option value="semantic">{t("Semantic only")}</option>
        </select></label>
        <label>{t("Vector representation")}<select value={row.representation} onChange={e => change(row.id, { representation: e.target.value as RetrievalProfile["representation"] })}>
          <option value="combined">{t("Combined description + example")}</option><option value="separate">{t("Separate description and example")}</option>
        </select></label>
        <label>{t("Candidates per source")}<input type="number" min={2} max={100} value={row.source_k} onChange={e => change(row.id, { source_k: Number(e.target.value) })} /></label>
        <label>{t("Candidate pool")}<input type="number" min={2} max={row.source_k} value={row.pool_k} onChange={e => change(row.id, { pool_k: Number(e.target.value) })} /></label>
        <label>{t("Candidates sent to LLM")}<input type="number" min={2} max={Math.min(40, row.pool_k)} value={row.candidate_k} onChange={e => change(row.id, { candidate_k: Number(e.target.value) })} /></label>
        <label>{t("Semantic weight (%)")}<input type="number" min={1} max={99} disabled={row.source === "semantic"} value={Math.round(row.semantic_weight * 100)} onChange={e => change(row.id, { semantic_weight: Number(e.target.value) / 100 })} /></label>
        <label className="profile-reranker">Reranker<select value={row.reranker_id || ""} onChange={e => change(row.id, { reranker_id: e.target.value || null })}>
          <option value="">{t("Off")}</option>
          {rerankers.map(r => <option key={r.id} value={r.id} disabled={!r.available}>{t(r.name)}{r.available ? "" : t(" · connection required")}</option>)}
        </select></label>
      </div>}
    </div>)}
    <p className="field-hint">{t("LLM candidates ≤ pool ≤ candidates per source. A reranker only reorders the pool; it cannot recover an intent outside it. Add a reranker connection in Model catalog.")}</p>
    {!profilesValid(selectedProfiles(rows), rerankers) && <p className="selection-warning" role="alert">{t("Check strategy selections, candidate budgets and the reranker connection.")}</p>}
  </fieldset>;
}
