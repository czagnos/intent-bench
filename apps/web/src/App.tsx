import { WorkspaceProvider, useWorkspaceApi, type CatalogPreset } from "./workspace";
import { createWorkspaceClient } from "./api";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Database,
  FileCheck2,
  FlaskConical,
  Layers3,
  LoaderCircle,
  MessageSquare,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Upload,
  Workflow,
  X,
} from "lucide-react";
import {
  download,
  type Candidate,
  type Case,
  type CaseSnapshot,
  type CaseVersions,
  type DataSplit,
  type ReviewDecision,
  type ConversationSplitResult,
  type Decision,
  type Evaluation,
  type ImportReport,
  type Intent,
  type MethodId,
  type ModelCatalog,
  type EvaluationResult,
  type Stage,
  type Status,
} from "./api";
import {
  ModelSelect,
  ModelChecklist,
  firstAvailableModel,
  initialModelIds,
} from "./ModelPicker";
import { CaseComparison } from "./CaseComparison";
import { ExecutionControls, validateExecutionControls, type ExecutionControlValues } from "./components/ExecutionControls";
import { ExecutionProgress, isEvaluationActive } from "./components/ExecutionProgress";
import { RepeatSummary } from "./components/RepeatSummary";
import Calibration, { RejectionControl, RejectionSummary } from "./Calibration";
import { CatalogSizes, parseCatalogSizes } from "./CatalogSizes";
import Models from "./Models";
import Setup from "./Setup";
import { RetrievalProfiles, initialProfiles, selectedProfiles, profilesValid } from "./RetrievalProfiles";
import { RetrievalDiagnostics, CandidateTrace } from "./RetrievalDiagnostics";
import CatalogQuality from "./CatalogQuality";
import AddIntent from "./AddIntent";
import "./retrieval-quality.css";
import { useI18n, type Translate } from "./i18n";
import RoutingVisualization from "./RoutingVisualization";
import {
  demoViews,
  mergeStages,
  routeCandidates,
  savedDemoView,
  selectedIntentId,
  VIEW_STORAGE_KEY,
  type DemoView,
} from "./routing-map";
import "./routing-visualization.css";

const nav = [
  { id: "demo", label: "Live demo", icon: MessageSquare },
  { id: "catalog", label: "Intent catalog", icon: Layers3 },
  { id: "models", label: "Model catalog", icon: Database },
  { id: "cases", label: "Cases", icon: FileCheck2 },
  { id: "calibration", label: "Calibration", icon: Settings2 },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
];
const decisionNames: Record<string, string> = {
  route: "Routed",
  continue: "Workflow in progress",
  clarify: "Clarification needed",
  cancel: "Cancelled",
  out_of_scope: "Out of scope",
  handoff: "Agent handoff",
  error: "Connection error",
};
const methodNames: Record<string, string> = {
  lexical: "Lexical baseline",
  e5: "Semantic search",
  hybrid_llm: "Hybrid retrieval + LLM",
};
const resultMethod = (id: string, result: EvaluationResult) =>
  result.method || id;
const baseResultLabel = (id: string, result: EvaluationResult, t: Translate) => {
  const method = resultMethod(id, result);
  const model = result.model_labels?.[method === "hybrid_llm" ? "llm" : "embedding"] || result.model;
  const embedding = method === "hybrid_llm" && result.embedding
    ? result.model_labels?.embedding || result.embedding.model
    : null;
  const models = [model, embedding].filter(Boolean).join(" + ");
  const name = t(result.retrieval_profile?.name || methodNames[method] || "Experiment");
  return `${name}${models ? " · " + models : ""}${result.catalog ? " · " + t("{count} intents", { count: result.catalog.intent_count }) : ""}`;
};
const resultLabel = (id: string, result: EvaluationResult, t: Translate) =>
  baseResultLabel(id, result, t) + (result.repeat_index ? ` · Repeat ${result.repeat_index}` : "");
const slotNames: Record<string, string> = {
  new_limit: "New limit",
  card_last4: "Last four card digits",
  transfer_reference: "Transfer reference",
};

function ErrorBox({ message }: { message: string }) {
  const { t, locale, tag, ms, pct } = useI18n();
  return (
    <div className="notice error" role="alert">
      <CircleHelp size={18} />
      <span>{t(message)}</span>
    </div>
  );
}
function Badge({
  children,
  tone = "",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={"badge " + tone}>{children}</span>;
}
function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  const { t, locale, tag, ms, pct } = useI18n();
  return (
    <div className="empty">
      <Workflow size={30} strokeWidth={1.4} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

const PRESET_STORAGE_KEY = "intent-studio-workspace";
const presetClient = createWorkspaceClient("demo");
function savedWorkspace() {
  try { return localStorage.getItem(PRESET_STORAGE_KEY) || "demo"; } catch { return "demo"; }
}

export default function App() {
  const [presets, setPresets] = useState<CatalogPreset[]>([]);
  const [workspace, setWorkspace] = useState(savedWorkspace);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    presetClient.api<CatalogPreset[]>("/catalog/presets", { signal: controller.signal })
      .then(items => {
        if (controller.signal.aborted) return;
        if (!items.length) throw new Error("No sector presets are available.");
        setPresets(items);
        setWorkspace(current => items.some(item => item.workspace === current) ? current : items[0].workspace);
        setError("");
      })
      .catch(e => { if (!controller.signal.aborted) setError((e as Error).message); });
    return () => controller.abort();
  }, [reload]);
  function selectWorkspace(value: string) {
    setWorkspace(value);
    try { localStorage.setItem(PRESET_STORAGE_KEY, value); } catch { /* Selection works without storage. */ }
  }
  const selected = presets.find(item => item.workspace === workspace);
  if (!selected) return <div className="loading-page">{error ? <div><ErrorBox message={error} /><button className="button" onClick={() => setReload(value => value + 1)}>Retry</button></div> : "Loading sector workspaces…"}</div>;
  return <WorkspaceProvider key={workspace} workspace={workspace}>
    <WorkspaceApp preset={selected} presets={presets} onWorkspaceChange={selectWorkspace} />
  </WorkspaceProvider>;
}

