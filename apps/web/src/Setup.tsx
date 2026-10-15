import { useEffect, useRef, useState } from "react";
import type { ConnectionProbe, SetupStatus, Status } from "./api";
import { firstAvailableModel, ModelSelect } from "./ModelPicker";
import { useWorkspaceApi } from "./workspace";

type Kind = "embedding" | "llm";
type Page = "models" | "calibration" | "experiments";
const indexLabels = { present: "Valid persistent index present", missing: "Index missing", invalid: "Index invalid or unreadable", unavailable: "Index unavailable" };
const calibrationLabels = { current: "Current calibration", missing_or_stale: "Missing or stale", unavailable: "Calibration unavailable" };

export default function Setup({ status, refresh, navigate }: {
  status: Status; refresh: () => Promise<void>; navigate: (page: Page) => void;
}) {
  const { api } = useWorkspaceApi();
  const [selection, setSelection] = useState({ embedding: firstAvailableModel(status.models.embedding), llm: firstAvailableModel(status.models.llm) });
  const embeddingId = status.models.embedding.some(option => option.id === selection.embedding && option.available)
    ? selection.embedding : firstAvailableModel(status.models.embedding);
  const llmId = status.models.llm.some(option => option.id === selection.llm && option.available)
    ? selection.llm : firstAvailableModel(status.models.llm);
  const [readiness, setReadiness] = useState<SetupStatus>();
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<Kind>();
  const [probes, setProbes] = useState<Partial<Record<Kind, ConnectionProbe>>>({});
  const generation = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    const current = ++generation.current;
    setReadiness(undefined);
    setError("");
    setProbes({});
    setBusy(undefined);
    const params = new URLSearchParams({ embedding_id: embeddingId, llm_id: llmId });
    api<SetupStatus>("/setup?" + params, { signal: controller.signal }).then(value => {
      if (current === generation.current) setReadiness(value);
    }).catch((error: Error) => {
      if (current === generation.current && !controller.signal.aborted) setError(error.message);
    });
    return () => { controller.abort(); generation.current++; };
  }, [api, embeddingId, llmId, status.catalog_version, status.models, reload]);

  function changeModel(kind: Kind, id: string) {
    generation.current++;
    setProbes({});
    setBusy(undefined);
    setSelection(current => ({ ...current, [kind]: id }));
  }
  async function refreshConnections() {
    generation.current++;
    setProbes({});
    setBusy(undefined);
    setReadiness(undefined);
    setRefreshing(true);
    try { await refresh(); } finally { setRefreshing(false); setReload(value => value + 1); }
  }
  async function check(kind: Kind) {
    const current = generation.current;
    const id = kind === "embedding" ? embeddingId : llmId;
    setBusy(kind);
    setError("");
    try {
      const result = await api<ConnectionProbe>(`/models/${kind}/${encodeURIComponent(id)}/check`, { method: "POST" });
      if (current === generation.current) setProbes(previous => ({ ...previous, [kind]: result }));
    } catch (error) {
      if (current === generation.current) setError((error as Error).message);
    } finally {
      if (current === generation.current) setBusy(undefined);
    }
  }

  return <div className="setup-content">
    <p className="eyebrow">MODEL CONNECTIONS</p>
    <h2>Model setup</h2>
    <p>Check server configuration, then test the connections you intend to use. Configuration alone does not confirm live access.</p>
    <div className="setup-instructions">
      <h3>Connect OpenRouter</h3>
      <ol>
        <li>Copy the repository-root <code>.env.example</code> to <code>.env</code>, retaining existing settings if you already have this file.</li>
        <li>Set <code>INTENT_OPENROUTER_API_KEY=your_openrouter_api_key</code>. The template uses this shared key for both the LLM and embedding models.</li>
        <li>Restart the API to reload this key. For Docker env-file changes, recreate the container: <code>docker compose up -d --force-recreate studio</code>.</li>
      </ol>
      <p>Start the API with the model-enabled command in the README. The offline command overrides and disables the default model connections.</p>
      <p>Custom connections can use their own server credentials. A shared OpenRouter key is not required for a configured private connection.</p>
    </div>
    <div className="setup-toolbar">
      <span>Shared OpenRouter key: <strong>{readiness ? readiness.shared_openrouter_key_present ? "Present on server" : "Not present" : "Checking…"}</strong></span>
      <button className="button subtle" disabled={refreshing} onClick={() => void refreshConnections()}>{refreshing ? "Refreshing…" : "Refresh connections"}</button>
    </div>
    {error && <div className="notice error" role="alert">{error}<button className="button subtle" onClick={() => void refreshConnections()}>Retry readiness</button></div>}
    {!readiness && !error && <p role="status">Checking readiness…</p>}
    <div className="setup-models">
      {(["embedding", "llm"] as const).map(kind => <section className="setup-model" key={kind} aria-label={kind === "embedding" ? "Embedding connection" : "LLM connection"}>
        <ModelSelect label={kind === "embedding" ? "Setup embedding model" : "Setup LLM model"} options={status.models[kind]}
          value={kind === "embedding" ? embeddingId : llmId} disabled={refreshing} onChange={id => changeModel(kind, id)} />
        <p>{readiness ? readiness[kind].configured ? "Connection configured" : "Connection required" : "Checking configuration…"}</p>
        {readiness?.[kind].reason && <p className="field-hint">{readiness[kind].reason}</p>}
        <p role="status">{probes[kind] ? probes[kind].ok ? `Test passed · ${probes[kind].elapsed_ms} ms · current session only` : `Test failed: ${probes[kind].error || "Connection error"}` : "Not tested in this session"}</p>
        <button className="button" disabled={!readiness?.[kind].configured || !!busy || refreshing} onClick={() => void check(kind)}>
          {busy === kind ? "Testing…" : kind === "embedding" ? "Test embedding connection" : "Test LLM connection"}
        </button>
      </section>)}
    </div>
    <p className="field-hint">Only Test connection sends fixed synthetic probes; it may use provider credits. Test results are current-session evidence, not an accuracy benchmark. Refreshing connections or changing selections clears them.</p>
    {readiness && <div className="setup-readiness">
      <section><h3>{indexLabels[readiness.index.state]}</h3><p>{readiness.index.reason}</p>
        <p>Scope: selected embedding, current full catalog, <strong>{readiness.index.representation}</strong> representation. Other experiment profiles can require separate indexes.</p>
        {readiness.embedding.configured && readiness.index.state !== "present" && <code className="config-example">{`.venv/bin/python scripts/${readiness.index.state === "invalid" ? "reindex" : "warm_models"}.py --workspace ${readiness.workspace} --embedding-id ${embeddingId} --representation ${readiness.index.representation}`}</code>}
        <p>Index preparation is a separate explicit action and may use embedding credits.</p>
      </section>
      <section><h3>{calibrationLabels[readiness.calibration.state]}</h3><p>{readiness.calibration.reason}</p>
        <p>Needed for calibrated semantic rejection. Lexical and hybrid routing do not require this threshold. On Calibration, choose the same embedding model before fitting.</p>
      </section>
    </div>}
    <div className="setup-actions">
      <button className="button" onClick={() => navigate("models")}>Open model catalog</button>
      <button className="button" onClick={() => navigate("calibration")}>Open calibration</button>
      <button className="button primary" onClick={() => navigate("experiments")}>Open experiments</button>
    </div>
  </div>;
}
