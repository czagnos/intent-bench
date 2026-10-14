import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import EvaluationRequest
from app.main import create_app
from app.model_catalog import ModelCatalog, embedding_key
from app.providers import OPENROUTER_BASE_URL


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, openrouter_api_key="matrix-secret",
                    llm_base_url=OPENROUTER_BASE_URL, llm_model="qwen/qwen3.5-35b-a3b",
                    embedding_mode="http", embedding_base_url=OPENROUTER_BASE_URL,
                    embedding_model="qwen/qwen3-embedding-8b", embedding_provider_only=["nebius"])


def wait_job(client, path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(path).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(.01)
    pytest.fail("Matrix job timed out")


def install_transports(studio, fail_embedding=None):
    requests = []
    lock = threading.Lock()

    def respond(request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer matrix-secret"
        with lock:
            requests.append(body)
        if request.url.path.endswith("/embeddings"):
            if body["model"] == fail_embedding:
                return httpx.Response(429, json={"error": {"code": 429, "metadata": {"provider_name": "DeepInfra"}}})
            dimensions = 3 if body["model"] == "baai/bge-m3" else 2
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.] * dimensions} for i in range(len(body["input"]))]})
        user = json.loads(body["messages"][1]["content"])
        assert "expected_intent_id" not in user and "reference_answer" not in user
        assert body["response_format"]["type"] == "json_schema"
        if "gpt-oss" in body["model"]:
            assert body["reasoning"] == {"effort": "low", "exclude": True}
            assert body["max_tokens"] == 4096
        elif "instruct-2507" in body["model"]:
            assert "reasoning" not in body
        intent_id = user["candidates"][0]["intent_id"]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"decision": "route", "intent_id": intent_id})}}], "usage": {"total_tokens": 50}})

    studio.embeddings.transport = httpx.MockTransport(respond)
    studio.selector.transport = httpx.MockTransport(respond)
    return requests


