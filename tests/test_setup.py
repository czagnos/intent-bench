import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import OPENROUTER_BASE_URL


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data",
                        model_credentials_file=tmp_path / "absent.env", openrouter_api_key="",
                        llm_api_key="", embedding_api_key="", llm_base_url=OPENROUTER_BASE_URL,
                        embedding_mode="http", embedding_base_url=OPENROUTER_BASE_URL)
    with TestClient(create_app(settings)) as client:
        yield client


def test_setup_reports_missing_key_without_provider_calls_or_index_writes(client):
    def reject_remote(request):
        pytest.fail("Readiness must never call a provider")

    studio = client.app.state.studio
    studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(reject_remote)
    before = sorted(str(path) for path in studio.settings.data_dir.rglob("*"))
    response = client.get("/v1/setup", params={"embedding_id": "default", "llm_id": "default"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["shared_openrouter_key_present"] is False
    assert result["embedding"]["configured"] is False
    assert result["llm"]["configured"] is False
    assert result["index"]["state"] == "unavailable"
    assert result["calibration"]["state"] == "unavailable"
    assert result["workspace"] == "demo"
    assert sorted(str(path) for path in studio.settings.data_dir.rglob("*")) == before


def register(client, kind, workspace="demo"):
    response = client.post("/v1/model-registry", params={"workspace": workspace}, json={
        "kind": kind, "name": kind + " local", "model": kind + "-model", "connection": "onprem",
        "base_url": "http://models.internal/v1", "auth": "none", "profile": "plain"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_setup_supports_registered_models_without_defaults_and_is_workspace_scoped(client):
    embedding, llm = register(client, "embedding"), register(client, "llm")
    selection = {"embedding_id": embedding, "llm_id": llm}
    response = client.get("/v1/setup", params=selection)
    assert response.status_code == 200
    result = response.json()
    assert result["embedding"]["configured"] and result["llm"]["configured"]
    assert result["shared_openrouter_key_present"] is False
    assert result["index"]["state"] == "missing"
    assert result["calibration"]["state"] == "missing_or_stale"
    assert not (client.app.state.studio.settings.data_dir / "vector-indexes").exists()
    client.get("/v1/status?workspace=airline")
    assert client.get("/v1/setup", params={**selection, "workspace": "airline"}).status_code == 422
    assert client.get("/v1/setup?workspace=unopened").status_code == 404
    assert client.app.state.studio.store.catalog("unopened") is None
    assert client.get("/v1/setup", params={"embedding_id": llm}).status_code == 422
    assert client.get("/v1/setup?llm_id=not-a-model").status_code == 422


def test_setup_validates_persistent_vectors_and_current_calibration_without_remote_use(client):
    studio = client.app.state.studio
    embedding = register(client, "embedding")
    calls = []

    def respond(request):
        calls.append(request)
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1., 0.]} for i in range(len(texts))]})

    studio.embeddings.transport = httpx.MockTransport(respond)
    job = client.post("/v1/calibrations", json={"embedding_ids": [embedding]}).json()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get("/v1/requests/" + job["id"]).json()
        if result["status"] not in ("queued", "running"):
            break
        time.sleep(.01)
    assert result["status"] == "completed", result
    call_count = len(calls)
    setup = client.get("/v1/setup", params={"embedding_id": embedding}).json()
    assert setup["index"]["state"] == "present"
    assert setup["calibration"]["state"] == "current"
    assert len(calls) == call_count
    index = next((studio.settings.data_dir / "vector-indexes").glob("*.npz"))
    index.write_bytes(b"broken index")
    case = studio.store.cases("demo", source="seed", split="calibration")[0]
    reviewed = client.patch("/v1/cases/" + case["case_id"] + "/review", json={
        "expected_decision": case["expected_decision"], "expected_intent_id": case["expected_intent_id"], "split": "test"})
    assert reviewed.status_code == 200, reviewed.text
    setup = client.get("/v1/setup", params={"embedding_id": embedding}).json()
    assert setup["index"]["state"] == "invalid"
    assert setup["calibration"]["state"] == "missing_or_stale"
    assert "changed" in setup["calibration"]["reason"]
    assert index.read_bytes() == b"broken index"
    assert len(calls) == call_count
    index.unlink()
    assert client.get("/v1/setup", params={"embedding_id": embedding}).json()["index"]["state"] == "missing"


