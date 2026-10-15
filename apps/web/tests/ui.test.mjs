import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const directory = dirname(dirname(fileURLToPath(import.meta.url)));
const temporary = mkdtempSync(join(directory, ".ui-test-"));
const bundle = join(temporary, "components.cjs");
await build({
  stdin: {
    contents:
      'export {default as App} from "./src/App"; export {LanguageProvider} from "./src/i18n"; export * from "./src/i18n-core"; export * from "./src/routing-map"; export {createWorkspaceClient} from "./src/api";',
    resolveDir: directory,
    loader: "tsx",
  },
  bundle: true,
  outfile: bundle,
  platform: "node",
  format: "cjs",
  packages: "external",
  jsx: "automatic",
  logLevel: "silent",
});
const dom = new JSDOM(
  '<!doctype html><html lang="tr"><head><meta name="description" content=""></head><body><div id="root"></div></body></html>',
  { url: "http://localhost" },
);
for (const key of [
  "window",
  "document",
  "HTMLElement",
  "HTMLSelectElement",
  "Event",
  "MouseEvent",
  "localStorage",
])
  globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
HTMLElement.prototype.scrollIntoView = () => {};
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
window.scrollTo = () => {};
const { createElement, act } = await import("react");
const { createRoot } = await import("react-dom/client");
const require = createRequire(import.meta.url);
const {
  App,
  LanguageProvider,
  translate,
  formatPercent,
  formatDuration,
  groupCatalog,
  layoutMap,
  createWorkspaceClient,
} = require(bundle);
const catalog = JSON.parse(
  readFileSync(join(directory, "../../data/demo/catalog.json"), "utf8"),
);
const model = (id, name, model) => ({
  id,
  name,
  model,
  available: true,
  description: "Current model and connection settings configured on the server.",
  settings: {},
  license: "MIT",
  weights_url: null,
});
const status = {
  catalog_version: "catalog-version",
  intent_count: 800,
  catalog_min_size: 48,
  customer_case_count: 0,
  reviewed_customer_count: 0,
  reviewed_customer_test_count: 0,
  seed_case_count: 29,
  embedding_configured: true,
  llm_configured: true,
  embedding_model: "qwen/qwen3-embedding-8b",
  llm_model: "qwen/qwen3.5-35b-a3b",
  methods: [
    {
      id: "lexical",
      name: "Lexical baseline",
      available: true,
      model: "char-tfidf-bm25",
    },
    {
      id: "e5",
      name: "Semantic search",
      available: true,
      model: "qwen/qwen3-embedding-8b",
    },
    {
      id: "hybrid_llm",
      name: "Hybrid retrieval + LLM",
      available: true,
      model: "qwen/qwen3.5-35b-a3b",
    },
  ],
  models: {
    embedding: [
      model(
        "default",
        "Qwen3 Embedding 8B · varsayılan",
        "qwen/qwen3-embedding-8b",
      ),
      model("bge-m3", "BGE-M3", "baai/bge-m3"),
    ],
    llm: [model("default", "Qwen3.5", "qwen/qwen3.5-35b-a3b")],
    reranker: [model("default", "BGE reranker", "BAAI/bge-reranker-v2-m3")],
    max_variants: 32,
  },
};
const fit = {
  id: "fit-for-demo-model",
  mode: "calibrated",
  calibrated: true,
  threshold: 0.5,
  source: "seed",
  created: 1,
  sample_count: 72,
  metrics: {
    in_scope_accept_rate: 0.95,
    in_scope_false_reject_rate: 0.05,
    oos_false_accept_rate: 0,
    low_retention: false,
  },
};
const calibrationData = {
  datasets: {
    seed: { total: 72, in_scope: 48, oos: 24 },
    customer: { total: 0, in_scope: 0, oos: 0 },
  },
  profiles: [
    {
      embedding_id: "default",
      model: status.embedding_model,
      available: true,
      calibration: fit,
    },
  ],
};
const question = catalog[0].examples[0];
const record = {
  case_id: "case-1",
  question,
  expected_decision: "route",
  expected_intent_id: "card.limit.change",
  decision: "route",
  intent_id: "card.limit.change",
  correct: true,
  total_ms: 500,
  reason_code: "nearest_intent_baseline",
  rejection_score: 0.9,
};
const metrics = {
  routing_accuracy: 0.9,
  decision_accuracy: 0.85,
  routing_correct: 9,
  routing_total: 10,
  macro_f1: 0.8,
  recall_at_k: 1,
  k: 20,
  coverage: 0.8,
  clarification_rate: 0.1,
  oos_false_accept_rate: 0,
  in_scope_false_reject_rate: 0.05,
  errors: 0,
  total: 29,
  intent_count: 26,
  latency_ms: { p95: 5500 },
};
const evaluation = {
  id: "eval-1",
  status: "completed",
  created: 1,
  selected_count: 29,
  unreviewed_excluded: 0,
  source_counts: { seed: 29 },
  catalog_version: "catalog-version",
  dataset_fingerprint: "test-fingerprint",
  results: {
    e5: {
      model: status.embedding_model,
      method: "e5",
      calibration: fit,
      metrics,
      records: [record],
    },
  },
};
const presets = [
  { id: "banking", name: "Banking", description: "Banking operations", workspace: "demo", intent_count: 800 },
  { id: "airline", name: "Airline", description: "Air travel operations", workspace: "airline", intent_count: 1 },
  { id: "insurance", name: "Insurance", description: "Policy and claim operations", workspace: "insurance", intent_count: 1 },
  { id: "ecommerce", name: "E-commerce", description: "Shopping operations", workspace: "ecommerce", intent_count: 1 },
];
const airlineIntent = { ...catalog[0], intent_id: "airline.booking.create", name: "Book a flight", domain: "Bookings",
  description: "Create an airline reservation.", examples: ["I want to book a flight."], confusable_with: [], required_slots: [],
  slot_questions: {}, workflow_id: "workflow.airline.booking.create", channels: ["chat", "voice"] };
let root, requests, streams, latestEvaluation, registeredModels, latestCatalog, workspaceCatalogs;
class EventStream {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.closed = false;
    streams.push(this);
  }
  addEventListener(type, listener) {
    this.listeners[type] = listener;
  }
  close() {
    this.closed = true;
  }
  emit(type, value) {
    this.listeners[type]?.({ data: JSON.stringify(value) });
  }
}
globalThis.EventSource = EventStream;
const delay = (duration = 20) =>
  new Promise((resolve) => setTimeout(resolve, duration));
const flush = () => act(() => delay());
const button = (text) =>
  [...document.querySelectorAll("button")].find(
    (element) => element.textContent.trim() === text,
  );
const select = (text) =>
  [...document.querySelectorAll("label")]
    .find((element) => element.textContent.trim().startsWith(text))
    ?.querySelector("select");