function WorkspaceApp({ preset, presets, onWorkspaceChange }: {
  preset: CatalogPreset; presets: CatalogPreset[]; onWorkspaceChange: (workspace: string) => void;
}) {
  const { api } = useWorkspaceApi();
  const { t, locale, tag, ms, pct } = useI18n();
  const [page, setPage] = useState("demo");
  const [status, setStatus] = useState<Status>();
  const [catalog, setCatalog] = useState<Intent[]>([]);
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsDialog = useRef<HTMLDialogElement | null>(null);
  useEffect(() => {
    if (settingsOpen) settingsDialog.current?.showModal();
  }, [settingsOpen]);
  const refreshGeneration = useRef(0);
  const refresh = useCallback(async () => {
    const generation = ++refreshGeneration.current;
    try {
      const [s, c, models] = await Promise.all([
        api<Status>("/status"),
        api<{ version: string; intents: Intent[] }>("/catalog"),
        api<ModelCatalog>("/models"),
      ]);
      if (generation !== refreshGeneration.current) return;
      setStatus({
        ...s,
        models,
        catalog_version: c.version || s.catalog_version,
        intent_count: c.intents.length,
      });
      setCatalog(c.intents);
      setError("");
    } catch (e) {
      if (generation === refreshGeneration.current) setError((e as Error).message);
    }
  }, [api]);
  useEffect(() => {
    void refresh();
    return () => { refreshGeneration.current++; };
  }, [refresh]);
  return (
    <div className="shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("demo");
          }}
        >
          <span className="brand-symbol">
            <Workflow size={25} />
          </span>
          <span>
            {t("Intent")}
            <span className="brand-light">{t("Bench")}</span>
          </span>
        </a>
        <div className="workspace">
          <div className="workspace-icon">
            <Database size={18} />
          </div>
          <div>
            <strong>{preset.name}</strong>
            <span>{t("Decision model benchmarks")}</span>
          </div>
        </div>
        <div className="nav-label">{t("WORKSPACE")}</div>
        <nav aria-label={t("Main navigation")}>
          {nav.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-item active" : "nav-item"}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={19} />
              <span>{t(item.label)}</span>
              {item.id === "cases" && !!status?.customer_case_count && (
                <span className="nav-count">{status.customer_case_count}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="system-note">
            <ShieldCheck size={18} />
            <span>
              {t("Workflow simulation")}
              <br />
              <small>{t("On-premises compatible architecture")}</small>
            </span>
          </div>
          <button className="nav-item" onClick={() => setSettingsOpen(true)}>
            <Settings2 size={18} />
            {t("Model connections")}
          </button>
          <div className="sidebar-version">
            {t("INTENTBENCH ")}
            <span>{t("v0.1")}</span>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            {t("Workspace ")}
            <span>/</span>{" "}
            <strong>{t(nav.find((n) => n.id === page)?.label)}</strong>
          </div>
          <div className="topbar-actions">
            <label className="sector-select">
              <span>Sector workspace</span>
              <select aria-label="Sector workspace" value={preset.workspace} onChange={event => onWorkspaceChange(event.target.value)}>
                {presets.map(item => <option key={item.id} value={item.workspace}>{item.name}</option>)}
              </select>
            </label>
          </div>
        </header>
        {error && (
          <div className="page-pad">
            <ErrorBox message={error} />
            <button className="button subtle" onClick={() => void refresh()}>
              {t("Reconnect")}
            </button>
          </div>
        )}
        {!status ? (
          !error && (
            <div className="loading-page">
              <LoaderCircle className="spin" />
              {t("Loading workspace…")}
            </div>
          )
        ) : (
          <>
            {page === "demo" && <Demo status={status} catalog={catalog} />}
            {page === "catalog" && (
              <Catalog catalog={catalog} version={status.catalog_version} refresh={refresh} />
            )}
            {page === "cases" && (
              <Cases catalog={catalog} status={status} refresh={refresh} />
            )}
            {page === "calibration" && <Calibration status={status} />}
            {page === "models" && <Models status={status} refresh={refresh} />}
            {page === "experiments" && <Experiments status={status} />}
          </>
        )}
      </main>
      {settingsOpen && (
        <dialog
          ref={settingsDialog}
          className="overlay"
          onCancel={() => setSettingsOpen(false)}
          onClick={() => setSettingsOpen(false)}
        >
          <section
            className="settings-panel"
            role="dialog"
            aria-modal="true"
            aria-label={t("Model connections")}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="icon-button close"
              aria-label={t("Close")}
              onClick={() => setSettingsOpen(false)}
            >
              <X />
            </button>
            {status ? <Setup status={status} refresh={refresh} navigate={page => {
              setSettingsOpen(false);
              setPage(page);
            }} /> : <p>Load the workspace before checking model setup.</p>}
          </section>
        </dialog>
      )}
    </div>
  );
}

export function Demo({
  status,
  catalog,
}: {
  status: Status;
  catalog: Intent[];
}) {
  const { api, waitForRoute } = useWorkspaceApi();
  const { t, locale, tag, ms, pct } = useI18n();
  const [view, setView] = useState<DemoView>(savedDemoView);
  const [visualTurn, setVisualTurn] = useState(0);
  const [requestedCatalogVersion, setRequestedCatalogVersion] =
    useState<string>();
  const [rejection, setRejection] = useState<"calibrated" | "off">(
    "calibrated",
  );
  const [embeddingId, setEmbeddingId] = useState(() =>
    firstAvailableModel(status.models.embedding),
  );
  const [llmId, setLlmId] = useState(() =>
    firstAvailableModel(status.models.llm),
  );
  const [recipeId, setRecipeId] = useState("hybrid");
  const [rerankerId, setRerankerId] = useState(() => firstAvailableModel(status.models.reranker || []));
  const demoRecipes = initialProfiles(status.models.reranker);
  const chosenRecipe = demoRecipes.find(p => p.id === recipeId)!;
  const { selected: _selectedRecipe, ...recipe } = { ...chosenRecipe, reranker_id: recipeId === "reranked" ? rerankerId : null };
  const [method, setMethod] = useState<MethodId>(() =>
    status.methods.find((m) => m.id === "hybrid_llm" && m.available)
      ? "hybrid_llm"
      : status.methods.find((m) => m.id === "e5" && m.available)
        ? "e5"
        : "lexical",
  );
  const [text, setText] = useState("");
  const [messages, setMessages] = useState<{ role: string; content: string }[]>(
    [],
  );
  const [result, setResult] = useState<Decision>();
  const [stages, setStages] = useState<Stage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const candidates = routeCandidates(stages, result);
  const session = useRef<{ session_id: string; revision: number } | null>(null);
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages, busy]);
  useEffect(() => () => { generation.current++; request.current?.abort(); }, []);
  useEffect(() => {
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, view);
    } catch {
      /* View changes still work without storage. */
    }
  }, [view]);
  const reset = () => {
    generation.current++;
    setVisualTurn(generation.current);
    setRequestedCatalogVersion(undefined);
    request.current?.abort();
    session.current = null;
    setMessages([]);
    setResult(undefined);
    setStages([]);
    setError("");
    setBusy(false);
  };
  async function send(value = text) {
    if (!value.trim() || busy) return;
    const version = ++generation.current;
    setVisualTurn(version);
    setRequestedCatalogVersion(undefined);
    setBusy(true);
    setError("");
    setText("");
    setStages([]);
    setResult(undefined);
    setMessages((previous) => [...previous, { role: "user", content: value }]);
    const controller = new AbortController();
    request.current = controller;
    try {
      if (!session.current) {
        const created = await api<{ session_id: string; revision: number }>(
          "/sessions",
          { method: "POST", signal: controller.signal },
        );
        if (generation.current !== version || controller.signal.aborted) return;
        session.current = created;
      }
      session.current.revision++;
      const data = await api<{ request_id: string; catalog_version?: string }>(
        "/route",
        {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({
            session_id: session.current.session_id,
            turn_revision: session.current.revision,
            user_text: value,
            method,
            semantic_rejection: rejection,
            embedding_id: method !== "lexical" ? embeddingId : undefined,
            llm_id: method === "hybrid_llm" ? llmId : undefined,
            ...(method === "hybrid_llm" && recipeId !== "hybrid" ? { retrieval_profile: recipe } : {}),
          }),
        },
      );
      if (generation.current !== version || controller.signal.aborted) return;
      setRequestedCatalogVersion(data.catalog_version);
      const job = await waitForRoute(
        data.request_id,
        (stage) => {
          if (generation.current === version)
            setStages((previous) => mergeStages(previous, [stage]));
        },
        controller.signal,
      );
      if (generation.current !== version) return;
      if (job.status === "superseded")
        throw new Error(
          job.error || "A newer conversation turn superseded this result.",
        );
      if (job.result) {
        setStages((previous) => mergeStages(previous, job.events || []));
        setResult(job.result);
        setMessages((previous) => [
          ...previous,
          { role: "assistant", content: job.result!.message },
        ]);
      } else throw new Error(job.error || "No decision could be produced.");
    } catch (e) {
      if (generation.current === version && (e as Error).name !== "AbortError")
        setError((e as Error).message);
    } finally {
      if (generation.current === version) setBusy(false);
    }
  }
  return (
    <div className="page-pad">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("LIVE DEMO")}</p>
          <h1>{t("From request to the right workflow.")}</h1>
          <p>
            {t(
              "Enter a request and inspect the decision model’s routing step by step.",
            )}
          </p>
        </div>
        <button className="button" onClick={reset}>
          <Plus size={17} />
          {t("New conversation")}
        </button>
      </div>
      <div className="summary-strip">
        <div>
          <span>{t("Catalog")}</span>
          <strong>
            {status.intent_count}
            <small>{t("intent")}</small>
          </strong>
        </div>
        <div>
          <span>{t("Customer cases")}</span>
          <strong>
            {status.customer_case_count}
            <small>{t("records")}</small>
          </strong>
        </div>
        <div>
          <span>{t("Reviewed customer labels")}</span>
          <strong>
            {status.reviewed_customer_count}
            <small>{t("cases")}</small>
          </strong>
        </div>
        <div>
          <span>{t("Accuracy target")}</span>
          <strong>
            {t("90%")}
            <small>{t("not yet validated")}</small>
          </strong>
        </div>
      </div>
      <div
        className="demo-view-picker"
        role="group"
        aria-label={t("Demo view")}
      >
        <span>{t("View")}</span>
        {demoViews.map(([id, label]) => (
          <button
            type="button"
            key={id}
            aria-pressed={view === id}
            onClick={() => setView(id)}
          >
            {t(label)}
          </button>
        ))}
      </div>
      <div
        className={
          "demo-grid" + (view === "standard" ? "" : " demo-grid-visual")
        }
      >
        <section className="panel conversation">
          <div className="panel-heading">
            <div className="heading-icon">
              <MessageSquare size={19} />
              <h2>{t("Conversation")}</h2>
            </div>
            <Badge>{t("Text")}</Badge>
          </div>
          <div className="method-picker">
            <label htmlFor="method">{t("Routing method")}</label>
            <select
              id="method"
              value={method}
              disabled={busy}
              onChange={(e) => {
                reset();
                setMethod(e.target.value as MethodId);
              }}
            >
              {status.methods.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available}>
                  {t(m.name)}
                  {!m.available ? t(" · connection required") : ""}
                </option>
              ))}
            </select>
            <p>{t(status.methods.find((m) => m.id === method)?.description)}</p>
            {method !== "lexical" && (
              <div className="demo-models">
                <ModelSelect
                  label={t("Embedding model")}
                  options={status.models.embedding}
                  value={embeddingId}
                  disabled={busy}
                  onChange={(id) => {
                    reset();
                    setEmbeddingId(id);
                  }}
                />
                {method === "hybrid_llm" && (
                  <ModelSelect
                    label={t("Decision model (LLM)")}
                    options={status.models.llm}
                    value={llmId}
                    disabled={busy}
                    onChange={(id) => {
                      reset();
                      setLlmId(id);
                    }}
                  />
                )}
                <small className="muted">
                  {t("Changing a model starts a new conversation.")}
                </small>
                {method === "hybrid_llm" && <>
                  <label className="model-select"><span>{t("Retrieval strategy")}</span><select value={recipeId} disabled={busy} onChange={e => { reset(); setRecipeId(e.target.value); }}>
                    {demoRecipes.map(p => <option key={p.id} value={p.id} disabled={p.id === "reranked" && !(status.models.reranker || []).some(r => r.available)}>{t(p.name)}</option>)}
                  </select><small>{t("Pool {pool} → LLM {final}", { pool: recipe.pool_k, final: recipe.candidate_k })}</small></label>
                  {recipeId === "reranked" && <ModelSelect label="Reranker" options={status.models.reranker || []} value={rerankerId} disabled={busy} onChange={id => { reset(); setRerankerId(id); }} />}
                </>}
              </div>
            )}
            {method === "e5" && (
              <RejectionControl
                value={rejection}
                disabled={busy}
                onChange={(mode) => {
                  reset();
                  setRejection(mode);
                }}
              />
            )}
          </div>
          <div className="chat-body" aria-live="polite">
            {messages.length === 0 && (
              <div className="chat-welcome">
                <div className="assistant-mark">
                  <Workflow size={24} />
                </div>
                <h3>{t("Which request shall we start with?")}</h3>
                <p>{t("Choose an example or write your own request.")}</p>
                <p className="field-hint">
                  {t("Source data and conversation content are shown in their original language.")}
                </p>
                <div className="scenario-list">
                  {catalog.slice(0, 3).map((intent) => (
                    <button key={intent.intent_id} onClick={() => void send(intent.examples[0])}>
                      {intent.examples[0]}
                      <ArrowUpRight size={16} />
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div className={"chat-message " + message.role} key={index}>
                <span className="speaker">
                  {message.role === "user" ? t("YOU") : t("ASSISTANT")}
                </span>
                <div>{message.content}</div>
              </div>
            ))}
            {busy && (
              <div className="chat-message assistant">
                <span className="speaker">{t("ASSISTANT")}</span>
                <div className="typing">
                  <i />
                  <i />
                  <i />
                  <span>{t(stages.at(-1)?.label || "Processing request")}</span>
                </div>
              </div>
            )}
            <div ref={bottom} />
          </div>
          {error && <ErrorBox message={error} />}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <label className="sr-only" htmlFor="message">
              {t("Your request")}
            </label>
            <textarea
              id="message"
              rows={2}
              maxLength={2000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t(
                "Enter a request to classify…",
              )}
              disabled={busy}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button
              className="send-button"
              disabled={busy || !text.trim()}
              aria-label={t("Send message")}
            >
              {busy ? (
                <LoaderCircle className="spin" size={19} />
              ) : (
                <Send size={19} />
              )}
            </button>
          </form>
          <div className="composer-note">
            {t("Enter to send · Shift + Enter for a new line")}
          </div>
        </section>
        <aside className="inspector">
          {view !== "standard" && (
            <RoutingVisualization
              view={view}
              catalog={catalog}
              catalogVersion={status.catalog_version}
              requestedCatalogVersion={requestedCatalogVersion}
              stages={stages}
              result={result}
              busy={busy}
              error={error}
              turnId={visualTurn}
            />
          )}
          <details
            key={view === "standard" ? "standard" : "visual"}
            className={
              "inspector-details" + (view === "standard" ? " standard" : "")
            }
            open={view === "standard"}
          >
            <summary>{t("Decision and candidate details")}</summary>
            <div className="inspector">
              <section className="panel">
                <div className="panel-heading">
                  <div className="heading-icon">
                    <Activity size={19} />
                    <h2>{t("Inspect the decision")}</h2>
                  </div>
                  <Badge tone="blue">{t("LIVE")}</Badge>
                </div>
                {!result ? (
                  <>
                    <Empty
                      title={
                        busy
                          ? t("Preparing the decision")
                          : t("Waiting for the first message")
                      }
                    >
                      {t(
                        "Intent candidates, the selected workflow and measured latency will appear here.",
                      )}
                    </Empty>
                    {busy && (
                      <div className="stage-list">
                        {stages.map((s) => (
                          <div key={s.id}>
                            <Check size={15} />
                            {t(s.label)}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="decision-content">
                    <div className="decision-top">
                      <Badge
                        tone={
                          ["error", "clarify", "out_of_scope"].includes(
                            result.decision,
                          )
                            ? "amber"
                            : "green"
                        }
                      >
                        {t(decisionNames[result.decision])}
                      </Badge>
                      <span>{ms(result.timings_ms.total)}</span>
                    </div>
                    <h3>
                      {result.intent_name || t(decisionNames[result.decision])}
                    </h3>
                    <p className="mono muted">
                      {result.intent_id || result.reason_code}
                    </p>
                    {result.workflow_id && (
                      <div className="workflow-box">
                        <Workflow size={19} />
                        <div>
                          <span>{t("TARGET WORKFLOW")}</span>
                          <strong>{result.workflow_id}</strong>
                        </div>
                      </div>
                    )}
                    {Object.entries(result.slots).map(([key, value]) => (
                      <div className="slot" key={key}>
                        <span>{t(slotNames[key] || key)}</span>
                        <strong>{value}</strong>
                        <Check size={15} />
                      </div>
                    ))}
                    {result.missing_slots.map((s) => (
                      <div className="slot pending" key={s}>
                        <span>{t(slotNames[s] || s)}</span>
                        <Badge tone="amber">{t("Pending")}</Badge>
                      </div>
                    ))}
                    {result.simulation_complete && (
                      <div className="notice success">
                        {t("Workflow simulation completed.")}
                      </div>
                    )}
                    <div className="timings">
                      {[
                        ["retrieval", "Candidate retrieval"],
                        ["selection", "Intent selection"],
                        ["policy", "Decision validation"],
                      ].map(([key, label]) => (
                        <div key={key}>
                          <span>{t(label)}</span>
                          <strong>{ms(result.timings_ms[key])}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div className="heading-icon">
                    <Layers3 size={18} />
                    <h2>{t("Intent candidates")}</h2>
                  </div>
                  <span className="muted">{candidates.length || "—"}</span>
                </div>
                {candidates.length ? (
                  <div className="candidate-list">
                    {candidates.slice(0, 5).map((c, index) => (
                      <CandidateRow
                        key={c.intent_id}
                        candidate={c}
                        rank={index + 1}
                        selected={c.intent_id === selectedIntentId(result)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="small-empty">
                    {t("Candidates will appear after retrieval.")}
                  </div>
                )}
              </section>
              {result && (
                <div className="run-meta">
                  <span>{t(methodNames[result.method])}</span>
                  <span>
                    {t("Catalog ")}
                    {result.catalog_version.slice(0, 8)}
                  </span>
                  <span>{result.model}</span>
                  <RejectionSummary value={result.calibration} />
                  {result.rejection_score != null && (
                    <span>
                      {t("Rejection score: {score}", {
                        score: result.rejection_score.toFixed(4),
                      })}
                    </span>
                  )}
                  {result.method === "hybrid_llm" && result.embedding && (
                    <span>
                      {t("Embedding: ")}
                      {result.embedding.model}
                    </span>
                  )}
                </div>
              )}
            </div>
          </details>
        </aside>
      </div>
    </div>
  );
}

function CandidateRow({
  candidate: c,
  rank,
  selected,
}: {
  candidate: Candidate;
  rank: number;
  selected?: boolean;
}) {
  const { t, locale, tag, ms, pct } = useI18n();
  return (
    <details className={"candidate " + (selected ? "selected" : "")}>
      <summary>
        <span className="rank">{String(rank).padStart(2, "0")}</span>
        <div>
          <strong>{c.name}</strong>
          <span>{c.domain}</span>
        </div>
        <span className="candidate-score">
          {c.score.toFixed(3)}
          {selected && <Check size={14} />}
        </span>
      </summary>
      <div className="candidate-detail">
        <p>{c.evidence}</p>
        <span>
          {c.score_type === "reciprocal_rank_fusion"
            ? t("Reciprocal rank fusion score")
            : c.score_type === "cosine_similarity"
              ? t("Cosine similarity")
              : t("Lexical similarity")}{" "}
          {t("· Not a probability.")}
        </span>
      </div>
    </details>
  );
}

export function Catalog({
  catalog,
  version,
  refresh,
}: {
  catalog: Intent[];
  version: string;
  refresh: () => Promise<void>;
}) {
  const { api } = useWorkspaceApi();
  const { t, locale, tag, ms, pct } = useI18n();
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("all");
  const [selected, setSelected] = useState<Intent>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const items = catalog.filter(
    (i) =>
      (domain === "all" || i.domain === domain) &&
      (i.name + " " + i.description + " " + i.intent_id)
        .toLocaleLowerCase("en")
        .includes(query.toLocaleLowerCase("en")),
  );
  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await api("/catalog/import", { method: "POST", body: await file.text() });
      await refresh();
      setSelected(undefined);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-pad">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("INTENT CATALOG")}</p>
          <h1>{t("A shared definition of every intent.")}</h1>
          <p>{t("Descriptions, example utterances and workflow mappings.")}</p>
          <p className="field-hint">
            {t("Source data and conversation content are shown in their original language.")}
          </p>
          {catalog.some((intent) => intent.intent_id.startsWith("bank.")) && (
            <p className="field-hint">
              {t(
                "The expanded demo catalog contains illustrative product/action definitions. Validate product availability and intent boundaries for a real customer catalog.",
              )}
            </p>
          )}
        </div>
        <div className="actions">
          <button className="button primary" onClick={() => { setAdding(true); setNotice(""); }}> <Plus size={16} />Add intent</button>
          <button
            className="button"
            onClick={() => download("intent-catalog.json", catalog)}
          >
            <ArrowDownToLine size={16} />
            {t("Export")}
          </button>
          <label className="button primary">
            <Upload size={16} />
            {busy ? t("Uploading…") : t("Import JSON")}
            <input
              className="sr-only"
              type="file"
              accept=".json"
              disabled={busy}
              onChange={(e) => void upload(e.target.files?.[0])}
            />
          </label>
        </div>
      </div>
      {error && <ErrorBox message={error} />}
      {notice && <p className="notice" role="status">{notice}</p>}
      {adding && <AddIntent version={version} catalog={catalog} refresh={refresh} onCancel={() => setAdding(false)} onSaved={() => { setAdding(false); setNotice("Intent added. Refit calibration and evaluate the updated catalog."); }} />}
      <div className="toolbar">
        <div className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Search intents")}
            placeholder={t("Search by intent name, description or ID…")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          aria-label={t("Domain")}
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        >
          <option value="all">{t("All domains")}</option>
          {[...new Set(catalog.map((i) => i.domain))].map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <Badge>
          {items.length}
          {t(" intent")}
        </Badge>
      </div>
      <CatalogQuality catalog={catalog} refresh={refresh} />
      <div className={"catalog-layout " + (selected ? "with-detail" : "")}>
        <div className="catalog-grid">
          {items.map((i) => (
            <button
              key={i.intent_id}
              className={
                "intent-card " +
                (selected?.intent_id === i.intent_id ? "selected" : "")
              }
              onClick={() => setSelected(i)}
            >
              <Badge>{i.domain}</Badge>
              <h3>{i.name}</h3>
              <p>{i.description}</p>
              <div>
                <span>
                  {i.examples.length}
                  {t(" examples")}
                </span>
                <ArrowUpRight size={17} />
              </div>
            </button>
          ))}
        </div>
        {selected && (
          <aside className="panel catalog-detail">
            <div className="panel-heading">
              <h2>{t("Intent details")}</h2>
              <button
                className="icon-button"
                onClick={() => setSelected(undefined)}
                aria-label={t("Close details")}
              >
                <X size={18} />
              </button>
            </div>
            <div className="detail-body">
              <Badge tone="blue">{selected.domain}</Badge>
              <h3>{selected.name}</h3>
              <code>{selected.intent_id}</code>
              <p>{selected.description}</p>
              <h4>{t("Example utterances")}</h4>
              {selected.examples.map((e) => (
                <blockquote key={e}>{e}</blockquote>
              ))}
              {!!selected.exclusions.length && (
                <>
                  <h4>{t("Exclusions")}</h4>
                  {selected.exclusions.map((e) => (
                    <p key={e} className="exclusion">
                      {e}
                    </p>
                  ))}
                </>
              )}
              <h4>{t("Workflow")}</h4>
              <code>{selected.workflow_id}</code>
              <h4>{t("Required information")}</h4>
              <p>
                {selected.required_slots
                  .map((s) => t(slotNames[s] || s))
                  .join(", ") || t("No slots required for the initial routing decision.")}
              </p>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

export function Cases({
  catalog,
  status,
  refresh,
}: {
  catalog: Intent[];
  status: Status;
  refresh: () => Promise<void>;
}) {
  const { api } = useWorkspaceApi();
  const { t, locale, tag, ms, pct } = useI18n();
  const [source, setSource] = useState(
    status.customer_case_count ? "customer" : "all",
  );
  const [query, setQuery] = useState("");
  const [splitFilter, setSplitFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: Case[]; total: number }>({
    items: [],
    total: 0,
  });
  const [selected, setSelected] = useState<Case>();
  const [decision, setDecision] = useState<ReviewDecision>("route");
  const [intentId, setIntentId] = useState("");
  const [split, setSplit] = useState<DataSplit>("test");
  const [conversationSplit, setConversationSplit] = useState<DataSplit>("test");
  const [splitMessage, setSplitMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ImportReport>();
  const [tick, setTick] = useState(0);
  const [versions, setVersions] = useState<CaseVersions>();
  const [historyLoading, setHistoryLoading] = useState(false);
  const mutationController = useRef<AbortController | null>(null);
  const versionsController = useRef<AbortController | null>(null);
  useEffect(() => () => {
    mutationController.current?.abort();
    versionsController.current?.abort();
  }, []);
  const contextIntent = selected?.context?.active_intent;
  const activeIntent = catalog.find(item => item.intent_id === contextIntent);
  const contextDecision = decision === "continue" || decision === "cancel";
  const requiresIntent = decision === "route" || contextDecision;
  const labelValid = !requiresIntent || (catalog.some(item => item.intent_id === intentId) && (!contextDecision || intentId === activeIntent?.intent_id));
  function beginMutation() {
    if (mutationController.current) return null;
    const controller = new AbortController();
    mutationController.current = controller;
    setBusy(true);
    setError("");
    return controller;
  }
  function finishMutation(controller: AbortController) {
    if (controller.signal.aborted) return;
    if (mutationController.current === controller) mutationController.current = null;
    setBusy(false);
  }
  function clearVersions() {
    versionsController.current?.abort();
    setVersions(undefined);
    setHistoryLoading(false);
  }
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api<{ items: Case[]; total: number }>(
        "/cases?source=" +
          source +
          (splitFilter === "all" ? "" : "&split=" + splitFilter) +
          "&offset=" +
          offset +
          "&q=" +
          encodeURIComponent(query),
        { signal: controller.signal },
      )
        .then((d) => {
          if (!controller.signal.aborted) setData(d);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    }, 200);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [api, source, query, offset, tick, splitFilter]);
  function open(c: Case) {
    if (busy) return;
    clearVersions();
    setError("");
    setSelected(c);
    setDecision(c.expected_decision || "route");
    setIntentId(c.expected_intent_id || c.suggestions[0]?.intent_id || "");
    setSplit(c.split);
    setConversationSplit(c.split);
    setSplitMessage("");
  }
  async function upload(file: File | undefined) {
    if (!file) return;
    const controller = beginMutation();
    if (!controller) return;
    try {
      const body = new FormData();
      body.append("file", file);
      const imported = await api<ImportReport>("/cases/import", { method: "POST", body, signal: controller.signal });
      if (controller.signal.aborted) return;
      setReport(imported);
      setSource("customer");
      setOffset(0);
      setTick(value => value + 1);
      await refresh();
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      finishMutation(controller);
    }
  }
  async function review() {
    if (!selected || !labelValid) return;
    const controller = beginMutation();
    if (!controller) return;
    clearVersions();
    try {
      const updated = await api<CaseSnapshot>("/cases/" + encodeURIComponent(selected.case_id) + "/review", {
        method: "PATCH", signal: controller.signal,
        body: JSON.stringify({ expected_decision: decision, expected_intent_id: requiresIntent ? intentId : null, split }),
      });
      if (controller.signal.aborted) return;
      setSelected({ ...selected, ...updated });
      setData(current => ({ ...current, items: current.items.map(item => item.case_id === selected.case_id ? { ...item, ...updated } : item) }));
      setTick(value => value + 1);
      await refresh();
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      finishMutation(controller);
    }
  }
  async function moveConversation() {
    if (!selected?.conversation_id || conversationSplit === selected.split) return;
    const controller = beginMutation();
    if (!controller) return;
    clearVersions();
    setSplitMessage("");
    try {
      const moved = await api<ConversationSplitResult>("/conversations/" + encodeURIComponent(selected.conversation_id) + "/split", {
        method: "PATCH", signal: controller.signal, body: JSON.stringify({ split: conversationSplit }),
      });
      if (controller.signal.aborted) return;
      setSelected({ ...selected, split: moved.split });
      setSplit(moved.split);
      setConversationSplit(moved.split);
      setData(current => ({ ...current, items: current.items.map(item => item.conversation_id === moved.conversation_id ? { ...item, split: moved.split } : item) }));
      setSplitMessage(`Moved ${moved.updated_count} turns to ${moved.split}; labels and review status preserved.`);
      setTick(value => value + 1);
      await refresh();
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      finishMutation(controller);
    }
  }
  async function loadVersions() {
    if (!selected || busy) return;
    versionsController.current?.abort();
    const controller = new AbortController();
    versionsController.current = controller;
    setHistoryLoading(true);
    try {
      const history = await api<CaseVersions>("/cases/" + encodeURIComponent(selected.case_id) + "/versions", { signal: controller.signal });
      if (!controller.signal.aborted) setVersions(history);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setHistoryLoading(false);
    }
  }
  return (
    <div className="page-pad">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("CASES")}</p>
          <h1>{t("Real utterances, measurable results.")}</h1>
          <p>
            {t(
              "Review the expected decision and assign the case to a data split.",
            )}
          </p>
          <p className="field-hint">
            {t("Source data and conversation content are shown in their original language.")}
          </p>
        </div>
        <label className="button primary">
          <Upload size={17} />
          {busy ? t("Processing…") : t("Upload benchmark CSV")}
          <input
            className="sr-only"
            type="file"
            accept=".csv"
            disabled={busy}
            onChange={(e) => void upload(e.target.files?.[0])}
          />
        </label>
      </div>
      {error && <ErrorBox message={error} />}
      <div className="notice">
        <FileCheck2 size={19} />
        <span>
          {t(
            "The TRUE/FALSE field in the customer file is not an intent label. Unreviewed cases are excluded from accuracy calculations; their count is shown separately.",
          )}
        </span>
      </div>
      <section className="panel transcript-guidance" aria-label="Transcript CSV guidance">
        <h2>Import transcript cases</h2>
        <p>Use UTF-8 CSV with a Question column; original language is preserved. For stable identity across files, include SourceDatasetId, BenchmarkSessionId and BenchmarkSessionMessageId (each at most 200 characters). Session and message IDs are required with explicit context or a source namespace.</p>
        <p>Optional Context contains a JSON pre-turn snapshot: active_intent, slots, pending_slot, pending_confirmation, clarification_options, clarifications and prior user/assistant messages. Use only workspace catalog intent IDs. Optional Split is dev, calibration or test (default test); every conversation stays in one split.</p>
        <p>Context allows up to 12 prior messages of 2,000 characters, 10 string slots, 4 clarification options and 10 clarifications. Labels and future context are never inferred from source answers or flags. Review each imported turn before evaluation.</p>
        <a className="text-button" href="/v1/cases/template" download="synthetic-demo-banking-transcripts.csv">Download synthetic banking CSV template</a>
        <p className="field-hint">Synthetic banking demo — not real transcript data. The fixed template uses the Banking workspace catalog; importing it into another workspace requires adapting its intent IDs. Downloading never imports cases.</p>
      </section>
      {report && (
        <div className="notice success">
          <Check size={18} />
          <span>
            {report.imported}
            {" unique candidate cases; "}
            {report.inserted ?? "Unavailable"}{" inserted; "}
            {report.already_present ?? "Unavailable"}{" already present; "}
            {report.duplicates}{" duplicate input rows. "}
            {report.skipped_empty_question}
            {t(" empty questions excluded; ")}
            {report.valid_traces}
            {t(" execution traces parsed.")}
          </span>
        </div>
      )}
      <div className="toolbar">
        <div className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Search cases")}
            placeholder={t("Search customer utterances…")}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <select
          value={source}
          aria-label={t("Data source")}
          onChange={(e) => {
            setSource(e.target.value);
            setOffset(0);
          }}
        >
          <option value="all">{t("All sources")}</option>
          <option value="customer">{t("Customer cases")}</option>
          <option value="seed">{t("Demo scenarios")}</option>
        </select>
        <select
          aria-label={t("Filter by data split")}
          value={splitFilter}
          onChange={(e) => {
            setSplitFilter(e.target.value);
            setOffset(0);
          }}
        >
          <option value="all">{t("All data splits")}</option>
          <option value="test">{t("Test")}</option>
          <option value="calibration">{t("Calibration")}</option>
          <option value="dev">{t("Development")}</option>
        </select>
        <Badge>
          {data.total}
          {t(" cases")}
        </Badge>
      </div>
      <div className={"cases-layout " + (selected ? "with-detail" : "")}>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("Utterance")}</th>
                  <th>{t("Source")}</th>
                  <th>{t("Label status")}</th>
                  <th>{t("Data split")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr
                    key={c.case_id}
                    className={
                      selected?.case_id === c.case_id ? "selected-row" : ""
                    }
                  >
                    <td>
                      <button
                        className="text-button question-button"
                        disabled={busy}
                        onClick={() => open(c)}
                      >
                        {c.question}
                      </button>
                    </td>
                    <td>
                      <Badge>
                        {c.source === "customer" ? t("Customer") : t("Demo")}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={c.reviewed ? "green" : "amber"}>
                        {c.reviewed ? t("Reviewed") : t("Awaiting review")}
                      </Badge>
                    </td>
                    <td>
                      {t(
                        c.split === "calibration"
                          ? "Calibration"
                          : c.split === "dev"
                            ? "Development"
                            : "Test",
                      )}
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        disabled={busy}
                        onClick={() => open(c)}
                        aria-label={t("Review case")}
                      >
                        <ArrowUpRight size={18} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.items.length && (
            <Empty title={t("No cases found")}>
              {t("Upload a CSV or change the search filters.")}
            </Empty>
          )}
          <div className="pagination">
            <span>
              {data.total ? offset + 1 : 0}–{Math.min(offset + 20, data.total)}{" "}
              / {data.total}
            </span>
            <div>
              <button
                className="icon-button"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - 20))}
                aria-label={t("Previous page")}
              >
                <ChevronLeft size={18} />
              </button>
              <button
                className="icon-button"
                disabled={offset + 20 >= data.total}
                onClick={() => setOffset((o) => o + 20)}
                aria-label={t("Next page")}
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        </section>
        {selected && (
          <aside className="panel review-panel">
            <div className="panel-heading">
              <h2>{t("Expected decision")}</h2>
              <button
                className="icon-button"
                disabled={busy}
                onClick={() => { clearVersions(); setSelected(undefined); }}
                aria-label={t("Close review")}
              >
                <X size={18} />
              </button>
            </div>
            <div className="detail-body">
              <blockquote className="review-question">
                {selected.question}
              </blockquote>
              <div className="case-review-status"><Badge tone={selected.reviewed ? "green" : "amber"}>{selected.reviewed ? "Reviewed" : "Awaiting review"}</Badge></div>
              <dl className="transcript-identifiers">
                <div><dt>Source dataset</dt><dd>{selected.source_dataset_id || "Legacy file-scoped identity"}</dd></div>
                <div><dt>Source session</dt><dd>{selected.source_session_id || "Unavailable"}</dd></div>
                <div><dt>Source message</dt><dd>{selected.source_message_id || "Unavailable"}</dd></div>
                <div><dt>Conversation</dt><dd>{selected.conversation_id || "Unavailable"}</dd></div>
                <div><dt>Conversation split</dt><dd>{selected.split}</dd></div>
              </dl>
              <section className="transcript-context" aria-label="Pre-turn context">
                <h3>Pre-turn context</h3>
                {selected.context && Object.keys(selected.context).length ? <pre>{JSON.stringify(selected.context, null, 2)}</pre> : <p>No pre-turn context supplied.</p>}
              </section>
              <label>
                {t("Decision type")}
                <select
                  value={decision}
                  disabled={busy}
                  onChange={(e) => {
                    const next = e.target.value as ReviewDecision;
                    setDecision(next);
                    if (next === "continue" || next === "cancel") setIntentId(activeIntent?.intent_id || "");
                  }}
                >
                  <option value="route">{t("Route to intent")}</option>
                  <option value="continue" disabled={!activeIntent}>Continue active workflow</option>
                  <option value="cancel" disabled={!activeIntent}>Cancel active workflow</option>
                  <option value="clarify">{t("Clarify")}</option>
                  <option value="out_of_scope">{t("Out of scope")}</option>
                  <option value="handoff">{t("Hand off to an agent")}</option>
                </select>
              </label>
              {requiresIntent && (
                <label>
                  {t("Correct intent")}
                  <select
                    value={intentId}
                    disabled={busy}
                    onChange={(e) => setIntentId(e.target.value)}
                  >
                    {!contextDecision && <option value="">{t("Select")}</option>}
                    {(contextDecision ? (activeIntent ? [activeIntent] : []) : catalog).map((i) => (
                      <option key={i.intent_id} value={i.intent_id}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                {t("Data split")}
                <select
                  value={split}
                  disabled={busy}
                  onChange={(e) => setSplit(e.target.value as DataSplit)}
                >
                  <option value="test">{t("Test")}</option>
                  <option value="dev">{t("Development")}</option>
                  <option value="calibration">{t("Calibration")}</option>
                </select>
              </label>
              <p className="field-hint">Continue and cancel require the matching active context intent. Other non-route decisions have no intent label. A conversation cannot cross data splits.</p>
              <p className="field-hint">
                {t(
                  "The initial selection is a lexical search suggestion. Verify the business meaning before saving.",
                )}
              </p>
              <button
                className="button primary full"
                disabled={busy || !labelValid}
                onClick={() => void review()}
              >
                <Check size={17} />
                {t("Confirm and save label")}
              </button>
              {selected.conversation_id && <section className="conversation-split" aria-label="Whole-conversation split">
                <h3>Move the whole conversation</h3>
                <p className="field-hint">Move every turn together. Existing labels and review status stay unchanged.</p>
                <label>Conversation split<select value={conversationSplit} disabled={busy} onChange={event => setConversationSplit(event.target.value as DataSplit)}>
                  <option value="test">Test</option><option value="dev">Development</option><option value="calibration">Calibration</option>
                </select></label>
                <button className="button full" disabled={busy || conversationSplit === selected.split} onClick={() => void moveConversation()}>Move whole conversation</button>
                {splitMessage && <p role="status" className="field-hint">{splitMessage}</p>}
              </section>}
              <button className="button subtle full" disabled={busy || historyLoading} onClick={() => void loadVersions()}>{historyLoading ? "Loading history…" : "View label history"}</button>
              {versions && <section aria-label="Label history" className="case-versions"><h3>Label history</h3>{versions.versions.length ? <ul>{versions.versions.map(version => <li key={version.version}><strong>{version.reason}</strong> · {version.version}<br />{version.case.expected_decision || "Unlabelled"} · {version.case.expected_intent_id || "No intent label"} · {version.case.split} · {version.case.reviewed ? "Reviewed" : "Awaiting review"}</li>)}</ul> : <p>No label changes recorded.</p>}</section>}
              <h4>{t("Retrieval suggestions")}</h4>
              {selected.suggestions.slice(0, 3).map((c, i) => (
                <CandidateRow key={c.intent_id} candidate={c} rank={i + 1} />
              ))}
              {selected.reference_answer && (
                <details className="source-answer">
                  <summary>{t("Answer from source file")}</summary>
                  <p>{selected.reference_answer}</p>
                  <span>
                    {t("This answer is not passed to the model for intent selection.")}
                  </span>
                </details>
              )}
              <div className="field-hint">
                {t("Source TRUE/FALSE: ")}
                {selected.source_flag || t("None")}
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

export function Experiments({ status }: { status: Status }) {
  const { api } = useWorkspaceApi();
  const { t, locale, tag, ms, pct } = useI18n();
  const [rejection, setRejection] = useState<"calibrated" | "off">(
    "calibrated",
  );
  const [methods, setMethods] = useState<MethodId[]>(["lexical"]);
  const [compareProfiles, setCompareProfiles] = useState(false);
  const [profileRows, setProfileRows] = useState(() => initialProfiles(status.models.reranker));
  const profiles = selectedProfiles(profileRows);
  const [embeddingIds, setEmbeddingIds] = useState<string[]>(() =>
    initialModelIds(status.models.embedding),
  );
  const [llmIds, setLlmIds] = useState<string[]>(() =>
    initialModelIds(status.models.llm),
  );
  const [source, setSource] = useState("seed");
  const [limit, setLimit] = useState(100);
  const [catalogSizesText, setCatalogSizesText] = useState(
    String(status.intent_count),
  );
  const [calibrationSource, setCalibrationSource] = useState("seed");
  const [calibrationTarget, setCalibrationTarget] = useState(5);
  const catalogMinimum =
    Math.max(1, status.catalog_min_size ?? Math.min(48, status.intent_count));
  const catalogSizes = parseCatalogSizes(
    catalogSizesText,
    catalogMinimum,
    status.intent_count,
  );
  const [execution, setExecution] = useState<ExecutionControlValues>({
    repetitions: "1", maxProviderRequests: "", maxDurationSeconds: "", maxReportedCostUsd: "",
  });
  const [job, setJob] = useState<Evaluation>();
  const [history, setHistory] = useState<Evaluation[]>([]);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [acceptedId, setAcceptedId] = useState<string>();
  const [selectedMethod, setSelectedMethod] = useState("lexical");
  const [cancellationPending, setCancellationPending] = useState(false);
  const selectionGeneration = useRef(0);
  const selectionController = useRef<AbortController | null>(null);
  const cancellationController = useRef<AbortController | null>(null);
  const pollController = useRef<AbortController | null>(null);
  const busy = starting || Boolean(acceptedId) || (!!job && isEvaluationActive(job.status));
  const pollingId = acceptedId || (job && isEvaluationActive(job.status) ? job.id : undefined);
  useEffect(() => () => {
    selectionGeneration.current++;
    selectionController.current?.abort();
    cancellationController.current?.abort();
    pollController.current?.abort();
  }, []);
  useEffect(() => {
    if (job && isEvaluationActive(job.status)) return;
    const controller = new AbortController();
    api<Evaluation[]>("/evaluations", { signal: controller.signal })
      .then(items => { if (!controller.signal.aborted) setHistory(items); })
      .catch(e => { if (!controller.signal.aborted) setError((e as Error).message); });
    return () => controller.abort();
  }, [api, job?.id, job?.status]);
  useEffect(() => {
    if (!pollingId || starting || cancellationPending) return;
    const controller = new AbortController();
    pollController.current = controller;
    const generation = selectionGeneration.current;
    const id = pollingId;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (controller.signal.aborted || generation !== selectionGeneration.current) return;
      try {
        const current = await api<Evaluation>("/evaluations/" + encodeURIComponent(id), { signal: controller.signal });
        if (controller.signal.aborted || generation !== selectionGeneration.current) return;
        setJob(current);
        setAcceptedId(undefined);
        setError("");
        if (!isEvaluationActive(current.status)) return;
      } catch (e) {
        if (controller.signal.aborted || generation !== selectionGeneration.current) return;
        setError((e as Error).message);
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 700);
    }
    timer = setTimeout(() => void poll(), 700);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [api, pollingId, job?.status, cancellationPending, starting]);
  function beginSelection() {
    selectionController.current?.abort();
    pollController.current?.abort();
    const controller = new AbortController();
    selectionController.current = controller;
    return { controller, generation: ++selectionGeneration.current };
  }
  async function run() {
    if (busy || invalidSelection || !executionValidation.valid) return;
    const { controller, generation } = beginSelection();
    setError("");
    setStarting(true);
    setJob(undefined);
    try {
      const created = await api<{ id: string }>("/evaluations", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          methods,
          ...executionValidation.payload,
          semantic_rejection: rejection,
          embedding_ids: embeddingIds.length ? embeddingIds : ["default"],
          llm_ids: llmIds.length ? llmIds : ["default"],
          ...(compareProfiles && methods.includes("hybrid_llm") ? { retrieval_profiles: profiles } : {}),
          source,
          split: "test",
          limit,
          catalog_sizes: catalogSizes,
          scale_calibration_source: calibrationSource,
          scale_max_oos_false_accept_rate: calibrationTarget / 100,
        }),
      });
      if (controller.signal.aborted || generation !== selectionGeneration.current) return;
      setAcceptedId(created.id);
      const current = await api<Evaluation>("/evaluations/" + encodeURIComponent(created.id), { signal: controller.signal });
      if (controller.signal.aborted || generation !== selectionGeneration.current) return;
      setSelectedMethod(methods[0]);
      setJob(current);
      setAcceptedId(undefined);
    } catch (e) {
      if (!controller.signal.aborted && generation === selectionGeneration.current) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted && generation === selectionGeneration.current) setStarting(false);
    }
  }
  async function open(id: string) {
    if (busy) return;
    const { controller, generation } = beginSelection();
    setError("");
    try {
      const current = await api<Evaluation>("/evaluations/" + encodeURIComponent(id), { signal: controller.signal });
      if (controller.signal.aborted || generation !== selectionGeneration.current) return;
      setJob(current);
      setSelectedMethod(Object.keys(current.results || {})[0] || "lexical");
    } catch (e) {
      if (!controller.signal.aborted && generation === selectionGeneration.current) setError((e as Error).message);
    }
  }
  async function cancel() {
    const id = acceptedId || job?.id;
    if (!id || (!acceptedId && (!job || !isEvaluationActive(job.status) || job.cancel_requested)) || cancellationPending || (starting && !acceptedId)) return;
    selectionController.current?.abort();
    pollController.current?.abort();
    const generation = ++selectionGeneration.current;
    const controller = new AbortController();
    cancellationController.current = controller;
    // Cancellation takes ownership even when the accepted job's first status read is still pending.
    setStarting(false);
    setCancellationPending(true);
    setError("");
    try {
      const current = await api<Evaluation>("/evaluations/" + encodeURIComponent(id) + "/cancel", { method: "POST", signal: controller.signal });
      if (!controller.signal.aborted && generation === selectionGeneration.current) {
        setJob(current);
        setAcceptedId(undefined);
      }
    } catch (e) {
      if (!controller.signal.aborted && generation === selectionGeneration.current) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted && generation === selectionGeneration.current) setCancellationPending(false);
    }
  }
  const selectedId = job?.results?.[selectedMethod]
    ? selectedMethod
    : Object.keys(job?.results || {})[0];
  const result = job?.results?.[selectedId];
  const metrics = result?.metrics;
  const needsEmbedding = methods.some((method) => method !== "lexical");
  const needsLlm = methods.includes("hybrid_llm");
  const modelPreview = methods.flatMap<{
    id: string;
    method: MethodId;
    embedding: string;
    llm: string;
    profile: string;
    reranker: string;
  }>((method) => {
    if (method === "lexical")
      return [{ id: method, method, embedding: "—", llm: "—", profile: "—", reranker: "—" }];
    return embeddingIds.flatMap((embedding) =>
      (method === "hybrid_llm" ? llmIds : [""]).flatMap((llm) =>
      (method === "hybrid_llm" && compareProfiles ? profiles : [null]).map(profile => ({
        id: `${method}/${embedding}/${llm}/${profile?.id || "default"}`,
        method,
        profile: profile?.name || "—",
        reranker: profile?.reranker_id ? status.models.reranker?.find(r => r.id === profile.reranker_id)?.name || profile.reranker_id : "—",
        embedding:
          status.models.embedding.find((model) => model.id === embedding)
            ?.name || embedding,
        llm: status.models.llm.find((model) => model.id === llm)?.name || "—",
      }))),
    );
  });
  const preview = modelPreview.flatMap((item) =>
    catalogSizes.map((size) => ({
      ...item,
      id: item.id + "/catalog/" + size,
      catalogSize: size,
    })),
  );
  const caseCount = Math.min(
    limit,
    source === "seed"
      ? status.seed_case_count
      : source === "customer"
        ? status.reviewed_customer_test_count
        : status.seed_case_count + status.reviewed_customer_test_count,
  );
  const executionValidation = validateExecutionControls(execution, preview.length * caseCount);
  const invalidSelection =
    !preview.length || !caseCount || !Number.isInteger(limit) || limit < 1 || limit > 2000 ||
    (methods.includes("e5") &&
      rejection === "calibrated" &&
      (!Number.isFinite(calibrationTarget) ||
        calibrationTarget < 0 ||
        calibrationTarget > 50)) ||
    preview.length > status.models.max_variants ||
    (needsEmbedding && !embeddingIds.length) ||
    (needsLlm && !llmIds.length) ||
    (needsLlm && compareProfiles && !profilesValid(profiles, status.models.reranker || []));
  const activeVariant = job?.variants?.find(
    (variant) => variant.id === job.active_variant,
  );
  return (
    <div className="page-pad">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("EXPERIMENTS")}</p>
          <h1>{t("Compare models on the same cases.")}</h1>
          <p>
            {t(
              "The same test cases, a fixed catalog version and explicit metric definitions.",
            )}
          </p>
        </div>
        {job && !isEvaluationActive(job.status) && (
          <button
            className="button"
            onClick={() => download("evaluation-" + job.id + ".json", job)}
          >
            <ArrowDownToLine size={16} />
            {t("Download results")}
          </button>
        )}
      </div>
      <section className="panel experiment-setup">
        <div className="experiment-controls">
          <label>
            {t("Test set")}
            <select
              value={source}
              disabled={busy}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="seed">
                {t("Demo scenarios (")}
                {status.seed_case_count})
              </option>
              <option value="customer">
                {t("Reviewed customer test cases (")}
                {status.reviewed_customer_test_count})
              </option>
              <option value="all">{t("All reviewed test cases")}</option>
            </select>
          </label>
          <label>
            {t("Maximum cases")}
            <input
              type="number"
              min={1}
              max={2000}
              value={limit}
              disabled={busy}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </label>
          <button
            className="button primary"
            disabled={busy || invalidSelection || !executionValidation.valid}
            onClick={() => void run()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <FlaskConical size={17} />
            )}
            {t("Run evaluation")}
          </button>
        </div>
        <CatalogSizes
          value={catalogSizesText}
          onChange={setCatalogSizesText}
          minimum={catalogMinimum}
          maximum={status.intent_count}
          disabled={busy}
        />
        <ExecutionControls value={execution} baseExecutionCount={preview.length * caseCount} disabled={busy} onChange={setExecution} />
        <div className="method-checks">
          {status.methods.map((m) => (
            <label key={m.id} className={!m.available ? "disabled" : ""}>
              <input
                type="checkbox"
                checked={methods.includes(m.id)}
                disabled={busy || !m.available}
                onChange={(e) =>
                  setMethods((previous) =>
                    e.target.checked
                      ? [...previous, m.id]
                      : previous.filter((id) => id !== m.id),
                  )
                }
              />
              <span>
                {t(m.name)}
                <small>
                  {m.available
                    ? m.id === "lexical"
                      ? m.model
                      : t("Uses the models selected below")
                    : t("Model connection required")}
                </small>
              </span>
            </label>
          ))}
        </div>
        {needsEmbedding && (
          <div className="experiment-models">
            <ModelChecklist
              label={t("Embedding models")}
              options={status.models.embedding}
              selected={embeddingIds}
              disabled={busy}
              onChange={setEmbeddingIds}
            />
            {needsLlm && (
              <ModelChecklist
                label={t("Decision models (LLM)")}
                options={status.models.llm}
                selected={llmIds}
                disabled={busy}
                onChange={setLlmIds}
              />
            )}
          </div>
        )}
        {needsLlm && <div className="strategy-toggle">
          <label><input type="checkbox" checked={compareProfiles} disabled={busy} onChange={e => setCompareProfiles(e.target.checked)} />{t("Compare retrieval strategies")}</label>
          {compareProfiles && <RetrievalProfiles rows={profileRows} onChange={setProfileRows} rerankers={status.models.reranker || []} disabled={busy} />}
        </div>}
        {methods.includes("e5") && (
          <RejectionControl
            value={rejection}
            disabled={busy}
            onChange={setRejection}
            experiment
          />
        )}
        {methods.includes("e5") && rejection === "calibrated" && (
          <div className="scale-calibration-controls">
            <label>
              {t("Experiment calibration data")}
              <select
                value={calibrationSource}
                disabled={busy}
                onChange={(e) => setCalibrationSource(e.target.value)}
              >
                <option value="seed">{t("Demo calibration cases")}</option>
                <option value="customer">
                  {t("Customer calibration cases")}
                </option>
              </select>
            </label>
            <label>
              {t("Maximum OOS false acceptance (%)")}
              <input
                type="number"
                min={0}
                max={50}
                step={1}
                value={calibrationTarget}
                disabled={busy}
                onChange={(e) => setCalibrationTarget(Number(e.target.value))}
              />
            </label>
          </div>
        )}
        <div className="matrix-summary">
          <strong>
            {preview.length}
            {t(" combinations · ")}
            {caseCount}
            {t(" cases · ")}
            {executionValidation.plannedCount ?? "—"}
            {t(" decisions")}
            {execution.repetitions !== "1" ? ` · ${execution.repetitions} repetitions` : ""}
          </strong>
          <p>
            {needsLlm && !compareProfiles
              ? t(
                  "{embeddings} embeddings × {llms} LLMs = {count} hybrid combinations. ",
                  {
                    embeddings: embeddingIds.length,
                    llms: llmIds.length,
                    count: embeddingIds.length * llmIds.length,
                  },
                )
              : ""}
            {t("{models} model/method selections × {sizes} catalog sizes", {
              models: modelPreview.length,
              sizes: catalogSizes.length,
            })}
            {" · "}
            {t("Each combination runs sequentially on the same cases.")}
          </p>
          {needsEmbedding && (
            <p>
              {t(
                "Each model selection makes separate API calls. A configured connection does not guarantee that every model is available from the provider.",
              )}
            </p>
          )}
          {invalidSelection && (
            <p className="selection-warning">
              {t("Select models from the required groups. A maximum of ")}
              {status.models.max_variants}
              {t(" combinations can run per evaluation.")}
            </p>
          )}
          {!!preview.length && (
            <details>
              <summary>{t("Show planned combinations")}</summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t("Method")}</th>
                      <th>{t("Catalog intents")}</th>
                      <th>{t("Embedding")}</th>
                      <th>{t("LLM")}</th>
                      <th>{t("Retrieval strategy")}</th>
                      <th>Reranker</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((item) => (
                      <tr key={item.id}>
                        <td>{t(methodNames[item.method])}</td>
                        <td>{item.catalogSize}</td>
                        <td>{t(item.embedding)}</td>
                        <td>{t(item.llm)}</td>
                        <td>{t(item.profile)}</td>
                        <td>{t(item.reranker)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      </section>
      {error && <ErrorBox message={error} />}{" "}
      {job?.error && <ErrorBox message={job.error} />}
      {acceptedId && !job && <div className="notice"><span>Evaluation {acceptedId} accepted. Loading evaluation status…</span><button className="button subtle" disabled={cancellationPending} onClick={() => void cancel()}>{cancellationPending ? "Cancellation pending" : "Cancel evaluation"}</button></div>}
      {job && <ExecutionProgress evaluation={job} cancellationPending={cancellationPending} onCancel={() => void cancel()} />}
      {activeVariant && <p className="field-hint">Active combination: {activeVariant.name}{activeVariant.repeat_index ? ` · Repeat ${activeVariant.repeat_index}` : ""}</p>}
      {job && (job.group_summaries?.length ? job.group_summaries.map(summary => {
        const entry = Object.entries(job.results || {}).find(([, item]) => item.group_id === summary.group_id);
        return <RepeatSummary key={summary.group_id} summary={summary} label={entry ? baseResultLabel(entry[0], entry[1], t) : summary.group_id} />;
      }) : <RepeatSummary />)}
      {job && metrics && result ? (
        <>
          <div className="result-context">
            <div>
              <Badge tone="blue">
                {job.source_counts.customer
                  ? t("Includes customer data")
                  : t("Demo dataset")}
              </Badge>
              <span>
                {job.selected_count}
                {t(" cases · ")}
                {metrics.intent_count}
                {t(" test intents ·")}{" "}
                {result.catalog && (
                  <>
                    {t("{count}-intent catalog", {
                      count: result.catalog.intent_count,
                    })}{" "}
                    ·{" "}
                  </>
                )}{" "}
                {job.unreviewed_excluded}
                {t(" unreviewed cases excluded")}
              </span>
            </div>
            <span className="mono">
              {t("Data ")}
              {job.dataset_fingerprint.slice(0, 8)}
              {t(" / Catalog")}{" "}
              {(result.catalog?.version || job.catalog_version).slice(0, 8)}
            </span>
          </div>
          {!job.source_counts.customer && (
            <div className="notice">
              {t(
                "These results are from demo scenarios. They do not validate the 90% target across the customer’s transaction scope.",
              )}
            </div>
          )}
          <div className="metric-grid">
            <div>
              <span>{t("In-scope routing accuracy")}</span>
              <strong
                className={
                  (metrics.routing_accuracy || 0) >= 0.9 ? "green-text" : ""
                }
              >
                {pct(metrics.routing_accuracy)}
              </strong>
              <small>
                {metrics.routing_correct} / {metrics.routing_total}
                {t(" correct routes · target 90%")}
              </small>
            </div>
            <div>
              <span>
                {t("Recall@")}
                {metrics.k}
              </span>
              <strong>{pct(metrics.recall_at_k)}</strong>
              <small>{t("Correct intent appears in the candidate list")}</small>
            </div>
            <div>
              <span>{t("Macro-F1")}</span>
              <strong>
                {metrics.macro_f1 == null ? "—" : metrics.macro_f1.toFixed(3)}
              </strong>
              <small>{t("Equal weight for each intent")}</small>
            </div>
            <div>
              <span>{t("p95 routing latency")}</span>
              <strong>{ms(metrics.latency_ms.p95)}</strong>
              <small>{t("Measured in this experiment")}</small>
            </div>
          </div>
          <p className="field-hint selected-result-label">
            {t("Selected result: ")}
            {resultLabel(selectedId, result, t)}
          </p>
          <section className="panel">
            <div className="panel-heading">
              <h2>{t("Model and method comparison")}</h2>
              <Badge>
                {Object.keys(job.results || {}).length}
                {t(" combinations")}
              </Badge>
            </div>
            <div className="table-wrap">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>{t("Method")}</th>
                    <th>{t("Catalog intents")}</th>
                    <th>
                      <abbr
                        title={t(
                          "Among cases that should route, the fraction returning route with the correct intent. Rejection, errors and unnecessary clarification count as failures.",
                        )}
                        tabIndex={0}
                      >
                        {t("In-scope accuracy")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Correct decisions across all cases, including OOS and other decision types. A route decision must also match the expected intent.",
                        )}
                        tabIndex={0}
                      >
                        {t("Overall decision accuracy")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Fraction of all cases returning route, whether correct or incorrect.",
                        )}
                        tabIndex={0}
                      >
                        {t("Auto-routing coverage")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t("Fraction of all cases returning clarify.")}
                        tabIndex={0}
                      >
                        {t("Clarification rate")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Fraction of OOS cases incorrectly returning route. Lower is better; errors or clarifications are not necessarily correct rejections.",
                        )}
                        tabIndex={0}
                      >
                        {t("OOS false acceptance")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Cases ending with a model or connection error. They count as failures in accuracy metrics.",
                        )}
                        tabIndex={0}
                      >
                        {t("Technical errors")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "The 95th percentile of individual request latency. About 95% of requests finish within this duration; this is not the total experiment runtime.",
                        )}
                        tabIndex={0}
                      >
                        {t("p95")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Fraction of cases whose expected intent is in the candidate list.",
                        )}
                      >
                        Recall@K
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "p95 of query embedding and candidate retrieval, excluding LLM selection.",
                        )}
                      >
                        {t("Retrieval p95")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Accuracy difference in percentage points against this model's smallest catalog in this experiment.",
                        )}
                      >
                        {t("Δ accuracy (pp)")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "p95 ratio against this model's smallest catalog. 2× means twice as long.",
                        )}
                      >
                        {t("p95 ratio")}
                      </abbr>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(job.results || {}).map(([id, r]) => (
                    <tr
                      key={id}
                      className={id === selectedId ? "selected-row" : ""}
                    >
                      <td>
                        <button
                          className="text-button"
                          onClick={() => setSelectedMethod(id)}
                        >
                          {t(r.retrieval_profile?.name || methodNames[resultMethod(id, r)] || "Experiment")}
                          {r.repeat_index ? ` · Repeat ${r.repeat_index}` : ""}
                        </button>
                        {r.complete === false ? <div className="selection-warning">Incomplete · {r.completed_count ?? r.records.length} / {r.selected_count ?? job.selected_count} cases</div> : null}
                        <div className="muted">{r.model}</div>
                        {r.reranker && <div className="muted">Reranker: {r.reranker.model}</div>}
                        {r.retrieval_profile && <div className="muted">{t("Pool {pool} → LLM {final}", { pool: r.retrieval_profile.pool_k, final: r.retrieval_profile.candidate_k })}</div>}
                        {r.model_labels && (
                          <div className="muted">
                            {Object.values(r.model_labels).join(" + ")}
                          </div>
                        )}
                        <RejectionSummary value={r.calibration} />
                        {resultMethod(id, r) === "hybrid_llm" &&
                          r.embedding && (
                            <div className="muted">
                              {t("Embedding: ")}
                              {r.embedding.model}
                            </div>
                          )}
                        {!!r.embedding?.provider_only?.length && (
                          <div className="muted">
                            {t("Provider: ")}
                            {r.embedding.provider_only.join(", ")}
                          </div>
                        )}
                      </td>
                      <td>{r.catalog?.intent_count ?? "—"}</td>
                      <td>{pct(r.metrics.routing_accuracy)}</td>
                      <td>{pct(r.metrics.decision_accuracy)}</td>
                      <td>{pct(r.metrics.coverage)}</td>
                      <td>{pct(r.metrics.clarification_rate)}</td>
                      <td>{pct(r.metrics.oos_false_accept_rate)}</td>
                      <td>
                        <span
                          className={
                            r.metrics.errors ? "selection-warning" : ""
                          }
                        >
                          {r.metrics.errors} / {r.metrics.total}
                        </span>
                      </td>
                      <td>{ms(r.metrics.latency_ms.p95)}</td>
                      <td>{pct(r.metrics.recall_at_k)}<small className="muted"> K={r.metrics.k}</small></td>
                      <td>{ms(r.metrics.stage_latency_ms?.retrieval?.p95)}</td>
                      <td>
                        {r.complete === false || r.scaling?.accuracy_delta_pp == null
                          ? "—"
                          : new Intl.NumberFormat(tag, {
                              signDisplay: "exceptZero",
                              maximumFractionDigits: 1,
                            }).format(r.scaling.accuracy_delta_pp)}
                      </td>
                      <td>
                        {r.complete === false || r.scaling?.p95_ratio == null
                          ? "—"
                          : r.scaling.p95_ratio.toFixed(2) + "×"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <RetrievalDiagnostics result={result} />
          {job.catalog_scopes && job.catalog_scopes.length > 1 && (
            <p className="field-hint">
              {t(
                "Deltas and ratios use each model's smallest catalog as the baseline. Every size uses the same cases: this measures competition from added intents, not validation of every intent in the catalog.",
              )}
            </p>
          )}
          {job.latency_protocol && (
            <p className="field-hint">
              {t(
                "p95 measures individual queries after the index is ready. Index preparation for the selected combination: ",
              )}
              {ms(result.index_build_ms)}
              {result.index_cache_hit ? t(" (cached index used)") : ""}
              {" · "}
              {t("Threshold preparation: {duration}", {
                duration: ms(result.calibration_build_ms ?? 0),
              })}
              {t(". Results may vary with provider load.")}
            </p>
          )}
          {result.calibration?.calibrated && (
            <p className="field-hint">
              {t(
                "In-scope false rejection on test data: {rate}. Valid routing cases that returned out of scope instead of the expected intent.",
                { rate: pct(metrics.in_scope_false_reject_rate) },
              )}
            </p>
          )}
          {result.index_error && <ErrorBox message={result.index_error} />}
          {Object.keys(job.results || {}).length > 1 && (
            <CaseComparison
              results={job.results!}
              labels={Object.fromEntries(
                Object.entries(job.results!).map(([id, item]) => [
                  id,
                  resultLabel(id, item, t),
                ]),
              )}
            />
          )}
          {result.complete === false ? <div className="notice">Incomplete result: {result.completed_count ?? result.records.length} of {result.selected_count ?? job.selected_count} cases completed. These metrics describe finished cases only and are excluded from repeat summaries and scaling comparisons.</div> : null}
          <div className="result-detail-bar">
            <h2>{t("Results by case")}</h2>
            <span>
              {resultLabel(selectedId, result, t)} · {metrics.errors}
              {t(" technical errors")}
            </span>
          </div>
          <section className="panel">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("Case")}</th>
                    <th>{t("Expected")}</th>
                    <th>{t("Predicted decision")}</th>
                    <th>{t("Decision / error details")}</th>
                    <th>{t("Latency")}</th>
                    <th>{t("Outcome")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.records.map((r) => (
                    <tr key={r.case_id}>
                      <td className="result-question">{r.question}</td>
                      <td className="mono">
                        {r.expected_intent_id ||
                          t(decisionNames[r.expected_decision])}
                      </td>
                      <td className="mono">
                        <div>{t(decisionNames[r.decision])}</div>
                        {r.intent_id && <div>{r.intent_id}</div>}
                      </td>
                      <td className="decision-detail">
                        <CandidateTrace record={r} />
                        <div>
                          {r.error ? t(r.error) : r.message || r.reason_code}
                        </div>
                        <small className="muted">{r.reason_code}</small>
                        {r.rejection_score != null && (
                          <small className="muted">
                            {t("Rejection score: {score}", {
                              score: r.rejection_score.toFixed(4),
                            })}
                          </small>
                        )}
                        {r.diagnostics && (
                          <details>
                            <summary>{t("Technical details")}</summary>
                            <pre>{JSON.stringify(r.diagnostics, null, 2)}</pre>
                          </details>
                        )}
                      </td>
                      <td>{ms(r.total_ms)}</td>
                      <td>
                        <Badge tone={r.correct ? "green" : "amber"}>
                          {r.correct ? t("Correct") : t("Needs review")}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {metrics.routing_accuracy_ci95 && (
            <p className="field-hint">
              {t("95% Wilson confidence interval for in-scope routing accuracy:")}{" "}
              {pct(metrics.routing_accuracy_ci95[0])}–
              {pct(metrics.routing_accuracy_ci95[1])}
              {t(
                ". Technical errors and unnecessary clarifications count as initial decision failures.",
              )}
            </p>
          )}
        </>
      ) : (
        !busy && (
          <section className="panel">
            <Empty title={t("No results yet")}>
              {t(
                "Choose a test set and a method to run your first comparison.",
              )}
            </Empty>
          </section>
        )
      )}
      {!!history.length && (
        <section className="history">
          <h2>{t("Previous runs")}</h2>
          {history.slice(0, 8).map((h) => (
            <button key={h.id} disabled={busy} onClick={() => void open(h.id)}>
              <FlaskConical size={17} />
              <span>{new Date(h.created * 1000).toLocaleString(tag)}</span>
              <span>
                {h.selected_count}
                {t(" cases")}
              </span>
              {h.variants && (
                <span>
                  {h.variants.length}
                  {t(" combinations")}
                </span>
              )}
              <Badge>
                {h.status.charAt(0).toUpperCase() + h.status.slice(1)}
              </Badge>
              <ArrowRight size={16} />
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
