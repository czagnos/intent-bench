# Synthetic conversation sample pack v1

This pack contains **192 English synthetic turns: 48 each for banking, airline, insurance, and e-commerce**. It provides inspectable sample inputs and expected decisions for the existing benchmark engine, including short contextual replies and difficult intent boundaries. It is separate from the project's 1,443 seeded test cases and 312 calibration cases; it does not replace or migrate them.

The examples and annotations were authored with AI assistance against the bundled catalogs. They are licensed under [Apache-2.0](../../../LICENSE), with provenance and limitations recorded in [manifest.json](manifest.json). No customer records, provider responses, or real personal data were copied. Labels are synthetic author annotations, not human-reviewed real transcripts. Public samples support development and regression checks; they are not an independent held-out benchmark or evidence of production accuracy. Challenge frequencies are deliberate and do not represent real traffic.

## Files and coverage

The sector JSON files are authoritative. Each contains the pack/schema version, language, workspace, catalog fingerprint, and 48 cases with a stable case ID, conversation ID, turn ID, question, explicit pre-turn context, expected decision/intent, test split, challenge, and labeling rationale. The CSV files are deterministic input-only exports from those JSON annotations.

| Sector | Workspace | Canonical annotations | Import example | Turns | Conversations | Multi-turn groups | Distinct route labels |
|---|---|---|---|---:|---:|---:|---:|
| Banking | `demo` | [banking.json](banking.json) | [banking.csv](banking.csv) | 48 | 39 | 3 | 26 |
| Airline | `airline` | [airline.json](airline.json) | [airline.csv](airline.csv) | 48 | 39 | 3 | 28 |
| Insurance | `insurance` | [insurance.json](insurance.json) | [insurance.csv](insurance.csv) | 48 | 40 | 4 | 23 |
| E-commerce | `ecommerce` | [ecommerce.json](ecommerce.json) | [ecommerce.csv](ecommerce.csv) | 48 | 40 | 4 | 23 |

Counts below are calculated from the canonical cases. Each turn has one challenge category; its expected decision is a separate annotation. For example, a context challenge can expect cancellation or handoff.

| Challenge | Banking | Airline | Insurance | E-commerce | Total |
|---|---:|---:|---:|---:|---:|
| `paraphrase` | 10 | 10 | 4 | 4 | 28 |
| `negation` | 4 | 4 | 4 | 4 | 16 |
| `correction` | 4 | 4 | 4 | 4 | 16 |
| `noisy_transcript` | 4 | 4 | 4 | 4 | 16 |
| `near_neighbor` | 4 | 4 | 4 | 4 | 16 |
| `ambiguity` | 3 | 3 | 4 | 4 | 14 |
| `multiple_intents` | 3 | 3 | 4 | 4 | 14 |
| `out_of_scope` | 2 | 2 | 4 | 4 | 12 |
| `handoff` | 2 | 2 | 4 | 4 | 12 |
| `context` | 12 | 12 | 12 | 12 | 48 |
| **Total** | **48** | **48** | **48** | **48** | **192** |

| Expected decision | Banking | Airline | Insurance | E-commerce | Total |
|---|---:|---:|---:|---:|---:|
| `route` | 30 | 33 | 24 | 24 | 111 |
| `continue` | 5 | 0 | 4 | 4 | 13 |
| `clarify` | 6 | 6 | 8 | 8 | 28 |
| `cancel` | 2 | 3 | 3 | 3 | 11 |
| `out_of_scope` | 2 | 2 | 4 | 4 | 12 |
| `handoff` | 3 | 4 | 5 | 5 | 17 |
| **Total** | **48** | **48** | **48** | **48** | **192** |

Every conversation stays in the test split. All four sectors include 12 turns with explicit prior-message snapshots. Banking exercises existing workflow slots and confirmations. Nonbank examples use clarification choices, active intents, topic changes, cancellation, and prior messages without inventing slot definitions or transaction-confirmation state. A continuation label can describe an answer to an ongoing enquiry even when the starter workflow has no structured slots; baseline failure on that answer remains a measured error.

Each turn is evaluated against its supplied state **immediately before that turn**. Earlier model predictions are not propagated to later turns. Grouped conversation IDs support provenance and split integrity; this is snapshot evaluation, not a sequential conversation rollout. Context contains prior information, not the current expected label or a future answer. Short contextual replies can repeat when their pre-turn contexts differ.

Written disfluencies and recognition-like mistakes are constructed text, not actual ASR output. These samples cannot measure audio recognition accuracy. Validation checks exact normalized wording against catalog examples and existing test/calibration questions, plus duplicate question/context pairs. It does not establish semantic independence between paraphrases. Labels and rationales follow the exact bundled catalog boundaries and must be reconsidered when those boundaries change.

## Run the samples offline

