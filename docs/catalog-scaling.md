# Catalog-size experiments

Updated for English sector workspaces: 14 October 2026. See [taxonomy v2 and routing changes](taxonomy-and-routing.md).

The banking workspace (`demo`) contains **800 intent definitions**. Airline, insurance, and e-commerce each contain **200**; select sizes within that workspace's catalog. Experiments can compare one or several catalog sizes while holding the test cohort and model settings fixed.

## Use the interface

1. Open **Experiments** and choose the test dataset and maximum case count.
2. In **Catalog sizes to search**, enter one number or a comma-separated list, such as `100, 200, 800` for the complete banking cohort. Preset buttons toggle sizes; **Compare all sizes** selects the available presets, but the selected cohort must fit every size. Custom sizes such as `150` work too.
3. Choose methods, embedding models and LLMs. The preview expands **method/model × catalog size**. There are at most eight sizes and 32 total combinations, after server-side model alias deduplication.
4. For calibrated semantic search, choose independent demo or customer calibration data and the empirical maximum OOS false-acceptance target. The experiment fits its own thresholds before timing the test questions. **Off** runs the uncalibrated semantic baseline.
5. Run the experiment. Each result has its own catalog size and fingerprint. The existing case comparison picker includes the size, so the same model at 100 and 800 intents can be compared directly.

**Maximum cases** limits the number of test questions. **Catalog size** limits the intents available to retrieval. For example, the complete 153-question banking cohort at three sizes produces 459 decisions per method/model combination; it does not create 800 test cases. Set **Maximum cases** to 153 or pass `--limit 153` for this complete cohort.

Each nonbank starter test cohort has 430 cases: 412 routes, five human handoffs, five clarifications, and eight OOS requests. Set **Maximum cases** to 430, or pass `--limit 430` to the CLI, whose default is 100. The complete cohort requires all 200 intents; it cannot be used unchanged at smaller catalog sizes. Choose a smaller fixed cohort before comparing smaller catalogs, and retain its required test and calibration targets at every size. A run on fewer cases does not establish full starter-catalog coverage.

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

There are 153 test cases (29 original plus 124 supplemental) and 72 separate calibration cases, totaling 225 seeded rows in a complete fresh banking workspace. The test cohort covers 58 distinct route labels, including all 47 routable core definitions and selected product-specific operations. The historical taxonomy-v2 migration revised five original test labels, twelve calibration labels, and one calibration question. The English migration translates recognized bundled definitions and utterances while retaining stable IDs; the separate case-depth migration adds eligible supplemental cases. Running them against 800 intents measures competition from the added intents; it does **not** validate all 800 intents or establish production accuracy across an entire operational domain. Add independently reviewed customer cases to measure that broader coverage.

## What is in each 200-intent sector catalog?

The airline, insurance, and e-commerce catalogs are explicit English definitions, expanded from 70, 74, and 84 intents respectively. Their 372 additions cover finer service operations with distinct workflow destinations and exclusions, rather than duplicating one operation for every field value. Each catalog provides 400 example utterances and separate test/calibration files.

The 430-case test set (205 original plus 225 supplemental) references every intent through route or handoff behavior, with at least two route cases per nonhuman intent. The **Test intents** metric counts only the 199 distinct route labels; the `service.human` handoff is evaluated as a separate decision. The 80 calibration cases contain 40 route and 40 OOS requests, giving 510 seeded rows in each complete fresh nonbank workspace. These are synthetic software examples, not independent accuracy evidence. Review the operation boundaries and collect representative held-out transcripts before drawing production conclusions.

## Fixed-cohort selection

Protocol: `fixed-cohort-nested-domain-v2`. Historical v1 runs retain their original snapshots.

