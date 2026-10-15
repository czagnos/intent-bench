import { useWorkspaceApi } from "./workspace";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Server,
  X,
} from "lucide-react";
import { type ConnectionProbe, type Status } from "./api";
import { useI18n } from "./i18n";

type Kind = "llm" | "embedding" | "reranker";
type Form = {
  kind: Kind;
  name: string;
  model: string;
  connection: "openrouter" | "onprem" | "typesafe";
  base_url: string;
  auth: "shared_openrouter" | "env" | "none";
  credential_env: string;
  enabled: boolean;
  description: string;
  weights_url: string;
  license: string;
  profile: "auto" | "qwen3" | "e5" | "plain";
  provider_only: string[];
  reasoning: "auto" | "disabled" | "low" | "none";
  max_tokens: number;
  response_format: "json_schema" | "json_object" | "prompt";
  thinking_parameter: "none" | "chat_template" | "top_level";
  send_temperature: boolean;
  timeout_seconds: number;
  reranker_protocol: "cohere" | "tei";
};
type RecordModel = Form & {
  id: string;
  available: boolean;
  unavailable_reason: string | null;
};
type Discovered = Pick<
  Form,
  | "model"
  | "name"
  | "kind"
  | "description"
  | "weights_url"
  | "response_format"
  | "reasoning"
  | "send_temperature"
> & { context_length: number | null; supported_parameters: string[] };
type Discovery = {
  items: Discovered[];
  total: number;
  fetched_at: number;
  cached: boolean;
};
const blank = (connection: Form["connection"], kind: Kind = "llm"): Form => ({
  kind,
  name: connection === "typesafe" ? "TypeSafe Jev" : "",
  model: connection === "typesafe" ? "jev-1.13.0" : "",
  connection,
  base_url: connection === "openrouter"
    ? "https://openrouter.ai/api/v1"
    : connection === "typesafe" ? "https://api.typesafe.ai/v1" : "",
  auth: connection === "openrouter"
    ? "shared_openrouter"
    : connection === "typesafe" ? "env" : "none",
  credential_env: connection === "typesafe" ? "INTENT_TYPESAFE_API_KEY" : "",
  enabled: true,
  description: "",
  weights_url: "",
  license: "",
  profile: "auto",
  provider_only: [],
  reasoning: "none",
  max_tokens: 600,
  response_format: "json_object",
  thinking_parameter: "none",
  send_temperature: connection !== "typesafe",
  timeout_seconds: 30,
  reranker_protocol: "cohere",
});
const editable = (record: RecordModel): Form =>
  Object.fromEntries(
    Object.keys(blank(record.connection)).map((key) => [
      key,
      record[key as keyof Form] ?? blank(record.connection)[key as keyof Form],
    ]),
  ) as Form;

