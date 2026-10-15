import gzip
import json
import time
import zlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model_catalog import embedding_key
from app.providers import OPENROUTER_BASE_URL


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", model_credentials_file=tmp_path / "model.env",
                        embedding_mode="disabled", llm_base_url="", openrouter_api_key="openrouter-secret")
    with TestClient(create_app(settings)) as client:
        yield client


def record(kind="llm", **overrides):
    return {"kind": kind, "name": "Bank model", "model": "bank-model", "connection": "onprem",
            "base_url": "http://bank.internal:9000/v1", "auth": "none", **overrides}


def add(client, body, workspace="demo"):
    result = client.post("/v1/model-registry", params={"workspace": workspace}, json=body)
    assert result.status_code == 201, result.text
    return result.json()


def test_registry_persists_and_resolves_workspace_owned_models_without_default_connections(client):
    embedding = add(client, record("embedding", model="qwen/qwen3-embedding-8b"))
    llm = add(client, record(model="gpt-oss", reasoning="low"))
    studio = client.app.state.studio
    assert all(m["available"] for m in client.get("/v1/methods").json())
    variant = studio.model_catalog.variant("hybrid_llm", embedding["id"], llm["id"])
    assert variant.settings.resolved_embedding_profile == "qwen3"
    assert variant.settings.resolved_llm_max_tokens == 4096
    assert variant.settings.resolved_llm_api_key == variant.settings.resolved_embedding_api_key == ""
    assert variant.settings.llm_thinking_parameter == "none"
    assert "openrouter-secret" not in json.dumps(variant.metadata)
    assert client.get("/v1/model-registry?workspace=other").json() == {"items": []}
    assert not next(m for m in client.get("/v1/methods?workspace=other").json() if m["id"] == "e5")["available"]
    with pytest.raises(ValueError, match="Unknown"):
        studio.model_catalog.variant("e5", embedding["id"], workspace="other")
    assert client.patch("/v1/model-registry/" + llm["id"] + "?workspace=other", json=record()).status_code == 404
    with TestClient(create_app(studio.settings)) as restarted:
        assert len(restarted.get("/v1/model-registry").json()["items"]) == 2
        assert any(m["id"] == embedding["id"] for m in restarted.get("/v1/models").json()["embedding"])


def test_keys_are_references_only_rotation_replaces_clients_and_aliases_keep_separate_indexes(client, monkeypatch):
    studio = client.app.state.studio
    secret_file = studio.settings.model_credentials_file
    secret_file.write_text("INTENT_MODEL_KEY_BANK=secret-one\n")
    first = add(client, record("embedding", auth="env", credential_env="INTENT_MODEL_KEY_BANK"))
    second = add(client, record("embedding", base_url="http://another-bank.internal/v1"))
    def settings():
        return studio.model_catalog.variant("e5", first["id"]).settings
    old = settings()
    old_retriever = studio.retriever("demo", settings=old)
    assert old.resolved_embedding_api_key == "secret-one"
    secret_file.write_text("INTENT_MODEL_KEY_BANK=secret-two\n")
    new = settings()
    assert embedding_key(old) == embedding_key(new)
    assert studio.retriever("demo", settings=new) is not old_retriever
    assert old_retriever.embeddings.settings.resolved_embedding_api_key == "secret-one"
    assert new.resolved_embedding_api_key == "secret-two"
    assert embedding_key(new) != embedding_key(studio.model_catalog.variant("e5", second["id"]).settings)
    for path in ("/v1/model-registry", "/v1/models", "/v1/status"):
        assert "secret-one" not in client.get(path).text and "secret-two" not in client.get(path).text
    with studio.store.connect() as db:
        persisted = db.execute("SELECT payload FROM model_registrations").fetchall()
        assert "secret-" not in str([tuple(r) for r in persisted])
    monkeypatch.setenv("INTENT_MODEL_KEY_BANK", "env-wins")
    assert settings().resolved_embedding_api_key == "env-wins"


def test_cloud_connections_do_not_reuse_private_endpoint_keys(client):
    studio = client.app.state.studio
    studio.settings.openrouter_api_key = ""
    studio.settings.llm_base_url = "http://private.internal/v1"
    studio.settings.llm_api_key = "private-secret"
    cloud = add(client, record(connection="openrouter", base_url="", auth="shared_openrouter"))
    assert not cloud["available"]
    with pytest.raises(ValueError, match="API key"):
        studio.model_catalog.resolve("llm", cloud["id"])
    studio.settings.openrouter_api_key = "cloud-secret"
    resolved = studio.model_catalog.resolve("llm", cloud["id"])
    assert resolved.resolved_llm_api_key == "cloud-secret"
    assert resolved.llm_base_url == OPENROUTER_BASE_URL


