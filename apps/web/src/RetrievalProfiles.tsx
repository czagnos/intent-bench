import type { ModelOption, RetrievalProfile } from "./api";
import { useI18n } from "./i18n";

export type ProfileDraft = RetrievalProfile & { selected: boolean };
export function initialProfiles(rerankers: ModelOption[] = []): ProfileDraft[] {
  const base: ProfileDraft = { id: "hybrid", name: "Mevcut hibrit", source: "hybrid", representation: "combined",
    source_k: 40, pool_k: 20, candidate_k: 20, semantic_weight: .5, reranker_id: null, selected: true };
  return [base,
    { ...base, id: "semantic", name: "Semantik adaylar + LLM", source: "semantic", selected: false },
    { ...base, id: "weighted", name: "Semantik ağırlıklı hibrit", semantic_weight: .75, selected: false },
    { ...base, id: "reranked", name: "Hibrit + reranker + LLM", source_k: 60, pool_k: 40, candidate_k: 8,
      reranker_id: rerankers.find(r => r.available)?.id || "default", selected: false },
    { ...base, id: "separate", name: "Ayrı tanım ve örnek vektörleri", representation: "separate", selected: false },
    { ...base, id: "semantic-shortlist", name: "Kontrol: semantik + LLM (8 aday)", source: "semantic", candidate_k: 8, selected: false },
    { ...base, id: "semantic-reranked", name: "Kontrol: semantik + reranker + LLM (8 aday)", source: "semantic", candidate_k: 8,
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
    <legend>{t("Arama stratejileri")}</legend>
    <p className="field-hint">{t("Seçili stratejiler her embedding ve LLM çiftiyle aynı vakalarda çalışır. Semantik arama ve sözcüksel referans yöntemleri kendi ayarlarını korur.")}</p>
    <div className="actions">
      <button type="button" className="button subtle" onClick={() => onChange(rows.map(p => ({ ...p, selected: ["hybrid", "semantic", "weighted"].includes(p.id) })))}>{t("İlk üç stratejiyi karşılaştır")}</button>
      <button type="button" className="button subtle" disabled={!availableReranker} onClick={compareReranker}>{t("Reranker açık/kapalı karşılaştır")}</button>
    </div>
    <p className="field-hint">{t("Reranker karşılaştırması: iki stratejide de semantik kaynak, 40 kaynak adayı, 20 havuz adayı ve LLM'e 8 aday. Yalnızca reranker değişir. Düğme bu iki stratejinin ayarlarını sıfırlar.")}</p>
    {!availableReranker && <p className="field-hint">{t("Bu karşılaştırma için Model kataloğu ekranından kullanılabilir bir reranker ekleyin.")}</p>}
    {rows.map(row => <div className={"retrieval-profile " + (row.selected ? "is-selected" : "")} key={row.id}>
      <label className="profile-title"><input type="checkbox" checked={row.selected} onChange={e => change(row.id, { selected: e.target.checked })} />{t(row.name)}</label>
      {row.selected && <div className="profile-controls">
        <label>{t("Aday kaynağı")}<select value={row.source} onChange={e => change(row.id, { source: e.target.value as RetrievalProfile["source"] })}>
          <option value="hybrid">{t("Hibrit RRF")}</option><option value="semantic">{t("Yalnız semantik")}</option>
        </select></label>
        <label>{t("Vektör temsili")}<select value={row.representation} onChange={e => change(row.id, { representation: e.target.value as RetrievalProfile["representation"] })}>
          <option value="combined">{t("Tanım + örnek birlikte")}</option><option value="separate">{t("Tanım ve örnek ayrı")}</option>
        </select></label>
        <label>{t("Kaynak başına aday")}<input type="number" min={2} max={100} value={row.source_k} onChange={e => change(row.id, { source_k: Number(e.target.value) })} /></label>
        <label>{t("Aday havuzu")}<input type="number" min={2} max={row.source_k} value={row.pool_k} onChange={e => change(row.id, { pool_k: Number(e.target.value) })} /></label>
        <label>{t("LLM'e giden aday")}<input type="number" min={2} max={Math.min(40, row.pool_k)} value={row.candidate_k} onChange={e => change(row.id, { candidate_k: Number(e.target.value) })} /></label>
        <label>{t("Semantik ağırlık (%)")}<input type="number" min={1} max={99} disabled={row.source === "semantic"} value={Math.round(row.semantic_weight * 100)} onChange={e => change(row.id, { semantic_weight: Number(e.target.value) / 100 })} /></label>
        <label className="profile-reranker">Reranker<select value={row.reranker_id || ""} onChange={e => change(row.id, { reranker_id: e.target.value || null })}>
          <option value="">{t("Kapalı")}</option>
          {rerankers.map(r => <option key={r.id} value={r.id} disabled={!r.available}>{t(r.name)}{r.available ? "" : t(" · bağlantı gerekli")}</option>)}
        </select></label>
      </div>}
    </div>)}
    <p className="field-hint">{t("LLM aday sayısı ≤ havuz ≤ kaynak başına aday. Reranker yalnızca havuzu yeniden sıralar; havuzda olmayan intenti bulamaz. Yeni reranker bağlantısını Model kataloğu ekranından ekleyebilirsin.")}</p>
    {!profilesValid(selectedProfiles(rows), rerankers) && <p className="selection-warning" role="alert">{t("Strateji seçimlerini, aday sayılarını ve reranker bağlantısını kontrol edin.")}</p>}
  </fieldset>;
}