- All selected reviewed test cases remain in every combination, including OOS cases. No case is dropped or relabelled to improve a smaller catalog's accuracy.
- All expected test intent IDs, active conversation intents, clarification targets, expected calibration intent IDs and built-in dialogue targets are protected. Other core intents fill the remaining budget first.
- The complete 153-case banking cohort requires at least 59 intents, or 67 with all 72 calibration cases. Use `100, 200, 800` for full-cohort comparisons across methods. The original 29-case cohort remains available by explicitly setting `--limit 29` (or **Maximum cases** to 29) in an unchanged starter workspace; a 48-intent scope applies only to a sufficiently small selected cohort. A customer cohort can change the minimum. A smaller requested size or a missing required intent returns a validation error before any job or model call.
- Each complete 430-case nonbank starter cohort protects all 200 intents, including the handoff target. Smaller catalog comparisons require a smaller cohort selected once before the experiment; calibration targets can raise its minimum further.
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
  "catalog_sizes": [100, 200, 800],
  "catalog_seed": 42,
  "semantic_rejection": "calibrated",
  "scale_calibration_source": "seed",
  "scale_max_oos_false_accept_rate": 0.05,
  "source": "seed",
  "split": "test",
  "limit": 153
}
```

This example has four method/model variants × three sizes = 12 combinations, each using the complete banking test cohort. Poll the existing evaluation endpoint; download through the existing results button.

```bash
.venv/bin/python scripts/evaluate.py --workspace demo --methods lexical --limit 153 --catalog-sizes 100 200 800
.venv/bin/python scripts/evaluate.py --workspace demo --methods e5 --embedding-ids default bge-m3 --limit 153 --catalog-sizes 100 200 800
.venv/bin/python scripts/evaluate.py --workspace demo --methods hybrid_llm --llm-ids gpt-oss-20b gpt-oss-120b --limit 153 --catalog-sizes 100 200 800
```

## Updating an existing installation

Stop the API. From the repository root:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

The API first performs the additive 800-intent migration, then applies taxonomy v2 only to untouched seed definitions and cases. User edits, customer labels, prior results and catalog revisions are preserved; changed cases are archived. Inspect **Intent catalog → Audit catalog → Demo taxonomy version** for the transition report. A custom catalog without that core is not expanded automatically. Fresh banking workspaces start with 800 intents; named sector workspaces seed their matching catalog and cases. The subsequent fingerprint-checked `demo-english-v3` migration updates only untouched recognized banking content. Human reviews and custom definitions remain unchanged. A prior 48-intent calibration remains in history but is not valid for live routing with the expanded catalog; fit the new live threshold on the Calibration page.

Nonbank workspaces apply their immutable `expansion-v2` migration when the complete original intent-ID set and recognized sector content remain. Untouched definitions are updated and new v2 IDs are appended; existing cases, edited/custom definitions, snapshots, and jobs are preserved. Trimmed/unrecognized catalogs and expansions exceeding 2,000 intents are skipped. Catalog and case changes, the report, and the completion marker are atomic and idempotent. Inspect `GET /v1/catalog/migrations?workspace=airline` or the corresponding sector workspace; see [preservation rules](../data/README.md#workspace-preservation-and-customization). Fresh nonbank workspaces start at 200 intents. Existing saved calibrations need refitting after expansion.

After historical releases, every sector applies its case-only `<sector>-case-depth-v1` supplement. This adds eligible test rows without another catalog version or calibration-data change. Edited target/context definitions, existing cases, and intentional deletions are preserved, so actual upgraded workspace counts can differ from fresh starter totals.

## Verification

Backend behavior tests cover migration preservation, snapshot isolation, deterministic nested subsets, fixed denominators, invalid sizes, matrix limits, per-size thresholds, and split separation. React/jsdom tests cover catalog-size controls, custom sizes, and stable request payloads. Run the current suites and production build sequentially; old test counts do not describe current coverage.

Historical verification on the earlier Turkish banking release reported 123 backend tests, six UI tests, and a successful production build. Its browser render attempt was blocked with `ERR_BLOCKED_BY_CLIENT`; no visual verification was claimed. Those records establish neither current English catalog accuracy nor live provider latency.

## Pitfalls

- Do not assume every workspace contains banking core IDs. A nonbank catalog still needs a positive catalog-size minimum, and its test/calibration targets determine the actual protected set.
- A preset count is not accuracy evidence. Even a synthetic cohort with a route/handoff case for every intent does not establish real-world performance; route-only coverage also excludes the handoff target.
- Raising the catalog count without raising the case limit can silently benchmark only part of the starter set. Use 153 for the complete banking test cohort or 430 for a complete nonbank cohort; use a deliberately fixed smaller cohort for smaller catalog comparisons.
- After expanding a cohort, audit linked guides, API examples, CLI limits, matrix arithmetic, and minimum catalog sizes together. Preserve measured historical results with their original cohort/version labels; do not present a historical denominator as a current full-cohort instruction.
- Update audit coverage assertions when supplemental cases add new route labels. Verify the public tested-intent count against distinct expected route IDs in the test split, while retaining checks that auditing never changes labels or catalog versions.
- Compare the same language, label version, catalog selection protocol, and case cohort. The English migration changes retrieval texts; historical Turkish percentages are not directly comparable.
