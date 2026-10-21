# Model catalog and connections

Open **Model catalog** to add, edit, test, or disable LLM, embedding, and reranker connections. Registrations are stored in SQLite for the selected **Sector workspace** and survive restarts. Switching sectors loads that workspace's registrations; it does not copy credentials or model choices. Server `.env` defaults and the bundled model presets remain available.

## Data and credentials

Protect `.env` with `chmod 600 .env` on macOS/Linux and never commit keys. Remote methods send input text and relevant catalog/context to the provider. Index preparation can send the entire selected catalog; reranking sends the query and candidate texts. Review the actual contents, destination, provider policy, and cost before connection tests, indexing, calibration, or evaluation. A workspace named `demo` can contain user data. See [security guidance](../SECURITY.md).

For local embedding choices, read [embedding selection](embedding-selection.md); reranker setup is in [retrieval quality](retrieval-quality.md#connecting-a-reranker).

## First-run readiness

Open **Model connections** for the setup panel. Create the root `.env` from `.env.example` if absent; otherwise merge the necessary settings into the existing file. The template points both default models at OpenRouter and uses `INTENT_OPENROUTER_API_KEY`. Start with the [model-enabled startup command](getting-started.md#openrouter-and-other-model-connections): the offline command explicitly disables the default connections. Restart the API after changing this shared key or other startup-loaded settings. For Docker `env_file` changes use `docker compose up -d --force-recreate studio`; a restart alone does not replace the container environment.

The panel shows only whether the shared key is present, never its value. Choose actual LLM and embedding options, including your workspace's registrations. A configured private connection works without either default connection or a shared OpenRouter key. Configuration is not proof of provider access. **Test embedding connection** and **Test LLM connection** explicitly send fixed synthetic probes and can use provider credits. Successful results apply to the current session; changing model selections, refreshing connections, or closing the panel discards them. They do not establish model accuracy.

Opening or refreshing the panel reads readiness without inference, model discovery, downloads, index creation, or calibration. The index check validates the persistent file for the selected embedding, current full catalog, and server-default retrieval representation. Different catalog subsets or experiment representations need their own compatible indexes. A missing index can be prepared with `scripts/warm_models.py`; an invalid index requires `scripts/reindex.py`. The panel supplies a command for the selected workspace and embedding. These commands are explicit actions and can incur embedding charges.

Calibration is checked using the same current-catalog/model/data validation as semantic routing. **Missing or stale** means fit or refit on the Calibration page; choose the same embedding there. Calibration is required for calibrated semantic rejection, not for lexical or hybrid routing. Navigation to **Model catalog**, **Calibration**, and **Experiments** does not run anything automatically.

API: `GET /v1/setup?workspace=airline&embedding_id=default&llm_id=default` returns typed readiness for an existing workspace. `POST /v1/models/{kind}/{model_id}/check` explicitly tests `embedding` or `llm` defaults, presets, or registrations. The existing `/v1/model-registry/{model_id}/check` endpoint remains available, including rerankers. Probe results never include credentials or raw provider error bodies.

## OpenRouter

1. Choose **Discover on OpenRouter**, select LLM or Embedding, and search by model or provider name. Discovery uses OpenRouter's model APIs rather than the bundled preset file. Results are cached for five minutes; **Refresh list** reloads them.
2. Choose **Add to catalog**, review the connection, and save. The server uses `INTENT_OPENROUTER_API_KEY`. When that shared key is absent, an existing key for the same model type's official OpenRouter connection can be used; private-server keys are not forwarded.
3. Use **Add by model ID** for a manual OpenRouter ID. Saving does not verify account access: run **Test connection**.
4. **Advanced model settings** controls JSON mode, reasoning, output budget, temperature, timeout, and provider restrictions. Discovery initializes these from advertised capabilities. Actual support can differ by provider and account.

**Has a model card** filters records with a reported Hugging Face ID. It does not verify licensing, downloadable weights, hardware compatibility, or local deployment. Models without a model card can still be used.

## TypeSafe Jev

**Add TypeSafe Jev** creates a direct connection using `jev-1.13.0`, `https://api.typesafe.ai/v1`, and the key-variable name `INTENT_TYPESAFE_API_KEY`. Put the key in the server `.env`, save the form, and test. If the key is added later, use **Refresh connections**. OpenRouter discovery and an OpenRouter key are unnecessary.

Jev runs at the intent-selection stage with your existing embedding/retrieval connection. Its native `POST /systemone` protocol does not use OpenAI JSON/reasoning/temperature/output-budget settings; the form hides those controls. The model ID and timeout remain editable. Custom key variables beginning with `INTENT_MODEL_KEY_` are also supported. See the [TypeSafe protocol and comparison guide](typesafe-jev.md).

## Private or on-premises endpoints

Choose **Add on-prem model**:

| Field | Meaning |
|---|---|
| Display name | For example, `Qwen GPU-1`, to distinguish servers using the same model |
| Model type | LLM or Embedding |
| Model ID | The server's served-model name; it need not be an OpenRouter slug |
| API base URL | For example, `http://localhost:8001/v1`, reachable from the API process |
| Authentication | No key, or the name of a server-side key variable |
| Embedding profile | `auto`, `qwen3`, `e5`, or `plain`; choose explicitly for custom served-model names |

The endpoint must be reachable from the **IntentBench API process**. Browser reachability is insufficient. The client appends `/chat/completions` or `/embeddings` and expects the corresponding OpenAI-compatible JSON protocol. Registering a connection does not download weights or launch a GPU server.

For authentication, add to the server `.env`:

```dotenv
INTENT_MODEL_KEY_PRIVATE_LLM=your_private_server_key
```

Enter only `INTENT_MODEL_KEY_PRIVATE_LLM` in **Key variable name**. Custom names must begin with `INTENT_MODEL_KEY_`. After adding a key, **Refresh connections** updates availability. Values are not returned to the browser or stored in registration/experiment payloads. The application does not rewrite `.env`.

Custom file-based credentials are reread for new operations; process environment variables take precedence. Restart the API after changing process environment values. Recreate the container after changing Docker `env_file` values; restarting a container alone retains its previous environment. `INTENT_MODEL_CREDENTIALS_FILE=/absolute/path/model.env` selects another key file.

OpenRouter keys are not sent to private endpoints. No-key connections omit Authorization. Generic OpenAI-compatible connections omit a thinking parameter by default; choose `chat_template` or `top_level` only when your server supports it. See [reranker protocols](retrieval-quality.md#connecting-a-reranker) for reranker endpoints.

## Experiments, calibration, and results

- Register the same model with different endpoints/settings to compare them. Results retain connection ID, configuration version, and display name, but no key. Editing a registration does not alter a queued run's frozen configuration.
- Each embedding connection/settings identity has its own index and calibration. Refit after changing endpoint, model, or embedding inference settings. Display-name or credential-value changes alone do not invalidate compatible vectors/calibration; new HTTP clients must still receive the current key.
- Disabled records cannot be selected for new requests. Historical results remain available. A workspace supports up to 200 registrations; an experiment supports up to 32 combinations including catalog sizes.
- `prompt` JSON mode omits `response_format` and supplies the schema in the prompt. Responses still undergo schema and candidate-membership validation. Invalid output is a technical error, not a route.

```bash
.venv/bin/python scripts/check_models.py --list-models --workspace airline
.venv/bin/python scripts/check_models.py --llm-only --llm-id model_REPLACE_WITH_ID --workspace airline
```

Use `.venv/bin/python scripts/check_models.py --workspace demo` to probe the default connections. Listing makes no inference call. Connection probes use synthetic text and can incur provider charges; they verify access and protocol behavior, not accuracy.

## Persistent vectors and reindexing

Indexes persist under `INTENT_DATA_DIR/vector-indexes/` (default `data/private/vector-indexes/`). Docker uses the `studio-data` volume mounted at `/app/data/private`. A restarted API can load compatible catalog/model/representation vectors. A new user request still computes a query embedding.

First open the chosen sector in the application so its workspace exists. Run these commands using the same data directory and `.env` as the API:

```bash
.venv/bin/python scripts/warm_models.py --workspace airline --embedding-id model_REPLACE_WITH_ID
.venv/bin/python scripts/reindex.py --workspace airline --embedding-id model_REPLACE_WITH_ID
```

Warm loads an existing index or builds a missing one; it makes no sample-query or LLM call. Reindex recomputes the full catalog. Use `--embedding-id default` for `.env` defaults. Both commands accept `--catalog-version VERSION` and `--representation combined|separate`. Without a version, they pin the catalog active when the command starts. They do not create a missing workspace/catalog.

Successful JSON reports `source=disk`, `built`, or `rebuilt`, plus generation, dimensions, text count, model, catalog version, elapsed time, and path. Reindex replaces the previous file atomically only after success; failure preserves it. Later API requests load the new generation while existing runs retain theirs. Corrupt files require explicit reindexing rather than silent provider calls.

```bash
docker compose exec studio python scripts/reindex.py --workspace demo --embedding-id default
```

Workspace scoping organizes local state. It does not add user authentication or organizational authorization. See [security guidance](../SECURITY.md).

## Discovery diagnostics and updates

For discovery 503 errors, inspect `OpenRouter discovery failed` in application logs. `category` distinguishes timeout, connection, decompression, JSON/catalog format, and provider failures. `upstream_status`, when present, is the actual provider HTTP status. The API exposes the same safe metadata under `diagnostics`; keys and raw provider responses are excluded.

A historical 9 September 2026 fix removed double decompression of model-list responses and corrected compression/length headers. Its 57-test result belongs to that release, not the current full-suite count.

Stop the API, retain `.env`, and update from the repository root:

```bash
.venv/bin/pip install -r requirements.lock
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1
```

Database schema updates are automatic. Current catalog language migrations preserve known user edits as described in [data handling](../data/README.md).

## API sources

Discovery reads the [LLM catalog](https://openrouter.ai/api/v1/models) and [embedding catalog](https://openrouter.ai/docs/api/api-reference/embeddings/list-all-embeddings-models) without pagination arguments; the UI filters and paginates metadata locally. Model-card links use the optional [Hugging Face ID](https://openrouter.ai/docs/client-sdks/python/components/model). Discovery itself performs no inference.

## Setup pitfalls

- A successful connection test is temporary evidence. Clear it when connection configuration is refreshed and ignore late responses from earlier selections or refresh generations.
- Validate provider-derived probe fields before serialization, including token usage. A typed response object alone does not validate values assigned after construction; malformed provider content must produce a sanitized failed probe.
- Keep readiness read-only: inspect and validate persistent vectors without calling index preparation. Missing, invalid, and valid files have distinct next actions; none should trigger hidden provider use.
- An unreadable vector file can fail during cached-index revision inspection before file loading. Handle both boundaries as an invalid/unreadable index and keep calibration and connection readiness available.
- Server-level shared settings load at startup, while registered file-based keys are reread for new operations. Process environment wins over the key file, and Docker environment changes require container recreation.
- Calibration invalidation tests must actually change reviewed data or its split through the review boundary. Reimporting a case with the same ID intentionally preserves the original and does not make a calibration stale.
- Run checks with an interpreter that has the locked test dependencies installed. A runtime-only virtual environment may have no `pytest`; absence of its executable is not a product-test failure.
- Native model selectors can retain a minimum intrinsic width longer than a dialog column. Constrain both the label and select to the available width and wrap model names/hints; verify the setup panel in an actual browser, not only DOM tests.