async function click(element) {
  assert.ok(element, "button exists");
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await delay();
  });
}
async function change(element, value) {
  assert.ok(element, "select exists");
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
    await delay();
  });
}
async function mount() {
  root = createRoot(document.getElementById("root"));
  await act(async () => {
    root.render(createElement(LanguageProvider, null, createElement(App)));
    await delay();
  });
}
beforeEach(async () => {
  localStorage.clear();
  requests = [];
  streams = [];
  latestEvaluation = evaluation;
  registeredModels = [];
  latestCatalog = { version: status.catalog_version, intents: catalog };
  workspaceCatalogs = new Map(presets.slice(1).map(p => [p.workspace, { version: p.workspace + "-version", intents: [airlineIntent] }]));
  globalThis.fetch = async (input, init = {}) => {
    const parsedUrl = new URL(input, "http://localhost");
    const path = parsedUrl.pathname;
    const workspace = parsedUrl.searchParams.get("workspace") || "demo";
    const body = init.body ? JSON.parse(init.body) : undefined;
    requests.push({ path, workspace, method: init.method || "GET", body });
    let data;
    if (path === "/v1/catalog/presets") data = presets;
    else if (path === "/v1/status") data = workspace === "demo" ? status : { ...status, workspace,
      catalog_version: workspaceCatalogs.get(workspace).version, intent_count: workspaceCatalogs.get(workspace).intents.length, catalog_min_size: 1 };

    else if (path === "/v1/catalog")
      data = workspace === "demo" ? latestCatalog : workspaceCatalogs.get(workspace);
    else if (path === "/v1/catalog/intents" && init.method === "POST") {
      const current = workspace === "demo" ? latestCatalog : workspaceCatalogs.get(workspace);
      const updated = { version: workspace + "-custom-version", intents: [...current.intents, body.intent] };
      if (workspace === "demo") latestCatalog = updated; else workspaceCatalogs.set(workspace, updated);
      data = { version: updated.version, intent_count: updated.intents.length, intent: body.intent };
    }
    else if (path === "/v1/catalog/audit") data = { catalog_version: latestCatalog.version, tested_intent_count: 26, untested_intent_count: 774,
      seed_migrations: [{ id: "demo-taxonomy-v2", applicable: true, updated_intents: ["transfer.status"], updated_cases: ["seed-011"],
        preserved_intents: [], preserved_cases: ["seed-007"], case_changes: [{ case_id: "seed-011", previous_intent_id: "transfer.status", intent_id: "bank.transfer.eft.status" }] }],
      intent_count: 800, case_count: 29, counts: { demo_scope_overlap: 1 }, issues: [{ id: "eft-overlap", kind: "demo_scope_overlap",
        intent_ids: ["transfer.status", "bank.transfer.eft.status"], documented_rule: false,
        cases: [{ case_id: "seed-011", question: "Yaptığım EFT alıcının hesabına geçmedi", split: "test", expected_intent_id: "transfer.status" }] }] };
    else if (path.startsWith("/v1/catalog/intents/")) {
      latestCatalog = { version: "edited-version", intents: latestCatalog.intents.map(i => i.intent_id === body.intent.intent_id ? body.intent : i) };
      data = { version: latestCatalog.version, intent: body.intent };
    }
    else if (path === "/v1/models")
      data = {
        ...status.models,
        llm: [
          ...status.models.llm,
          ...registeredModels
            .filter((m) => m.kind === "llm")
            .map((m) => ({
              ...m,
              registered: true,
              available: m.enabled,
              settings: {},
            })),
        ],
        embedding: [
          ...status.models.embedding,
          ...registeredModels
            .filter((m) => m.kind === "embedding")
            .map((m) => ({
              ...m,
              registered: true,
              available: m.enabled,
              settings: {},
            })),
        ],
        reranker: [...status.models.reranker, ...registeredModels.filter(m => m.kind === "reranker").map(m => ({ ...m, available: m.enabled, settings: {} }))],
      };
    else if (path === "/v1/model-registry") {
      if (init.method === "POST") {
        const item = {
          ...body,
          id: "model_" + registeredModels.length,
          available: true,
        };
        registeredModels.push(item);
        data = item;
      } else data = { items: registeredModels };
    } else if (path.startsWith("/v1/model-registry/")) {
      if (path.endsWith("/check")) data = { ok: true, elapsed_ms: 12 };
      else {
        const id = path.split("/").pop();
        data = { ...body, id, available: body.enabled };
        registeredModels = registeredModels.map((m) =>
          m.id === id ? data : m,
        );
      }
    } else if (path === "/v1/model-discovery/openrouter") {
      const kind = new URL(input, "http://localhost").searchParams.get("kind");
      data = {
        total: 1,
        fetched_at: 1000,
        items: [
          {
            kind,
            name: kind === "llm" ? "OpenAI GPT-OSS" : "Qwen Embedding",
            model:
              kind === "llm" ? "openai/gpt-oss-20b" : "qwen/qwen3-embedding-8b",
            description: "Test discovery model",
            weights_url: "https://huggingface.co/openai/gpt-oss-20b",
            supported_parameters: ["structured_outputs", "reasoning"],
            response_format: "json_schema",
            reasoning: "auto",
            send_temperature: false,
          },
        ],
      };
    } else if (path === "/v1/sessions")
      data = { session_id: "session-1", revision: 0 };
    else if (path === "/v1/route") data = { request_id: "route-1" };
    else if (path === "/v1/calibrations")
      data = init.method === "POST" ? { id: "cal-1" } : calibrationData;
    else if (path === "/v1/requests/cal-1")
      data = {
        id: "cal-1",
        status: "completed",
        progress: 72,
        total: 72,
        results: {
          default: {
            status: "completed",
            model: status.embedding_model,
            calibration: fit,
          },
        },
      };
    else if (path === "/v1/evaluations") {
      if (init.method === "POST")
        latestEvaluation = {
          ...evaluation,
          results: {
            e5: {
              ...evaluation.results.e5,
              calibration:
                body.semantic_rejection === "off"
                  ? { mode: "off", calibrated: false }
                  : fit,
            },
          },
        };
      data = init.method === "POST" ? { id: evaluation.id } : [];
    } else if (path === "/v1/evaluations/eval-1") data = latestEvaluation;
    else if (path === "/v1/cases") data = { items: [], total: 0 };
    else throw new Error("Unexpected test request: " + path);
    return { ok: true, json: async () => data };
  };
  await mount();
});
afterEach(async () => {
  await act(() => root.unmount());
});
after(() => {
  dom.window.close();
  rmSync(temporary, { recursive: true, force: true });
});

test("English interface preserves an in-flight semantic request, its settings and source utterance", async () => {
  await change(document.getElementById("method"), "e5");
  await change(select("Embedding model"), "bge-m3");
  await click(button(question));
  const request = requests.find((r) => r.path === "/v1/route");
  assert.equal(request.body.user_text, question);
  assert.equal(request.body.embedding_id, "bge-m3");
  assert.equal(request.body.semantic_rejection, "calibrated");
  assert.equal(streams.length, 1);
  assert.equal(document.documentElement.lang, "en");
  assert.equal(document.title, "IntentBench · Decision Model Benchmarks");
  assert.equal(document.getElementById("method").value, "e5");
  assert.equal(select("Embedding model").value, "bge-m3");
  assert.equal(streams[0].closed, false);
  assert.equal(requests.filter((r) => r.path === "/v1/route").length, 1);
  assert.match(document.body.textContent, /From request to the right workflow/);
  assert.match(document.body.textContent, /Banking/);
  assert.ok(document.body.textContent.includes(question));
  await act(async () =>
    streams[0].emit("result", {
      status: "completed",
      result: {
        ...record,
        intent_name: "Kart limiti",
        workflow_id: null,
        slots: {},
        missing_slots: [],
        clarification_options: [],
        timings_ms: { total: 500 },
        model: status.embedding_model,
        method: "e5",
        catalog_version: "catalog-version",
        calibration: fit,
        candidates: [],
        message: "Yeni limitiniz ne olsun?",
      },
    }),
  );
  assert.match(document.body.textContent, /Calibrated · threshold 0.5000/);
  assert.match(document.body.textContent, /Routed/);
  assert.ok(document.body.textContent.includes("Yeni limitiniz ne olsun?"));
  // Persisted language is restored on a fresh application mount.
  await act(() => root.unmount());
  await mount();
  assert.equal(document.querySelector(".language-select"), null);
});