def test_kind_aware_default_probe_is_explicit_and_hides_upstream_secrets(client):
    studio = client.app.state.studio
    studio.settings.openrouter_api_key = "synthetic-secret"
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "synthetic-secret and private upstream response"})

    studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
    response = client.get("/v1/setup")
    assert response.json()["shared_openrouter_key_present"] is True
    assert "synthetic-secret" not in response.text
    assert not calls
    for kind in ("embedding", "llm"):
        response = client.post(f"/v1/models/{kind}/default/check")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["ok"] is False
        assert result["accuracy_benchmark"] is False
        assert "synthetic-secret" not in response.text and "private upstream" not in response.text
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["llm", "embedding"])
@pytest.mark.parametrize("selection", ["default", "preset", "registered"])
def test_probe_checks_selected_kind_for_defaults_presets_and_registrations(client, kind, selection):
    studio = client.app.state.studio
    studio.settings.openrouter_api_key = "synthetic-secret"
    if selection == "registered":
        model_id = register(client, kind)
    elif selection == "preset":
        presets = studio.model_catalog.catalog.llms if kind == "llm" else studio.model_catalog.catalog.embeddings
        model_id = presets[-1].id
    else:
        model_id = "default"
    calls = []

    def respond(request):
        calls.append(request)
        if kind == "embedding":
            assert request.url.path.endswith("/embeddings")
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1., .5]}]})
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "decision": "route", "intent_id": "card.limit.change", "reason_code": "model_selection"})}}]})

    studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
    response = client.post(f"/v1/models/{kind}/{model_id}/check")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True, response.text
    assert len(calls) == (2 if kind == "embedding" else 1)
    assert "synthetic-secret" not in response.text
    assert not (studio.settings.data_dir / "vector-indexes").exists()
    if selection == "registered":
        other_kind = "embedding" if kind == "llm" else "llm"
        assert client.post(f"/v1/models/{other_kind}/{model_id}/check").status_code == 422
        assert client.post(f"/v1/models/{kind}/{model_id}/check?workspace=airline").status_code == 422


def test_probe_rejects_malformed_usage_without_echoing_provider_content(client):
    model_id = register(client, "llm")
    client.app.state.studio.selector.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "decision": "route", "intent_id": "card.limit.change", "reason_code": "model_selection"})}}],
        "usage": {"prompt_tokens": "private-provider-body"},
    }))
    response = client.post(f"/v1/models/llm/{model_id}/check")
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "private-provider-body" not in response.text


def test_setup_reports_unreadable_index_even_after_vectors_are_cached(client, monkeypatch):
    studio = client.app.state.studio
    embedding = register(client, "embedding")
    studio.embeddings.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [
        {"index": i, "embedding": [1., 0.]} for i, text in enumerate(json.loads(request.content)["input"])]}))
    settings = studio.model_catalog.resolve("embedding", embedding)
    retriever = studio.retriever("demo", settings=settings)
    retriever.prepare_index()
    index = next((studio.settings.data_dir / "vector-indexes").glob("*.npz"))
    original_stat = Path.stat

    def unavailable(path, *args, **kwargs):
        if path == index:
            raise PermissionError("synthetic filesystem denial")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", unavailable)
    response = client.get("/v1/setup", params={"embedding_id": embedding})
    assert response.status_code == 200
    assert response.json()["index"]["state"] == "invalid"
    assert "synthetic filesystem denial" not in response.text
