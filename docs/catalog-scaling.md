# Catalog-size experiments

Updated: 10 September 2026. See [taxonomy v2 and routing changes](taxonomy-and-routing.md).

The banking demo now contains **800 intent definitions**. Experiments can compare one or several catalog sizes while holding the test cohort and model settings fixed.

## Use the interface

1. Open **Experiments / Deneyler** and choose the test dataset and maximum case count.
2. In **Catalog sizes to search / Aranacak katalog büyüklükleri**, enter one number or a comma-separated list, such as `48, 100, 200, 400, 800`. Preset buttons toggle sizes; **Compare all sizes** selects the available presets. Custom sizes such as `150` work too.
3. Choose methods, embedding models and LLMs. The preview expands **method/model × catalog size**. There are at most eight sizes and 32 total combinations, after server-side model alias deduplication.
4. For calibrated semantic search, choose independent demo or customer calibration data and the empirical maximum OOS false-acceptance target. The experiment fits its own thresholds before timing the test questions. **Off** runs the uncalibrated semantic baseline.
5. Run the experiment. Each result has its own catalog size and fingerprint. The existing case comparison picker includes the size, so the same model at 48 and 800 intents can be compared directly.

**Maximum cases** limits the number of test questions. **Catalog size** limits the intents available to retrieval. For example, the 29-question demo at five sizes produces 145 decisions per method/model combination; it does not create 800 test cases.

## What is in the 800-intent catalog?

The 48 core IDs and workflow mappings are retained in `data/demo/catalog-core.json`. Taxonomy v2 adds selection rules and revises some broad examples. `scripts/build_demo_catalog.py` adds 752 illustrative product/action definitions: 47 named product or service families, each with 16 explicit operation or information requests.

| Additional families | Families | Added intents |
|---|---:|---:|
| Account types | 6 | 96 |
| Loan types | 6 | 96 |
| Card types | 4 | 64 |
| Transfer methods | 6 | 96 |
| Investment instruments | 6 | 96 |
| Insurance products | 4 | 64 |
| Merchant collection services | 5 | 80 |
| Digital channels | 5 | 80 |
| Deposit products | 5 | 80 |
| **Total additions** | **47** | **752** |

Each definition contains a distinct ID and name, scope description, two sample utterances, exclusions, neighbouring intents, channels and a simulated workflow mapping. Virtual-card definitions replace inapplicable physical delivery/damage operations with card-details and number-regeneration requests.

These are **synthetic routing definitions**, not customer-approved labels or a claim that a particular bank offers every listed product. Product-specific variants intentionally create close competitors to broad intents. A bank must review that granularity and decide whether product distinctions belong in separate intents or slots. All banking execution remains a simulation.

Regenerate the shareable JSON with:

```bash
.venv/bin/python scripts/build_demo_catalog.py
```

There are 29 test cases and 72 separate calibration cases. Taxonomy v2 versions five test labels and twelve calibration labels and simplifies one calibration question; the 29 test questions are unchanged. Running them against 800 intents measures competition from the added intents; it does **not** validate all 800 intents or establish production accuracy across an entire operational domain. Add independently reviewed customer cases to measure that broader coverage.

## Fixed-cohort selection

Protocol: `fixed-cohort-nested-domain-v2`. Historical v1 runs retain their original snapshots.

- All selected reviewed test cases remain in every combination, including OOS cases. No case is dropped or relabelled to improve a smaller catalog's accuracy.
- All expected test intent IDs, active conversation intents, clarification targets, expected calibration intent IDs and built-in dialogue targets are protected. Other core intents fill the remaining budget first.
- The 29-case demo fits a 48-intent scope. Including all 72 calibration cases requires at least 53 intents under v2; use, for example, `64, 200, 800` for calibrated semantic comparisons. A customer cohort can change the minimum. A smaller requested size or a missing required intent returns a validation error before any job or model call.
- After core fillers, remaining intents are ordered deterministically by domain, with a seeded hash order within each domain. The default seed is `42`. Larger subsets include all smaller subsets in the same experiment. With the revised demo labels, a 48-intent experiment no longer contains exactly the original 48 core intents.
- The original catalog order and definition contents are preserved. Absent confusable neighbours are ignored by the existing retrieval logic; they are not injected outside the selected subset.
- Gold labels are used once to ensure the evaluation catalog supports the cohort. They do not enter a query, ranking function or LLM prompt. Reference answers and historical traces remain excluded.
- Actual selected IDs, subset fingerprint, parent catalog version, selection protocol and seed are saved with each result. Query records share the same case IDs and denominators.
- Subsets are stored as experiment snapshots. They do not replace the live catalog or appear as an active catalog revision. Queued runs continue using their pinned snapshots after later catalog edits.

This is a controlled catalog expansion experiment, not an unbiased random sample of every bank intent. For different distractor selections, the CLI/API can change `catalog_seed`; hold it fixed when comparing models.

## Calibration at each size

Changing the candidate catalog changes nearest-neighbour scores, so a threshold learned on 48 intents cannot silently be transferred to 800.

