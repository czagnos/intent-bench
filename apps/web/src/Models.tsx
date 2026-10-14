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
import { api, type Status } from "./api";
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
type Probe = {
  ok: boolean;
  error?: string;
  elapsed_ms: number;
  dimensions?: number;
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
  const [probes, setProbes] = useState<Record<string, Probe>>({});
  const loadRecords = useCallback(async () => {
    const data = await api<{ items: RecordModel[] }>("/model-registry");
    setRecords(data.items);
  }, []);
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
        "Model kaydedildi. Canlı demo, deney ve kalibrasyon seçimleri güncellendi.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function check(record: RecordModel) {
    setBusy(record.id);
    setError("");
    try {
      const result = await api<Probe>(
        "/model-registry/" + record.id + "/check",
        { method: "POST" },
      );
      setProbes((current) => ({ ...current, [record.id]: result }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="page-pad model-registry-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("MODEL KATALOĞU")}</p>
          <h1>{t("Modelleri ekle, bağlantıları karşılaştır.")}</h1>
          <p>
            {t(
              "OpenRouter, TypeSafe Jev ve kendi sunucundaki modelleri aynı deneyde karşılaştır.",
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
            {t("TypeSafe Jev ekle")}
          </button>
          <button className="button subtle" disabled={!!busy} onClick={() => open({ ...blank("onprem", "reranker"),
            name: "BGE reranker v2 M3", model: "BAAI/bge-reranker-v2-m3", weights_url: "https://huggingface.co/BAAI/bge-reranker-v2-m3" })}>
            <Plus size={17} />{t("Reranker ekle")}
          </button>
          <button
            className="button subtle"
            disabled={!!busy}
            onClick={async () => {
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
            {t("Bağlantıları yenile")}
          </button>
          <button
            className="button primary"
            disabled={!!busy}
            onClick={() => open(blank("onprem"))}
          >
            <Plus size={17} />
            {t("On-prem model ekle")}
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
          aria-label={t("Model bağlantısı formu")}
        >
          <div className="panel-heading">
            <h2>{t(editing ? "Modeli düzenle" : "Yeni model bağlantısı")}</h2>
            <button
              className="icon-button"
              aria-label={t("Kapat")}
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
                {t("Görünen ad")}
                <input
                  required
                  maxLength={120}
                  value={form.name}
                  onChange={(e) => patch("name", e.target.value)}
                  placeholder="Bank Qwen / OpenRouter GPT-OSS"
                />
              </label>
              <label>
                {t("Model türü")}
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
                {t("Bağlantı türü")}
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
                  <option value="onprem">{t("On-prem / özel endpoint")}</option>
                </select>
              </label>
              <label>
                {t("Model kimliği")}
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
                {t("API kök adresi")}
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
                    form.connection === "typesafe" ? "TypeSafe'e doğrudan bağlanır. Jev, intent adayları arasından seçim yapar." : form.kind === "reranker" ? "Reranker API kök adresini girin. /rerank yolu uygulama tarafından eklenir." : "API sunucusundan erişilebilen OpenAI uyumlu adres. /chat/completions veya /embeddings eklemeyin.",
                  )}
                </small>
              </label>
              {form.kind === "reranker" && <label>{t("Reranker protokolü")}<select value={form.reranker_protocol} onChange={e => patch("reranker_protocol", e.target.value as Form["reranker_protocol"])}><option value="cohere">Cohere / vLLM</option><option value="tei">Hugging Face TEI</option></select></label>}
              <label>
                {t("Kimlik doğrulama")}
                <select
                  value={form.auth}
                  onChange={(e) =>
                    patch("auth", e.target.value as Form["auth"])
                  }
                >
                  {form.connection === "openrouter" && (
                    <option value="shared_openrouter">
                      {t("Mevcut OpenRouter anahtarı")}
                    </option>
                  )}
                  {form.connection === "onprem" && (
                    <option value="none">{t("Anahtar gerekmiyor")}</option>
                  )}
                  <option value="env">
                    {t("Sunucudaki anahtar değişkeni")}
                  </option>
                </select>
              </label>
              {form.auth === "env" && (
                <label>
                  {t("Anahtar değişkeninin adı")}
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
                    ? "Anahtarı bu alana yapıştırmayın. Sunucunun .env dosyasına INTENT_TYPESAFE_API_KEY=anahtar ekleyin; burada yalnızca değişken adı bulunur. Bağlantıları yenile ile kullanılabilirliği güncelleyin."
                    : form.auth === "env"
                      ? "Anahtarı bu alana yapıştırmayın. Sunucunun .env dosyasına INTENT_MODEL_KEY_BANK_LLM=anahtar ekleyip burada yalnızca değişken adını kullanın. Bu değişkenler yeniden başlatmadan okunur."
                      : form.auth === "shared_openrouter"
                        ? "INTENT_OPENROUTER_API_KEY kullanılır; yeniden anahtar girmeniz gerekmez."
                        : "Bu bağlantıya Authorization başlığı gönderilmez.",
                )}
              </p>
            </fieldset>
            <details className="registry-advanced">
              <summary>{t("Gelişmiş model ayarları")}</summary>
              <fieldset className="registry-fields" disabled={!!busy}>
                {form.kind === "embedding" ? (
                  <label>
                    {t("Embedding metin profili")}
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
                      {t("JSON yanıt modu")}
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
                        <option value="prompt">{t("Prompt ile JSON")}</option>
                      </select>
                      <small>
                        {t(
                          "Tüm modlarda yanıt şeması ve aday intent kimlikleri sunucuda doğrulanır.",
                        )}
                      </small>
                    </label>
                    <label>
                      {t("Reasoning parametresi")}
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
                      {t("En fazla çıktı tokenı")}
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
                          "Reasoning low seçildiğinde en az 4096 token ayrılır.",
                        )}
                      </small>
                    </label>
                    {form.connection === "onprem" && (
                      <label>
                        {t("Sunucu thinking parametresi")}
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
                      {t("temperature: 0 gönder")}
                    </label>
                  </>
                ) : null}
                {form.connection === "openrouter" && (
                  <label>
                    {t("Sağlayıcı filtresi (isteğe bağlı)")}
                    <input
                      value={form.provider_only.join(",")}
                      onChange={(e) =>
                        patch("provider_only", e.target.value.split(","))
                      }
                      placeholder="nebius"
                    />
                    <small>
                      {t(
                        "Virgülle ayırın. Boş bırakılırsa OpenRouter sağlayıcı seçer.",
                      )}
                    </small>
                  </label>
                )}
                <label>
                  {t("İstek zaman aşımı (sn)")}
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
                  {t("Model kartı adresi (isteğe bağlı)")}
                  <input
                    type="url"
                    value={form.weights_url}
                    onChange={(e) => patch("weights_url", e.target.value)}
                    placeholder="https://huggingface.co/organization/model"
                  />
                </label>
                <label>
                  {t("Lisans notu (isteğe bağlı)")}
                  <input
                    maxLength={80}
                    value={form.license}
                    onChange={(e) => patch("license", e.target.value)}
                  />
                </label>
                <label className="registry-wide">
                  {t("Açıklama")}
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
                {t("Modeli kaydet")}
              </button>
              <button
                type="button"
                className="button subtle"
                disabled={!!busy}
                onClick={() => setForm(undefined)}
              >
                {t("Vazgeç")}
              </button>
            </div>
          </form>
        </section>
      )}
      <div
        className="registry-tabs"
        role="tablist"
        aria-label={t("Model kaynakları")}
      >
        <button
          role="tab"
          aria-selected={tab === "saved"}
          className={"button " + (tab === "saved" ? "primary" : "subtle")}
          onClick={() => setTab("saved")}
        >
          {t("Modellerim")} ({records.length})
        </button>
        <button
          role="tab"
          aria-selected={tab === "discovery"}
          className={"button " + (tab === "discovery" ? "primary" : "subtle")}
          onClick={() => setTab("discovery")}
        >
          {t("OpenRouter’dan keşfet")}
        </button>
        <button
          className="button subtle"
          disabled={!!busy}
          onClick={() => open(blank("openrouter", kind))}
        >
          <Plus size={16} />
          {t("Model kimliğiyle ekle")}
        </button>
      </div>
      {tab === "discovery" ? (
        <section className="panel registry-discovery">
          <div className="registry-toolbar">
            <label>
              {t("Model türü")}
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
              {t("Model ara")}
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
              {t("Model kartı bulunanlar")}
            </label>
            <button
              className="button subtle"
              disabled={loading}
              onClick={() => setReload((v) => v + 1)}
            >
              <RefreshCw size={16} />
              {t("Listeyi yenile")}
            </button>
          </div>
          <p className="field-hint">
            {t(
              "Model kartı bağlantısı on-prem lisans veya donanım uygunluğunu doğrulamaz. Modeli eklemeden kartını inceleyebilirsin.",
            )}
          </p>
          {loading ? (
            <div className="empty" role="status">
              <LoaderCircle className="spin" />
              {t("OpenRouter modelleri yükleniyor…")}
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
                          {t("Bağlam: {count} token", {
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
                            {t("Model kartı ↗")}
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
                          {t("Kataloğa ekle")}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
                {!discovery.items.length && (
                  <div className="empty">
                    <Search size={24} />
                    {t("Bu filtreyle model bulunamadı.")}
                  </div>
                )}
                <div className="registry-pagination">
                  <small>
                    {t("{count} model · liste güncellemesi: {time}", {
                      count: discovery.total,
                      time: new Date(
                        discovery.fetched_at * 1000,
                      ).toLocaleTimeString(tag),
                    })}
                  </small>
                  <div>
                    <button
                      className="icon-button"
                      aria-label={t("Önceki sayfa")}
                      disabled={!offset}
                      onClick={() => {
                        setOffset((v) => Math.max(0, v - 20));
                      }}
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t("Sonraki sayfa")}
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
              <h2>{t("Eklediğin modeller")}</h2>
              <p className="field-hint">
                {t(
                  "Bağlantı testi sabit demo metni gönderir; API kullanımı ücretli olabilir. Bu test doğruluk ölçmez.",
                )}
              </p>
            </div>
          </div>
          {!records.length ? (
            <div className="empty">
              <Server size={28} />
              <h3>{t("İlk model bağlantını ekle.")}</h3>
              <p>
                {t(
                  "TypeSafe Jev ekle, OpenRouter’dan bir model seç veya kendi sunucunun endpoint’ini tanımla.",
                )}
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t("Model")}</th>
                    <th>{t("Bağlantı")}</th>
                    <th>{t("Durum")}</th>
                    <th>{t("İşlemler")}</th>
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
                              : t("On-prem / özel endpoint")}
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
                              ? "Bağlantı ayarlı"
                              : record.unavailable_reason || "Bağlantı gerekli",
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
                              ? t("Test başarılı · {duration}", {
                                  duration: ms(probes[record.id].elapsed_ms),
                                })
                              : t(probes[record.id].error || "Bağlantı hatası")}
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
                            {t("Bağlantıyı test et")}
                          </button>
                          <button
                            className="button subtle"
                            disabled={!!busy}
                            onClick={() => open(editable(record), record.id)}
                          >
                            {t("Düzenle")}
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
                                ? "Devre dışı bırak"
                                : "Etkinleştir",
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
        <summary>{t("Başlangıç modelleri ve .env varsayılanları")}</summary>
        <p className="field-hint">
          {t(
            "Bu hazır seçenekler mevcut deneylerle uyumluluk için korunur. Yeni modeller yukarıdan eklenir.",
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
                    {t(m.available ? "Bağlantı ayarlı" : "Bağlantı gerekli")}
                  </span>
                </div>
              )),
          )}
        </div>
      </details>
    </div>
  );
}
