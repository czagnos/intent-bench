# Calibrated semantic rejection and interface language

The semantic method can now reject out-of-scope requests using a fitted cosine threshold. It makes **no LLM call**. A language selector in the top bar switches the interface between Turkish and English and remembers the selection in the browser.

## Update an existing installation

Stop the API, then run from the repository root:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Refresh the browser. Keep the existing model/API key settings. The database adds its calibration table and seeds the new calibration cases automatically, preserving customer records and reviewed labels.

## Catalog-size experiments (9 September 2026)

The demo catalog now has 800 intents. Live-demo calibration still fits the active full catalog. Existing 48-intent thresholds become stale after catalog expansion and must be refitted for live semantic routing.

Experiments now send explicit `catalog_sizes`. In calibrated semantic runs, each size/model gets a run-private threshold fitted on the chosen independent calibration split before query timing starts. These fits do not replace live calibration. With `catalog_sizes` omitted, existing API/CLI behavior remains unchanged: a current saved calibration is required. See [catalog scaling](catalog-scaling.md) for the fixed-cohort protocol and preparation costs.

## First run

1. Open **Calibration / Kalibrasyon**. Select the embedding models you want to compare.
2. Start with **Demo calibration cases** and the default **5% maximum OOS false acceptance** target. Click **Fit thresholds / Eşikleri hesapla**. This prepares each model's index and embeds each calibration question; it uses the existing embedding connection/key.
3. Inspect the fitted threshold, **in-scope retention**, **in-scope false rejection**, **OOS false acceptance**, sample count and source. A failed model is reported separately and cannot publish a partial fit. Other selected models continue.
4. In **Live demo** or **Experiments**, select **Semantic search** and **Calibrated threshold**. All selected semantic embedding models must have a current calibration. A missing or stale fit returns an explicit error before a run starts.
5. Evaluate on the separate **test** split. To compare with the previous semantic baseline, run the same test selection with **Off · previous baseline**. Each run saves its mode and threshold; previous results are unchanged. Hybrid retrieval + LLM retains its existing decision process.

The default target is an **empirical constraint on the calibration samples**, not a guarantee that at most 5% of future OOS requests will be accepted. It is separate from an independently chosen intent accuracy target.

## What the threshold learns

For every labelled calibration utterance, the existing retriever computes the highest cosine similarity across the catalog's intent examples. The question is embedded with that model's existing query formatting. Expected decisions and intent labels are not embedded and do not enter retrieval.

Candidate thresholds separate the observed score groups, including accepting all or rejecting all. For each threshold, we measure:

| Calibration metric | Calculation |
|---|---|
| In-scope retention | In-scope scores at or above the threshold / all in-scope calibration cases |
| In-scope false rejection | In-scope scores below the threshold / all in-scope calibration cases |
| OOS false acceptance | OOS scores at or above the threshold / all OOS calibration cases |

Among thresholds satisfying the chosen maximum empirical OOS false acceptance rate, the algorithm maximizes in-scope retention. Ties favor lower false acceptance, then the lower threshold. Threshold equality is accepted consistently in fitting and routing. Overlapping score distributions can force the rejection of many valid requests; the fit exposes this loss, highlighting retention below 90% rather than claiming success from a low OOS rate alone.

At inference, a score below the threshold produces `out_of_scope` with `reason_code=calibrated_semantic_rejection`. This adds a scalar comparison after retrieval, **not an extra model request**. It does not eliminate embedding/network latency. Existing deterministic conversation rules still handle slot answers, confirmations, active-flow cancellation and explicit clarification, so these rules can bypass the threshold. Calibration rates describe the similarity gate on context-free utterances; held-out evaluation measures the complete routing policy.