@pytest.mark.parametrize("changes", [
    {"base_url": "file:///etc/passwd"}, {"base_url": "http://169.254.169.254/latest"},
    {"base_url": "http://metadata.google.internal/v1"}, {"base_url": "http://user:supersecret@bank/v1"},
    {"base_url": "http://bank/v1?key=supersecret"}, {"base_url": "http://bank/v1#supersecret"},
    {"auth": "shared_openrouter"}, {"auth": "env", "credential_env": "AWS_SECRET_ACCESS_KEY"},
    {"auth": "env", "credential_env": "supersecret"}, {"api_key": "supersecret"},
    {"kind": "image"}, {"connection": "openrouter", "auth": "shared_openrouter"},
])
def test_invalid_admin_input_does_not_echo_keys(client, changes):
    response = client.post("/v1/model-registry", json=record(**changes))
    assert response.status_code == 422
    assert "supersecret" not in response.text
    assert client.get("/v1/model-registry").json()["items"] == []


def test_edit_disable_and_model_type_protection_keep_queued_settings_frozen(client):
    registry = client.app.state.studio.model_catalog
    embedding = add(client, record("embedding"))
    llm = add(client, record())
    old = registry.variant("hybrid_llm", embedding["id"], llm["id"])
    response = client.patch("/v1/model-registry/" + llm["id"], json=record(model="next-model", name="New name"))
    assert response.status_code == 200
    new = registry.variant("hybrid_llm", embedding["id"], llm["id"])
    assert old.settings.llm_model == "bank-model" and new.settings.llm_model == "next-model"
    assert old.metadata["model_labels"]["llm"] == "Bank model"
    assert new.metadata["model_labels"]["llm"] == "New name" and new.id != old.id
    assert client.patch("/v1/model-registry/" + llm["id"], json=record("embedding")).status_code == 422
    assert client.patch("/v1/model-registry/" + llm["id"], json=record(enabled=False)).status_code == 200
    with pytest.raises(ValueError, match="disabled"):
        registry.variant("hybrid_llm", embedding["id"], llm["id"])
    assert not next(m for m in client.get("/v1/models").json()["llm"] if m["id"] == llm["id"])["available"]


def test_discovery_uses_live_llm_and_embedding_endpoints_with_cached_search(client):
    calls = []
    def transport(request):
        calls.append(request)
        assert request.method == "GET" and request.headers["Authorization"] == "Bearer openrouter-secret"
        if request.url.path.endswith("embeddings/models"):
            return httpx.Response(200, json={"data": [{"id": "baai/bge-m3", "architecture": {"input_modalities": ["text"], "output_modalities": ["embeddings"]}}]})
        return httpx.Response(200, json={"data": [
            {"id": "openai/gpt-oss-20b", "hugging_face_id": "openai/gpt-oss-20b", "supported_parameters": ["structured_outputs", "reasoning"]},
            {"id": "cloud/model", "supported_parameters": ["response_format", "temperature"]},
            {"id": "image/model", "architecture": {"output_modalities": ["image"]}},
            {"id": "prompt/model"},
        ]})
    client.app.state.studio.model_catalog.registry.transport = httpx.MockTransport(transport)
    data = client.get("/v1/model-discovery/openrouter?kind=llm&limit=1").json()
    assert data["total"] == 3 and len(data["items"]) == 1
    assert data["items"][0]["response_format"] == "json_schema" and not data["items"][0]["send_temperature"]
    data = client.get("/v1/model-discovery/openrouter?q=cloud").json()
    assert data["cached"] and data["total"] == 1 and data["items"][0]["response_format"] == "json_object"
    assert client.get("/v1/model-discovery/openrouter?with_weights=true").json()["total"] == 1
    assert len(calls) == 1
    assert client.get("/v1/model-discovery/openrouter?refresh=true").status_code == 200
    assert len(calls) == 2
    assert client.get("/v1/model-discovery/openrouter?kind=embedding").json()["items"][0]["model"] == "baai/bge-m3"
    assert calls[-1].url.path == "/api/v1/embeddings/models"


def test_discovery_failure_is_explicit_and_never_echoes_upstream_body(client):
    registry = client.app.state.studio.model_catalog.registry
    registry.transport = httpx.MockTransport(lambda _: httpx.Response(429, json={"error": {"message": "secret-upstream"}}))
    response = client.get("/v1/model-discovery/openrouter")
    assert response.status_code == 503 and "secret-upstream" not in response.text
    registry.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"data": "bad"}))
    assert client.get("/v1/model-discovery/openrouter").status_code == 503


def compressed_response(payload, encoding="gzip", status=200, headers=None):
    encoded = json.dumps(payload).encode()
    content = gzip.compress(encoded) if encoding == "gzip" else zlib.compress(encoded)

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            midpoint = len(content) // 2
            yield content[:midpoint]
            yield content[midpoint:]

    return httpx.Response(status, stream=Stream(), headers={"Content-Type": "application/json",
                          "Content-Encoding": encoding, "Content-Length": str(len(content)), **(headers or {})})


