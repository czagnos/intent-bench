import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import ts from "typescript";

const directory = dirname(dirname(fileURLToPath(import.meta.url)));
const temporary = mkdtempSync(join(directory, ".ui-test-"));
const bundle = join(temporary, "experiment-components.cjs");
await build({
  stdin: {
    contents: 'export * from "./src/components/ExecutionControls"; export * from "./src/components/ExecutionProgress"; export * from "./src/components/RepeatSummary";',
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
const dom = new JSDOM('<!doctype html><html lang="en"><body><div id="root"></div></body></html>', {
  url: "http://localhost",
});
for (const key of ["window", "document", "HTMLElement", "HTMLInputElement", "Event", "MouseEvent"])
  globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createElement, act } = await import("react");
const { createRoot } = await import("react-dom/client");
const require = createRequire(import.meta.url);
const { ExecutionControls, validateExecutionControls, ExecutionProgress, RepeatSummary } = require(bundle);
let root;
beforeEach(() => { root = createRoot(document.getElementById("root")); });
afterEach(async () => { await act(() => root.unmount()); });
after(() => { dom.window.close(); rmSync(temporary, { recursive: true, force: true }); });

const emptyControls = {
  repetitions: "1", maxProviderRequests: "", maxDurationSeconds: "", maxReportedCostUsd: "",
};
const input = (label) => document.querySelector(`input[aria-label="${label}"]`);
async function render(Component, props) {
  await act(() => root.render(createElement(Component, props)));
}
async function enter(element, value) {
  assert.ok(element, "Input is rendered");
  await act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

test("execution controls emit controlled values, preview repetitions and omit empty limits", async () => {
  let value = { ...emptyControls };
  const onChange = (next) => { value = next; };
  await render(ExecutionControls, { value, onChange, baseExecutionCount: 24 });
  assert.ok(input("Repetitions"), "Repetitions input is rendered");
  assert.equal(input("Repetitions").value, "1");
  assert.match(document.body.textContent, /24 × 1 = 24 planned case executions/);
  assert.deepEqual(validateExecutionControls(value, 24), {
    valid: true, payload: { repetitions: 1 }, plannedCount: 24,
  });
  await enter(input("Repetitions"), "3");
  await render(ExecutionControls, { value, onChange, baseExecutionCount: 24 });
  assert.match(document.body.textContent, /24 × 3 = 72 planned case executions/);
  await enter(input("Maximum provider requests"), "0");
  await render(ExecutionControls, { value, onChange, baseExecutionCount: 24 });
  await enter(input("Maximum duration in seconds"), "1.5");
  await render(ExecutionControls, { value, onChange, baseExecutionCount: 24 });
  await enter(input("Reported USD threshold"), "0.025");
  await render(ExecutionControls, { value, onChange, baseExecutionCount: 24 });
  assert.deepEqual(validateExecutionControls(value, 24), {
    valid: true,
    payload: { repetitions: 3, execution_limits: {
      max_provider_requests: 0, max_duration_seconds: 1.5, max_reported_cost_usd: 0.025,
    } },
    plannedCount: 72,
  });
  assert.match(document.body.textContent, /USD is a soft stop threshold/);
  assert.match(document.body.textContent, /Unknown cost stops/);
  assert.match(document.body.textContent, /In-flight HTTP or local work may finish/);
});

test("invalid limits and plans have accessible errors and never produce an execution payload", async () => {
  const invalidFields = [
    ["repetitions", "Repetitions", ["", "0", "6", "1.5", "1e0", "true"]],
    ["maxProviderRequests", "Maximum provider requests", ["-1", "100001", "0.5", "Infinity", "false"]],
    ["maxDurationSeconds", "Maximum duration in seconds", ["0", "86401", "NaN", "Infinity", "1e309", "0x20"]],
    ["maxReportedCostUsd", "Reported USD threshold", ["0", "-1", "10000.1", "NaN", "Infinity", "1e309"]],
  ];
  for (const [key, label, values] of invalidFields) {
    for (const invalid of values) {
      const value = { ...emptyControls, [key]: invalid };
      await render(ExecutionControls, { value, baseExecutionCount: 10, onChange: () => {} });
      assert.equal(input(label).getAttribute("aria-invalid"), "true", `${label}: ${invalid}`);
      const result = validateExecutionControls(value, 10);
      assert.equal(result.valid, false);
      assert.ok(result.errors[key]);
      assert.equal("payload" in result, false);
      assert.ok(document.querySelector('[role="alert"]'));
    }
  }
  await render(ExecutionControls, {
    value: { ...emptyControls, repetitions: "5" }, baseExecutionCount: 25000, onChange: () => {},
  });
  assert.match(document.body.textContent, /125,000 planned case executions/);
  assert.match(document.querySelector('[role="alert"]').textContent, /100,000/);
  assert.equal(validateExecutionControls({ ...emptyControls, repetitions: "5" }, 25000).valid, false);
  for (const base of [null, -1, 1.5, Infinity]) {
    await render(ExecutionControls, { value: emptyControls, baseExecutionCount: base, onChange: () => {} });
    assert.match(document.body.textContent, /Planned case executions unavailable/);
    assert.equal(validateExecutionControls(emptyControls, base).valid, false);
  }
  const boundary = {
    repetitions: "5", maxProviderRequests: "100000", maxDurationSeconds: "86400", maxReportedCostUsd: "10000",
  };
  assert.deepEqual(validateExecutionControls(boundary, 20000), {
    valid: true, plannedCount: 100000,
    payload: { repetitions: 5, execution_limits: {
      max_provider_requests: 100000, max_duration_seconds: 86400, max_reported_cost_usd: 10000,
    } },
  });
  assert.deepEqual(validateExecutionControls({ ...emptyControls, maxProviderRequests: "  " }, 0), {
    valid: true, plannedCount: 0, payload: { repetitions: 1 },
  });
  await render(ExecutionControls, { value: boundary, baseExecutionCount: 20000, disabled: true, onChange: () => {} });
  assert.equal(input("Repetitions").matches(":disabled"), true);
});

const evaluation = {
  id: "synthetic-evaluation", status: "running", created: 1, selected_count: 4,
  unreviewed_excluded: 0, progress: 3, total: 8, dataset_fingerprint: "fixture",
  catalog_version: "fixture", source_counts: { seed: 4 }, phase: "cases",
  options: { repetitions: 2, execution_limits: { max_provider_requests: 0 } },
  cancel_requested: false, stop_reason: null,
};
const accounting = {
  provider_requests: 4, known_prompt_tokens: 10, known_completion_tokens: 5,
  known_total_tokens: 15, unknown_prompt_token_requests: 1, unknown_completion_token_requests: 1,
  unknown_total_token_requests: 1, known_cost_usd: 0.05, unknown_cost_requests: 1,
  reported_cost_usd: null, by_service_stage: [],
};
const detail = (label) => [...document.querySelectorAll("dt")]
  .find((element) => element.textContent === label)?.nextElementSibling?.textContent;
const cancelButton = () => [...document.querySelectorAll("button")]
  .find((element) => /cancel/i.test(element.textContent));

test("evaluation response types preserve nested saved options and keep request execution fields separate", () => {
  const { options, ...legacyEvaluation } = evaluation;
  const response = {
    ...evaluation,
    options: {
      ...options, methods: ["lexical"], embedding_ids: ["default"], llm_ids: ["default"],
      semantic_rejection: "calibrated", source: "seed", split: "test", limit: 4,
      catalog_sizes: null, catalog_seed: 42, scale_calibration_source: "seed",
      scale_max_oos_false_accept_rate: 0.05, retrieval_profiles: null,
    },
  };
  const fixture = join(temporary, "evaluation-response.ts");
  writeFileSync(fixture, `
    import type { Evaluation, EvaluationExecutionOptions } from "../src/api";
    const saved: Evaluation = ${JSON.stringify(response)};
    const legacy: Evaluation = ${JSON.stringify(legacyEvaluation)};
    const oldOptions: Evaluation = { ...legacy, options: { methods: ["lexical"] } };
    const repetitions: number | undefined = saved.options?.repetitions;
    const requestLimit: number | null | undefined = saved.options?.execution_limits?.max_provider_requests;
    const request: EvaluationExecutionOptions = { repetitions: 2, execution_limits: { max_provider_requests: 0 } };
    const misplacedRepeat: Evaluation = { ...legacy,
      // @ts-expect-error Request repetitions are nested under options in saved responses.
      repetitions: 2,
    };
    const misplacedLimits: Evaluation = { ...legacy,
      // @ts-expect-error Request limits are nested under options in saved responses.
      execution_limits: { max_provider_requests: 0 },
    };
  `);
  const program = ts.createProgram([fixture], {
    strict: true, noEmit: true, skipLibCheck: true, target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  });
  const diagnostics = ts.getPreEmitDiagnostics(program)
    .map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"));
  assert.deepEqual(diagnostics, [], "Public response-shaped fixtures must typecheck");
});

test("execution progress reports known subtotal, unknown total and counts while cancellation remains available", async () => {
  let cancellations = 0;
  await render(ExecutionProgress, { evaluation: { ...evaluation, accounting }, onCancel: () => cancellations++ });
  assert.equal(detail("Completed / planned"), "3 / 8");
  assert.equal(detail("Provider requests"), "4");
  assert.equal(detail("Known reported USD subtotal"), "$0.05");
  assert.equal(detail("Reported USD total"), "Unknown");
  assert.equal(detail("Requests with unknown cost"), "1");
  assert.match(document.body.textContent, /Running/);
  assert.match(document.body.textContent, /cases/);
  assert.equal(document.querySelector("progress").value, 3);
  assert.equal(document.querySelector("progress").max, 8);
  assert.equal(cancelButton().disabled, false);
  await act(() => cancelButton().dispatchEvent(new MouseEvent("click", { bubbles: true })));
  assert.equal(cancellations, 1);
});

test("pending cancellation stays running, terminal states disable cancellation, and old accounting is unavailable", async () => {
  let cancellations = 0;
  const onCancel = () => cancellations++;
  await render(ExecutionProgress, { evaluation, onCancel, cancellationPending: true });
  assert.equal(cancelButton().disabled, true);
  assert.match(document.querySelector('[role="status"]').textContent, /Requesting cancellation.*running/i);
  await act(() => cancelButton().dispatchEvent(new MouseEvent("click", { bubbles: true })));
  assert.equal(cancellations, 0);
  await render(ExecutionProgress, { evaluation: { ...evaluation, cancel_requested: true }, onCancel });
  assert.equal(cancelButton().disabled, true);
  assert.match(document.querySelector('[role="status"]').textContent, /Cancellation requested.*running/i);
  assert.match(document.body.textContent, /In-flight HTTP or local work may finish/);
  for (const [status, reason, message] of [
    ["stopped", "request_limit", "Provider request limit reached"],
    ["stopped", "duration_limit", "Duration limit reached"],
    ["stopped", "reported_cost_limit", "Reported USD threshold reached"],
    ["stopped", "reported_cost_unknown", "Reported cost unavailable"],
    ["cancelled", "user_cancelled", "Cancelled by user"],
    ["failed", "interrupted", "Interrupted by restart"],
    ["completed", null, "Completed"],
  ]) {
    await render(ExecutionProgress, {
      evaluation: { ...evaluation, status, stop_reason: reason, cancel_requested: true }, onCancel,
    });
    assert.equal(cancelButton().disabled, true);
    assert.match(document.body.textContent, new RegExp(message));
    assert.doesNotMatch(document.querySelector('[role="status"]').textContent, /Cancellation requested/);
  }
  await render(ExecutionProgress, { evaluation: { ...evaluation, status: "queued" }, onCancel });
  assert.equal(cancelButton().disabled, false);
  assert.match(document.querySelector('[role="status"]').textContent, /Queued/);
  assert.match(document.body.textContent, /accounting unavailable for this saved evaluation/);
  assert.equal(detail("Provider requests"), undefined);
  assert.doesNotMatch(document.body.textContent, /\$0/);
  await render(ExecutionProgress, {
    evaluation: { ...evaluation, status: "stopped", accounting: {
      ...accounting, provider_requests: 0, known_cost_usd: 0, unknown_cost_requests: 0, reported_cost_usd: 0,
    } }, onCancel,
  });
  assert.equal(detail("Reported USD total"), "$0");
  assert.match(document.body.textContent, /excludes self-hosting costs/);
  assert.match(document.body.textContent, /Incomplete evaluation/);
  assert.equal(detail("Completed / planned"), "3 / 8");
});

const metric = (count, mean, sample_sd, min = mean, max = mean) => ({ count, mean, sample_sd, min, max });
const repeatSummary = {
  group_id: "lexical", planned_count: 1, complete_count: 1, partial_count: 0, missing_count: 0,
  metrics: {
    routing_accuracy: metric(1, 0.75, null), decision_accuracy: metric(1, 0.8, null),
    macro_f1: metric(1, 0.7, null), recall_at_k: metric(1, 1, null),
    latency_p95_ms: metric(1, 12.5, null), technical_error_rate: metric(1, 0.1, null),
  },
  latency_label: "Mean of per-run p95 latency (ms)",
  disagreement: {
    compared_repeat_count: 1, eligible_case_count: 0, excluded_technical_error_case_count: 0,
    disagreeing_case_count: 0, disagreement_rate: null, cases: [],
  },
};
const metricRow = (name) => [...document.querySelectorAll("tbody tr")]
  .find((row) => row.querySelector("th")?.textContent === name);

test("one-repeat summaries show run statistics with unavailable sample SD and explicitly label per-run p95", async () => {
  await render(RepeatSummary, { summary: repeatSummary, label: "Lexical baseline · 48 intents" });
  assert.equal(detail("Planned repeats"), "1");
  assert.equal(detail("Complete repeats"), "1");
  assert.equal(detail("Partial repeats"), "0");
  assert.equal(detail("Missing repeats"), "0");
  assert.match(document.body.textContent, /Lexical baseline · 48 intents/);
  assert.deepEqual([...document.querySelectorAll("thead th")].map((cell) => cell.textContent), [
    "Metric", "Count", "Mean", "Sample SD", "Min", "Max",
  ]);
  assert.deepEqual([...metricRow("Routing accuracy").querySelectorAll("td")].map((cell) => cell.textContent), [
    "1", "75.0%", "Unavailable (n < 2)", "75.0%", "75.0%",
  ]);
  assert.match(metricRow("Mean of per-run p95 latency (ms)").textContent, /12\.5 ms/);
  assert.match(metricRow("Technical error rate").textContent, /10\.0%/);
  assert.match(document.body.textContent, /At least two complete repeats are required/);
  assert.match(document.body.textContent, /Completed runs with technical errors remain included/);
  assert.match(document.body.textContent, /No pooled confidence interval/);
  assert.match(document.body.textContent, /provider and caching effects/);
});

test("partial repeats stay excluded and disagreement states its eligible denominator and technical-error exclusions", async () => {
  await render(RepeatSummary, { summary: {
    ...repeatSummary, planned_count: 5, complete_count: 2, partial_count: 1, missing_count: 2,
    metrics: {
      ...repeatSummary.metrics, routing_accuracy: metric(2, 0.8, 0.07071068, 0.75, 0.85),
      recall_at_k: metric(0, null, null, null, null),
    },
    disagreement: {
      compared_repeat_count: 2, eligible_case_count: 3, excluded_technical_error_case_count: 1,
      disagreeing_case_count: 2, disagreement_rate: 2 / 3,
      cases: [
        { case_id: "synthetic-a", distinct_outcome_count: 2, disagrees: true },
        { case_id: "synthetic-b", distinct_outcome_count: 2, disagrees: true },
        { case_id: "synthetic-c", distinct_outcome_count: 1, disagrees: false },
      ],
    },
  } });
  assert.match(document.body.textContent, /2 of 3 eligible cases disagree \(66\.7%\) across 2 complete repeats/);
  assert.match(document.body.textContent, /1 case\(s\) excluded because of a technical error in at least one compared repeat/);
  assert.equal(detail("Planned repeats"), "5");
  assert.equal(detail("Complete repeats"), "2");
  assert.equal(detail("Partial repeats"), "1");
  assert.equal(detail("Missing repeats"), "2");
  assert.match(document.body.textContent, /Partial and missing repeats are excluded/);
  assert.deepEqual([...metricRow("Routing accuracy").querySelectorAll("td")].map((cell) => cell.textContent), [
    "2", "80.0%", "7.1 pp", "75.0%", "85.0%",
  ]);
  assert.deepEqual([...metricRow("Recall@K").querySelectorAll("td")].map((cell) => cell.textContent), [
    "0", "Unavailable", "Unavailable (n < 2)", "Unavailable", "Unavailable",
  ]);
  await render(RepeatSummary, { summary: {
    ...repeatSummary,
    disagreement: { ...repeatSummary.disagreement, compared_repeat_count: 2, excluded_technical_error_case_count: 4 },
  } });
  assert.match(document.body.textContent, /No eligible cases/);
  assert.doesNotMatch(document.body.textContent, /0 of 0 eligible cases disagree/);
  await render(RepeatSummary, {});
  assert.match(document.body.textContent, /Repeat summary unavailable for this saved evaluation/);
  assert.equal(document.querySelector("table"), null);
});
