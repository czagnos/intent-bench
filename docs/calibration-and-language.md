# Calibrated semantic rejection and interface language

The semantic method rejects out-of-scope requests using a fitted cosine threshold and makes **no LLM call**. The interface is English. Select a sector workspace before fitting: its catalog, seed cases, imported cases, model registrations, and saved fits are separate.

## Update an existing installation

Stop the API, then run from the repository root:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Refresh the browser. Keep the existing model/API key settings. Fresh sector workspaces receive their matching calibration cases. Existing customer records, reviewed labels, and custom catalogs are preserved; recognized untouched banking records are migrated to the current English release. Recognized nonbank starter workspaces receive the versioned 200-intent expansion and eligible new cases while retaining all existing cases. Inspect the sector's `GET /v1/catalog/migrations` report and refit after an applied catalog expansion; see [preservation rules](../data/README.md#workspace-preservation-and-customization).

## Catalog-size experiments (9 September 2026)

The demo catalog now has 800 intents. Live-demo calibration still fits the active full catalog. Existing 48-intent thresholds become stale after catalog expansion and must be refitted for live semantic routing.

Experiments now send explicit `catalog_sizes`. In calibrated semantic runs, each size/model gets a run-private threshold fitted on the chosen independent calibration split before query timing starts. These fits do not replace live calibration. With `catalog_sizes` omitted, existing API/CLI behavior remains unchanged: a current saved calibration is required. See [catalog scaling](catalog-scaling.md) for the fixed-cohort protocol and preparation costs.

## First run

1. Open **Calibration**. Select the embedding models you want to compare.
2. Start with **Demo calibration cases** and the default **5% maximum OOS false acceptance** target. Click **Fit thresholds**. This prepares each model's index and embeds each calibration question; it uses the existing embedding connection/key.
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

- The banking calibration set has **72 handwritten, context-free cases: 48 in scope (47 route, one human handoff), 24 OOS**. The **153 banking test cases** (29 original plus 124 supplemental) remain separate and are not used to choose thresholds. A complete fresh banking workspace stores 225 seeded rows across these two splits. Its full test cohort requires at least 59 intents, or 67 with calibration; use `100, 200, 800` for full-cohort size comparisons. These are illustrative datasets, not representative bank-call validation.
- Airline, insurance, and e-commerce each provide **80 context-free calibration cases: 40 route and 40 OOS**, separate from 400 catalog example utterances and 430 test cases. A complete fresh workspace stores 510 seeded rows. The full test cohort requires all 200 sector intents. Keep both calibration and test targets when choosing a smaller fixed cohort for catalog-size experiments.
- For customer calibration, review labels on **Cases** and assign whole conversations to the **Calibration** split. At least 10 in-scope and 10 OOS cases are required. This minimum is a software prerequisite, not a statistically sufficient sample-size claim. Only reviewed context-free `route`, `handoff`, and `out_of_scope` cases are eligible; `clarify`, `continue`, `cancel`, and cases with context are rejected by explicit validation rather than silently relabelled.
- Normalized duplicate utterances within calibration, and overlaps with test utterances or catalog examples, are rejected. Selected conversation IDs are also checked across all stored splits, including legacy/manual rows and unreviewed siblings. Unrelated split problems do not block an independent cohort. These guards do not detect paraphrases or differently identified copies; keep near-duplicates together manually.
- Evaluating a calibrated semantic model on the utterances used to fit its threshold is blocked. Reviewed customer test counts exclude calibration/development cases.
- Fits are stored per workspace, catalog version, embedding model, endpoint identity, provider restrictions, query profile/instruction, candidate count and calibration algorithm version. Provider identity here means the configured endpoint/restrictions; an automatically routed provider can still change underneath the same configuration.
- The labelled calibration dataset fingerprint and selected-conversation separation are checked when a fit is used. Editing its labels/split requires refitting; a newly inserted sibling in another split also blocks reuse even if the fit-row fingerprint is unchanged. A catalog or dataset change while fitting prevents publication. Calibration artifacts and compatible embedding indexes persist across API restarts.
- Calibration metadata is frozen when a route/evaluation is queued. A later fit cannot change the threshold of an existing run. Results include calibration ID, threshold, model, source, catalog/data fingerprints and per-case `rejection_score` when semantic retrieval ran.
- A failed refit does not erase an earlier valid fit. The page shows failed jobs separately from active, timestamped fits. A mixed-success calibration job has `status=completed` with individual failed results; check each result. The CLI exits nonzero if any selected model fails.

## Held-out metrics

Calibration retention is not correct-intent accuracy. After calibration, inspect the existing test metrics and the new **in-scope false rejection** rate together:

| Test metric | Denominator and meaning |
|---|---|
| In-scope routing accuracy | Correct `route` + intent / all expected-`route` cases. Rejection, errors and unnecessary clarification count as failures. |
| Overall decision accuracy | Correct decision / all cases; route, continue, and cancel also need the expected intent. |
| Auto-routing coverage | Predicted `route` / all cases, whether the route is correct or not. |
| Clarification rate | Predicted `clarify` / all cases. |
| OOS false acceptance | Predicted `route` among expected-OOS cases / all expected-OOS cases. Errors and clarification do not count as false acceptance, but are not necessarily correct rejection. |
| In-scope false rejection | Predicted `out_of_scope` among expected-`route` cases / all expected-`route` cases. |
| p95 latency | 95th percentile of individual query times after index preparation; not total experiment runtime. |

The existing OOS metric deliberately retains its original `route` definition for comparison with previous runs. The calibration gate metric counts any score above threshold as accepted, regardless of the eventual route/handoff/clarification. The two metrics can therefore differ. Inspect overall decision accuracy and case-level outcomes too.

## CLI and API

```bash
.venv/bin/python scripts/calibrate.py --source seed --embedding-ids default bge-m3 --max-oos-far 0.05
.venv/bin/python scripts/evaluate.py --workspace demo --source seed --methods e5 --embedding-ids default bge-m3 --limit 153
.venv/bin/python scripts/evaluate.py --workspace demo --source seed --methods e5 --embedding-ids default bge-m3 --semantic-rejection off --limit 153
```

The calibration CLI and API use the same store and fitter. Run them with the same data directory as the API. Calibration output is written under ignored `artifacts/calibrations/`; it is not added to Git.

These evaluation commands include the complete banking test cohort. Use the matching sector workspace and `--limit 430` for a complete nonbank test cohort. Without an explicit limit, the evaluation CLI selects at most 100 cases.

Evaluation accepts `--repetitions` and optional request/duration/reported-USD limits. Limits include evaluation-owned index preparation and calibration fits across all variants/repeats; they do not apply to a separate `scripts/calibrate.py` invocation. Compatible frozen fits can be reused within a repeated experiment. See [experiment controls and transcript review](benchmark-experiments.md) for accounting, cooperative cancellation, complete-run statistics, bounded pre-turn context, and conversation split actions.

```http
POST /v1/calibrations?workspace=demo
Content-Type: application/json

{"embedding_ids":["default","bge-m3"],"source":"seed","max_oos_false_accept_rate":0.05}
```

The response contains the job `id`. Poll `GET /v1/requests/{id}?workspace=demo`. `GET /v1/calibrations?workspace=demo` returns active profiles and calibration split counts without making inference calls.

`POST /v1/route` and `POST /v1/evaluations` accept `semantic_rejection: "calibrated" | "off"`, defaulting to `calibrated`. The setting affects method `e5` only. Existing semantic clients that need the previous baseline must send `off`; otherwise they need a fit first. Lexical and hybrid runs do not require calibration. Clients cannot supply arbitrary thresholds or credentials.

## English interface and multilingual inputs

The interface, current bundled catalogs/cases, model instructions, and server responses are English. Old Turkish interface preferences do not restore a Turkish UI. User-owned utterances, descriptions, examples, source answers, and model-generated conversation text remain unchanged; interface translation is not part of inference.

Identifiers, decision values, workflow IDs, labels, and JSON keys stay stable. Historical Turkish labels stored by earlier releases can be displayed through a compatibility translation layer. English confirmation/cancellation and supported banking amount parsing are exercised through the full request flow; Turkish inputs remain supported by existing deterministic rules. That compatibility is not a claim of equal model accuracy across languages.

Banking's separate seed calibration set contains 72 cases. Airline, insurance, and e-commerce each have 80: 40 route and 40 OOS. All current starter utterances are English synthetic software examples. Calibrate against reviewed data representative of the target catalog, language, and speech-transcript conditions; an OOS banking example may become in scope for another sector, and a previously excluded operation may become in scope after expansion.

## Verification

Run backend integration tests, frontend DOM interaction checks and the production build:

```bash
.venv/bin/pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

Provider tests use controlled network responses. Interface tests use React and jsdom with simulated responses and events. They check English defaults, workspace isolation during requests, stable request contents, calibration/evaluation controls, metric definitions, original text, and saved workspace preferences. They do not measure model accuracy, live latency, browser layout, or rendering speed. Fit live thresholds separately using your configured model connection.

## Pitfalls

- An English interface does not create an English benchmark. Check retrieval instructions, prompts, source cases, response text, confirmation/cancellation, numeric formats, and field continuation through public requests.
- Do not carry seed calibration data across sector catalogs. Review both in-scope labels and OOS exclusions when replacing a catalog.
- Normalize all catalog example, test, and calibration utterances when checking duplicate leakage. Distinct IDs or different punctuation do not make repeated wording independent data.
- Recheck every OOS example against the expanded operation set. Preserving an old OOS label does not prove the request remains outside the new scope.
- Calibration estimates an empirical score threshold, not a calibrated probability or a guarantee on unseen traffic. Keep final tests independent of threshold selection.