Cosine scores are **not confidence probabilities**. This feature calibrates a decision threshold; it does not calibrate posterior class probabilities or introduce an LLM-skipping fast path for the hybrid method. A general reference on separating scores from decision thresholds and using held-out data is the [scikit-learn threshold-tuning guide](https://scikit-learn.org/stable/modules/classification_threshold.html). This implementation fits the explicit empirical false-acceptance constraint directly and does not add a scikit-learn dependency.

## Data separation and provenance

- The new demo calibration set has **72 handwritten, context-free cases: 48 in scope (47 route, one human handoff), 24 OOS**. The existing **29 demo test cases** remain separate and are not used to choose thresholds. These are illustrative datasets, not representative bank-call validation.
- For customer calibration, review labels on **Cases** and assign them to the **Calibration** split. At least 10 in-scope and 10 OOS cases are required. This minimum is a software prerequisite, not a statistically sufficient sample-size claim. Ambiguous `clarify` cases and cases containing conversation context are excluded by explicit validation rather than silently relabelled.
- Normalized duplicate utterances within calibration, and overlaps with test utterances or catalog examples, are rejected. This catches exact normalized overlap; it does not detect paraphrase or conversation-level leakage. Keep conversations and near-duplicates in one split when preparing customer data.
- Evaluating a calibrated semantic model on the utterances used to fit its threshold is blocked. Reviewed customer test counts exclude calibration/development cases.
- Fits are stored per workspace, catalog version, embedding model, endpoint identity, provider restrictions, query profile/instruction, candidate count and calibration algorithm version. Provider identity here means the configured endpoint/restrictions; an automatically routed provider can still change underneath the same configuration.
- The labelled calibration dataset fingerprint is checked when a fit is used. Editing its labels/split requires refitting. A catalog or dataset change while fitting prevents publication. Calibration artifacts and compatible embedding indexes persist across API restarts.
- Calibration metadata is frozen when a route/evaluation is queued. A later fit cannot change the threshold of an existing run. Results include calibration ID, threshold, model, source, catalog/data fingerprints and per-case `rejection_score` when semantic retrieval ran.
- A failed refit does not erase an earlier valid fit. The page shows failed jobs separately from active, timestamped fits. A mixed-success calibration job has `status=completed` with individual failed results; check each result. The CLI exits nonzero if any selected model fails.

## Held-out metrics

Calibration retention is not correct-intent accuracy. After calibration, inspect the existing test metrics and the new **in-scope false rejection** rate together:

| Test metric | Denominator and meaning |
|---|---|
| In-scope routing accuracy | Correct `route` + intent / all expected-`route` cases. Rejection, errors and unnecessary clarification count as failures. |
| Overall decision accuracy | Correct decision / all cases; a route also needs the expected intent. |
| Auto-routing coverage | Predicted `route` / all cases, whether the route is correct or not. |
| Clarification rate | Predicted `clarify` / all cases. |
| OOS false acceptance | Predicted `route` among expected-OOS cases / all expected-OOS cases. Errors and clarification do not count as false acceptance, but are not necessarily correct rejection. |
| In-scope false rejection | Predicted `out_of_scope` among expected-`route` cases / all expected-`route` cases. |
| p95 latency | 95th percentile of individual query times after index preparation; not total experiment runtime. |

The existing OOS metric deliberately retains its original `route` definition for comparison with previous runs. The calibration gate metric counts any score above threshold as accepted, regardless of the eventual route/handoff/clarification. The two metrics can therefore differ. Inspect overall decision accuracy and case-level outcomes too.

## CLI and API

```bash
.venv/bin/python scripts/calibrate.py --source seed --embedding-ids default bge-m3 --max-oos-far 0.05
.venv/bin/python scripts/evaluate.py --source seed --methods e5 --embedding-ids default bge-m3
.venv/bin/python scripts/evaluate.py --source seed --methods e5 --embedding-ids default bge-m3 --semantic-rejection off
```

The calibration CLI and API use the same store and fitter. Run them with the same data directory as the API. Calibration output is written under ignored `artifacts/calibrations/`; it is not added to Git.

```http
POST /v1/calibrations?workspace=demo
Content-Type: application/json

{"embedding_ids":["default","bge-m3"],"source":"seed","max_oos_false_accept_rate":0.05}
```

The response contains the job `id`. Poll `GET /v1/requests/{id}?workspace=demo`. `GET /v1/calibrations?workspace=demo` returns active profiles and calibration split counts without making inference calls.

`POST /v1/route` and `POST /v1/evaluations` accept `semantic_rejection: "calibrated" | "off"`, defaulting to `calibrated`. The setting affects method `e5` only. Existing semantic clients that need the previous baseline must send `off`; otherwise they need a fit first. Lexical and hybrid runs do not require calibration. Clients cannot supply arbitrary thresholds or credentials.

## English interface

The switch covers navigation, forms, model descriptions, decision labels, metric names and definitions, progress, common service errors, dates, percentages and duration units. Switching language preserves the current page, selections and in-flight conversation request. The browser persists the choice; blocked local storage does not prevent switching.

Customer utterances, catalog names/descriptions/examples, source answers and model-generated conversation content retain their original language. Model identifiers, workflow IDs, API decision values, dataset labels and exported JSON keys also stay stable. The sample conversation and deterministic slot handling remain Turkish; switching the UI is not an English banking benchmark or a translation step in inference.

## Verification

Run backend integration tests, frontend DOM interaction checks and the production build:

```bash
.venv/bin/pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

Provider tests use controlled network responses. Interface tests use React and jsdom with simulated responses and events. They check language switching during a request, stable request contents, calibration controls, evaluation controls, metric definitions, original text, and saved preferences. They do not measure model accuracy, live latency, browser layout, or rendering speed. Fit live thresholds separately using your configured model connection.