test("English calibration and experiments submit stable API values and show metric definitions", async () => {
  await click(button("Calibration"));
  assert.match(
    document.body.textContent,
    /48 in scope · 24 out of scope · 72 calibration cases/,
  );
  await click(button("Fit thresholds"));
  assert.deepEqual(
    requests.find((r) => r.method === "POST" && r.path === "/v1/calibrations")
      .body,
    {
      embedding_ids: ["default"],
      source: "seed",
      max_oos_false_accept_rate: 0.05,
    },
  );
  assert.match(document.body.textContent, /Calibration saved/);
  await click(button("Experiments"));
  const semantic = [...document.querySelectorAll(".method-checks label")]
    .find((label) => label.textContent.includes("Semantic search"))
    .querySelector("input");
  await click(semantic);
  await change(select("Semantic OOS rejection"), "off");
  await click(button("Run evaluation"));
  const body = requests.find(
    (r) => r.method === "POST" && r.path === "/v1/evaluations",
  ).body;
  assert.deepEqual(body.methods, ["lexical", "e5"]);
  assert.equal(body.semantic_rejection, "off");
  assert.equal(body.split, "test");
  assert.match(document.body.textContent, /Overall decision accuracy/);
  assert.match(document.body.textContent, /OOS rejection off/);
  await change(select("Semantic OOS rejection"), "calibrated");
  await click(button("Run evaluation"));
  assert.match(
    document.body.textContent,
    /In-scope false rejection on test data/,
  );
  assert.match(
    document.querySelector('abbr[title*="95th percentile"]').title,
    /not the total experiment runtime/,
  );
  assert.ok(document.body.textContent.includes(question));
});

test("English catalog and cases retain original content and translate navigation and filters", async () => {
  await click(button("Intent catalog"));
  assert.match(document.body.textContent, /Example|examples/);
  assert.ok(document.body.textContent.includes(catalog[0].name));
  await click(button("Cases"));
  assert.equal(
    document.querySelector('[aria-label="Filter by data split"]').value,
    "all",
  );
  await change(
    document.querySelector('[aria-label="Filter by data split"]'),
    "calibration",
  );
  await act(() => delay(240));
  assert.match(document.body.textContent, /Awaiting|No cases found/);
  assert.equal(document.documentElement.lang, "en");
  assert.match(
    document.body.textContent,
    /Real utterances, measurable results/,
  );
});

test("localized formatting and provider errors preserve values and diagnostics", () => {
  assert.equal(formatPercent("en", 0.9), "90.0%");
  assert.equal(formatPercent("tr", 0.9), "%90,0");
  assert.equal(formatDuration("en", 5500), "5.50 s");
  assert.equal(formatDuration("tr", 5500), "5,50 sn");
  assert.equal(
    translate(
      "en",
      "Embedding: API istek sınırına veya sağlayıcı kapasitesine ulaşıldı.",
    ),
    "Embedding: API rate limit or provider capacity reached.",
  );
  assert.equal(
    translate("en", "  Rejection score: {score} ", { score: 0.9 }),
    "  Rejection score: 0.9 ",
  );
  assert.equal(translate("en", question), question);
  assert.equal(
    translate("en", "3 intent adayı bulundu"),
    "3 intent candidates retrieved",
  );
});

test("catalog size controls preserve the test cohort and language while multiplying the matrix", async () => {
  await click(button("Experiments"));
  await click(button("Compare all sizes"));
  assert.equal(
    document.querySelector('[aria-label="Catalog sizes to search"]')
      .value,
    "48, 100, 200, 400, 800",
  );
  assert.match(
    document.querySelector(".matrix-summary").textContent,
    /5 combinations · 29 cases · 145 decisions/,
  );
  assert.equal(
    document.querySelector('[aria-label="Catalog sizes to search"]').value,
    "48, 100, 200, 400, 800",
  );
  assert.match(
    document.body.textContent,
    /larger catalogs contain the smaller catalogs/,
  );
  await click(button("Run evaluation"));
  const body = requests.find(
    (r) => r.method === "POST" && r.path === "/v1/evaluations",
  ).body;
  assert.deepEqual(body.catalog_sizes, [48, 100, 200, 400, 800]);
  assert.equal(body.limit, 100);
  assert.equal(body.source, "seed");
  assert.equal(body.split, "test");
  assert.equal(body.scale_calibration_source, "seed");
  assert.equal(body.scale_max_oos_false_accept_rate, 0.05);
  assert.match(document.body.textContent, /Catalog intents/);
  assert.match(document.body.textContent, /Retrieval p95/);
});

test("custom catalog sizes are validated and an empty selection cannot start a run", async () => {
  await click(button("Experiments"));
  await click(button("800"));
  assert.equal(button("Run evaluation").disabled, true);
  assert.match(document.body.textContent, /Enter valid catalog sizes/);
  const input = document.querySelector(
    '[aria-label="Catalog sizes to search"]',
  );
  async function fill(value) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await delay();
    });
  }
  await fill("48, 801");
  assert.equal(button("Run evaluation").disabled, true);
  await fill("48, 150, 400");
  assert.equal(button("Run evaluation").disabled, false);
  await click(button("Run evaluation"));
  assert.deepEqual(
    requests.find((r) => r.method === "POST" && r.path === "/v1/evaluations")
      .body.catalog_sizes,
    [48, 150, 400],
  );
});

const inputByLabel = (text) =>
  [...document.querySelectorAll("label")]
    .find((element) => element.textContent.trim().startsWith(text))
    ?.querySelector("input, textarea");
async function fillInput(input, value) {
  assert.ok(input, "input exists");
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      input.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype,
      "value",
    ).set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await delay();
  });
}

test("English model registry saves on-prem connections, tests them, and updates experiment choices", async () => {
  await click(button("Model catalog"));
  await click(button("Add on-prem model"));
  await fillInput(inputByLabel("Display name"), "Bank GPU");
  await fillInput(inputByLabel("Model ID"), "bank/qwen");
  await fillInput(inputByLabel("API base URL"), "http://bank.internal:8001/v1");
  await change(select("Authentication"), "env");
  await fillInput(inputByLabel("Key variable name"), "INTENT_MODEL_KEY_BANK");
  assert.match(document.body.textContent, /Do not paste the key here/);
  await click(button("Save model"));
  const saved = requests.find(
    (r) => r.path === "/v1/model-registry" && r.method === "POST",
  );
  assert.equal(saved.body.credential_env, "INTENT_MODEL_KEY_BANK");
  assert.equal(saved.body.base_url, "http://bank.internal:8001/v1");
  assert.equal(saved.body.thinking_parameter, "none");
  assert.equal(saved.body.api_key, undefined);
  assert.match(document.body.textContent, /Model saved/);
  await click(button("Test connection"));
  assert.match(document.body.textContent, /Test passed/);
  await click(button("Live demo"));
  assert.ok(
    [...select("Decision model (LLM)").options].some(
      (option) => option.value === "model_0",
    ),
  );
  await click(button("Experiments"));
  await click(
    [...document.querySelectorAll(".method-checks label")]
      .find((label) => label.textContent.includes("Hybrid retrieval + LLM"))
      .querySelector("input"),
  );
  await click(
    [...document.querySelectorAll(".model-option")]
      .find((option) => option.textContent.includes("Bank GPU"))
      .querySelector("input"),
  );
  await click(button("Run evaluation"));
  const experiment = requests.find(
    (r) => r.path === "/v1/evaluations" && r.method === "POST",
  );
  assert.deepEqual(experiment.body.llm_ids, ["default", "model_0"]);
  assert.equal(experiment.body.base_url, undefined);
  await click(button("Model catalog"));
  await click(button("Edit"));
  assert.equal(inputByLabel("Model ID").value, "bank/qwen");
  await fillInput(inputByLabel("Display name"), "Bank GPU updated");
  await click(button("Save model"));
  assert.equal(registeredModels[0].name, "Bank GPU updated");
  await click(button("Disable"));
  assert.equal(registeredModels[0].enabled, false);
  await click(button("Live demo"));
  assert.equal(
    [...select("Decision model (LLM)").options].find(
      (option) => option.value === "model_0",
    ).disabled,
    true,
  );
});

