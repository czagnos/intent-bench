# Comparing decision and embedding models

**Live demo** and **Experiments** use connections from [Model catalog](model-registry.md), the server's `.env` defaults, and the [bundled profiles](../data/model-presets.json). Registered connections belong to the selected sector workspace. Model choices can change without restarting the API; changing a live-demo model starts a fresh conversation.

## First comparison

1. Select a sector and freeze its catalog and reviewed test cohort. For semantic search, fit each embedding model on **Calibration**, or choose **Semantic OOS rejection → Off** to study the uncalibrated baseline. Hybrid selection does not use that semantic rejection threshold.
2. In **Experiments**, choose semantic and/or hybrid methods, embedding models, and decision models. Inspect the matrix preview before running.
3. Two embeddings × two LLMs produce four hybrid combinations. Adding the semantic method adds two combinations. Set **Maximum cases** to 153 for the complete banking cohort: six combinations produce 918 decisions at one catalog size. Each complete nonbank cohort has 430 cases; use that limit in its sector workspace.
4. Inspect metrics and case-level errors for each row. **Compare two combinations case by case** shows disagreements; **Only different decisions** filters them.
5. Download JSON to retain settings, catalog/data identities, and individual outcomes. Historical single-model runs remain readable.

Change one component at a time: hold the embedding/retrieval strategy fixed when comparing decision models, then hold the decision model fixed when comparing embeddings. Connectivity checks and synthetic starter cases are preparation for evaluation on independent reviewed data.

## Bundled LLM profiles

The following are shipped configuration identifiers, not a current model ranking or guarantee of provider availability. Confirm licensing, hardware requirements, and endpoint support before deployment.

| Profile ID | OpenRouter model | Generation settings | Model card / recorded license |
|---|---|---|---|
| `qwen35-35b` | `qwen/qwen3.5-35b-a3b` | Thinking disabled, 600 output tokens | [Qwen3.5](https://huggingface.co/Qwen/Qwen3.5-35B-A3B), Apache-2.0 |
| `gpt-oss-20b` | `openai/gpt-oss-20b` | Low reasoning, 4096 output tokens | [GPT-OSS 20B](https://huggingface.co/openai/gpt-oss-20b), Apache-2.0 |
| `gpt-oss-120b` | `openai/gpt-oss-120b` | Low reasoning, 4096 output tokens | [GPT-OSS 120B](https://huggingface.co/openai/gpt-oss-120b), Apache-2.0 |
| `qwen3-30b-instruct` | `qwen/qwen3-30b-a3b-instruct-2507` | No reasoning parameter, 600 output tokens | [Qwen3 Instruct](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507), Apache-2.0 |
| `deepseek-v32` | `deepseek/deepseek-v3.2` | Thinking disabled, 600 output tokens | [DeepSeek V3.2](https://huggingface.co/deepseek-ai/DeepSeek-V3.2), MIT |
| `glm47-flash` | `z-ai/glm-4.7-flash` | Thinking disabled, 600 output tokens | [GLM 4.7 Flash](https://huggingface.co/zai-org/GLM-4.7-Flash), MIT |

Reasoning tokens can consume time and output budget even when they are omitted from the visible answer. Truncated JSON is a technical error. See the model's [reasoning guidance](https://huggingface.co/openai/gpt-oss-20b#reasoning-levels) and [OpenRouter reasoning settings](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

## Bundled embedding profiles

| Profile ID | OpenRouter model | Input formatting | Model card / recorded license |
|---|---|---|---|
| `qwen3-8b` | `qwen/qwen3-embedding-8b` | Qwen query instruction; Nebius preference | [Qwen3 8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B), Apache-2.0 |
| `qwen3-4b` | `qwen/qwen3-embedding-4b` | Qwen query instruction; automatic provider | [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B), Apache-2.0 |
| `bge-m3` | `baai/bge-m3` | No prefix; dense vectors | [BGE-M3](https://huggingface.co/BAAI/bge-m3), MIT |
| `multilingual-e5-large` | `intfloat/multilingual-e5-large` | `query` / `passage` prefixes | [E5 Large](https://huggingface.co/intfloat/multilingual-e5-large), MIT |

The 8B/Nebius restriction is not copied to other model profiles. Equivalent defaults are hidden in the menu and deduplicated in experiments. The original profile selection targeted multilingual Turkish banking tests; it does not imply those models are best for every English sector dataset.

The original OpenRouter catalog inspection was on **8 September 2026**. Model access and advertised structured-output support can change; use current discovery and connection tests. Qwen3 Embedding 0.6B was absent from that historical cloud catalog, though local configuration was supported.

## Measurement and failure behavior

- Every combination uses the same frozen reviewed cases and catalog version. Expected labels, source answers, and historical traces are excluded from model inputs.
- Settings are copied when queued. Requests contain model profile IDs; endpoints and credentials stay server-side.
- Index identity separates workspace, catalog, model, input formatting/instruction, endpoint, representation, and provider restriction. Equal vector dimensions do not make different models interchangeable.
- Different LLMs with the same embedding configuration can share catalog vectors. Query embeddings are still computed per case/combination.
- `index_build_ms` records preparation separately. Query p50/p95/p99 describe sequential case processing after preparation. A first live request's cold start is a different timing condition; the first LLM call can still be cold at the provider.
- Runs are sequential, not concurrent load tests. Network, provider load, reasoning, and execution order affect latency.
- An index failure produces error records for every affected case without rebuilding for each one. Other models continue. Query/model errors remain failures in the full denominator; there is no silent model fallback.
- Completed combinations become visible while remaining ones run. The limit is 32 combinations, including retrieval strategies and catalog sizes.

Read routing accuracy alongside overall decisions, OOS false acceptance, false rejection, clarification, and technical errors. A small starter dataset cannot demonstrate broad production accuracy.

## CLI and API

```bash
.venv/bin/python scripts/check_models.py --workspace airline --list-models
.venv/bin/python scripts/check_models.py --workspace airline --llm-only --llm-id gpt-oss-20b
.venv/bin/python scripts/check_models.py --workspace airline --embedding-only --embedding-id bge-m3
```

Listing makes no inference request; probes can incur charges. `GET /v1/models?workspace=airline` returns options and non-secret settings. `POST /v1/route?workspace=airline` accepts `embedding_id` and `llm_id`; omitted IDs use `default`.

Example body for `POST /v1/evaluations?workspace=airline`:

```json
{
  "methods": ["e5", "hybrid_llm"],
  "embedding_ids": ["default", "bge-m3"],
  "llm_ids": ["default", "gpt-oss-20b"],
  "semantic_rejection": "calibrated",
  "source": "seed",
  "split": "test",
  "limit": 100
}
```

With `catalog_sizes` omitted, calibrated semantic evaluation needs a current saved fit. `e5` is the backward-compatible API name for semantic retrieval regardless of the embedding model. New result keys identify combinations; each result also records `method`, `embedding`, `llm`, and `model`. Original default combinations retain their legacy keys.

## Adding profiles

For interactive use, register a connection in **Model catalog**. To distribute a server profile, add it to the appropriate group in [data/model-presets.json](../data/model-presets.json) and restart the API, or use `INTENT_MODEL_CATALOG_PATH` for another absolute file path. Verify the model ID, license, language suitability, structured-output support, and embedding input format. Do not include keys or endpoints in the shared preset file.

For a configured private endpoint, additional server profiles can use `connection: "configured"` and the server's accepted model ID. `INTENT_LLM_THINKING_PARAMETER` controls its supported thinking convention. Do not send OpenRouter-specific parameters blindly to a private server.
