# Data provenance and handling

## Bundled sector examples

All current starter catalogs and synthetic cases are English. The banking catalog lives under `demo/`; `presets/manifest.json` lists the four application workspaces, and `presets/airline/`, `presets/insurance/`, and `presets/ecommerce/` contain their own `catalog.json`, original `cases.json`, supplemental `benchmark-cases.json`, and separate `calibration-cases.json`.

| Sector | Workspace | Intents |
|---|---|---:|
| Banking | `demo` | 800, including 48 core definitions |
| Airline | `airline` | 200, expanded from 70 |
| Insurance | `insurance` | 200, expanded from 74 |
| E-commerce | `ecommerce` | 200, expanded from 84 |

| Sector | Original tests | Supplemental tests | Combined tests | Calibration |
|---|---:|---:|---:|---:|
| Banking | 29 | 124 | 153 | 72 |
| Airline | 205 | 225 | 430 | 80 |
| Insurance | 205 | 225 | 430 | 80 |
| E-commerce | 205 | 225 | 430 | 80 |

Banking's combined cohort contains 139 route, four clarification, three handoff, and seven out-of-scope cases. The supplement contributes two new paraphrases for each of the 47 routable core definitions and 30 challenge/context cases. Its 58 distinct route labels also include selected product-specific targets. It does **not** test all 800 banking intents; the larger generated catalog remains primarily a distractor set for scaling experiments.

Each other sector retains 400 catalog example utterances and 80 calibration cases (40 route, 40 OOS). Its supplement adds one independently worded route case per 199 routable intents, 24 challenge cases, and two context cases. The combined cohort contains 412 route, five clarification, five handoff, and eight out-of-scope cases. It exercises every catalog intent through routing or human handoff, with at least two route examples for every nonhuman intent. Handoff is a separate decision and does not count as a route label.

Supplemental rows have stable IDs, `source=seed`, `split=test`, `reviewed=true`, `label_origin=curated_synthetic`, and a `challenge` category: paraphrase, negation, correction, noisy_transcript, ambiguity, out_of_scope, handoff, or context. Synthetic noisy transcripts contain written speech-style disfluencies and recognition-like errors; they were not produced by recorded audio or an ASR system. Context examples use the existing active-intent or clarification-option contract.

These English synthetic examples exercise software behavior, operation boundaries, and catalog scaling. They are not representative customer traffic, an independent held-out benchmark, or proof of production accuracy. Original and calibration files remain unchanged; normalized supplemental utterances are disjoint from catalog examples, original tests, and calibration. Exact duplicate checks cannot establish semantic independence, so production evaluation still needs separately collected and reviewed conversations.

`scripts/build_demo_catalog.py` generates the expanded banking catalog from core and reusable product/action definitions. New-sector catalogs are explicit definitions with descriptions, examples, exclusions, nearby confusable intents, selection rules, and workflow mappings. Review their operation sets against the products and workflows your organization actually supports.

The nonbank expansion adds 130 airline, 126 insurance, and 116 e-commerce definitions. Airline adds finer ticket, baggage-incident, disruption, accessibility, family, airport, onboard, and loyalty operations. Insurance expands policy servicing, claims, specialist quotes, coverage/renewals, and health/provider support. E-commerce adds digital goods, home services, marketplace selling, business purchasing, recurring purchases, gifts, rentals, and product safety. Existing broad definitions retain their IDs while their boundaries distinguish the new operations.

The bundled definitions and examples use the project's [Apache-2.0 license](../LICENSE), unless a file states otherwise. This does not grant rights to third-party datasets, weights, or hosted services. Record provenance and permissions for new data; calling it synthetic does not establish its origin.

## Workspace preservation and customization

A fresh sector workspace is seeded with its matching catalog and cases. Switching sectors does not replace an existing catalog or copy model registrations. **Add intent** appends a versioned custom definition; **Import JSON** replaces the active full catalog. Imported labels must still reference intents in that catalog. Recalibrate after changing definitions or labels.

Fresh workspaces publish the catalog, original cases, calibration cases, and supplement in one transaction. Existing workspaces receive the supplement through `<sector>-case-depth-v1`, after their historical migrations. Each new `migrations/case-depth-v1.json` captures the complete preceding normalized catalog fingerprints and original test/calibration IDs. The case-only migration adds no catalog version: it appends eligible new rows while preserving current cases, customer ID collisions, human review history, customized intent/context definitions, snapshots, jobs, and intentionally deleted original rows. Restarting after completion never restores deleted supplemental rows. Unrecognized or trimmed current catalogs are skipped, and failed case insertion rolls back the entire depth migration for safe retry.

The `demo-english-v3` banking migration uses fingerprints of known preceding bundled records. It preserves edited definitions, human-reviewed labels, imported customer records, prior snapshots, and historical jobs. Migration records and historical test fixtures may contain Turkish text to identify and verify those older versions; they are not the current English starter data. Existing user content is not automatically translated.

Each nonbank sector keeps an immutable `migrations/expansion-v2.json` manifest with its v1 intent fingerprints and case IDs. The corresponding `airline-expansion-v2`, `insurance-expansion-v2`, or `ecommerce-expansion-v2` migration recognizes a catalog only when all original intent IDs remain and at least one sector-specific original definition matches its fingerprint, or the full current starter catalog already matches. It updates untouched definitions, appends missing v2 intent IDs, and adds new cases only when their referenced definitions are safe. Edited/custom definitions, every existing case, intentionally deleted original cases, catalog snapshots, and jobs are preserved. Existing workspaces can therefore have different case counts from a fresh installation.

Trimmed or unrelated catalogs are skipped. An expansion that would exceed 2,000 intents is also skipped. Catalog changes, case additions, the migration report, and the completion marker share one transaction; a failed update rolls back and can be retried. Reports are available from `GET /v1/catalog/migrations?workspace=airline` (substitute the sector workspace). Refit calibration after an applied expansion.

Keep seed cohorts paired with their sector. A request that was out of scope for banking can be a valid airline or shopping request. Reusing old OOS labels with a different catalog invalidates the evaluation even when the files load successfully.

## Private inputs and outputs

Keep imports under `data/private/` or outside the repository. That directory also holds the default SQLite database, credentials, and vector indexes. `artifacts/` contains local runs and analysis outputs. Both locations are ignored by Git and excluded from the Docker build context. Do not force-add their contents or copy them into public documentation/tests.

Imported rows can retain questions, answers, identifiers, and selected source metadata for review. Experiment exports can contain per-case outcomes and context. Embedding vectors and fingerprints are not automatically anonymous. Review files and screenshots before sharing them.

Use reviewed development, calibration, and test splits. Keep conversation turns and near-duplicates together. Do not put labels, source answers, or held-out test utterances into retrieval indexing or prompt tuning. For transcript benchmarks, record the source speech pipeline and distinguish transcription errors from decision errors. Check the actual workspace contents before enabling a remote provider.

## Adding a publishable dataset

Document the source, owner, license, creation/collection method, permitted uses, languages, sector, labeling process, known limitations, split method, and version/fingerprint. Obtain permission for upstream material and remove personal or confidential data. Confirm permission both to redistribute and to send data to the selected model providers. Keep the provenance record alongside the release, excluding private approval documents.