test("model editor offers only supported public connections and server key references", async () => {
  await click(button("Model catalog"));
  await click(button("Add TypeSafe Jev"));
  assert.deepEqual([...select("Connection type").options].map(option => option.value).sort(),
    ["onprem", "openrouter", "typesafe"]);
  assert.deepEqual([...select("Authentication").options].map(option => option.value), ["env"]);
  assert.equal(document.querySelector('input[type="password"]'), null);
});

test("TypeSafe Jev registers directly and works in live and experiment selections", async () => {
  await click(button("Model catalog"));
  assert.ok(button("Add TypeSafe Jev"));
  await click(button("Add TypeSafe Jev"));
  assert.equal(select("Connection type").value, "typesafe");
  assert.equal(select("Model type").value, "llm");
  assert.equal(inputByLabel("Display name").value, "TypeSafe Jev");
  assert.equal(inputByLabel("Model ID").value, "jev-1.13.0");
  assert.equal(inputByLabel("API base URL").value, "https://api.typesafe.ai/v1");
  assert.equal(inputByLabel("API base URL").readOnly, true);
  assert.equal(select("Authentication").value, "env");
  assert.deepEqual([...select("Authentication").options].map(option => option.value), ["env"]);
  assert.equal(inputByLabel("Key variable name").value, "INTENT_TYPESAFE_API_KEY");
  assert.equal(inputByLabel("Key variable name").checkValidity(), true);
  assert.equal(select("JSON response mode"), undefined);
  assert.equal(select("Reasoning parameter"), undefined);
  assert.equal(inputByLabel("Maximum output tokens"), undefined);
  assert.equal(inputByLabel("Send temperature: 0"), undefined);
  assert.match(document.body.textContent, /Do not paste the key here/);
  await click(button("Save model"));
  const saved = requests.find(r => r.path === "/v1/model-registry" && r.method === "POST");
  assert.equal(saved.body.connection, "typesafe");
  assert.equal(saved.body.kind, "llm");
  assert.equal(saved.body.model, "jev-1.13.0");
  assert.equal(saved.body.credential_env, "INTENT_TYPESAFE_API_KEY");
  assert.equal(saved.body.api_key, undefined);
  assert.equal(saved.body.auth, "env");
  assert.deepEqual(saved.body.provider_only, []);
  const row = [...document.querySelectorAll("tbody tr")].find(row => row.textContent.includes("TypeSafe Jev"));
  assert.ok(row);
  assert.match(row.cells[1].textContent, /^TypeSafe/);
  await click(button("Test connection"));
  assert.ok(requests.some(r => r.path === "/v1/model-registry/model_0/check" && r.method === "POST"));
  assert.match(document.body.textContent, /Test passed/);
  await click(button("Live demo"));
  await change(document.getElementById("method"), "hybrid_llm");
  await change(select("Decision model (LLM)"), "model_0");
  await click(button(question));
  const live = requests.find(r => r.path === "/v1/route");
  assert.equal(live.body.llm_id, "model_0");
  assert.equal(live.body.embedding_id, "default");
  assert.equal(live.body.credential_env, undefined);
  await click(button("Experiments"));
  await click([...document.querySelectorAll(".method-checks label")]
    .find(label => label.textContent.includes("Hybrid retrieval + LLM")).querySelector("input"));
  await click([...document.querySelectorAll(".model-option")]
    .find(option => option.textContent.includes("TypeSafe Jev")).querySelector("input"));
  await click(button("Run evaluation"));
  const experiment = requests.find(r => r.path === "/v1/evaluations" && r.method === "POST");
  assert.deepEqual(experiment.body.llm_ids, ["default", "model_0"]);
  assert.deepEqual(experiment.body.embedding_ids, ["default"]);
  assert.equal(experiment.body.api_key, undefined);
  assert.equal(experiment.body.credential_env, undefined);
  await click(button("Model catalog"));
  await click(button("Edit"));
  assert.equal(select("Connection type").value, "typesafe");
  assert.equal(inputByLabel("Key variable name").value, "INTENT_TYPESAFE_API_KEY");
  await fillInput(inputByLabel("Display name"), "Jev comparison");
  await click(button("Save model"));
  assert.equal(registeredModels[0].name, "Jev comparison");
  await click(button("Disable"));
  await click(button("Live demo"));
  assert.equal([...select("Decision model (LLM)").options].find(option => option.value === "model_0").disabled, true);
  assert.equal(requests.some(r => r.path === "/v1/model-discovery/openrouter"), false);
});

test("OpenRouter discovery imports both model kinds with advertised response settings", async () => {
  await click(button("Model catalog"));
  await click(button("Discover on OpenRouter"));
  await act(() => delay(300));
  assert.match(document.body.textContent, /OpenAI GPT-OSS/);
  await click(button("Add to catalog"));
  assert.equal(inputByLabel("Model ID").value, "openai/gpt-oss-20b");
  assert.equal(select("JSON response mode").value, "json_schema");
  await click(button("Save model"));
  assert.equal(registeredModels[0].connection, "openrouter");
  assert.equal(registeredModels[0].reasoning, "auto");
  assert.equal(registeredModels[0].send_temperature, false);
  assert.equal(registeredModels[0].supported_parameters, undefined);
  await click(button("Discover on OpenRouter"));
  await change(select("Model type"), "embedding");
  await act(() => delay(300));
  await click(button("Add to catalog"));
  await click(button("Save model"));
  assert.equal(registeredModels[1].kind, "embedding");
  await click(button("Calibration"));
  assert.ok(
    [...document.querySelectorAll(".model-option")].some((option) =>
      option.textContent.includes("Qwen Embedding"),
    ),
  );
});

test("new connections are selected when env defaults are unavailable", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    if (new URL(input, "http://localhost").pathname === "/v1/models")
      return {
        ok: true,
        json: async () => ({
          ...status.models,
          llm: [
            { ...status.models.llm[0], available: false },
            model("custom_llm", "Bank LLM", "local-llm"),
          ],
          embedding: [
            { ...status.models.embedding[0], available: false },
            model("custom_embedding", "Bank embedding", "local-embedding"),
          ],
        }),
      };
    return originalFetch(input, init);
  };
  await act(() => root.unmount());
  await mount();
  assert.equal(select("Embedding model").value, "custom_embedding");
  assert.equal(select("Decision model (LLM)").value, "custom_llm");
  await click(button("Experiments"));
  await click(
    [...document.querySelectorAll(".method-checks label")]
      .find((label) => label.textContent.includes("Hybrid retrieval + LLM"))
      .querySelector("input"),
  );
  await click(button("Run evaluation"));
  const experiment = requests.find(
    (r) => r.path === "/v1/evaluations" && r.method === "POST",
  );
  assert.deepEqual(experiment.body.embedding_ids, ["custom_embedding"]);
  assert.deepEqual(experiment.body.llm_ids, ["custom_llm"]);
});

