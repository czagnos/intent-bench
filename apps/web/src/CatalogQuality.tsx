import { useWorkspaceApi } from "./workspace";
import { useState } from "react";
import { download, type Intent } from "./api";
import { useI18n } from "./i18n";

type Finding = { id: string; kind: string; intent_ids: string[]; intent_names: string[]; documented_rule: boolean;
  cases: { case_id: string; question: string; split: string; expected_intent_id: string | null }[]; example: string | null };
type Audit = { catalog_version: string; tested_intent_count: number; untested_intent_count: number; intent_count: number; case_count: number;
  counts: Record<string, number>; issues: Finding[];
  seed_migrations?: { id: string; applicable: boolean; updated_intents: string[]; updated_cases: string[]; preserved_intents: string[]; preserved_cases: string[];
    case_changes: { case_id: string; previous_intent_id: string; intent_id: string }[] }[] };
const names: Record<string, string> = { demo_scope_overlap: "General / product-specific scope overlap", duplicate_example: "Same example across intents",
  example_test_overlap: "Catalog example overlaps a case", conflicting_labels: "Conflicting labels for the same question and context", split_overlap: "Same question across dataset splits" };

export default function CatalogQuality({ catalog, refresh }: { catalog: Intent[]; refresh: () => Promise<void> }) {
  const { api } = useWorkspaceApi();
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
      setNotice("New catalog version saved. Recalibrate and measure again using the same independent test set.");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const findings = audit?.issues.filter(i => filter === "all" || i.kind === filter) || [];
  return <section className="panel catalog-quality">
    <div className="panel-heading"><h2>{t("Catalog consistency")}</h2><div className="actions">
      {audit && <button className="button subtle" onClick={() => download("catalog-audit.json", audit)}>{t("Download audit")}</button>}
      <button className="button" disabled={busy} onClick={() => void inspect()}>{t(busy ? "Checking…" : "Audit catalog")}</button>
    </div></div>
    <p className="field-hint">{t("Find duplicate examples, dataset overlaps and general/product-specific intent pairs in the demo catalog. Findings are review candidates, not a semantic audit or automatic label correction.")}</p>
    {error && <p className="notice error" role="alert">{t(error)}</p>}
    {notice && <p className="notice" role="status">{t(notice)}</p>}
    {audit && <>
      {audit.seed_migrations?.filter(m => m.applicable).map(m => <details className="notice" key={m.id}>
        <summary>{t("Demo taxonomy version")}: {m.id}</summary>
        <p>{t("Updated: {intents} intents, {cases} cases. Preserved user edits: {savedIntents} intents, {savedCases} cases.",
          { intents: m.updated_intents.length, cases: m.updated_cases.length, savedIntents: m.preserved_intents.length, savedCases: m.preserved_cases.length })}</p>
        <p>{t("Previous experiments remain unchanged. Run calibration and experiments again for the new catalog. Accuracy values from different label versions are not directly comparable.")}</p>
        <p>{t("The demo release label changes are listed below; user-edited records are not changed automatically.")}</p>
        <ul>{m.case_changes.map(c => <li key={c.case_id}>{c.case_id}: {c.previous_intent_id} → {c.intent_id}</li>)}</ul>
      </details>)}
      <p>{t("Intents represented in tests: {tested} / {total} · intents without test cases: {untested}", { tested: audit.tested_intent_count, total: audit.intent_count, untested: audit.untested_intent_count })}</p>
      <p className="field-hint">{t("Keep test questions out of training examples. Validate changes informed by this review on a separate test set.")}</p>
      {editing && <form className="intent-definition-editor" aria-label={t("Edit intent definition")} onSubmit={e => { e.preventDefault(); void save(); }}>
        <h3>{editing.intent_id}</h3>
        <fieldset disabled={busy}>
          <label>{t("Intent name")}<input required minLength={2} maxLength={160} value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} /></label>
          <label>{t("Description")}<textarea required minLength={5} maxLength={1600} value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} /></label>
          <label>{t("Disambiguation rule")}<textarea maxLength={800} value={editing.selection_rule || ""} onChange={e => setEditing({ ...editing, selection_rule: e.target.value })} /></label>
          <label>{t("Examples (one utterance per line)")}<textarea required value={examples} onChange={e => setExamples(e.target.value)} /></label>
          <label>{t("Exclusions (one per line)")}<textarea value={exclusions} onChange={e => setExclusions(e.target.value)} /></label>
        </fieldset>
        <p className="field-hint">{t("The rule is included in LLM and reranker inputs. Writing a rule does not verify that the overlap is resolved or accuracy has improved.")}</p>
        <div className="actions"><button className="button primary" disabled={busy} type="submit">{t("Save as a new version")}</button><button type="button" className="button subtle" disabled={busy} onClick={() => setEditing(undefined)}>{t("Cancel")}</button></div>
      </form>}
      <details className="audit-findings">
        <summary>{t("Findings to review")} ({audit.issues.length})</summary>
        <label>{t("Finding type")}<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("All")}</option>{Object.entries(audit.counts).map(([id, count]) => <option key={id} value={id}>{t(names[id] || id)} ({count})</option>)}</select></label>
        <div className="audit-list">{findings.map(item => <article key={item.id}>
          <h3>{t(names[item.kind] || item.kind)}</h3>
          <div className="actions">{item.intent_ids.map(id => <button key={id} disabled={busy || !catalog.some(i => i.intent_id === id)} className="button subtle" onClick={() => void edit(id)}>{id}</button>)}</div>
          {item.documented_rule && <small>{t("Rules are documented; verify the outcome with tests.")}</small>}
          {item.example && <p>{item.example}</p>}
          {item.cases.map(c => <p key={c.case_id}><strong>{c.case_id} · {c.split}</strong>: {c.question}<small>{t("Expected")}: {c.expected_intent_id || "—"}</small></p>)}
        </article>)}</div>
      </details>
    </>}
  </section>;
}
