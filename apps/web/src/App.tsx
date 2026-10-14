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
  api,
  download,
  waitForRoute,
  type Candidate,
  type Case,
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
import Calibration, { RejectionControl, RejectionSummary } from "./Calibration";
import { CatalogSizes, parseCatalogSizes } from "./CatalogSizes";
import Models from "./Models";
import { RetrievalProfiles, initialProfiles, selectedProfiles, profilesValid } from "./RetrievalProfiles";
import { RetrievalDiagnostics, CandidateTrace } from "./RetrievalDiagnostics";
import CatalogQuality from "./CatalogQuality";
import "./retrieval-quality.css";
import { LanguageSelect, useI18n, type Translate } from "./i18n";
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
  { id: "demo", label: "Canlı demo", icon: MessageSquare },
  { id: "catalog", label: "Intent kataloğu", icon: Layers3 },
  { id: "models", label: "Model kataloğu", icon: Database },
  { id: "cases", label: "Vakalar", icon: FileCheck2 },
  { id: "calibration", label: "Kalibrasyon", icon: Settings2 },
  { id: "experiments", label: "Deneyler", icon: FlaskConical },
];
const decisionNames: Record<string, string> = {
  route: "Yönlendirildi",
  continue: "Akış sürüyor",
  clarify: "Netleştirme gerekli",
  cancel: "İptal edildi",
  out_of_scope: "Kapsam dışı",
  handoff: "Temsilciye aktarım",
  error: "Bağlantı hatası",
};
const methodNames: Record<string, string> = {
  lexical: "Sözcüksel referans",
  e5: "Semantik arama",
  hybrid_llm: "Hibrit arama + LLM",
};
const resultMethod = (id: string, result: EvaluationResult) =>
  result.method || id;
const resultLabel = (id: string, result: EvaluationResult, t: Translate) =>
  `${t(result.retrieval_profile?.name || methodNames[resultMethod(id, result)] || "Deney")} · ${result.model_labels?.[resultMethod(id, result) === "hybrid_llm" ? "llm" : "embedding"] || result.model}${resultMethod(id, result) === "hybrid_llm" && result.embedding ? " + " + (result.model_labels?.embedding || result.embedding.model) : ""}${result.catalog ? " · " + t("{count} intent", { count: result.catalog.intent_count }) : ""}`;