const mapViews = [
  "Workflow map",
  "Radial map",
  "Intent galaxy",
  "Intent mosaic",
];
const mapCandidate = (id, score = 0.9) => {
  const intent = catalog.find((item) => item.intent_id === id);
  return {
    intent_id: id,
    name: intent.name,
    domain: intent.domain,
    score,
    score_type: "cosine_similarity",
    evidence: intent.description,
    semantic_score: score,
    lexical_score: null,
  };
};
const liveCandidates = [
  mapCandidate("transfer.status", 0.91),
  mapCandidate("card.limit.change", 0.89),
];
const liveStages = [
  {
    id: 1,
    stage: "context",
    label: "Conversation context ready",
    catalog_version: "catalog-version",
    at: 100,
  },
  {
    id: 2,
    stage: "retrieval",
    label: "2 intent adayı bulundu",
    catalog_version: "catalog-version",
    at: 101,
    candidates: liveCandidates,
  },
  {
    id: 3,
    stage: "selection",
    label: "Intent decision produced",
    catalog_version: "catalog-version",
    at: 102,
  },
  {
    id: 4,
    stage: "policy",
    label: "Decision and workflow mapping validated",
    catalog_version: "catalog-version",
    at: 103,
  },
];
function liveDecision(overrides = {}) {
  return {
    decision: "route",
    intent_id: "card.limit.change",
    intent_name: "Kart limit değişikliği",
    workflow_id: "workflow.card.limit.change",
    slots: {},
    missing_slots: ["new_limit"],
    pending_confirmation: false,
    simulation_complete: false,
    reason_code: "selected_from_candidates",
    candidates: liveCandidates,
    clarification_options: [],
    timings_ms: { total: 456, retrieval: 100, selection: 300, policy: 1 },
    model: status.llm_model,
    method: "hybrid_llm",
    catalog_version: "catalog-version",
    message: "Yeni kart limitiniz kaç TL olsun?",
    usage: {},
    ...overrides,
  };
}
async function deliver(result, events = liveStages) {
  await act(async () =>
    streams
      .at(-1)
      .emit("result", {
        status: result.decision === "error" ? "failed" : "completed",
        result,
        events,
      }),
  );
}
async function sendText(value) {
  await act(async () => {
    const element = document.getElementById("message");
    Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    ).set.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click(document.querySelector('button[aria-label="Send message"]'));
}

test("all live views share one request, show early candidates and select the actual decision", async () => {
  const conversation = document.querySelector(".conversation");
  await click(button("Workflow map"));
  await click(button(question));
  const stream = streams[0];
  await act(async () => {
    stream.emit("stage", liveStages[0]);
    stream.emit("stage", liveStages[1]);
    stream.emit("stage", liveStages[1]); // Duplicate SSE delivery must not duplicate nodes or events.
  });
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="candidate"]').length,
    2,
  );
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="selected"]').length,
    0,
  );
  for (const label of [...mapViews.slice(1), "Standard", mapViews[0]]) {
    await click(button(label));
    assert.equal(document.querySelector(".conversation"), conversation);
    assert.equal(stream.closed, false);
    assert.equal(document.getElementById("method").value, "hybrid_llm");
    assert.ok(document.body.textContent.includes(question));
  }
  assert.equal(requests.filter((r) => r.path === "/v1/route").length, 1);
  assert.equal(requests.filter((r) => r.path === "/v1/sessions").length, 1);
  assert.equal(streams.length, 1);
  await deliver(liveDecision()); // Rank 2 wins: the map must not assume that rank 1 is selected.
  for (const label of mapViews) {
    await click(button(label));
    const selected = document.querySelectorAll(
      '.routing-intent[data-state="selected"]',
    );
    assert.equal(selected.length, 1);
    assert.equal(
      selected[0].getAttribute("data-intent-id"),
      "card.limit.change",
    );
    assert.equal(document.querySelectorAll(".routing-map").length, 1);
    assert.match(
      document.querySelector(".routing-workflow").textContent,
      /New limit.*Pending/s,
    );
    assert.match(
      document.querySelector(".routing-statusbar").textContent,
      /456 ms/,
    );
  }
  assert.equal(requests.filter((r) => r.path === "/v1/route").length, 1);
  await click(button("Full catalog"));
  assert.equal(document.querySelectorAll(".routing-intent").length, 800);
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="selected"]').length,
    1,
  );
  assert.ok(button("Intent mosaic"));
  assert.match(
    document.querySelector(".routing-visualization").textContent,
    /Animation duration is not included in measurements/,
  );
  assert.ok(
    document
      .querySelector(".routing-workflow")
      .textContent.includes("Yeni kart limitiniz kaç TL olsun?"),
  );
  assert.equal(requests.filter((r) => r.path === "/v1/route").length, 1);
});

test("visual replay never sends a request and reset discards stale events and old playback", async () => {
  await click(button("Intent galaxy"));
  await click(button(question));
  const oldStream = streams[0];
  await deliver(liveDecision());
  const before = requests.length;
  await click(button("Replay"));
  assert.match(
    document.querySelector(".routing-statusbar").textContent,
    /REPLAY/,
  );
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="selected"]').length,
    0,
  );
  await click(button("Pause"));
  await click(button("Radial map"));
  assert.ok(button("Resume"));
  assert.equal(requests.length, before);
  assert.ok(
    document
      .querySelector(".chat-body")
      .textContent.includes("Yeni kart limitiniz kaç TL olsun?"),
  );
  await click(button("New conversation"));
  await act(async () =>
    oldStream.emit("stage", {
      id: 99,
      stage: "retrieval",
      label: "STALE",
      candidates: liveCandidates,
    }),
  );
  assert.equal(
    document.querySelectorAll(
      '.routing-intent[data-state="candidate"], .routing-intent[data-state="selected"]',
    ).length,
    0,
  );
  assert.ok(
    !document
      .querySelector(".routing-statusbar")
      .textContent.includes("REPLAY"),
  );
  assert.ok(!document.body.textContent.includes("STALE"));
  assert.equal(
    document.querySelector(".demo-view-picker [aria-pressed=true]").textContent,
    "Radial map",
  );
  await click(button(question));
  await act(async () =>
    oldStream.emit("stage", { ...liveStages[1], label: "STALE" }),
  );
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="candidate"]').length,
    0,
  );
  assert.equal(requests.filter((r) => r.path === "/v1/route").length, 2);
});

test("clarification, rejection, handoff, cancellation and errors never look like a successful route", async () => {
  for (const decision of [
    "clarify",
    "out_of_scope",
    "handoff",
    "cancel",
    "error",
  ]) {
    await click(button("New conversation"));
    await click(button("Workflow map"));
    await click(button(question));
    await deliver(
      liveDecision({
        decision,
        workflow_id: null,
        missing_slots: [],
        clarification_options:
          decision === "clarify"
            ? [
                {
                  intent_id: "card.limit.change",
                  name: "Kart limit değişikliği",
                },
              ]
            : [],
        message: "Çıkış: " + decision,
      }),
    );
    for (const label of mapViews) {
      await click(button(label));
      assert.equal(
        document.querySelectorAll('.routing-intent[data-state="selected"]')
          .length,
        0,
        decision,
      );
      assert.equal(
        document.querySelector(".routing-exit")?.getAttribute("data-outcome"),
        decision,
      );
      assert.equal(document.querySelector(".routing-workflow"), null);
    }
  }
});

test("contextual slot replies and confirmation use the active workflow without stale retrieval candidates", async () => {
  await click(button("Workflow map"));
  await click(button(question));
  await deliver(liveDecision());
  await sendText("3000");
  assert.equal(
    document.querySelectorAll(
      '.routing-intent[data-state="candidate"], .routing-intent[data-state="selected"]',
    ).length,
    0,
  );
  const contextStages = [liveStages[0], { ...liveStages[3], id: 2 }];
  await deliver(
    liveDecision({
      decision: "continue",
      candidates: [],
      slots: { new_limit: "3000" },
      missing_slots: [],
      pending_confirmation: true,
      message: "3000 TL için onaylıyor musunuz?",
    }),
    contextStages,
  );
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="candidate"]').length,
    0,
  );
  assert.equal(
    document.querySelectorAll('.routing-intent[data-state="selected"]').length,
    1,
  );
  assert.equal(
    document.querySelector('[data-confirmation="true"]') !== null,
    true,
  );
  assert.ok(
    !document
      .querySelector(".routing-trace")
      .textContent.includes("Candidate retrieval"),
  );
  await sendText("evet");
  await deliver(
    liveDecision({
      decision: "continue",
      candidates: [],
      slots: { new_limit: "3000" },
      missing_slots: [],
      simulation_complete: true,
      message: "Simülasyon tamamlandı.",
    }),
    contextStages,
  );
  assert.match(
    document.querySelector(".routing-workflow").textContent,
    /Simülasyon tamamlandı/,
  );
  assert.equal(
    document.querySelectorAll(".routing-workflow li.pending").length,
    0,
  );
  const turns = requests.filter((r) => r.path === "/v1/route");
  assert.deepEqual(
    turns.map((r) => r.body.turn_revision),
    [1, 2, 3],
  );
  assert.equal(new Set(turns.map((r) => r.body.session_id)).size, 1);
});