@pytest.mark.parametrize("kind", ["llm", "embedding"])
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_discovery_decodes_compressed_streams_once(client, kind, encoding):
    calls = []
    def transport(request):
        calls.append(request)
        return compressed_response({"data": [{"id": "test/model", "name": "Türkçe model",
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text" if kind == "llm" else "embeddings"]}}]}, encoding)
    client.app.state.studio.model_catalog.registry.transport = httpx.MockTransport(transport)
    response = client.get("/v1/model-discovery/openrouter", params={"kind": kind})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["name"] == "Türkçe model"
    assert response.json()["total"] == 1
    assert client.get("/v1/model-discovery/openrouter", params={"kind": kind, "q": "test"}).json()["cached"]
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 429, 503])
def test_compressed_provider_errors_keep_safe_diagnostics(client, caplog, status):
    registry = client.app.state.studio.model_catalog.registry
    registry.transport = httpx.MockTransport(lambda _: compressed_response(
        {"error": {"code": status, "message": "secret-upstream openrouter-secret"}},
        status=status, headers={"Retry-After": "7"}))
    response = client.get("/v1/model-discovery/openrouter")
    assert response.status_code == 503
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["upstream_status"] == diagnostics["http_status"] == status
    assert diagnostics["category"] == "upstream_error"
    assert diagnostics["retry_after_seconds"] == 7
    assert f"upstream_status={status}" in caplog.text
    assert "secret-upstream" not in response.text + caplog.text
    assert "openrouter-secret" not in response.text + caplog.text
    assert registry.cache == {}


@pytest.mark.parametrize("category", ["timeout", "connection", "response_decoding", "response_json", "catalog_schema", "response_size", "client_configuration"])
def test_discovery_errors_identify_failure_stage_without_exposing_payloads(client, caplog, category):
    def transport(request):
        if category == "timeout":
            raise httpx.ReadTimeout("secret-upstream", request=request)
        if category == "connection":
            raise httpx.ConnectError("secret-upstream", request=request)
        if category == "client_configuration":
            raise ImportError("secret-upstream")
        if category == "response_decoding":
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"broken secret-upstream"))
        if category == "response_json":
            return httpx.Response(200, text="<html>secret-upstream</html>")
        if category == "response_size":
            return httpx.Response(200, stream=httpx.ByteStream(b" " * (12 * 1024 * 1024 + 1)))
        return httpx.Response(200, json={"data": "secret-upstream"})
    registry = client.app.state.studio.model_catalog.registry
    registry.transport = httpx.MockTransport(transport)
    response = client.get("/v1/model-discovery/openrouter")
    assert response.status_code == 503
    assert response.json()["diagnostics"]["category"] == category
    assert f"category={category}" in caplog.text
    assert "secret-upstream" not in response.text + caplog.text
    assert registry.cache == {}


def inference_transport(request):
    payload = json.loads(request.content)
    assert "Authorization" not in request.headers
    if request.url.path.endswith("embeddings"):
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.5, 0.2]} for i in range(len(payload["input"]))]})
    assert "response_format" not in payload and "temperature" not in payload and "chat_template_kwargs" not in payload
    message = json.loads(payload["messages"][1]["content"])
    assert "response_schema" in message
    selected = message["candidates"][0]["intent_id"]
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"decision": "route", "intent_id": selected, "reason_code": "model_selection"})}}]})


def test_connection_probes_and_multi_model_experiments_use_registered_endpoints(client):
    studio = client.app.state.studio
    calls = []
    def transport(request):
        calls.append((str(request.url), json.loads(request.content)["model"]))
        return inference_transport(request)
    studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(transport)
    embeddings = [add(client, record("embedding", name=f"Embedding {i}", model=f"embed-{i}", base_url=f"http://embedding-{i}.internal/v1"))["id"] for i in range(2)]
    llms = [add(client, record(name=f"LLM {i}", model=f"llm-{i}", base_url=f"http://llm-{i}.internal/v1", response_format="prompt", send_temperature=False))["id"] for i in range(2)]
    for model_id in (embeddings[0], llms[0]):
        response = client.post(f"/v1/model-registry/{model_id}/check").json()
        assert response["ok"] and not response["accuracy_benchmark"]
    response = client.post("/v1/evaluations", json={"methods": ["e5", "hybrid_llm"], "embedding_ids": embeddings,
                           "llm_ids": llms, "semantic_rejection": "off", "limit": 1, "catalog_sizes": [48]})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    for _ in range(300):
        job = client.get("/v1/evaluations/" + job_id).json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(.02)
    assert job["status"] == "completed" and len(job["results"]) == 6
    assert all(r["metrics"]["errors"] == 0 for r in job["results"].values())
    assert {m for _, m in calls} == {"embed-0", "embed-1", "llm-0", "llm-1"}
    assert all(httpx.URL(url).host == m.replace("embed-", "embedding-") + ".internal" for url, m in calls)
    assert all("model_labels" in r for r in job["results"].values())
    assert "openrouter-secret" not in json.dumps(job)


def test_bad_probe_response_is_not_a_pass(client):
    llm = add(client, record())
    client.app.state.studio.selector.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "not-json secret-body"}}]}))
    result = client.post("/v1/model-registry/" + llm["id"] + "/check").json()
    assert not result["ok"] and "secret-body" not in json.dumps(result)