def test_model_list_keeps_working_default_and_does_not_expose_secrets(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/models")
        assert response.status_code == 200
        assert "matrix-secret" not in response.text and "api_key" not in response.text and "base_url" not in response.text
        models = response.json()
        assert {"gpt-oss-20b", "gpt-oss-120b", "deepseek-v32", "glm47-flash"} <= {p["id"] for p in models["llm"]}
        assert models["embedding"][0]["settings"]["provider_only"] == ["nebius"]
        assert [p["model"] for p in models["embedding"]].count("qwen/qwen3-embedding-8b") == 1
        assert all(p["available"] for p in models["llm"] + models["embedding"])


def test_provider_and_format_overrides_are_scoped_to_each_embedding(settings):
    registry = ModelCatalog(settings)
    bge = registry.resolve("embedding", "bge-m3")
    e5 = registry.resolve("embedding", "multilingual-e5-large")
    assert bge.embedding_provider_only == e5.embedding_provider_only == []
    assert bge.resolved_embedding_profile == "plain" and e5.resolved_embedding_profile == "e5"
    assert settings.embedding_provider_only == ["nebius"] and settings.resolved_embedding_profile == "qwen3"
    changed_provider = settings.model_copy(update={"embedding_provider_only": []})
    changed_instruction = settings.model_copy(update={"embedding_query_instruction": "Different retrieval task"})
    assert len({embedding_key(settings), embedding_key(changed_provider), embedding_key(changed_instruction), embedding_key(bge)}) == 4


def test_openrouter_presets_do_not_send_onprem_credentials_elsewhere(settings):
    settings.llm_base_url = settings.embedding_base_url = "http://localhost:9000/v1"
    settings.llm_api_key = "onprem-secret"
    registry = ModelCatalog(settings)
    options = registry.options()
    assert all(p["id"] == "default" for p in options["llm"] + options["embedding"] if p["available"])
    with pytest.raises(ValueError, match="OpenRouter"):
        registry.variant("hybrid_llm", "default", "gpt-oss-20b")


def test_matrix_deduplicates_equivalent_default_aliases_and_freezes_settings(settings):
    registry = ModelCatalog(settings)
    variants = registry.expand(EvaluationRequest(methods=["lexical", "e5", "hybrid_llm"],
                               embedding_ids=["default", "qwen3-8b", "bge-m3"],
                               llm_ids=["default", "qwen35-35b"]))
    assert len(variants) == 5  # lexical + two semantic + two hybrid; aliases aren't extra experiments.
    settings.llm_model = "changed-after-queue"
    settings.embedding_provider_only.append("other")
    assert all(v.settings.llm_model != "changed-after-queue" for v in variants)
    assert variants[1].metadata["embedding"]["provider_only"] == ["nebius"]


def test_unknown_model_and_request_endpoint_injection_rejected_before_claiming_turn(settings):
    with TestClient(create_app(settings)) as client:
        requests = install_transports(client.app.state.studio)
        sid = client.post("/v1/sessions").json()["session_id"]
        body = {"session_id": sid, "turn_revision": 1, "user_text": "Kart limitimi artır", "method": "hybrid_llm"}
        assert client.post("/v1/route", json={**body, "llm_id": "does-not-exist"}).status_code == 422
        assert client.post("/v1/route", json={**body, "llm_base_url": "https://elsewhere.example"}).status_code == 422
        assert not requests
        accepted = client.post("/v1/route", json={**body, "llm_id": "gpt-oss-20b"})
        assert accepted.status_code == 202
        assert wait_job(client, "/v1/requests/" + accepted.json()["request_id"])["status"] == "completed"
        assert client.post("/v1/evaluations", json={"methods": ["e5"], "embedding_ids": ["unknown"]}).status_code == 422


def test_full_matrix_uses_same_cases_separate_models_and_shared_index(settings):
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        requests = install_transports(studio)
        response = client.post("/v1/evaluations", json={"methods": ["lexical", "e5", "hybrid_llm"], "semantic_rejection": "off", "embedding_ids": ["default", "bge-m3"], "llm_ids": ["gpt-oss-20b", "gpt-oss-120b"], "limit": 2})
        assert response.status_code == 202, response.text
        job = wait_job(client, "/v1/evaluations/" + response.json()["id"])
        assert job["status"] == "completed" and job["progress"] == job["total"] == 14
        assert len(job["results"]) == len(job["variants"]) == 7
        expected_cases = [r["case_id"] for r in next(iter(job["results"].values()))["records"]]
        for result in job["results"].values():
            assert [r["case_id"] for r in result["records"]] == expected_cases
            assert result["metrics"]["total"] == 2 and result["metrics"]["errors"] == 0
            if result["method"] == "hybrid_llm":
                assert result["llm"]["model"] == result["model"]
                assert result["index_cache_hit"] is True
        hybrid = [r for r in job["results"].values() if r["method"] == "hybrid_llm"]
        assert len({(r["llm"]["model"], r["embedding"]["model"]) for r in hybrid}) == 4
        by_model = {}
        for request in requests:
            if "input" in request:
                by_model.setdefault(request["model"], []).append(request)
                if request["model"] == "baai/bge-m3":
                    assert "provider" not in request and not request["input"][0].startswith("Instruct:")
        doc_count = len(studio.retriever("demo").documents)
        for calls in by_model.values():
            assert sum(len(r["input"]) for r in calls if len(r["input"]) > 1) == doc_count
            assert len([r for r in calls if len(r["input"]) == 1]) == 6  # Queries are measured, not memoized.
        assert "matrix-secret" not in json.dumps(job)
        saved = client.get("/v1/evaluations/" + job["id"]).json()
        assert saved["results"] == job["results"]


def test_broken_embedding_does_not_abort_others_or_repeat_index_failures(settings):
    with TestClient(create_app(settings)) as client:
        requests = install_transports(client.app.state.studio, fail_embedding="baai/bge-m3")
        response = client.post("/v1/evaluations", json={"methods": ["e5", "hybrid_llm"], "semantic_rejection": "off", "embedding_ids": ["bge-m3", "default"], "llm_ids": ["gpt-oss-20b", "gpt-oss-120b"], "limit": 2})
        job = wait_job(client, "/v1/evaluations/" + response.json()["id"])
        assert job["status"] == "completed" and job["progress"] == 12
        assert len([r for r in requests if r["model"] == "baai/bge-m3"]) == 1
        for result in job["results"].values():
            broken = result["embedding"]["model"] == "baai/bge-m3"
            assert result["metrics"]["errors"] == (2 if broken else 0)
            assert result["metrics"]["total"] == 2
            if broken:
                assert result["records"][0]["diagnostics"]["http_status"] == 429


def test_concurrent_demo_requests_keep_model_and_embedding_selection(settings):
    with TestClient(create_app(settings)) as client:
        requests = install_transports(client.app.state.studio)
        selections = [("default", "gpt-oss-20b"), ("bge-m3", "qwen3-30b-instruct")]
        def run(pair):
            sid = client.post("/v1/sessions").json()["session_id"]
            response = client.post("/v1/route", json={"session_id": sid, "turn_revision": 1, "user_text": "Kart limitimi artırmak istiyorum", "method": "hybrid_llm", "embedding_id": pair[0], "llm_id": pair[1]})
            assert response.status_code == 202
            return wait_job(client, "/v1/requests/" + response.json()["request_id"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(run, selections))
        assert all(job["status"] == "completed" for job in jobs)
        assert jobs[0]["result"]["model"] == "openai/gpt-oss-20b"
        assert jobs[0]["result"]["embedding"]["model"] == "qwen/qwen3-embedding-8b"
        assert jobs[1]["result"]["model"] == "qwen/qwen3-30b-a3b-instruct-2507"
        assert jobs[1]["result"]["embedding"]["model"] == "baai/bge-m3"
        assert settings.llm_model == "qwen/qwen3.5-35b-a3b" and requests


def test_equally_sized_embedding_vectors_never_share_model_index(settings):
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        first = studio.retriever("demo")
        alternate = studio.model_catalog.resolve("embedding", "qwen3-4b")
        second = studio.retriever("demo", settings=alternate)
        first.matrix = np.ones((len(first.documents), 2))
        assert second.matrix is None and first is not second
        assert studio.retriever("demo", settings=alternate) is second