test("map geometry represents each catalog intent once and remains within narrow and wide viewports", () => {
  const groups = groupCatalog(catalog);
  assert.equal(
    groups.reduce((sum, g) => sum + g.intents.length, 0),
    800,
  );
  for (const width of [260, 400, 640, 1100]) {
    for (const view of ["radial", "galaxy", "mosaic"]) {
      for (const focus of [null, "Kartlar"]) {
        const layout = layoutMap(view, groups, width, 540, focus, null);
        const expected = focus
          ? catalog.filter((i) => i.domain === focus)
          : catalog;
        assert.equal(layout.marks.length, expected.length);
        assert.equal(
          new Set(layout.marks.map((m) => m.intent.intent_id)).size,
          expected.length,
        );
        for (const mark of layout.marks) {
          assert.ok(Number.isFinite(mark.x) && Number.isFinite(mark.y));
          assert.ok(
            mark.x >= 0 && mark.x + (mark.w || 0) <= width,
            `${view} x bounds`,
          );
          assert.ok(
            mark.y >= 0 && mark.y + (mark.h || 0) <= 540,
            `${view} y bounds`,
          );
          assert.ok(!mark.d?.includes("NaN"));
        }
      }
    }
  }
});

test("retrieval strategy matrix preserves the cohort and submits explicit validated budgets", async () => {
  await click(button("Experiments"));
  await click([...document.querySelectorAll(".method-checks label")].find(l => l.textContent.includes("Hybrid retrieval + LLM")).querySelector("input"));
  await click(document.querySelector(".strategy-toggle > label input"));
  await click(button("Compare the first three strategies"));
  assert.equal(document.querySelectorAll(".retrieval-profile.is-selected").length, 3);
  assert.match(document.querySelector(".matrix-summary").textContent, /4 combinations/);
  await click(button("Run evaluation"));
  const call = requests.find(r => r.path === "/v1/evaluations" && r.method === "POST");
  assert.equal(call.body.source, "seed");
  assert.deepEqual(call.body.catalog_sizes, [800]);
  assert.deepEqual(call.body.retrieval_profiles.map(p => p.id), ["hybrid", "semantic", "weighted"]);
  assert.deepEqual(call.body.retrieval_profiles.map(p => p.semantic_weight), [.5, .5, .75]);
  assert.ok(call.body.retrieval_profiles.every(p => p.candidate_k === 20 && p.reranker_id === null && p.selected === undefined));
  const row = document.querySelector(".retrieval-profile.is-selected");
  const budget = [...row.querySelectorAll("label")].find(l => l.textContent.startsWith("Candidates sent to LLM")).querySelector("input");
  await fillInput(budget, "99");
  assert.equal(button("Run evaluation").disabled, true);
  assert.match(document.body.textContent, /Check strategy selections/);
});

test("controlled reranker comparison submits identical retrieval and LLM budgets", async () => {
  await click(button("Experiments"));
  await click([...document.querySelectorAll(".method-checks label")].find(l => l.textContent.includes("Hybrid retrieval + LLM")).querySelector("input"));
  await click(document.querySelector(".strategy-toggle > label input"));
  await click(button("Compare reranker on/off"));
  assert.equal(document.querySelectorAll(".retrieval-profile.is-selected").length, 2);
  assert.match(document.body.textContent, /Only the reranker changes/);
  await click(button("Run evaluation"));
  const call = requests.find(r => r.path === "/v1/evaluations" && r.method === "POST");
  const [off, on] = call.body.retrieval_profiles;
  assert.deepEqual([off.id, on.id], ["semantic-shortlist", "semantic-reranked"]);
  assert.equal(off.reranker_id, null);
  assert.equal(on.reranker_id, "default");
  const budgets = ({ id, name, reranker_id, ...rest }) => rest;
  assert.deepEqual(budgets(off), budgets(on));
  assert.deepEqual([off.source, off.source_k, off.pool_k, off.candidate_k], ["semantic", 40, 20, 8]);
});

test("catalog review exposes versioned demo relabeling and preserved edits in English", async () => {
  await click(button("Intent catalog"));
  await click(button("Audit catalog"));
  assert.match(document.body.textContent, /Demo taxonomy version: demo-taxonomy-v2/);
  assert.match(document.body.textContent, /Preserved user edits: 0 intents, 1 cases/);
  assert.match(document.body.textContent, /different label versions are not directly comparable/);
  assert.match(document.body.textContent, /seed-011: transfer.status → bank.transfer.eft.status/);
});

test("custom TEI reranker can be registered and selected in live demo without exposing a key", async () => {
  await click(button("Model catalog"));
  await click(button("Add reranker"));
  assert.equal(select("Model type").value, "reranker");
  assert.equal([...select("Connection type").options].find(o => o.value === "openrouter").disabled, true);
  await fillInput(inputByLabel("API base URL"), "http://rank.internal:8080");
  await change(select("Reranker protocol"), "tei");
  await click(button("Save model"));
  const saved = requests.find(r => r.path === "/v1/model-registry" && r.method === "POST");
  assert.equal(saved.body.kind, "reranker");
  assert.equal(saved.body.reranker_protocol, "tei");
  assert.equal(saved.body.auth, "none");
  assert.equal(saved.body.api_key, undefined);
  await click(button("Live demo"));
  await change(select("Retrieval strategy"), "reranked");
  await change(select("Reranker"), "model_0");
  await click(button(question));
  const route = requests.find(r => r.path === "/v1/route");
  assert.equal(route.body.retrieval_profile.reranker_id, "model_0");
  assert.equal(route.body.retrieval_profile.pool_k, 40);
  assert.equal(route.body.retrieval_profile.candidate_k, 8);
  assert.equal(route.body.retrieval_profile.base_url, undefined);
});

test("stage diagnostics distinguish a retrieval miss from a selection error in English", async () => {
  const baseFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const response = await baseFetch(url, init);
    if (new URL(url, "http://localhost").pathname !== "/v1/evaluations/eval-1") return response;
    return { ok: true, json: async () => ({ ...evaluation, results: { hybrid: { ...evaluation.results.e5,
      method: "hybrid_llm", retrieval_profile: { name: "Semantic candidates + LLM", pool_k: 20, candidate_k: 20 },
      metrics: { ...metrics, stage_quality: { protocol: "routing-stage-quality-v1", routing_total: 3, retrieval_completed: 3, context_bypasses: 0, retrieval_incomplete: 0,
        stages: { semantic: { hits: 2, total: 3, recall: 2/3 }, lexical: { hits: 0, total: 0, recall: null }, pool: { hits: 2, total: 3, recall: 2/3 }, final: { hits: 2, total: 3, recall: 2/3 } },
        candidate_conditioned_accuracy: .5, candidate_conditioned_correct: 1, candidate_conditioned_total: 2,
        categories: { correct: 1, retrieval_miss: 1, selection_error: 1 }, technical_stages: {} } },
      records: [{ ...record, correct: false, analysis: { category: "selection_error", expected_ranks: { semantic: 2, lexical: null, pool: 2, final: 2 } },
        candidates: [{ intent_id: "card.limit.change", name: "Kart limit değişikliği", score: .8, score_type: "cosine_similarity" }] }] } } }) };
  };
  await click(button("Experiments"));
  await click(button("Run evaluation"));
  assert.match(document.querySelector(".retrieval-diagnostics").textContent, /Where is accuracy lost/);
  assert.match(document.querySelector(".retrieval-diagnostics").textContent, /Retrieval miss/);
  assert.match(document.querySelector(".retrieval-diagnostics").textContent, /Wrong intent selection/);
  assert.match(document.querySelector(".quality-cards").textContent, /50\.0%/);
  assert.match(document.querySelector(".candidate-trace").textContent, /Show candidate trace/);
  assert.match(document.querySelector(".candidate-trace").textContent, /card.limit.change/);
});