After [local setup](../../../README.md#start-locally), run these commands from the repository root. Use your environment's Python executable if it differs from `.venv/bin/python`.

```bash
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  .venv/bin/python scripts/evaluate.py --sample-pack synthetic-v1 --workspace demo \
  --methods lexical --limit 48 --repetitions 2 --max-provider-requests 0

INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  .venv/bin/python scripts/evaluate.py --sample-pack synthetic-v1 --workspace airline \
  --methods lexical --limit 48 --repetitions 2 --max-provider-requests 0

INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  .venv/bin/python scripts/evaluate.py --sample-pack synthetic-v1 --workspace insurance \
  --methods lexical --limit 48 --repetitions 2 --max-provider-requests 0

INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  .venv/bin/python scripts/evaluate.py --sample-pack synthetic-v1 --workspace ecommerce \
  --methods lexical --limit 48 --repetitions 2 --max-provider-requests 0
```

Each command evaluates exactly its selected sector samples in a temporary workspace with the matching full bundled catalog. The temporary database, vector index, and calibration storage are cleaned up after the run. Existing private workspaces, edits, reviews, and model registrations are not copied or changed. The sample adapter uses the existing internal `customer` source category with `reviewed=true` and `label_origin=ai_assisted_synthetic`; this records eligible authored annotations, not real customer provenance or human review. Ordinary seeded cases are not included in the selected cohort.

Do not combine `--sample-pack` with `--source`; the CLI rejects that combination. `--limit` selects the first cases in canonical order, up to the 48 available. It does not create a random or stratified subset, so small limits omit some challenge categories. Repetitions reuse those same selected cases and context snapshots; two repetitions produce 96 records per sector, not 96 independent examples.

The printed summary identifies the local export at `artifacts/runs/<job-id>.json`. It and the saved job include `sample_pack` metadata: pack version, sector, source namespace, language, license, label origin, content SHA-256, catalog fingerprint, available/selected counts, selected case IDs, and selected challenge/decision counts. Those counts describe the actual selected cohort before repetition expansion. The content hash covers normalized canonical JSON; the catalog fingerprint covers normalized bundled intent definitions. Compare both before comparing runs. Exports remain local and Git-ignored after temporary storage is removed.

### Recorded lexical baseline

The four commands above were run against implementation `305f31c`, the canonical pack introduced in `73e18b8`, and their matching full bundled catalogs. Both repetitions produced the same decisions. Counts in this table are **per repetition**; decision accuracy includes all 48 expected decisions, while routing accuracy includes only cases whose expected decision is `route`.

| Sector | Decision accuracy | Routing accuracy | Technical errors | Recorded context bypasses |
|---|---:|---:|---:|---:|
| Banking | 26/48 (54.17%) | 23/30 (76.67%) | 0/48 | 0/48 |
| Airline | 26/48 (54.17%) | 23/33 (69.70%) | 0/48 | 0/48 |
| Insurance | 21/48 (43.75%) | 17/24 (70.83%) | 0/48 | 0/48 |
| E-commerce | 25/48 (52.08%) | 21/24 (87.50%) | 0/48 | 0/48 |

All four jobs completed: **384 case executions across 192 distinct samples, zero provider requests, zero technical errors, and zero disagreement between repeats**. Recorded context bypasses count `retrieval_trace.context_bypass` across all records; zero does not mean the pack has no contextual inputs. These are lexical baseline results, not LLM scores or real-world accuracy estimates. The labels and routing policy were not adjusted after observing the scores. Rerun the commands to obtain local artifacts with the sample/content and catalog fingerprints needed to identify the exact evaluated data; do not pool the two repetitions as independent evidence.

## Use configured models explicitly

Sample mode reads the default model connections from the environment and `.env`; it does not import private workspace model registrations, saved indexes, or saved calibrations. Configure the default endpoints/models and keys using the [model connection guide](../../../docs/model-registry.md). Then, for example:

```bash
.venv/bin/python scripts/evaluate.py --sample-pack synthetic-v1 --workspace airline \
  --methods hybrid_llm --embedding-ids default --llm-ids default \
  --semantic-rejection off --limit 48 --repetitions 1 \
  --max-provider-requests 250 --max-duration-seconds 300
```

This example makes remote requests and may incur charges. Index preparation can embed the **entire selected catalog before the first query**, including catalog examples; `--limit` restricts scored cases, not catalog preparation. The request and duration controls include preparation. They may stop the run before all 48 cases finish; inspect status, accounting, completed counts, and any technical errors. Duration is cooperative, and a request limit is not a dollar spending cap. Compatible preparation can be reused within a repeated job, but a separate sample command starts fresh temporary storage.

`--semantic-rejection off` makes the comparison setting explicit. That setting controls the `e5` semantic baseline; lexical and hybrid methods do not require calibration. To try `--methods e5` in this fresh sample workspace, keep rejection `off` unless deliberately using the existing catalog-size experiment protocol that fits a separate run-private calibration. A default calibrated `e5` run requires a saved fit, which sample mode does not copy from private workspaces. Never use these test labels to fit thresholds. See [calibration](../../../docs/calibration-and-language.md) and [experiment controls](../../../docs/benchmark-experiments.md) for the existing protocols.

## Import and inspect the CSV examples

The CSVs use the normal transcript schema, including `SourceDatasetId`, session/turn IDs, `Question`, `Context`, and `Split`. Their source namespace is `intentbench-synthetic-v1-<sector>`. `Answer`, `Message Flow`, and `TRUE/FALSE` are empty. Expected decisions, expected intents, and labeling rationales stay in the JSON; they are never inserted into CSV model input or context.

Importing a CSV through **Cases → Import benchmark CSV** or `scripts/import_benchmark.py` creates **unreviewed** rows. Read the corresponding JSON rationale, check it against the current catalog, and review each label before evaluating the import. Importing into your own workspace is a separate persistent action from the isolated sample command above. Follow the [transcript review workflow](../../../docs/benchmark-experiments.md#import-transcripts-without-changing-their-meaning); source flags and provenance text never become automatic labels.

To regenerate CSVs after an intentional canonical JSON edit, or check them without writing:

```bash
.venv/bin/python scripts/export_synthetic_samples.py
.venv/bin/python scripts/export_synthetic_samples.py --check
```

Both paths validate the complete fixed pack and matching catalogs before export. `--check` returns nonzero for missing/stale CSVs and leaves files unchanged. Keep versioned identities, annotations, rationales, catalog fingerprints, and derived CSVs consistent when publishing a change. Do not alter labels or routing policy merely to improve a sample score.
