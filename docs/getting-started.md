# Getting started

[Documentation index](README.md) · [Model connections](model-registry.md) · [Contributing](../CONTRIBUTING.md)

Use Python 3.12 and Node.js 22 or newer. Clone the repository, then install dependencies and build the interface:

```bash
git clone https://github.com/czagnos/intent-bench.git
cd intent-bench
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
npm --prefix apps/web ci
npm --prefix apps/web run build
```

## Offline lexical demo

```bash
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= PYTHONPATH=apps/api \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1
```

The lexical baseline needs no API key or model download and makes no provider calls. This command explicitly disables the default model connections, overriding their `.env` settings. Registered model connections remain selectable; choose **Lexical baseline** for an offline evaluation. Dependency installation still requires network access.

Open [the application](http://127.0.0.1:8002) or [API documentation](http://127.0.0.1:8002/docs).

## OpenRouter and other model connections

If `.env` does not exist, create it from the root [`.env.example`](../.env.example). If it already exists, merge the required settings without overwriting your keys or other configuration. The template configures both default models for OpenRouter. Set:

```dotenv
INTENT_OPENROUTER_API_KEY=your_openrouter_api_key
```

Both the LLM and embedding defaults use this shared key unless a dedicated model key overrides it. Start the API without the offline overrides:

```bash
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1
```

In **Model connections**, inspect shared-key presence, choose your LLM and embedding connections, and explicitly test them. **Connection configured** only indicates that server settings are available; a passed test is separate current-session evidence. The panel also checks the selected embedding's persistent index and calibration without making model calls or building an index. See the [model connection guide](model-registry.md) for next actions and private endpoints.

Restart the API after changing the shared OpenRouter key or other startup-loaded settings. Custom file-based registration keys have a separate refresh workflow documented in the guide.

## Frontend development and Windows

For frontend development, run `npm --prefix apps/web run dev` in another terminal; its proxy targets port 8002. On Windows, replace `.venv/bin` with `.venv/Scripts` and use your shell's environment-variable syntax. Persistent vector index locking requires WSL or Docker.

## Docker

```bash
docker compose up --build
```

Docker serves the interface/API on local port 8002 and persists data in `studio-data`. After changing values supplied through `.env` / Compose `env_file`, recreate the container so it receives the updated environment:

```bash
docker compose up -d --force-recreate studio
```

An ordinary container restart retains its existing environment. The base image contains no PyTorch or model weights. Use one API worker: jobs and coordination are managed in-process.

Next, choose a [sector workspace](taxonomy-and-routing.md#sector-workspaces-and-custom-intents), try the [live views](live-demo-views.md), or [run a benchmark](benchmarking.md). Keep the application on loopback and follow the [security guidance](../SECURITY.md) when connecting providers or importing data.
