import { useState } from "react";
import { api, download, type Intent } from "./api";
import { useI18n } from "./i18n";

type Finding = { id: string; kind: string; intent_ids: string[]; intent_names: string[]; documented_rule: boolean;
  cases: { case_id: string; question: string; split: string; expected_intent_id: string | null }[]; example: string | null };
type Audit = { catalog_version: string; tested_intent_count: number; untested_intent_count: number; intent_count: number; case_count: number;
  counts: Record<string, number>; issues: Finding[];
  seed_migrations?: { id: string; applicable: boolean; updated_intents: string[]; updated_cases: string[]; preserved_intents: string[]; preserved_cases: string[];
    case_changes: { case_id: string; previous_intent_id: string; intent_id: string }[] }[] };
const names: Record<string, string> = { demo_scope_overlap: "Genel / ürüne özel kapsam çakışması", duplicate_example: "Birden fazla intentte aynı örnek",
  example_test_overlap: "Katalog örneği ile vaka örtüşmesi", conflicting_labels: "Aynı soru ve bağlamda farklı etiket", split_overlap: "Veri bölümleri arasında aynı soru" };

export default function CatalogQuality({ catalog, refresh }: { catalog: Intent[]; refresh: () => Promise<void> }) {
  const { t } = useI18n();
  const [audit, setAudit] = useState<Audit>();
  const [editing, setEditing] = useState<Intent>();
  const [examples, setExamples] = useState("");
  const [exclusions, setExclusions] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function inspect() {
    setBusy(true); setError(""); setEditing(undefined);
    try { setAudit(await api<Audit>("/catalog/audit")); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function edit(id: string) {
    if (!audit) return;
    setBusy(true); setError(""); setNotice("");
    try {
      // Load the audited version, rather than stale parent props from another browser session.
      const snapshot = await api<{ intents: Intent[] }>("/catalog?version=" + encodeURIComponent(audit.catalog_version));
      const intent = snapshot.intents.find(i => i.intent_id === id);
      if (intent) { setEditing({ ...intent }); setExamples(intent.examples.join("\n")); setExclusions(intent.exclusions.join("\n")); }
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    if (!editing || !audit) return;
    setBusy(true); setError("");
    const lines = (s: string) => s.split("\n").map(v => v.trim()).filter(Boolean);
    try {
      await api("/catalog/intents/" + encodeURIComponent(editing.intent_id), { method: "PATCH", body: JSON.stringify({ expected_version: audit.catalog_version,
        intent: { ...editing, examples: lines(examples), exclusions: lines(exclusions) } }) });
      setEditing(undefined);
      await refresh();
      setAudit(await api<Audit>("/catalog/audit"));
      setNotice("Yeni katalog sürümü kaydedildi. Kalibrasyonu yenileyip aynı bağımsız test kümesiyle tekrar ölçün.");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const findings = audit?.issues.filter(i => filter === "all" || i.kind === filter) || [];
  return <section className="panel catalog-quality">
    <div className="panel-heading"><h2>{t("Katalog tutarlılığı")}</h2><div className="actions">
      {audit && <button className="button subtle" onClick={() => download("catalog-audit.json", audit)}>{t("Denetimi indir")}</button>}
      <button className="button" disabled={busy} onClick={() => void inspect()}>{t(busy ? "Kontrol ediliyor…" : "Kataloğu denetle")}</button>
    </div></div>
    <p className="field-hint">{t("Aynı örnekleri, veri örtüşmesini ve demo kataloğundaki genel/ürüne özel intent çiftlerini gösterir. Bulgular inceleme adayıdır; semantik denetim veya otomatik etiket düzeltmesi değildir.")}</p>
    {error && <p className="notice error" role="alert">{t(error)}</p>}
    {notice && <p className="notice" role="status">{t(notice)}</p>}
    {audit && <>
      {audit.seed_migrations?.filter(m => m.applicable).map(m => <details className="notice" key={m.id}>
        <summary>{t("Demo taksonomi sürümü")}: {m.id}</summary>
        <p>{t("Güncellenen: {intents} intent, {cases} vaka. Kullanıcı düzenlemesi nedeniyle korunan: {savedIntents} intent, {savedCases} vaka.",
          { intents: m.updated_intents.length, cases: m.updated_cases.length, savedIntents: m.preserved_intents.length, savedCases: m.preserved_cases.length })}</p>
        <p>{t("Önceki deneyler değişmez. Yeni katalog için kalibrasyonu ve deneyleri yeniden çalıştırın. Etiket sürümleri farklı olan accuracy değerlerini doğrudan karşılaştırmayın.")}</p>
        <p>{t("Demo sürümündeki etiket değişiklikleri aşağıdadır; kullanıcı tarafından düzenlenen kayıtlar otomatik değiştirilmez.")}</p>
        <ul>{m.case_changes.map(c => <li key={c.case_id}>{c.case_id}: {c.previous_intent_id} → {c.intent_id}</li>)}</ul>
      </details>)}
      <p>{t("Testte temsil edilen intent: {tested} / {total} · test vakası olmayan intent: {untested}", { tested: audit.tested_intent_count, total: audit.intent_count, untested: audit.untested_intent_count })}</p>
      <p className="field-hint">{t("Bulgulara bakarak test sorularını eğitim örneğine eklemeyin. Öğrenilen düzeltmeleri ayrı bir test kümesiyle doğrulayın.")}</p>
      {editing && <form className="intent-definition-editor" aria-label={t("Intent tanımını düzenle")} onSubmit={e => { e.preventDefault(); void save(); }}>
        <h3>{editing.intent_id}</h3>
        <fieldset disabled={busy}>
          <label>{t("Intent adı")}<input required minLength={2} maxLength={160} value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} /></label>
          <label>{t("Açıklama")}<textarea required minLength={5} maxLength={1600} value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} /></label>
          <label>{t("Ayırt edici seçim kuralı")}<textarea maxLength={800} value={editing.selection_rule || ""} onChange={e => setEditing({ ...editing, selection_rule: e.target.value })} /></label>
          <label>{t("Örnekler (her satıra bir ifade)")}<textarea required value={examples} onChange={e => setExamples(e.target.value)} /></label>
          <label>{t("Kapsam dışı durumlar (her satıra bir ifade)")}<textarea value={exclusions} onChange={e => setExclusions(e.target.value)} /></label>
        </fieldset>
        <p className="field-hint">{t("Seçim kuralı LLM ve reranker girdisine eklenir. Bir kural yazılması, çakışmanın çözüldüğünü veya accuracy'nin arttığını doğrulamaz.")}</p>
        <div className="actions"><button className="button primary" disabled={busy} type="submit">{t("Yeni sürüm olarak kaydet")}</button><button type="button" className="button subtle" disabled={busy} onClick={() => setEditing(undefined)}>{t("Vazgeç")}</button></div>
      </form>}
      <details className="audit-findings">
        <summary>{t("İncelenecek bulgular")} ({audit.issues.length})</summary>
        <label>{t("Bulgu türü")}<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("Tümü")}</option>{Object.entries(audit.counts).map(([id, count]) => <option key={id} value={id}>{t(names[id] || id)} ({count})</option>)}</select></label>
        <div className="audit-list">{findings.map(item => <article key={item.id}>
          <h3>{t(names[item.kind] || item.kind)}</h3>
          <div className="actions">{item.intent_ids.map(id => <button key={id} disabled={busy || !catalog.some(i => i.intent_id === id)} className="button subtle" onClick={() => void edit(id)}>{id}</button>)}</div>
          {item.documented_rule && <small>{t("Seçim kuralı yazılmış; sonuç testle doğrulanmalı.")}</small>}
          {item.example && <p>{item.example}</p>}
          {item.cases.map(c => <p key={c.case_id}><strong>{c.case_id} · {c.split}</strong>: {c.question}<small>{t("Beklenen")}: {c.expected_intent_id || "—"}</small></p>)}
        </article>)}</div>
      </details>
    </>}
  </section>;
}
