# IntentBench

**Evaluating the decision layer behind agent orchestration**

[Getting started](docs/getting-started.md) · [Architecture](docs/architecture.md) · [Strategy](docs/taxonomy-and-routing.md) · [Benchmarking](docs/benchmarking.md) · [Research](docs/research.md) · [All docs](docs/README.md)

IntentBench is a local workbench for comparing how models and retrieval strategies interpret requests, use conversation context, choose routes, ask for clarification, and identify out-of-scope requests. Compare decision quality, latency, and cost through a React interface or Python CLI using the same evaluation engine.

Start with ready-to-use banking, airline, insurance, and e-commerce scenarios, and connect your own open-weight models through compatible endpoints.

It accepts text and conversation context, including transcripts from your speech pipeline. It does not process audio or execute real business transactions. The interface, guides, and bundled synthetic data are English; imported utterances retain their original language.

## What you can do

- Compare lexical matching, embedding retrieval, and retrieval followed by constrained LLM selection, with optional reranking and calibrated semantic rejection.
- Start with banking, airline, insurance, or e-commerce workspaces, then customize intent catalogs and import reviewed cases.
- Inspect routing decisions and conversation behavior in live views; compare methods, models, retrieval strategies, and catalog sizes in repeatable experiments.
- Connect OpenRouter, TypeSafe Jev, local embeddings, or OpenAI-compatible endpoints.

## Start locally

Use **Python 3.12** and **Node.js 22 or newer**:

```bash
git clone https://github.com/czagnos/intent-bench.git
cd intent-bench
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
npm --prefix apps/web ci
npm --prefix apps/web run build
```

Start the offline lexical demo:

```bash
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1
```

Open **[IntentBench](http://127.0.0.1:8002)** and choose **Lexical baseline**. This method needs no API key or model download; dependency installation requires network access. The command disables default model connections, including those configured in `.env`; registered connections remain selectable.

For model-backed runs, follow [model configuration](docs/getting-started.md#openrouter-and-other-model-connections). The [setup guide](docs/getting-started.md) also covers frontend development, Windows, and persistence.

### Docker

```bash
docker compose up --build
```

Open the same local URL. See [Docker setup](docs/getting-started.md#docker) for persistent storage and configuration updates.

## Run a benchmark

From the repository root:

```bash
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  .venv/bin/python scripts/evaluate.py --workspace airline --source seed --methods lexical --limit 430
```

Results are saved in `artifacts/runs/`. Use `demo`, `insurance`, or `ecommerce` for another sector. The bundled cases are synthetic development fixtures, not evidence of production accuracy.

See the [benchmarking guide](docs/benchmarking.md) for cohort sizes, metrics, and diagnostics; [experiment controls](docs/benchmark-experiments.md) for repetitions and limits; and the [conversation sample pack](data/samples/synthetic-v1/README.md) for ready examples.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, project structure, and verification commands. Technical guides are indexed in [docs](docs/README.md).

## Security

IntentBench is intended for a trusted local operator and has no user authentication. Keep it on loopback and read [SECURITY.md](SECURITY.md) before connecting services, importing private data, or reporting vulnerabilities.

## License

The project's code, documentation, and bundled synthetic examples use [Apache-2.0](LICENSE), unless stated otherwise. Third-party libraries, model weights, datasets, and services retain their own licenses and terms.