export default function Models({
  status,
  refresh,
}: {
  status: Status;
  refresh: () => Promise<void>;
}) {
  const { api } = useWorkspaceApi();
  const { t, tag, ms } = useI18n();
  const [records, setRecords] = useState<RecordModel[]>([]);
  const [tab, setTab] = useState<"saved" | "discovery">("saved");
  const [kind, setKind] = useState<Kind>("llm");
  const [q, setQ] = useState("");
  const [weights, setWeights] = useState(false);
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const consumedReload = useRef(0);
  const [discovery, setDiscovery] = useState<Discovery>();
  const [form, setForm] = useState<Form>();
  const [editing, setEditing] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [probes, setProbes] = useState<Record<string, ConnectionProbe>>({});
  const probeGeneration = useRef(0);
  useEffect(() => {
    probeGeneration.current++;
    setProbes({});
    setBusy("");
    return () => { probeGeneration.current++; };
  }, [status.models]);
  const loadRecords = useCallback(async () => {
    const data = await api<{ items: RecordModel[] }>("/model-registry");
    setRecords(data.items);
  }, [api]);
  useEffect(() => {
    void loadRecords().catch((e) => setError(e.message));
  }, [loadRecords]);
  useEffect(() => {
    if (tab !== "discovery") return;
    let active = true;
    setLoading(true);
    setDiscovery(undefined);
    setError("");
    const timer = setTimeout(() => {
      const params = new URLSearchParams({
        kind,
        q,
        with_weights: String(weights),
        offset: String(offset),
        limit: "20",
      });
      // Refresh is consumed once; filtering/pagination reuse the server's five-minute metadata cache.
      if (reload !== consumedReload.current) params.set("refresh", "true");
      consumedReload.current = reload;
      void api<Discovery>("/model-discovery/openrouter?" + params)
        .then((data) => {
          if (active) setDiscovery(data);
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [tab, kind, q, weights, offset, reload]);
  function open(value: Form, id?: string) {
    setForm(value);
    setEditing(id);
    setError("");
    setNotice("");
  }
  function patch<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  }
  async function save(value: Form, id?: string) {
    setBusy(id || "save");
    setError("");
    setNotice("");
    try {
      await api<RecordModel>("/model-registry" + (id ? "/" + id : ""), {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify({
          ...value,
          provider_only: value.provider_only
            .map((v) => v.trim())
            .filter(Boolean),
        }),
      });
      if (id)
        setProbes((current) => {
          const next = { ...current };
          delete next[id];
          return next;
        });
      setForm(undefined);
      setEditing(undefined);
      setTab("saved");
      await loadRecords();
      await refresh();
      setNotice(
        "Model saved. Live demo, experiment and calibration selections are updated.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function check(record: RecordModel) {
    const generation = probeGeneration.current;
    setBusy(record.id);
    setError("");
    try {
      const result = await api<ConnectionProbe>(
        "/model-registry/" + record.id + "/check",
        { method: "POST" },
      );
      if (generation === probeGeneration.current) setProbes((current) => ({ ...current, [record.id]: result }));
    } catch (e) {
      if (generation === probeGeneration.current) setError((e as Error).message);
    } finally {
      if (generation === probeGeneration.current) setBusy("");
    }
  }
  return (
    <div className="page-pad model-registry-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("MODEL CATALOG")}</p>
          <h1>{t("Add models. Compare connections.")}</h1>
          <p>
            {t(
              "Compare OpenRouter, TypeSafe Jev and models on your own server in the same experiment.",
            )}
          </p>
        </div>
        <div className="registry-actions">
          <button
            className="button subtle"
            disabled={!!busy}
            onClick={() => open(blank("typesafe"))}
          >
            <Plus size={17} />
            {t("Add TypeSafe Jev")}
          </button>
          <button className="button subtle" disabled={!!busy} onClick={() => open({ ...blank("onprem", "reranker"),
            name: "BGE reranker v2 M3", model: "BAAI/bge-reranker-v2-m3", weights_url: "https://huggingface.co/BAAI/bge-reranker-v2-m3" })}>
            <Plus size={17} />{t("Add reranker")}
          </button>
          <button
            className="button subtle"
            disabled={!!busy}
            onClick={async () => {
              probeGeneration.current++;
              setProbes({});
              setBusy("refresh");
              setError("");
              try {
                await loadRecords();
                await refresh();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy("");
              }
            }}
          >
            <RefreshCw size={17} />
            {t("Refresh connections")}
          </button>
          <button
            className="button primary"
            disabled={!!busy}
            onClick={() => open(blank("onprem"))}
          >
            <Plus size={17} />
            {t("Add on-prem model")}
          </button>
        </div>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {t(error)}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          <Check size={17} />
          {t(notice)}
        </div>
      )}
      {form && (
        <section
          className="panel registry-form"
          aria-label={t("Model connection form")}
        >
          <div className="panel-heading">
            <h2>{t(editing ? "Edit model" : "New model connection")}</h2>
            <button
              className="icon-button"
              aria-label={t("Close")}
              disabled={!!busy}
              onClick={() => setForm(undefined)}
            >
              <X size={18} />
            </button>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void save(form, editing);
            }}
          >
            <fieldset disabled={!!busy} className="registry-fields">
              <label>
                {t("Display name")}
                <input
                  required
                  maxLength={120}
                  value={form.name}
                  onChange={(e) => patch("name", e.target.value)}
                  placeholder="Qwen decision model / OpenRouter GPT-OSS"
                />
              </label>
              <label>
                {t("Model type")}
                <select
                  value={form.kind}
                  disabled={!!editing}
                  onChange={(e) => {
                    const next = e.target.value as Kind;
                    setForm(next === "reranker" ? { ...form, kind: next, connection: "onprem", base_url: form.connection === "onprem" ? form.base_url : "", auth: form.auth === "shared_openrouter" ? "none" : form.auth, provider_only: [] } : { ...form, kind: next });
                  }}
                >
                  <option value="llm">LLM</option>
                  <option value="embedding" disabled={form.connection === "typesafe"}>Embedding</option>
                  <option value="reranker" disabled={form.connection === "typesafe"}>Reranker</option>
                </select>
              </label>
              <label>
                {t("Connection type")}
                <select
                  value={form.connection}
                  onChange={(e) => {
                    const connection = e.target.value as Form["connection"];
                    setForm(connection === "typesafe" ? blank("typesafe") : {
                      ...form,
                      connection,
                      base_url: blank(connection).base_url,
                      auth: blank(connection).auth,
                      credential_env: "",
                      provider_only: [],
                    });
                  }}
                >
                  <option value="openrouter" disabled={form.kind === "reranker"}>OpenRouter</option>
                  <option value="typesafe" disabled={form.kind !== "llm"}>TypeSafe</option>
                  <option value="onprem">{t("On-prem / custom endpoint")}</option>
                </select>
              </label>
              <label>
                {t("Model ID")}
                <input
                  required
                  maxLength={200}
                  value={form.model}
                  onChange={(e) => patch("model", e.target.value)}
                  placeholder={
                    form.connection === "openrouter"
                      ? "openai/gpt-oss-20b"
                      : "my-served-model"
                  }
                />
              </label>
              <label className="registry-wide">
                {t("API base URL")}
                <input
                  required
                  type="url"
                  readOnly={form.connection !== "onprem"}
                  maxLength={500}
                  value={form.base_url}
                  onChange={(e) => patch("base_url", e.target.value)}
                  placeholder="http://localhost:8001/v1"
                />
                <small>
                  {t(
                    form.connection === "typesafe" ? "Connects directly to TypeSafe. Jev selects from the candidate intents." : form.kind === "reranker" ? "Enter the reranker API base URL. The application appends /rerank." : "OpenAI-compatible URL reachable from the API server. Do not append /chat/completions or /embeddings.",
                  )}
                </small>
              </label>
              {form.kind === "reranker" && <label>{t("Reranker protocol")}<select value={form.reranker_protocol} onChange={e => patch("reranker_protocol", e.target.value as Form["reranker_protocol"])}><option value="cohere">Cohere / vLLM</option><option value="tei">Hugging Face TEI</option></select></label>}
              <label>
                {t("Authentication")}
                <select
                  value={form.auth}
                  onChange={(e) =>
                    patch("auth", e.target.value as Form["auth"])
                  }
                >
                  {form.connection === "openrouter" && (
                    <option value="shared_openrouter">
                      {t("Existing OpenRouter key")}
                    </option>
                  )}
                  {form.connection === "onprem" && (
                    <option value="none">{t("No key required")}</option>
                  )}
                  <option value="env">
                    {t("Server key variable")}
                  </option>
                </select>
              </label>
              {form.auth === "env" && (
                <label>
                  {t("Key variable name")}
                  <input
                    required
                    pattern={form.connection === "typesafe" ? "(INTENT_TYPESAFE_API_KEY|INTENT_MODEL_KEY_[A-Z0-9_]+)" : "INTENT_MODEL_KEY_[A-Z0-9_]+"}
                    maxLength={120}
                    value={form.credential_env}
                    onChange={(e) => patch("credential_env", e.target.value)}
                    placeholder={form.connection === "typesafe" ? "INTENT_TYPESAFE_API_KEY" : "INTENT_MODEL_KEY_BANK_LLM"}
                  />
                </label>
              )}
              <p className="field-hint registry-wide">
                {t(
                  form.connection === "typesafe"
                    ? "Do not paste the key here. Add INTENT_TYPESAFE_API_KEY=your_key to the server .env file; enter only the variable name here. Use Refresh connections to update availability."
                    : form.auth === "env"
                      ? "Do not paste the key here. Enter only the server variable name. File-based keys are reread on Refresh connections; process environment changes require an API restart, and Docker env-file changes require container recreation."
                      : form.auth === "shared_openrouter"
                        ? "Uses INTENT_OPENROUTER_API_KEY from the server. Restart the API after changing this shared key; recreate Docker containers after env-file changes."
                        : "No Authorization header is sent to this connection.",
                )}
              </p>
            </fieldset>
            <details className="registry-advanced">
              <summary>{t("Advanced model settings")}</summary>
              <fieldset className="registry-fields" disabled={!!busy}>
                {form.kind === "embedding" ? (
                  <label>
                    {t("Embedding text profile")}
                    <select
                      value={form.profile}
                      onChange={(e) =>
                        patch("profile", e.target.value as Form["profile"])
                      }
                    >
                      {["auto", "qwen3", "e5", "plain"].map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : form.kind === "llm" && form.connection !== "typesafe" ? (
                  <>
                    <label>
                      {t("JSON response mode")}
                      <select
                        value={form.response_format}
                        onChange={(e) =>
                          patch(
                            "response_format",
                            e.target.value as Form["response_format"],
                          )
                        }
                      >
                        <option value="json_schema">JSON Schema</option>
                        <option value="json_object">JSON Object</option>
                        <option value="prompt">{t("JSON via prompt")}</option>
                      </select>
                      <small>
                        {t(
                          "Response schema and candidate intent IDs are validated on the server in every mode.",
                        )}
                      </small>
                    </label>
                    <label>
                      {t("Reasoning parameter")}
                      <select
                        value={form.reasoning}
                        onChange={(e) =>
                          patch(
                            "reasoning",
                            e.target.value as Form["reasoning"],
                          )
                        }
                      >
                        {["none", "auto", "disabled", "low"].map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {t("Maximum output tokens")}
                      <input
                        type="number"
                        required
                        min={128}
                        max={8192}
                        value={form.max_tokens}
                        onChange={(e) =>
                          patch("max_tokens", Number(e.target.value))
                        }
                      />
                      <small>
                        {t(
                          "Reasoning low reserves at least 4096 tokens.",
                        )}
                      </small>
                    </label>
                    {form.connection === "onprem" && (
                      <label>
                        {t("Server thinking parameter")}
                        <select
                          value={form.thinking_parameter}
                          onChange={(e) =>
                            patch(
                              "thinking_parameter",
                              e.target.value as Form["thinking_parameter"],
                            )
                          }
                        >
                          {["none", "chat_template", "top_level"].map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    <label className="registry-checkbox">
                      <input
                        type="checkbox"
                        checked={form.send_temperature}
                        onChange={(e) =>
                          patch("send_temperature", e.target.checked)
                        }
                      />
                      {t("Send temperature: 0")}
                    </label>
                  </>
                ) : null}
                {form.connection === "openrouter" && (
                  <label>
                    {t("Provider filter (optional)")}
                    <input
                      value={form.provider_only.join(",")}
                      onChange={(e) =>
                        patch("provider_only", e.target.value.split(","))
                      }
                      placeholder="nebius"
                    />
                    <small>
                      {t(
                        "Separate with commas. Leave empty for OpenRouter to select providers.",
                      )}
                    </small>
                  </label>
                )}
                <label>
                  {t("Request timeout (seconds)")}
                  <input
                    type="number"
                    required
                    min={1}
                    max={120}
                    value={form.timeout_seconds}
                    onChange={(e) =>
                      patch("timeout_seconds", Number(e.target.value))
                    }
                  />
                </label>
                <label>
                  {t("Model card URL (optional)")}
                  <input
                    type="url"
                    value={form.weights_url}
                    onChange={(e) => patch("weights_url", e.target.value)}
                    placeholder="https://huggingface.co/organization/model"
                  />
                </label>
                <label>
                  {t("License note (optional)")}
                  <input
                    maxLength={80}
                    value={form.license}
                    onChange={(e) => patch("license", e.target.value)}
                  />
                </label>
                <label className="registry-wide">
                  {t("Description")}
                  <textarea
                    maxLength={500}
                    value={form.description}
                    onChange={(e) => patch("description", e.target.value)}
                  />
                </label>
              </fieldset>
            </details>
            <div className="registry-actions">
              <button
                className="button primary"
                disabled={!!busy}
                type="submit"
              >
                {busy ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Check size={17} />
                )}{" "}
                {t("Save model")}
              </button>
              <button
                type="button"
                className="button subtle"
                disabled={!!busy}
                onClick={() => setForm(undefined)}
              >
                {t("Cancel")}
              </button>
            </div>
          </form>
        </section>
      )}
      <div
        className="registry-tabs"
        role="tablist"
        aria-label={t("Model sources")}
      >
        <button
          role="tab"
          aria-selected={tab === "saved"}
          className={"button " + (tab === "saved" ? "primary" : "subtle")}
          onClick={() => setTab("saved")}
        >
          {t("My models")} ({records.length})
        </button>
        <button
          role="tab"
          aria-selected={tab === "discovery"}
          className={"button " + (tab === "discovery" ? "primary" : "subtle")}
          onClick={() => setTab("discovery")}
        >
          {t("Discover on OpenRouter")}
        </button>
        <button
          className="button subtle"
          disabled={!!busy}
          onClick={() => open(blank("openrouter", kind))}
        >
          <Plus size={16} />
          {t("Add by model ID")}
        </button>
      </div>
      {tab === "discovery" ? (
        <section className="panel registry-discovery">
          <div className="registry-toolbar">
            <label>
              {t("Model type")}
              <select
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as Kind);
                  setOffset(0);
                }}
              >
                <option value="llm">LLM</option>
                <option value="embedding">Embedding</option>
              </select>
            </label>
            <label className="registry-search">
              {t("Search models")}
              <input
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setOffset(0);
                }}
                placeholder="Qwen, GPT-OSS, DeepSeek, BGE…"
              />
            </label>
            <label className="registry-checkbox">
              <input
                type="checkbox"
                checked={weights}
                onChange={(e) => {
                  setWeights(e.target.checked);
                  setOffset(0);
                }}
              />
              {t("Has a model card")}
            </label>
            <button
              className="button subtle"
              disabled={loading}
              onClick={() => setReload((v) => v + 1)}
            >
              <RefreshCw size={16} />
              {t("Refresh list")}
            </button>
          </div>
          <p className="field-hint">
            {t(
              "A model card link does not confirm on-prem licensing or hardware suitability. You can inspect the card before adding the model.",
            )}
          </p>
          {loading ? (
            <div className="empty" role="status">
              <LoaderCircle className="spin" />
              {t("Loading OpenRouter models…")}
            </div>
          ) : (
            discovery && (
              <>
                <div className="registry-cards">
                  {discovery.items.map((item) => (
                    <article className="registry-card" key={item.model}>
                      <span className="badge blue">
                        {item.kind === "llm" ? "LLM" : "Embedding"}
                      </span>
                      <h3>{item.name}</h3>
                      <code>{item.model}</code>
                      <p>{item.description}</p>
                      {item.context_length && (
                        <small>
                          {t("Context: {count} tokens", {
                            count: item.context_length.toLocaleString(tag),
                          })}
                        </small>
                      )}
                      <div className="registry-card-footer">
                        {item.weights_url && (
                          <a
                            href={item.weights_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("Model card ↗")}
                          </a>
                        )}
                        <button
                          className="button subtle"
                          disabled={!!busy}
                          onClick={() => {
                            const {
                              context_length,
                              supported_parameters,
                              ...fields
                            } = item;
                            open({
                              ...blank("openrouter", item.kind),
                              ...fields,
                            });
                            window.scrollTo?.({ top: 0, behavior: "smooth" });
                          }}
                        >
                          <Plus size={15} />
                          {t("Add to catalog")}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
                {!discovery.items.length && (
                  <div className="empty">
                    <Search size={24} />
                    {t("No models match these filters.")}
                  </div>
                )}
                <div className="registry-pagination">
                  <small>
                    {t("{count} models · list updated: {time}", {
                      count: discovery.total,
                      time: new Date(
                        discovery.fetched_at * 1000,
                      ).toLocaleTimeString(tag),
                    })}
                  </small>
                  <div>
                    <button
                      className="icon-button"
                      aria-label={t("Previous page")}
                      disabled={!offset}
                      onClick={() => {
                        setOffset((v) => Math.max(0, v - 20));
                      }}
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t("Next page")}
                      disabled={offset + 20 >= discovery.total}
                      onClick={() => {
                        setOffset((v) => v + 20);
                      }}
                    >
                      <ChevronRight size={18} />
                    </button>
                  </div>
                </div>
              </>
            )
          )}
        </section>
      ) : (
        <section className="panel registry-saved">
          <div className="panel-heading">
            <div>
              <h2>{t("Your registered models")}</h2>
              <p className="field-hint">
                {t(
                  "Connection tests send fixed demo text and may incur API charges. They do not measure accuracy.",
                )}
              </p>
            </div>
          </div>
          {!records.length ? (
            <div className="empty">
              <Server size={28} />
              <h3>{t("Add your first model connection.")}</h3>
              <p>
                {t(
                  "Add TypeSafe Jev, choose a model from OpenRouter or register your own server endpoint.",
                )}
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t("Model")}</th>
                    <th>{t("Connection")}</th>
                    <th>{t("Status")}</th>
                    <th>{t("Actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => (
                    <tr key={record.id}>
                      <td>
                        <strong>{record.name}</strong>
                        <small>
                          {record.kind === "llm" ? "LLM" : "Embedding"} ·{" "}
                          {record.model}
                        </small>
                        <code className="registry-id">{record.id}</code>
                      </td>
                      <td>
                        <span>
                          {record.connection === "openrouter"
                            ? "OpenRouter"
                            : record.connection === "typesafe"
                              ? "TypeSafe"
                              : t("On-prem / custom endpoint")}
                        </span>
                        <small>{record.base_url}</small>
                      </td>
                      <td>
                        <span
                          className={
                            "badge " + (record.available ? "blue" : "")
                          }
                        >
                          {t(
                            record.available
                              ? "Connection configured"
                              : record.unavailable_reason || "Connection required",
                          )}
                        </span>
                        {probes[record.id] && (
                          <small
                            role="status"
                            className={
                              probes[record.id].ok ? "" : "registry-probe-error"
                            }
                          >
                            {probes[record.id].ok
                              ? t("Test passed · {duration}", {
                                  duration: ms(probes[record.id].elapsed_ms),
                                })
                              : t(probes[record.id].error || "Connection error")}
                          </small>
                        )}
                      </td>
                      <td>
                        <div className="registry-actions">
                          <button
                            className="button subtle"
                            disabled={!!busy || !record.available}
                            onClick={() => void check(record)}
                          >
                            {busy === record.id ? (
                              <LoaderCircle className="spin" size={15} />
                            ) : null}
                            {t("Test connection")}
                          </button>
                          <button
                            className="button subtle"
                            disabled={!!busy}
                            onClick={() => open(editable(record), record.id)}
                          >
                            {t("Edit")}
                          </button>
                          <button
                            className="button subtle"
                            disabled={!!busy}
                            onClick={() =>
                              void save(
                                {
                                  ...editable(record),
                                  enabled: !record.enabled,
                                },
                                record.id,
                              )
                            }
                          >
                            {t(
                              record.enabled
                                ? "Disable"
                                : "Enable",
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      <details className="panel registry-builtins">
        <summary>{t("Starter models and .env defaults")}</summary>
        <p className="field-hint">
          {t(
            "These starter options remain available for existing experiments. Add new models above.",
          )}
        </p>
        <div className="registry-builtin-list">
          {(["llm", "embedding"] as const).flatMap((kind) =>
            status.models[kind]
              .filter((m) => !m.registered)
              .map((m) => (
                <div key={kind + m.id}>
                  <strong>{t(m.name)}</strong>
                  <small>
                    {kind === "llm" ? "LLM" : "Embedding"} · {m.model}
                  </small>
                  <span>
                    {t(m.available ? "Connection configured" : "Connection required")}
                  </span>
                </div>
              )),
          )}
        </div>
      </details>
    </div>
  );
}
