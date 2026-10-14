# IntentBench

IntentBench is an open-source workbench for benchmarking intent recognition models on the same labeled cases. It runs locally and helps you compare methods under consistent evaluation conditions. It supports a lexical baseline, embedding retrieval, retrieval plus constrained LLM selection, optional reranking, and out-of-scope calibration. A React interface and Python CLI share the evaluation engine.

The included Turkish banking catalog and conversations are synthetic examples for development. Banking workflows are simulations. Use an independently reviewed dataset to measure performance in your own domain; the demo is not a production accuracy claim.

**License:** the project’s own code, documentation, and bundled synthetic examples are licensed under [Apache-2.0](LICENSE), unless a file states otherwise. Third-party libraries, model weights, datasets, and hosted services retain their own licenses and terms.

Read the [security guidance](SECURITY.md) before connecting model services or importing your own data. The application is designed for a trusted local operator; it does not provide user authentication.

## Start locally

Use Python 3.12 and Node.js 22 or newer. Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
npm --prefix apps/web ci
npm --prefix apps/web run build
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= PYTHONPATH=apps/api \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1
```

Open [the local application](http://127.0.0.1:8002) or [API documentation](http://127.0.0.1:8002/docs). A fresh installation needs no API key or model download for the lexical baseline. Dependency installation requires network access; baseline evaluation itself does not call a model provider. The application reads an existing `.env`, so check your own settings before enabling other methods.

For frontend development, run `npm --prefix apps/web run dev` in a separate terminal. Its proxy uses the API on port 8002. On Windows, replace `.venv/bin` with `.venv/Scripts` and use your shell's environment-variable syntax; persistent vector index locking requires WSL or Docker.

```bash
docker compose up --build
```

Docker serves the interface and API on the local machine's port 8002 and persists data in the `studio-data` volume. The base image does not include PyTorch or model weights. Use one API worker: jobs and request coordination are managed in-process.

## Run a baseline benchmark

```bash
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  .venv/bin/python scripts/evaluate.py --source seed --methods lexical
```

Results are written to ignored `artifacts/runs/` files. The interface's **Experiments** page uses the same evaluation path and lets you compare cases and model combinations.

For reproducible comparisons:

1. Freeze the catalog, reviewed labels, dataset split, and selected cases. Keep conversations and near-duplicates in a single split; never tune prompts or thresholds on the final test set.
2. Record model identifiers, provider, retrieval settings, prompt/protocol version, catalog and dataset fingerprints, hardware, and concurrency. Provider aliases and remotely hosted models can change.
3. Hold other settings fixed when changing a model or retrieval strategy. Fit semantic rejection thresholds on a separate calibration set.
4. Report routing and overall decision accuracy, macro-F1, candidate Recall@K, out-of-scope false acceptance, false rejection, clarification, coverage, and technical-error counts together with their denominators.
5. Report index/threshold preparation separately from query p50/p95 latency. Include sample counts and token usage when available. Small demo runs are functional checks, not evidence of general model quality.

The bundled demo has been used while developing routing rules. It is not an independent held-out benchmark. Historical demo measurements in the technical guides are labeled snapshots of earlier catalog/software versions and should be rerun before comparison.

[Model comparison](docs/model-comparison.md) · [Catalog sizes](docs/catalog-scaling.md) · [Calibration](docs/calibration-and-language.md) · [Retrieval and reranking](docs/retrieval-quality.md)

## Use your own data

Keep imports under `data/private/` or outside the repository. Upload a CSV in **Cases → Import benchmark CSV**, or run:

```bash
.venv/bin/python scripts/import_benchmark.py data/private/benchmark.csv
```

The importer accepts UTF-8/BOM, comma/semicolon/tab separators, and multiline fields. `Question` supplies the routing input. Optional `BenchmarkSessionId` and `BenchmarkSessionMessageId` identify source records; `Answer` is review context and is not sent to the model; `Message Flow` provides limited source metadata. A source `TRUE/FALSE` value is preserved without assuming it is a correct intent label. Review labels and assign development, calibration, and test splits before evaluating imported cases. The existing API calls imported data `customer`; this is a source identifier, not proof of provenance or authorization.

Database files, raw imports, credentials, vector indexes, and case-level experiment outputs stay local. Git ignore rules do not anonymize data or protect files copied into another folder. See [data provenance and handling](data/README.md).

## Connect models deliberately

Copy `.env.example` to `.env` only when configuring models, and protect the file with `chmod 600 .env` on macOS/Linux. Never commit keys. OpenRouter, TypeSafe Jev, local embeddings, OpenAI-compatible endpoints, and optional rerankers are documented in the [model connection guide](docs/model-registry.md). Model weights and hosted services have their own licenses and terms; inclusion in a preset list does not grant redistribution rights.

Enabling a remote method sends input text and relevant catalog/context to that provider. Index preparation can send the entire selected catalog; reranking sends a query and candidate texts. Review the actual data, endpoint, provider policy, and expected cost before connection tests, indexing, calibration, or evaluation. Selecting a workspace named `demo` does not guarantee its contents are still synthetic.

```bash
.venv/bin/python scripts/check_models.py
.venv/bin/python scripts/warm_models.py
.venv/bin/python scripts/reindex.py --workspace demo --embedding-id default
```

Connection checks send fixed synthetic requests and may incur charges. Warm/reindex commands prepare the selected catalog index and can incur embedding charges. Successful connectivity does not establish model accuracy. Vector indexes are stored under `INTENT_DATA_DIR/vector-indexes/`; changes to a model, catalog, or representation require a compatible index.

[Embedding options](docs/embedding-selection.md) · [TypeSafe Jev](docs/typesafe-jev.md) · [Taxonomy and workflow boundaries](docs/taxonomy-and-routing.md) · [Live views](docs/live-demo-views.md)

## Development

```bash
.venv/bin/pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

Run backend tests and the production build sequentially because both can access the frontend asset directory. Tests cover CSV parsing, routing contracts, data separation, provider failures, evaluation metrics, state isolation, and interface behavior. HTTP fixtures do not establish live model quality.

| Path | Purpose |
|---|---|
| `apps/api/app` | API, storage, retrieval, routing, calibration, evaluation |
| `apps/web` | React/TypeScript interface |
| `data/demo` | Synthetic catalog, test cases, and separate calibration examples |
| `data/private` | Ignored local data and credentials |
| `scripts` | Import, evaluation, model checks, indexing |
| `tests` | Behavior and integration tests |
| `docs` | Technical protocols and release preparation |

Read [contribution guidelines](CONTRIBUTING.md) before submitting a change. Include the [license](LICENSE) when redistributing the project and retain applicable third-party notices.