const slotNames: Record<string, string> = {
  new_limit: "Yeni limit",
  card_last4: "Kartın son dört hanesi",
  transfer_reference: "Transfer referansı",
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

export default function App() {
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
  const refresh = useCallback(async () => {
    try {
      const [s, c, models] = await Promise.all([
        api<Status>("/status"),
        api<{ version: string; intents: Intent[] }>("/catalog"),
        api<ModelCatalog>("/models"),
      ]);
      setStatus({
        ...s,
        models,
        catalog_version: c.version || s.catalog_version,
        intent_count: c.intents.length,
      });
      setCatalog(c.intents);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
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
            <strong>{t("Bankacılık")}</strong>
            <span>{t("PoC çalışma alanı")}</span>
          </div>
        </div>
        <div className="nav-label">{t("ÇALIŞMA ALANI")}</div>
        <nav aria-label={t("Ana menü")}>
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
              {t("İşlem simülasyonu")}
              <br />
              <small>{t("On-prem uyumlu mimari")}</small>
            </span>
          </div>
          <button className="nav-item" onClick={() => setSettingsOpen(true)}>
            <Settings2 size={18} />
            {t("Model bağlantıları")}
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
            {t("Çalışma alanı ")}
            <span>/</span>{" "}
            <strong>{t(nav.find((n) => n.id === page)?.label)}</strong>
          </div>
          <div className="topbar-actions">
            <LanguageSelect />
            <Badge tone="blue">{t("BANKACILIK PoC")}</Badge>
          </div>
        </header>
        {error && (
          <div className="page-pad">
            <ErrorBox message={error} />
            <button className="button subtle" onClick={() => void refresh()}>
              {t("Yeniden bağlan")}
            </button>
          </div>
        )}
        {!status ? (
          !error && (
            <div className="loading-page">
              <LoaderCircle className="spin" />
              {t("Çalışma alanı yükleniyor…")}
            </div>
          )
        ) : (
          <>
            {page === "demo" && <Demo status={status} catalog={catalog} />}
            {page === "catalog" && (
              <Catalog catalog={catalog} refresh={refresh} />
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
            aria-label={t("Model bağlantıları")}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="icon-button close"
              aria-label={t("Kapat")}
              onClick={() => setSettingsOpen(false)}
            >
              <X />
            </button>
            <p className="eyebrow">{t("MODEL BAĞLANTILARI")}</p>
            <h2>
              {t("Cloud’da başla.")}
              <br />
              {t("On-prem’e taşı.")}
            </h2>
            <p>
              {t(
                "LLM ve embedding modellerini OpenRouter üzerinden veya kendi sunucunuzda çalıştırabilirsiniz.",
              )}
            </p>
            <div className="setting-row">
              <span>{t("Seçim modeli")}</span>
              <strong>{status?.llm_model}</strong>
              <Badge tone={status?.llm_configured ? "green" : "amber"}>
                {status?.llm_configured
                  ? t("Bağlantı tanımlı")
                  : t("Bağlantı bekliyor")}
              </Badge>
            </div>
            <div className="setting-row">
              <span>{t("Embedding modeli")}</span>
              <strong>{status?.embedding_model}</strong>
              <Badge>
                {status?.embedding_configured
                  ? t("Bağlantı tanımlı")
                  : t("Bağlantı bekliyor")}
              </Badge>
            </div>
            <div className="notice">
              {status?.llm_provider === "openrouter"
                ? t(
                    "OpenRouter için sunucudaki .env dosyasına tek API anahtarı ekleyin; aynı anahtar iki model için de kullanılır. Ardından API’yi yeniden başlatın.",
                  )
                : t(
                    "Sunucudaki .env dosyasında model endpoint’ini ve gerekiyorsa API anahtarını tanımlayın.",
                  )}{" "}
              {t(
                "Bağlantı tanımı, canlı erişimin doğrulandığı anlamına gelmez.",
              )}
            </div>
            <code className="config-example">
              {status?.llm_provider === "openrouter"
                ? t("INTENT_OPENROUTER_API_KEY")
                : t(
                    "INTENT_LLM_BASE_URL / INTENT_LLM_MODEL / INTENT_LLM_API_KEY",
                  )}
            </code>
            <a
              className="button primary"
              href="https://github.com/czagnos/intent-bench/blob/main/README.md"
              target="_blank"
              rel="noreferrer"
            >
              {t("Kurulum rehberi ")}
              <ArrowUpRight size={16} />
            </a>
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
  useEffect(() => () => request.current?.abort(), []);
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
          job.error || "Yeni konuşma adımı nedeniyle eski sonuç uygulanmadı.",
        );
      if (job.result) {
        setStages((previous) => mergeStages(previous, job.events || []));
        setResult(job.result);
        setMessages((previous) => [
          ...previous,
          { role: "assistant", content: job.result!.message },
        ]);
      } else throw new Error(job.error || "Karar üretilemedi.");
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
          <p className="eyebrow">{t("CANLI DEMO")}</p>
          <h1>{t("İstekten doğru akışa.")}</h1>
          <p>
            {t(
              "Bir bankacılık isteği yazın, yönlendirme kararını adım adım inceleyin.",
            )}
          </p>
        </div>
        <button className="button" onClick={reset}>
          <Plus size={17} />
          {t("Yeni konuşma")}
        </button>
      </div>
      <div className="summary-strip">
        <div>
          <span>{t("Katalog")}</span>
          <strong>
            {status.intent_count}
            <small>{t("intent")}</small>
          </strong>
        </div>
        <div>
          <span>{t("Müşteri vakaları")}</span>
          <strong>
            {status.customer_case_count}
            <small>{t("kayıt")}</small>
          </strong>
        </div>
        <div>
          <span>{t("Doğrulanmış müşteri etiketi")}</span>
          <strong>
            {status.reviewed_customer_count}
            <small>{t("vaka")}</small>
          </strong>
        </div>
        <div>
          <span>{t("Doğruluk hedefi")}</span>
          <strong>
            {t("%90")}
            <small>{t("henüz doğrulanmadı")}</small>
          </strong>
        </div>
      </div>
      <div
        className="demo-view-picker"
        role="group"
        aria-label={t("Demo görünümü")}
      >
        <span>{t("Görünüm")}</span>
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
              <h2>{t("Konuşma")}</h2>
            </div>
            <Badge>{t("Metin")}</Badge>
          </div>
          <div className="method-picker">
            <label htmlFor="method">{t("Yönlendirme yöntemi")}</label>
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
                  {!m.available ? t(" · bağlantı gerekli") : ""}
                </option>
              ))}
            </select>
            <p>{t(status.methods.find((m) => m.id === method)?.description)}</p>
            {method !== "lexical" && (
              <div className="demo-models">
                <ModelSelect
                  label={t("Embedding modeli")}
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
                    label={t("Karar modeli (LLM)")}
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
                  {t("Model seçimi değişince yeni konuşma başlar.")}
                </small>
                {method === "hybrid_llm" && <>
                  <label className="model-select"><span>{t("Arama stratejisi")}</span><select value={recipeId} disabled={busy} onChange={e => { reset(); setRecipeId(e.target.value); }}>
                    {demoRecipes.map(p => <option key={p.id} value={p.id} disabled={p.id === "reranked" && !(status.models.reranker || []).some(r => r.available)}>{t(p.name)}</option>)}
                  </select><small>{t("Havuz {pool} → LLM {final}", { pool: recipe.pool_k, final: recipe.candidate_k })}</small></label>
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
                <h3>{t("Hangi işlemle başlayalım?")}</h3>
                <p>{t("Bir örnek seçin veya kendi cümlenizi yazın.")}</p>
                <p className="field-hint">
                  {t("Veri ve konuşma içeriği özgün dilinde gösterilir.")}
                </p>
                <div className="scenario-list">
                  {[
                    "Kart limitimi artırmak istiyorum.",
                    "Gönderdiğim para karşıya ulaşmadı.",
                    "Kartımı kapatmak istiyorum.",
                  ].map((s) => (
                    <button key={s} onClick={() => void send(s)}>
                      {s}
                      <ArrowUpRight size={16} />
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div className={"chat-message " + message.role} key={index}>
                <span className="speaker">
                  {message.role === "user" ? t("SİZ") : t("ASİSTAN")}
                </span>
                <div>{message.content}</div>
              </div>
            ))}
            {busy && (
              <div className="chat-message assistant">
                <span className="speaker">{t("ASİSTAN")}</span>
                <div className="typing">
                  <i />
                  <i />
                  <i />
                  <span>{t(stages.at(-1)?.label || "İstek işleniyor")}</span>
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
              {t("Bankacılık isteğiniz")}
            </label>
            <textarea
              id="message"
              rows={2}
              maxLength={2000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t(
                "Örn. Kredi kartımın limitini yükseltmek istiyorum…",
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
              aria-label={t("Mesajı gönder")}
            >
              {busy ? (
                <LoaderCircle className="spin" size={19} />
              ) : (
                <Send size={19} />
              )}
            </button>
          </form>
          <div className="composer-note">
            {t("Enter ile gönder · Shift + Enter ile yeni satır")}
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
            <summary>{t("Karar ve aday ayrıntıları")}</summary>
            <div className="inspector">
              <section className="panel">
                <div className="panel-heading">
                  <div className="heading-icon">
                    <Activity size={19} />
                    <h2>{t("Kararı incele")}</h2>
                  </div>
                  <Badge tone="blue">{t("CANLI")}</Badge>
                </div>
                {!result ? (
                  <>
                    <Empty
                      title={
                        busy
                          ? t("Karar hazırlanıyor")
                          : t("İlk mesajı bekliyor")
                      }
                    >
                      {t(
                        "Aday intent’ler, seçilen akış ve ölçülen süre burada görünecek.",
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
                          <span>{t("HEDEF WORKFLOW")}</span>
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
                        <Badge tone="amber">{t("Bekleniyor")}</Badge>
                      </div>
                    ))}
                    {result.simulation_complete && (
                      <div className="notice success">
                        {t("İşlem simülasyonu tamamlandı.")}
                      </div>
                    )}
                    <div className="timings">
                      {[
                        ["retrieval", "Aday arama"],
                        ["selection", "Intent seçimi"],
                        ["policy", "Karar kontrolü"],
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
                    <h2>{t("Intent adayları")}</h2>
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
                    {t("Arama tamamlandığında adaylar listelenir.")}
                  </div>
                )}
              </section>
              {result && (
                <div className="run-meta">
                  <span>{t(methodNames[result.method])}</span>
                  <span>
                    {t("Katalog ")}
                    {result.catalog_version.slice(0, 8)}
                  </span>
                  <span>{result.model}</span>
                  <RejectionSummary value={result.calibration} />
                  {result.rejection_score != null && (
                    <span>
                      {t("Reddetme skoru: {score}", {
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
            ? t("Birleştirilmiş sıra puanı")
            : c.score_type === "cosine_similarity"
              ? t("Cosine benzerliği")
              : t("Sözcüksel benzerlik")}{" "}
          {t("· Olasılık değildir.")}
        </span>
      </div>
    </details>
  );
}

export function Catalog({
  catalog,
  refresh,
}: {
  catalog: Intent[];
  refresh: () => Promise<void>;
}) {
  const { t, locale, tag, ms, pct } = useI18n();
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("all");
  const [selected, setSelected] = useState<Intent>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const items = catalog.filter(
    (i) =>
      (domain === "all" || i.domain === domain) &&
      (i.name + " " + i.description + " " + i.intent_id)
        .toLocaleLowerCase("tr")
        .includes(query.toLocaleLowerCase("tr")),
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
          <p className="eyebrow">{t("INTENT KATALOĞU")}</p>
          <h1>{t("İşlemlerin ortak dili.")}</h1>
          <p>{t("Açıklamalar, örnek ifadeler ve workflow eşlemeleri.")}</p>
          <p className="field-hint">
            {t("Veri ve konuşma içeriği özgün dilinde gösterilir.")}
          </p>
          {catalog.some((intent) => intent.intent_id.startsWith("bank.")) && (
            <p className="field-hint">
              {t(
                "Genişletilmiş demo kataloğu temsili ürün/işlem tanımları içerir. Gerçek müşteri kataloğu için ürün kapsamı ve intent ayrımları doğrulanmalıdır.",
              )}
            </p>
          )}
        </div>
        <div className="actions">
          <button
            className="button"
            onClick={() => download("intent-catalog.json", catalog)}
          >
            <ArrowDownToLine size={16} />
            {t("Dışa aktar")}
          </button>
          <label className="button primary">
            <Upload size={16} />
            {busy ? t("Yükleniyor…") : t("JSON içe aktar")}
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
      <div className="toolbar">
        <div className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Intent ara")}
            placeholder={t("Intent adı, açıklama veya kimlik ara…")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          aria-label={t("İşlem alanı")}
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        >
          <option value="all">{t("Tüm alanlar")}</option>
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
                  {t(" örnek")}
                </span>
                <ArrowUpRight size={17} />
              </div>
            </button>
          ))}
        </div>
        {selected && (
          <aside className="panel catalog-detail">
            <div className="panel-heading">
              <h2>{t("Intent ayrıntısı")}</h2>
              <button
                className="icon-button"
                onClick={() => setSelected(undefined)}
                aria-label={t("Ayrıntıyı kapat")}
              >
                <X size={18} />
              </button>
            </div>
            <div className="detail-body">
              <Badge tone="blue">{selected.domain}</Badge>
              <h3>{selected.name}</h3>
              <code>{selected.intent_id}</code>
              <p>{selected.description}</p>
              <h4>{t("Örnek ifadeler")}</h4>
              {selected.examples.map((e) => (
                <blockquote key={e}>{e}</blockquote>
              ))}
              {!!selected.exclusions.length && (
                <>
                  <h4>{t("Ayrı değerlendirilmesi gerekenler")}</h4>
                  {selected.exclusions.map((e) => (
                    <p key={e} className="exclusion">
                      {e}
                    </p>
                  ))}
                </>
              )}
              <h4>{t("Workflow")}</h4>
              <code>{selected.workflow_id}</code>
              <h4>{t("Gerekli bilgiler")}</h4>
              <p>
                {selected.required_slots
                  .map((s) => t(slotNames[s] || s))
                  .join(", ") || t("İlk yönlendirmede gerekli slot yok.")}
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
  const [decision, setDecision] = useState("route");
  const [intentId, setIntentId] = useState("");
  const [split, setSplit] = useState("test");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ImportReport>();
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      api<{ items: Case[]; total: number }>(
        "/cases?source=" +
          source +
          (splitFilter === "all" ? "" : "&split=" + splitFilter) +
          "&offset=" +
          offset +
          "&q=" +
          encodeURIComponent(query),
      )
        .then((d) => {
          if (active) setData(d);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [source, query, offset, tick, splitFilter]);
  function open(c: Case) {
    setSelected(c);
    setDecision(c.expected_decision || "route");
    setIntentId(c.expected_intent_id || c.suggestions[0]?.intent_id || "");
    setSplit(c.split);
  }
  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const imported = await api<ImportReport>("/cases/import", {
        method: "POST",
        body,
      });
      setReport(imported);
      setSource("customer");
      setOffset(0);
      setTick((t) => t + 1);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function review() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Case>(
        "/cases/" + selected.case_id + "/review",
        {
          method: "PATCH",
          body: JSON.stringify({
            expected_decision: decision,
            expected_intent_id: decision === "route" ? intentId : null,
            split,
          }),
        },
      );
      setSelected({ ...selected, ...updated });
      setTick((t) => t + 1);
      await refresh();
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
          <p className="eyebrow">{t("VAKALAR")}</p>
          <h1>{t("Gerçek ifadeler, ölçülebilir sonuçlar.")}</h1>
          <p>
            {t(
              "Beklenen kararı doğrulayın; vakayı değerlendirme kümesine alın.",
            )}
          </p>
          <p className="field-hint">
            {t("Veri ve konuşma içeriği özgün dilinde gösterilir.")}
          </p>
        </div>
        <label className="button primary">
          <Upload size={17} />
          {busy ? t("İşleniyor…") : t("Benchmark CSV yükle")}
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
            "Müşteri dosyasındaki TRUE/FALSE alanı intent etiketi değildir. Doğrulanmamış vakalar accuracy hesabına katılmaz; bekleyen vaka sayısı ayrıca gösterilir.",
          )}
        </span>
      </div>
      {report && (
        <div className="notice success">
          <Check size={18} />
          <span>
            {report.imported}
            {t(" vaka alındı. ")}
            {report.skipped_empty_question}
            {t(" boş soru kaydı ayrıldı; ")}
            {report.valid_traces}
            {t(" çalışma izi çözümlendi.")}
          </span>
        </div>
      )}
      <div className="toolbar">
        <div className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Vaka ara")}
            placeholder={t("Müşteri ifadesinde ara…")}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <select
          value={source}
          aria-label={t("Veri kaynağı")}
          onChange={(e) => {
            setSource(e.target.value);
            setOffset(0);
          }}
        >
          <option value="all">{t("Tüm kaynaklar")}</option>
          <option value="customer">{t("Müşteri vakaları")}</option>
          <option value="seed">{t("Demo senaryoları")}</option>
        </select>
        <select
          aria-label={t("Veri bölümü filtresi")}
          value={splitFilter}
          onChange={(e) => {
            setSplitFilter(e.target.value);
            setOffset(0);
          }}
        >
          <option value="all">{t("Tüm veri bölümleri")}</option>
          <option value="test">{t("Test")}</option>
          <option value="calibration">{t("Kalibrasyon")}</option>
          <option value="dev">{t("Geliştirme")}</option>
        </select>
        <Badge>
          {data.total}
          {t(" vaka")}
        </Badge>
      </div>
      <div className={"cases-layout " + (selected ? "with-detail" : "")}>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("İfade")}</th>
                  <th>{t("Kaynak")}</th>
                  <th>{t("Etiket durumu")}</th>
                  <th>{t("Veri bölümü")}</th>
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
                        onClick={() => open(c)}
                      >
                        {c.question}
                      </button>
                    </td>
                    <td>
                      <Badge>
                        {c.source === "customer" ? t("Müşteri") : t("Demo")}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={c.reviewed ? "green" : "amber"}>
                        {c.reviewed ? t("Doğrulandı") : t("İnceleme bekliyor")}
                      </Badge>
                    </td>
                    <td>
                      {t(
                        c.split === "calibration"
                          ? "Kalibrasyon"
                          : c.split === "dev"
                            ? "Geliştirme"
                            : "Test",
                      )}
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        onClick={() => open(c)}
                        aria-label={t("Vakayı incele")}
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
            <Empty title={t("Vaka bulunamadı")}>
              {t("CSV yükleyin veya arama koşullarını değiştirin.")}
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
                aria-label={t("Önceki sayfa")}
              >
                <ChevronLeft size={18} />
              </button>
              <button
                className="icon-button"
                disabled={offset + 20 >= data.total}
                onClick={() => setOffset((o) => o + 20)}
                aria-label={t("Sonraki sayfa")}
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        </section>
        {selected && (
          <aside className="panel review-panel">
            <div className="panel-heading">
              <h2>{t("Beklenen karar")}</h2>
              <button
                className="icon-button"
                onClick={() => setSelected(undefined)}
                aria-label={t("İncelemeyi kapat")}
              >
                <X size={18} />
              </button>
            </div>
            <div className="detail-body">
              <blockquote className="review-question">
                {selected.question}
              </blockquote>
              <label>
                {t("Karar türü")}
                <select
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                >
                  <option value="route">{t("Intent’e yönlendir")}</option>
                  <option value="clarify">{t("Netleştir")}</option>
                  <option value="out_of_scope">{t("Kapsam dışı")}</option>
                  <option value="handoff">{t("Temsilciye aktar")}</option>
                </select>
              </label>
              {decision === "route" && (
                <label>
                  {t("Doğru intent")}
                  <select
                    value={intentId}
                    onChange={(e) => setIntentId(e.target.value)}
                  >
                    <option value="">{t("Seçin")}</option>
                    {catalog.map((i) => (
                      <option key={i.intent_id} value={i.intent_id}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                {t("Veri bölümü")}
                <select
                  value={split}
                  onChange={(e) => setSplit(e.target.value)}
                >
                  <option value="test">{t("Test")}</option>
                  <option value="dev">{t("Geliştirme")}</option>
                  <option value="calibration">{t("Kalibrasyon")}</option>
                </select>
              </label>
              <p className="field-hint">
                {t(
                  "İlk seçim sözcüksel arama önerisidir. Kaydetmeden önce iş anlamını doğrulayın.",
                )}
              </p>
              <button
                className="button primary full"
                disabled={busy || (decision === "route" && !intentId)}
                onClick={() => void review()}
              >
                <Check size={17} />
                {t("Etiketi doğrula ve kaydet")}
              </button>
              <h4>{t("Arama önerileri")}</h4>
              {selected.suggestions.slice(0, 3).map((c, i) => (
                <CandidateRow key={c.intent_id} candidate={c} rank={i + 1} />
              ))}
              {selected.reference_answer && (
                <details className="source-answer">
                  <summary>{t("Kaynak dosyadaki yanıt")}</summary>
                  <p>{selected.reference_answer}</p>
                  <span>
                    {t("Bu yanıt intent seçimi için modele verilmez.")}
                  </span>
                </details>
              )}
              <div className="field-hint">
                {t("Kaynak TRUE/FALSE: ")}
                {selected.source_flag || t("Yok")}
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

export function Experiments({ status }: { status: Status }) {
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
    status.catalog_min_size ?? Math.min(48, status.intent_count);
  const catalogSizes = parseCatalogSizes(
    catalogSizesText,
    catalogMinimum,
    status.intent_count,
  );
  const [job, setJob] = useState<Evaluation>();
  const [history, setHistory] = useState<Evaluation[]>([]);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [selectedMethod, setSelectedMethod] = useState("lexical");
  const busy =
    starting || (!!job && ["queued", "running"].includes(job.status));
  useEffect(() => {
    api<Evaluation[]>("/evaluations")
      .then(setHistory)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = setInterval(() => {
      api<Evaluation>("/evaluations/" + job.id)
        .then((j) => {
          if (active) {
            setJob(j);
            if (!["queued", "running"].includes(j.status))
              api<Evaluation[]>("/evaluations").then(setHistory);
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 700);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [job?.id, job?.status]);
  async function run() {
    setError("");
    setStarting(true);
    try {
      const created = await api<{ id: string }>("/evaluations", {
        method: "POST",
        body: JSON.stringify({
          methods,
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
      setSelectedMethod(methods[0]);
      setJob(await api<Evaluation>("/evaluations/" + created.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }
  async function open(id: string) {
    try {
      const j = await api<Evaluation>("/evaluations/" + id);
      setJob(j);
      setSelectedMethod(Object.keys(j.results || {})[0] || "lexical");
    } catch (e) {
      setError((e as Error).message);
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
  const invalidSelection =
    !preview.length ||
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
          <p className="eyebrow">{t("DENEYLER")}</p>
          <h1>{t("Modelleri aynı vakalarla karşılaştır.")}</h1>
          <p>
            {t(
              "Aynı test vakaları, sabit katalog sürümü ve açık metrik tanımları.",
            )}
          </p>
        </div>
        {job?.status === "completed" && (
          <button
            className="button"
            onClick={() => download("evaluation-" + job.id + ".json", job)}
          >
            <ArrowDownToLine size={16} />
            {t("Sonuçları indir")}
          </button>
        )}
      </div>
      <section className="panel experiment-setup">
        <div className="experiment-controls">
          <label>
            {t("Test kümesi")}
            <select
              value={source}
              disabled={busy}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="seed">
                {t("Demo senaryoları (")}
                {status.seed_case_count})
              </option>
              <option value="customer">
                {t("Doğrulanmış müşteri vakaları (")}
                {status.reviewed_customer_test_count})
              </option>
              <option value="all">{t("Tüm doğrulanmış vakalar")}</option>
            </select>
          </label>
          <label>
            {t("En fazla vaka")}
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
            disabled={busy || invalidSelection || limit < 1 || limit > 2000}
            onClick={() => void run()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <FlaskConical size={17} />
            )}
            {t("Değerlendirmeyi çalıştır")}
          </button>
        </div>
        <CatalogSizes
          value={catalogSizesText}
          onChange={setCatalogSizesText}
          minimum={catalogMinimum}
          maximum={status.intent_count}
          disabled={busy}
        />
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
                      : t("Aşağıdaki model seçimini kullanır")
                    : t("Model bağlantısı gerekli")}
                </small>
              </span>
            </label>
          ))}
        </div>
        {needsEmbedding && (
          <div className="experiment-models">
            <ModelChecklist
              label={t("Embedding modelleri")}
              options={status.models.embedding}
              selected={embeddingIds}
              disabled={busy}
              onChange={setEmbeddingIds}
            />
            {needsLlm && (
              <ModelChecklist
                label={t("Karar modelleri (LLM)")}
                options={status.models.llm}
                selected={llmIds}
                disabled={busy}
                onChange={setLlmIds}
              />
            )}
          </div>
        )}
        {needsLlm && <div className="strategy-toggle">
          <label><input type="checkbox" checked={compareProfiles} disabled={busy} onChange={e => setCompareProfiles(e.target.checked)} />{t("Arama stratejilerini karşılaştır")}</label>
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
              {t("Deney kalibrasyon verisi")}
              <select
                value={calibrationSource}
                disabled={busy}
                onChange={(e) => setCalibrationSource(e.target.value)}
              >
                <option value="seed">{t("Demo kalibrasyon vakaları")}</option>
                <option value="customer">
                  {t("Müşteri kalibrasyon vakaları")}
                </option>
              </select>
            </label>
            <label>
              {t("En fazla OOS yanlış kabul (%)")}
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
            {t(" kombinasyon · ")}
            {caseCount}
            {t(" vaka · ")}
            {preview.length * caseCount}
            {t(" karar")}
          </strong>
          <p>
            {needsLlm && !compareProfiles
              ? t(
                  "{embeddings} embedding × {llms} LLM = {count} hibrit kombinasyon. ",
                  {
                    embeddings: embeddingIds.length,
                    llms: llmIds.length,
                    count: embeddingIds.length * llmIds.length,
                  },
                )
              : ""}
            {t("{models} model/yöntem seçimi × {sizes} katalog büyüklüğü", {
              models: modelPreview.length,
              sizes: catalogSizes.length,
            })}
            {" · "}
            {t("Her kombinasyon aynı vakalarda sırayla çalışır.")}
          </p>
          {needsEmbedding && (
            <p>
              {t(
                "Model seçimi ayrı API çağrıları oluşturur. Bağlantı durumu, her modelin sağlayıcıda erişilebilir olduğunu garanti etmez.",
              )}
            </p>
          )}
          {invalidSelection && (
            <p className="selection-warning">
              {t("Gerekli model gruplarından seçim yapın. En fazla ")}
              {status.models.max_variants}
              {t(" kombinasyon çalıştırılabilir.")}
            </p>
          )}
          {!!preview.length && (
            <details>
              <summary>{t("Çalıştırılacak kombinasyonları göster")}</summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t("Yöntem")}</th>
                      <th>{t("Katalog intent sayısı")}</th>
                      <th>{t("Embedding")}</th>
                      <th>{t("LLM")}</th>
                      <th>{t("Arama stratejisi")}</th>
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
      {busy && job && (
        <div className="evaluation-progress">
          <div>
            <LoaderCircle size={17} className="spin" />
            <span>
              {job.progress} / {job.total}
              {t(" karar değerlendirildi")}
              {activeVariant && (
                <small className="active-variant">
                  {activeVariant.llm?.model ||
                    activeVariant.embedding?.model ||
                    t(activeVariant.name)}
                  {activeVariant.llm && activeVariant.embedding
                    ? " + " + activeVariant.embedding.model
                    : ""}{" "}
                  ·{" "}
                  {activeVariant.catalog && (
                    <>
                      {t("{count} intent", {
                        count: activeVariant.catalog.intent_count,
                      })}{" "}
                      ·{" "}
                    </>
                  )}
                  {job.phase === "calibration"
                    ? t("Eşik hesaplanıyor")
                    : job.phase === "index"
                      ? t("İndeks hazırlanıyor")
                      : t("Vakalar çalışıyor")}
                </small>
              )}
            </span>
          </div>
          <progress value={job.progress} max={job.total} />
        </div>
      )}
      {job && metrics && result ? (
        <>
          <div className="result-context">
            <div>
              <Badge tone="blue">
                {job.source_counts.customer
                  ? t("Müşteri verisi içeriyor")
                  : t("Demo veri kümesi")}
              </Badge>
              <span>
                {job.selected_count}
                {t(" vaka · ")}
                {metrics.intent_count}
                {t(" test intenti ·")}{" "}
                {result.catalog && (
                  <>
                    {t("{count} intentlik katalog", {
                      count: result.catalog.intent_count,
                    })}{" "}
                    ·{" "}
                  </>
                )}{" "}
                {job.unreviewed_excluded}
                {t(" etiketsiz vaka hariç")}
              </span>
            </div>
            <span className="mono">
              {t("Veri ")}
              {job.dataset_fingerprint.slice(0, 8)}
              {t(" / Katalog")}{" "}
              {(result.catalog?.version || job.catalog_version).slice(0, 8)}
            </span>
          </div>
          {!job.source_counts.customer && (
            <div className="notice">
              {t(
                "Bu sonuç demo senaryolarına aittir. Müşterinin işlem kapsamındaki %90 hedefini doğrulamaz.",
              )}
            </div>
          )}
          <div className="metric-grid">
            <div>
              <span>{t("İlk karar doğruluğu")}</span>
              <strong
                className={
                  (metrics.routing_accuracy || 0) >= 0.9 ? "green-text" : ""
                }
              >
                {pct(metrics.routing_accuracy)}
              </strong>
              <small>
                {metrics.routing_correct} / {metrics.routing_total}
                {t(" yönlendirme doğru · hedef %90")}
              </small>
            </div>
            <div>
              <span>
                {t("Recall@")}
                {metrics.k}
              </span>
              <strong>{pct(metrics.recall_at_k)}</strong>
              <small>{t("Doğru intent aday listesinde")}</small>
            </div>
            <div>
              <span>{t("Macro-F1")}</span>
              <strong>
                {metrics.macro_f1 == null ? "—" : metrics.macro_f1.toFixed(3)}
              </strong>
              <small>{t("Intent’lere eşit ağırlık")}</small>
            </div>
            <div>
              <span>{t("p95 yönlendirme")}</span>
              <strong>{ms(metrics.latency_ms.p95)}</strong>
              <small>{t("Bu deneyde ölçüldü")}</small>
            </div>
          </div>
          <p className="field-hint selected-result-label">
            {t("Seçili sonuç: ")}
            {resultLabel(selectedId, result, t)}
          </p>
          <section className="panel">
            <div className="panel-heading">
              <h2>{t("Model ve yöntem karşılaştırması")}</h2>
              <Badge>
                {Object.keys(job.results || {}).length}
                {t(" kombinasyon")}
              </Badge>
            </div>
            <div className="table-wrap">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>{t("Yöntem")}</th>
                    <th>{t("Katalog intent sayısı")}</th>
                    <th>
                      <abbr
                        title={t(
                          "Beklenen kararı route olan vakalarda doğru intent ve route kararı oranı. Ret, hata ve gereksiz netleştirme başarısız sayılır.",
                        )}
                        tabIndex={0}
                      >
                        {t("Doğruluk")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "OOS ve diğer karar türleri dahil tüm vakalarda doğru karar oranı; route için intent de eşleşmelidir.",
                        )}
                        tabIndex={0}
                      >
                        {t("Tüm kararlar")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Doğru veya yanlış, route dönen vakaların tüm vakalara oranı.",
                        )}
                        tabIndex={0}
                      >
                        {t("Otomatik yönlendirme")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t("clarify dönen vakaların tüm vakalara oranı.")}
                        tabIndex={0}
                      >
                        {t("Netleştirme")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Kapsam dışı vakalarda yanlışlıkla route dönenlerin oranı. Düşük olması iyidir; hata veya netleştirme doğru ret anlamına gelmez.",
                        )}
                        tabIndex={0}
                      >
                        {t("OOS yanlış kabul")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Model veya bağlantı hatasıyla sonuçlanan vaka sayısı. Accuracy hesabında başarısız sayılır.",
                        )}
                        tabIndex={0}
                      >
                        {t("Teknik hata")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Tek bir isteğin gecikmesinin 95. yüzdeliği. İsteklerin yaklaşık %95’i bu sürede veya daha hızlı tamamlanır; toplam deney süresi değildir.",
                        )}
                        tabIndex={0}
                      >
                        {t("p95")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Doğru intentin aday listesinde bulunma oranı.",
                        )}
                      >
                        Recall@K
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Embedding ve aday aramasının p95 süresi; LLM seçimi hariç.",
                        )}
                      >
                        {t("Arama p95")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Aynı modelin bu deneydeki en küçük katalog sonucuna göre doğruluk farkı; yüzde puan.",
                        )}
                      >
                        {t("Δ doğruluk (yp)")}
                      </abbr>
                    </th>
                    <th>
                      <abbr
                        title={t(
                          "Aynı modelin en küçük katalog sonucuna göre p95 oranı. 2×, iki kat süre demektir.",
                        )}
                      >
                        {t("p95 oranı")}
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
                          {t(r.retrieval_profile?.name || methodNames[resultMethod(id, r)] || "Deney")}
                        </button>
                        <div className="muted">{r.model}</div>
                        {r.reranker && <div className="muted">Reranker: {r.reranker.model}</div>}
                        {r.retrieval_profile && <div className="muted">{t("Havuz {pool} → LLM {final}", { pool: r.retrieval_profile.pool_k, final: r.retrieval_profile.candidate_k })}</div>}
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
                            {t("Sağlayıcı: ")}
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
                        {r.scaling?.accuracy_delta_pp == null
                          ? "—"
                          : new Intl.NumberFormat(tag, {
                              signDisplay: "exceptZero",
                              maximumFractionDigits: 1,
                            }).format(r.scaling.accuracy_delta_pp)}
                      </td>
                      <td>
                        {r.scaling?.p95_ratio == null
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
                "Fark ve oranlar her modelin bu deneydeki en küçük kataloğuna göredir. Tüm büyüklüklerde aynı vakalar kullanılır; bu ölçüm eklenen intentlerin rekabet etkisini gösterir, katalogdaki her intentin doğrulandığı anlamına gelmez.",
              )}
            </p>
          )}
          {job.latency_protocol && (
            <p className="field-hint">
              {t(
                "p95, indeks hazırlandıktan sonraki sorguları ölçer. Seçili kombinasyonda indeks hazırlığı: ",
              )}
              {ms(result.index_build_ms)}
              {result.index_cache_hit ? t(" (hazır indeks kullanıldı)") : ""}
              {" · "}
              {t("Eşik hazırlığı: {duration}", {
                duration: ms(result.calibration_build_ms ?? 0),
              })}
              {t(". Sonuçlar anlık sağlayıcı yükünden etkilenebilir.")}
            </p>
          )}
          {result.calibration?.calibrated && (
            <p className="field-hint">
              {t(
                "Testte kapsam içi yanlış ret: {rate}. Beklenen intent yerine kapsam dışı dönen geçerli vakaların oranı.",
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
          <div className="result-detail-bar">
            <h2>{t("Vaka bazında sonuçlar")}</h2>
            <span>
              {result.model} · {metrics.errors}
              {t(" teknik hata")}
            </span>
          </div>
          <section className="panel">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("Vaka")}</th>
                    <th>{t("Beklenen")}</th>
                    <th>{t("Üretilen karar")}</th>
                    <th>{t("Karar / hata ayrıntısı")}</th>
                    <th>{t("Süre")}</th>
                    <th>{t("Sonuç")}</th>
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
                            {t("Reddetme skoru: {score}", {
                              score: r.rejection_score.toFixed(4),
                            })}
                          </small>
                        )}
                        {r.diagnostics && (
                          <details>
                            <summary>{t("Teknik ayrıntı")}</summary>
                            <pre>{JSON.stringify(r.diagnostics, null, 2)}</pre>
                          </details>
                        )}
                      </td>
                      <td>{ms(r.total_ms)}</td>
                      <td>
                        <Badge tone={r.correct ? "green" : "amber"}>
                          {r.correct ? t("Doğru") : t("İncelenmeli")}
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
              {t("İlk karar doğruluğu için %95 Wilson güven aralığı:")}{" "}
              {pct(metrics.routing_accuracy_ci95[0])}–
              {pct(metrics.routing_accuracy_ci95[1])}
              {t(
                ". Teknik hatalar ve gereksiz netleştirmeler ilk karar başarısızlığı sayılır.",
              )}
            </p>
          )}
        </>
      ) : (
        !busy && (
          <section className="panel">
            <Empty title={t("Henüz sonuç yok")}>
              {t(
                "Bir test kümesi ve yöntem seçerek ilk karşılaştırmayı çalıştırın.",
              )}
            </Empty>
          </section>
        )
      )}
      {!!history.length && (
        <section className="history">
          <h2>{t("Önceki çalışmalar")}</h2>
          {history.slice(0, 8).map((h) => (
            <button key={h.id} onClick={() => void open(h.id)}>
              <FlaskConical size={17} />
              <span>{new Date(h.created * 1000).toLocaleString(tag)}</span>
              <span>
                {h.selected_count}
                {t(" vaka")}
              </span>
              {h.variants && (
                <span>
                  {h.variants.length}
                  {t(" kombinasyon")}
                </span>
              )}
              <Badge>
                {h.status === "completed"
                  ? t("Tamamlandı")
                  : h.status === "failed"
                    ? t("Hata")
                    : t("Çalışıyor")}
              </Badge>
              <ArrowRight size={16} />
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