test("catalog audit edits are versioned and preserve original labels and source language", async () => {
  await click(button("Intent catalog"));
  // Another browser edits the server catalog after this page has loaded its props.
  latestCatalog = { version: "other-session-version", intents: catalog.map(i => i.intent_id === "transfer.status"
    ? { ...i, description: "Diğer oturumda güncellenmiş açıklama." } : i) };
  await click(button("Audit catalog"));
  assert.match(document.querySelector(".catalog-quality").textContent, /26 \/ 800/);
  assert.match(document.querySelector(".catalog-quality").textContent, /Yaptığım EFT alıcının hesabına geçmedi/);
  await click(button("transfer.status"));
  assert.ok([...document.querySelectorAll("textarea")].some(el => el.value === "Diğer oturumda güncellenmiş açıklama."));
  const rule = [...document.querySelectorAll("label")].find(l => l.textContent.startsWith("Disambiguation rule")).querySelector("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value").set.call(rule, "Ürün belirtilmediğinde bu genel akışı kullan.");
    rule.dispatchEvent(new Event("input", { bubbles: true }));
    await delay();
  });
  await click(button("Save as a new version"));
  const edit = requests.find(r => r.path === "/v1/catalog/intents/transfer.status" && r.method === "PATCH");
  assert.equal(edit.body.expected_version, "other-session-version");
  assert.equal(edit.body.intent.description, "Diğer oturumda güncellenmiş açıklama.");
  assert.equal(edit.body.intent.selection_rule, "Ürün belirtilmediğinde bu genel akışı kullan.");
  assert.equal(edit.body.intent.workflow_id, catalog.find(i => i.intent_id === "transfer.status").workflow_id);
  assert.ok(!requests.some(r => r.path.startsWith("/v1/cases/") && r.method === "PATCH"));
  assert.match(document.body.textContent, /New catalog version saved/);
});

test("interface is English even when a previous installation stored Turkish", async () => {
  await act(() => root.unmount());
  localStorage.setItem("intent-studio-language", "tr");
  await mount();
  assert.equal(document.documentElement.lang, "en");
  assert.equal(document.title, "IntentBench · Decision Model Benchmarks");
  assert.ok(button("Intent catalog"));
  assert.equal(document.querySelector(".language-select"), null);
  assert.match(document.body.textContent, /Decision model benchmarks/);
});

test("sector selection isolates catalog, requests and streams and restores the saved workspace", async () => {
  await click(button(question));
  const oldStream = streams[0];
  assert.match(oldStream.url, /workspace=demo/);
  await change(document.querySelector('[aria-label="Sector workspace"]'), "airline");
  assert.equal(oldStream.closed, true);
  assert.ok(button("I want to book a flight."));
  assert.equal(button(question), undefined);
  await click(button("I want to book a flight."));
  assert.equal(requests.filter(r => r.path === "/v1/route").at(-1).workspace, "airline");
  assert.equal(requests.filter(r => r.path === "/v1/sessions").at(-1).workspace, "airline");
  assert.match(streams[1].url, /workspace=airline/);
  await act(async () => oldStream.emit("result", { status: "completed", result: { ...record, message: "STALE BANKING RESULT" } }));
  assert.doesNotMatch(document.body.textContent, /STALE BANKING RESULT/);
  await act(() => root.unmount());
  await mount();
  assert.equal(document.querySelector('[aria-label="Sector workspace"]').value, "airline");
  assert.ok(button("I want to book a flight."));
});

test("custom intents append to the selected sector and survive switching without translating input", async () => {
  await change(document.querySelector('[aria-label="Sector workspace"]'), "airline");
  await click(button("Intent catalog"));
  await click(button("Add intent"));
  await fillInput(inputByLabel("Intent ID"), "airline.lounge.reserve");
  await fillInput(inputByLabel("Intent name"), "Reserve a lounge");
  await fillInput(inputByLabel("Domain"), "Airport services");
  await fillInput(inputByLabel("Workflow ID"), "workflow.airline.lounge.reserve");
  await fillInput(inputByLabel("Description"), "Reserve airport lounge access.");
  await fillInput(inputByLabel("Examples"), "Lounge erişimi ayırtmak istiyorum.");
  await click(button("Save intent"));
  const created = requests.find(r => r.path === "/v1/catalog/intents" && r.method === "POST");
  assert.equal(created.workspace, "airline");
  assert.equal(created.body.expected_version, "airline-version");
  assert.deepEqual(created.body.intent.examples, ["Lounge erişimi ayırtmak istiyorum."]);
  assert.deepEqual(created.body.intent.channels, ["chat", "voice"]);
  assert.match(document.body.textContent, /Reserve a lounge/);
  assert.match(document.body.textContent, /Book a flight/);
  await change(document.querySelector('[aria-label="Sector workspace"]'), "demo");
  await click(button("Intent catalog"));
  assert.doesNotMatch(document.body.textContent, /Reserve a lounge/);
  await change(document.querySelector('[aria-label="Sector workspace"]'), "airline");
  await click(button("Intent catalog"));
  assert.match(document.body.textContent, /Reserve a lounge/);
});

test("aborting a fallback poll prevents late stage callbacks and retains the original workspace", async () => {
  const originalFetch = globalThis.fetch;
  let release;
  let pollSignal;
  let pollWorkspace;
  globalThis.fetch = async (input, init) => {
    if (new URL(input, "http://localhost").pathname === "/v1/requests/pending-route") {
      pollSignal = init.signal;
      pollWorkspace = new URL(input, "http://localhost").searchParams.get("workspace");
      return new Promise(resolve => { release = resolve; });
    }
    return originalFetch(input, init);
  };
  const controller = new AbortController();
  const delivered = [];
  const client = createWorkspaceClient("airline");
  const waiting = client.waitForRoute("pending-route", stage => delivered.push(stage), controller.signal);
  const rejected = assert.rejects(waiting, error => error.name === "AbortError");
  streams.at(-1).onerror();
  await act(() => delay(800));
  assert.equal(pollWorkspace, "airline");
  controller.abort();
  await rejected;
  release({ ok: true, json: async () => ({ status: "completed", events: [{ id: 99, stage: "selection" }] }) });
  await flush();
  assert.deepEqual(delivered, []);
  assert.equal(pollSignal, controller.signal);
});

test("a stale custom-intent form retains edits and can refresh its version before retrying", async () => {
  await change(document.querySelector('[aria-label="Sector workspace"]'), "airline");
  await click(button("Intent catalog"));
  await click(button("Add intent"));
  await fillInput(inputByLabel("Intent ID"), "airline.pet.travel");
  await fillInput(inputByLabel("Intent name"), "Travel with a pet");
  await fillInput(inputByLabel("Domain"), "Travel preparation");
  await fillInput(inputByLabel("Workflow ID"), "workflow.airline.pet.travel");
  await fillInput(inputByLabel("Description"), "Arrange travel with a pet.");
  await fillInput(inputByLabel("Examples"), "I want to fly with my dog.");
  const originalFetch = globalThis.fetch;
  let stale = true;
  globalThis.fetch = async (input, init) => {
    if (new URL(input, "http://localhost").pathname === "/v1/catalog/intents" && stale) {
      stale = false;
      workspaceCatalogs.set("airline", { version: "changed-elsewhere", intents: [airlineIntent] });
      return { ok: false, json: async () => ({ detail: "The catalog changed. Refresh the catalog before retrying." }) };
    }
    return originalFetch(input, init);
  };
  await click(button("Save intent"));
  assert.match(document.querySelector('[role="alert"]').textContent, /catalog changed/);
  assert.equal(inputByLabel("Intent ID").value, "airline.pet.travel");
  await click(button("Refresh catalog"));
  await click(button("Save intent"));
  assert.equal(requests.find(r => r.path === "/v1/catalog/intents").body.expected_version, "changed-elsewhere");
  assert.match(document.body.textContent, /Travel with a pet/);
});