When `catalog_sizes` is explicitly provided and semantic rejection is calibrated, the experiment freezes a separate calibration split at queue time. Each embedding model/subset computes its own threshold against that exact index. The sample labels and utterances stay fixed across sizes. All calibration intents are protected in each subset.

The existing validation rules still apply: at least ten in-scope and ten OOS examples; no context-bearing calibration cases; no normalized duplicates or overlap with catalog examples and test questions. This exact-overlap check does not detect paraphrase leakage. An evaluation using its calibration utterances is rejected before running.

Fits are private to the experiment and included in the downloaded results with their operating metrics and provenance. They do not overwrite live-demo calibrations. Calibration failure produces explicit technical-error records for the affected semantic combination; other combinations continue. Existing model/index error isolation applies separately to each subset.

Calibration adds embedding work during preparation. It makes no LLM call. Query p95 excludes both calibration and index preparation. Comparing calibrated results includes the effect of adapting the rejection policy to the catalog; use Recall@K and uncalibrated semantic runs to study retrieval separately.

With `catalog_sizes` omitted, legacy API and CLI behavior is preserved: the active full catalog is used and calibrated semantic evaluation requires a current saved fit from the Calibration page.

## Measurements

| Field | Meaning |
|---|---|
| Catalog intents | Actual number of searchable intent definitions for that result |
| Test intents | Distinct expected route labels represented in the fixed test cohort |
| Accuracy | Correct route and intent / all expected-route cases |
| Recall@K | Expected intent found in the candidate list / expected-route cases |
| Retrieval p95 | 95th percentile of query embedding and candidate-search time, excluding LLM selection; computed over cases where retrieval ran |
| p95 | 95th percentile of individual complete routing computations after preparation; not total experiment time |
| Δ accuracy (pp) | Accuracy difference in percentage points from the same model's smallest catalog in this run |
| p95 ratio | p95 divided by that model's smallest-catalog p95; omitted if either result contains technical errors |
| Index preparation | Retriever/index preparation time, separate from query latency; cache reuse is labelled |
| Threshold preparation | Time fitting the run-private threshold, separate from query latency |

All previous OOS, false rejection, clarification, coverage, decision accuracy and technical-error metrics remain available. Exported JSON also includes per-stage p50/p95 and counts, token totals, query records and the full subset definitions via their stored fingerprints/IDs.

The candidate budget and LLM settings stay constant across sizes. The hybrid LLM receives its candidate list (default K=20), not all 800 definitions. Latency therefore need not grow linearly with catalog size. Network/provider load, warm caches and sequential execution order affect elapsed time. This is not a concurrent call-center load test.

The pure semantic path now skips unused TF-IDF/BM25 query scoring. Its lexical score field is `null`; semantic ranking and threshold scoring are unchanged. Historical semantic latency measurements before this optimization are not directly interchangeable with a fresh scaling run.

## API and CLI

```http
POST /v1/evaluations?workspace=demo
Content-Type: application/json

{
  "methods": ["lexical", "e5", "hybrid_llm"],
  "embedding_ids": ["default"],
  "llm_ids": ["gpt-oss-20b", "gpt-oss-120b"],
  "catalog_sizes": [48, 100, 200, 400, 800],
  "catalog_seed": 42,
  "semantic_rejection": "calibrated",
  "scale_calibration_source": "seed",
  "scale_max_oos_false_accept_rate": 0.05,
  "source": "seed",
  "split": "test",
  "limit": 100
}
```

This example has four method/model variants × five sizes = 20 combinations. Poll the existing evaluation endpoint; download through the existing results button.

```bash
.venv/bin/python scripts/evaluate.py --methods lexical --catalog-sizes 48 100 200 400 800
.venv/bin/python scripts/evaluate.py --methods e5 --embedding-ids default bge-m3 --catalog-sizes 64 100 400 800
.venv/bin/python scripts/evaluate.py --methods hybrid_llm --llm-ids gpt-oss-20b gpt-oss-120b --catalog-sizes 48 100 400 800
```

## Updating an existing installation

Stop the API. From the repository root:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

The API first performs the additive 800-intent migration, then applies taxonomy v2 only to untouched seed definitions and cases. User edits, customer labels, prior results and catalog revisions are preserved; changed cases are archived. Inspect **Intent catalog → Audit catalog → Demo taxonomy version** for the transition report. A custom catalog without that core is not expanded automatically. Fresh workspaces start with 800 intents. A prior 48-intent calibration remains in history but is not valid for live routing with the expanded catalog; fit the new live threshold on the Calibration page.

## Verification

- 123 backend tests passed, including migration preservation, snapshot isolation, deterministic nested selection, fixed cohort/denominators, invalid sizes, matrix cap, separate per-size thresholds and calibration/test separation.
- Six React/jsdom tests passed, including Turkish/English size controls, preserved selections, custom size validation and stable experiment payloads.
- TypeScript/Vite production build passed. A browser render check was attempted, but the available cloud browser blocked the local preview address with `ERR_BLOCKED_BY_CLIENT`; no visual-browser verification is claimed.
- Provider behavior in tests uses controlled HTTP responses. No live embedding/LLM accuracy or provider-latency claim is made for the expanded catalog.
