import { useState } from "react";
import type { Intent } from "./api";
import { useWorkspaceApi } from "./workspace";

const lines = (value: string) => value.split("\n").map(item => item.trim()).filter(Boolean);

type Props = {
  version: string;
  catalog: Intent[];
  refresh: () => Promise<void>;
  onSaved: () => void;
  onCancel: () => void;
};

export default function AddIntent({ version, catalog, refresh, onSaved, onCancel }: Props) {
  const { api } = useWorkspaceApi();
  const [intent, setIntent] = useState<Intent>({
    intent_id: "", name: "", domain: "", description: "", examples: [], exclusions: [],
    confusable_with: [], workflow_id: "", required_slots: [], slot_questions: {},
    kind: "information", channels: ["chat", "voice"], selection_rule: "",
  });
  const [examples, setExamples] = useState("");
  const [exclusions, setExclusions] = useState("");
  const [neighbors, setNeighbors] = useState("");
  const [slots, setSlots] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setError("");
    const examplesList = lines(examples);
    const excluded = lines(exclusions);
    const confusable = lines(neighbors);
    const ids = new Set(catalog.map(item => item.intent_id));
    if (ids.has(intent.intent_id)) { setError("This intent ID already exists. Choose a unique ID."); return; }
    if (examplesList.length < 1 || examplesList.length > 30) { setError("Provide between 1 and 30 example utterances."); return; }
    if (excluded.length > 20 || confusable.length > 20) { setError("Provide at most 20 exclusions and 20 confusable intents."); return; }
    if (confusable.some(id => !ids.has(id))) { setError("Each confusable intent must exist in this workspace catalog."); return; }
    if (!intent.channels.length) { setError("Select at least one channel."); return; }
    const slotQuestions: Record<string, string> = {};
    for (const entry of lines(slots)) {
      const separator = entry.indexOf(":");
      const name = entry.slice(0, separator).trim();
      const question = entry.slice(separator + 1).trim();
      if (separator < 1 || !/^[a-z][a-z0-9_]*$/.test(name) || !question || name in slotQuestions) {
        setError("Use one unique slot_name: question per line."); return;
      }
      slotQuestions[name] = question;
    }
    if (Object.keys(slotQuestions).length > 10) { setError("Provide at most 10 required slots."); return; }
    setBusy(true);
    try {
      await api<{ version: string; intent_count: number; intent: Intent }>("/catalog/intents", {
        method: "POST", body: JSON.stringify({ expected_version: version, intent: {
          ...intent, examples: examplesList, exclusions: excluded, confusable_with: confusable,
          required_slots: Object.keys(slotQuestions), slot_questions: slotQuestions,
        } }),
      });
      await refresh();
      onSaved();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <form className="intent-definition-editor add-intent" aria-label="Add intent" onSubmit={event => { event.preventDefault(); void save(); }}>
    <h2>Add a custom intent</h2>
    <p className="field-hint">Add to the current sector workspace. Existing intents are retained. Examples and descriptions stay in the language you enter.</p>
    {error && <div className="notice error" role="alert"><p>{error}</p><button className="button subtle" type="button" disabled={busy} onClick={() => void refresh()}>Refresh catalog</button><small>Your form is retained. Refresh before retrying if another editor changed the catalog.</small></div>}
    <fieldset disabled={busy}>
      <div className="intent-form-grid">
        <label>Intent ID<input autoFocus required pattern="[a-z][a-z0-9_.]{1,99}" maxLength={100} placeholder="custom.request.status" value={intent.intent_id} onChange={event => setIntent({ ...intent, intent_id: event.target.value })} /></label>
        <label>Intent name<input required minLength={2} maxLength={160} value={intent.name} onChange={event => setIntent({ ...intent, name: event.target.value })} /></label>
        <label>Domain<input required minLength={2} maxLength={80} placeholder="Support" value={intent.domain} onChange={event => setIntent({ ...intent, domain: event.target.value })} /></label>
        <label>Workflow ID<input required pattern="[a-z][a-z0-9_.]{1,119}" maxLength={120} placeholder="workflow.custom.request.status" value={intent.workflow_id} onChange={event => setIntent({ ...intent, workflow_id: event.target.value })} /></label>
      </div>
      <label>Description<textarea required minLength={5} maxLength={1600} value={intent.description} onChange={event => setIntent({ ...intent, description: event.target.value })} /></label>
      <label>Examples (one utterance per line)<textarea required value={examples} onChange={event => setExamples(event.target.value)} /></label>
      <details><summary>Routing boundaries and workflow details</summary><div className="intent-form-options">
        <label>Disambiguation rule<textarea maxLength={800} value={intent.selection_rule} onChange={event => setIntent({ ...intent, selection_rule: event.target.value })} /></label>
        <label>Exclusions (one per line)<textarea value={exclusions} onChange={event => setExclusions(event.target.value)} /></label>
        <label>Confusable intent IDs (one per line)<textarea value={neighbors} onChange={event => setNeighbors(event.target.value)} /></label>
        <label>Intent kind<select value={intent.kind} onChange={event => setIntent({ ...intent, kind: event.target.value as Intent["kind"] })}><option value="information">Information</option><option value="transaction">Transaction</option></select></label>
        <fieldset className="channel-options"><legend>Channels</legend>{(["chat", "voice"] as const).map(channel => <label key={channel}><input type="checkbox" checked={intent.channels.includes(channel)} onChange={event => setIntent({ ...intent, channels: event.target.checked ? [...intent.channels, channel] : intent.channels.filter(value => value !== channel) })} />{channel === "chat" ? "Chat" : "Voice"}</label>)}</fieldset>
        <label>Required slots (slot_name: question per line)<textarea placeholder="booking_reference: What is your booking reference?" value={slots} onChange={event => setSlots(event.target.value)} /></label>
        <p className="field-hint">Slots belong to the workflow after intent selection. The preview does not execute real transactions; custom slot validation requires a workflow implementation.</p>
      </div></details>
    </fieldset>
    <div className="actions"><button className="button primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save intent"}</button><button className="button subtle" type="button" disabled={busy} onClick={onCancel}>Cancel</button></div>
  </form>;
}