test("late catalog loading cannot replace the newly selected workspace", async () => {
  const originalFetch = globalThis.fetch;
  let release;
  globalThis.fetch = async (input, init) => {
    const parsed = new URL(input, "http://localhost");
    if (parsed.pathname === "/v1/catalog" && parsed.searchParams.get("workspace") === "demo") {
      return new Promise(resolve => { release = resolve; });
    }
    return originalFetch(input, init);
  };
  await act(() => root.unmount());
  await mount();
  await change(document.querySelector('[aria-label="Sector workspace"]'), "airline");
  assert.ok(button("I want to book a flight."));
  release({ ok: true, json: async () => latestCatalog });
  await flush();
  assert.equal(document.querySelector('[aria-label="Sector workspace"]').value, "airline");
  assert.ok(button("I want to book a flight."));
  assert.equal(button(question), undefined);
});

test("model setup opens read-only with explicit shared-key instructions and selected-model readiness", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    if (new URL(input, "http://localhost").pathname === "/v1/setup") return { ok: true, json: async () => ({
      workspace: "demo", catalog_version: "catalog-version", shared_openrouter_key_present: false,
      embedding: { id: "default", model: "embedding", configured: true },
      llm: { id: "default", model: "llm", configured: true },
      index: { state: "missing", representation: "combined" }, calibration: { state: "missing_or_stale" },
    }) };
    return originalFetch(input, init);
  };
  const postsBefore = requests.filter(r => r.method === "POST").length;
  await click(button("Model connections"));
  const dialog = document.querySelector('section[aria-label="Model connections"]');
  assert.match(dialog.textContent, /Model setup/);
  assert.match(dialog.textContent, /INTENT_OPENROUTER_API_KEY/);
  assert.match(dialog.textContent, /recreate the container/);
  assert.match(dialog.textContent, /Not present/);
  assert.match(dialog.textContent, /Not tested in this session/);
  assert.match(dialog.textContent, /Index missing/);
  assert.match(dialog.textContent, /Missing or stale/);
  assert.match(dialog.textContent, /Lexical and hybrid routing do not require/);
  assert.equal(requests.filter(r => r.method === "POST").length, postsBefore);
  assert.equal(button("Test embedding connection").disabled, false);
  assert.ok(button("Open experiments"));
});

test("refreshing model catalog connections clears previous probe evidence", async () => {
  await click(button("Model catalog"));
  await click(button("Add TypeSafe Jev"));
  await click(button("Save model"));
  await click(button("Test connection"));
  assert.match(document.body.textContent, /Test passed/);
  await click(button("Refresh connections"));
  assert.doesNotMatch(document.body.textContent, /Test passed/);
});

function setupBody(url) {
  return {
    workspace: url.searchParams.get("workspace"), catalog_version: "catalog-version", shared_openrouter_key_present: true,
    embedding: { id: url.searchParams.get("embedding_id"), model: "embedding", configured: true },
    llm: { id: url.searchParams.get("llm_id"), model: "llm", configured: true },
    index: { state: "present", representation: "combined" }, calibration: { state: "current" },
  };
}

test("setup tests only on request and discards pending evidence after selection or refresh", async () => {
  const originalFetch = globalThis.fetch;
  const probes = [];
  let release;
  let defer = false;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input, "http://localhost");
    if (url.pathname === "/v1/setup") return { ok: true, json: async () => setupBody(url) };
    if (url.pathname.startsWith("/v1/models/") && url.pathname.endsWith("/check")) {
      probes.push({ path: url.pathname, workspace: url.searchParams.get("workspace"), method: init.method });
      const result = { ok: true, json: async () => ({ ok: true, elapsed_ms: 12, accuracy_benchmark: false, model: "selected" }) };
      return defer ? new Promise(resolve => { release = () => resolve(result); }) : result;
    }
    return originalFetch(input, init);
  };
  await click(button("Model connections"));
  assert.deepEqual(probes, []);
  await click(button("Test embedding connection"));
  assert.match(document.querySelector(".setup-content").textContent, /Test passed.*current session only/);
  assert.deepEqual(probes, [{ path: "/v1/models/embedding/default/check", workspace: "demo", method: "POST" }]);
  await click(button("Refresh connections"));
  assert.doesNotMatch(document.querySelector(".setup-content").textContent, /Test passed/);
  assert.equal(probes.length, 1);
  defer = true;
  await click(button("Test embedding connection"));
  await change(select("Setup embedding model"), "bge-m3");
  await act(async () => { release(); await delay(); });
  assert.doesNotMatch(document.querySelector(".setup-content").textContent, /Test passed/);
  await click(button("Test embedding connection"));
  await click(button("Refresh connections"));
  await act(async () => { release(); await delay(); });
  assert.doesNotMatch(document.querySelector(".setup-content").textContent, /Test passed/);
  await click(button("Open calibration"));
  assert.equal(document.querySelector(".setup-content"), null);
  assert.ok(button("Fit thresholds"));
});

test("setup retries read-only failures and selects configured registrations when defaults are unavailable", async () => {
  const originalFetch = globalThis.fetch;
  const reads = [];
  let fail = true;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input, "http://localhost");
    if (url.pathname === "/v1/models") return { ok: true, json: async () => ({ ...status.models,
      embedding: [{ ...status.models.embedding[0], available: false }, model("model_embedding", "Private embedding", "private-embedding")],
      llm: [{ ...status.models.llm[0], available: false }, model("model_llm", "Private LLM", "private-llm")],
    }) };
    if (url.pathname === "/v1/setup") {
      reads.push(url);
      return fail ? { ok: false, json: async () => ({ detail: "Readiness temporarily unavailable" }) }
        : { ok: true, json: async () => setupBody(url) };
    }
    return originalFetch(input, init);
  };
  await act(() => root.unmount());
  await mount();
  await change(document.querySelector('[aria-label="Sector workspace"]'), "airline");
  await click(button("Model connections"));
  assert.match(document.querySelector('.setup-content [role="alert"]').textContent, /Readiness temporarily unavailable/);
  assert.equal(button("Test embedding connection").disabled, true);
  assert.equal(select("Setup embedding model").value, "model_embedding");
  assert.equal(select("Setup LLM model").value, "model_llm");
  fail = false;
  await click(button("Retry readiness"));
  assert.equal(document.querySelector('.setup-content [role="alert"]'), null);
  assert.equal(button("Test embedding connection").disabled, false);
  assert.ok(reads.every(url => url.searchParams.get("workspace") === "airline"));
  assert.ok(reads.every(url => url.searchParams.get("embedding_id") === "model_embedding"));
  assert.ok(!requests.some(request => request.method === "POST"));
});

test("a late model-catalog probe cannot restore success after setup refreshes connections", async () => {
  await click(button("Model catalog"));
  await click(button("Add TypeSafe Jev"));
  await click(button("Save model"));
  const originalFetch = globalThis.fetch;
  let release;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input, "http://localhost");
    if (url.pathname === "/v1/setup") return { ok: true, json: async () => setupBody(url) };
    if (url.pathname === "/v1/model-registry/model_0/check") return new Promise(resolve => {
      release = () => resolve({ ok: true, json: async () => ({ ok: true, elapsed_ms: 12 }) });
    });
    return originalFetch(input, init);
  };
  await click(button("Test connection"));
  await click(button("Model connections"));
  await click([...document.querySelectorAll('.setup-content button')].find(button => button.textContent === "Refresh connections"));
  await click(document.querySelector('button[aria-label="Close"]'));
  await act(async () => { release(); await delay(); });
  assert.doesNotMatch(document.body.textContent, /Test passed/);
  assert.equal(button("Test connection").disabled, false);
});
