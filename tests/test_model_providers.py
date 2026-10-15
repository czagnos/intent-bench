import json
import time

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.contracts import Intent
from app.main import create_app
from app.providers import OPENROUTER_BASE_URL, is_openrouter
from app.retrieval import Embeddings, ModelUnavailable, Retriever
from app.selector import Selector


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, data_dir=tmp_path, openrouter_api_key="unit-test-key",
        llm_base_url=OPENROUTER_BASE_URL, llm_model="qwen/qwen3.5-35b-a3b",
        embedding_mode="http", embedding_base_url=OPENROUTER_BASE_URL,
        embedding_model="qwen/qwen3-embedding-4b",
    )


def selector_input(settings):
    catalog = [Intent.model_validate(i) for i in json.loads((ROOT / "data/demo/catalog.json").read_text())]
    retriever = Retriever(catalog, "test", Embeddings(settings))
    return retriever.search("I want to increase my credit card limit", k=5), retriever.intents


def completion_response(intent="card.limit.change", **choice_fields):
    return httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"decision": "route", "intent_id": intent})}, **choice_fields}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
    })


def test_openrouter_chat_contract_and_shared_key(settings):
    def respond(request):
        assert str(request.url) == OPENROUTER_BASE_URL + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer unit-test-key"
        body = json.loads(request.content)
        assert body["model"] == "qwen/qwen3.5-35b-a3b"
        assert body["reasoning"] == {"enabled": False, "exclude": True}
        assert body["provider"] == {"require_parameters": True, "sort": "latency"}
        assert body["response_format"]["type"] == "json_schema"
        assert "chat_template_kwargs" not in body and "enable_thinking" not in body
        assert "card.limit.change" in body["response_format"]["json_schema"]["schema"]["properties"]["intent_id"]["enum"]
        return completion_response()
    proposal, usage = Selector(settings, httpx.MockTransport(respond)).select("I want to increase my credit card limit", {}, *selector_input(settings))
    assert proposal.intent_id == "card.limit.change" and usage["total_tokens"] == 50


def test_missing_openrouter_key_disables_methods_without_network(settings):
    settings.openrouter_api_key = ""
    assert not settings.llm_configured and not Embeddings(settings).enabled
    with TestClient(create_app(settings)) as client:
        methods = client.get("/v1/methods").json()
        assert [m["id"] for m in methods if m["available"]] == ["lexical"]
    with pytest.raises(ModelUnavailable, match="API"):
        Selector(settings).select("test", {}, [], {})
    with pytest.raises(ModelUnavailable, match="API"):
        Embeddings(settings).encode(["test"])


def test_shipped_env_preset_enables_both_models_with_one_key(tmp_path):
    settings = Settings(_env_file=ROOT / ".env.example", data_dir=tmp_path)
    assert not settings.llm_configured and not Embeddings(settings).enabled
    settings.openrouter_api_key = "local-test-key"
    assert settings.llm_configured and Embeddings(settings).enabled
    assert settings.llm_model == "qwen/qwen3.5-35b-a3b"
    assert settings.embedding_model == "qwen/qwen3-embedding-4b"
    assert settings.resolved_embedding_profile == "qwen3"


def test_service_keys_override_shared_key_and_never_cross_endpoints(settings):
    settings.llm_api_key = "llm-key"
    settings.embedding_api_key = "embedding-key"
    assert settings.resolved_llm_api_key == "llm-key"
    assert settings.resolved_embedding_api_key == "embedding-key"
    settings.llm_api_key = settings.embedding_api_key = ""
    settings.llm_base_url = settings.embedding_base_url = "https://another-provider.example/v1"
    assert settings.resolved_llm_api_key == settings.resolved_embedding_api_key == ""
    assert settings.llm_configured and Embeddings(settings).enabled  # Auth-optional on-prem endpoints.
    assert not is_openrouter("https://openrouter.ai.another-provider.example/api/v1")
    assert not is_openrouter("http://openrouter.ai/api/v1")


@pytest.mark.parametrize("mode,field", [("chat_template", "chat_template_kwargs"), ("top_level", "enable_thinking"), ("none", None)])
def test_onprem_and_other_providers_keep_their_request_format(settings, mode, field):
    settings.llm_base_url = "http://localhost:9000/v1"
    settings.llm_thinking_parameter = mode
    def respond(request):
        body = json.loads(request.content)
        assert "Authorization" not in request.headers
        assert "provider" not in body and "reasoning" not in body
        assert (field in body) if field else not ("chat_template_kwargs" in body or "enable_thinking" in body)
        return completion_response()
    Selector(settings, httpx.MockTransport(respond)).select("I want to increase my credit card limit", {}, *selector_input(settings))


def test_qwen_embeddings_use_instruction_only_for_queries_and_batch_in_order(settings):
    settings.embedding_batch_size = 2
    inputs = []
    def respond(request):
        assert str(request.url) == OPENROUTER_BASE_URL + "/embeddings"
        assert request.headers["Authorization"] == "Bearer unit-test-key"
        body = json.loads(request.content)
        assert body["model"] == "qwen/qwen3-embedding-4b"
        assert body["encoding_format"] == "float"
        inputs.append(body["input"])
        # Reverse response order to exercise per-batch index alignment.
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [float(len(text)), 1.0]} for i, text in reversed(list(enumerate(body["input"])))
        ]})
    embeddings = Embeddings(settings, httpx.MockTransport(respond))
    texts = ["Kart", "Hesap bakiyesi", "Transfer sorgulama"]
    vectors = embeddings.encode(texts)
    assert inputs == [texts[:2], texts[2:]]
    expected = np.array([[len(t), 1.] for t in texts])
    np.testing.assert_allclose(vectors, expected / np.linalg.norm(expected, axis=1, keepdims=True), rtol=1e-6)
    embeddings.encode(["Increase my credit card limit"], query=True)
    assert inputs[-1] == [f"Instruct: {settings.embedding_query_instruction}\nQuery:Increase my credit card limit"]


@pytest.mark.parametrize("model,profile,query,passage", [
    ("intfloat/multilingual-e5-base", "e5", "query: Kart", "passage: Kart"),
    ("Qwen/Qwen3-Embedding-4B", "qwen3", "Instruct: Find banking intents.\nQuery:Kart", "Kart"),
    ("qwen/qwen3-embedding-0.6b", "qwen3", "Instruct: Find banking intents.\nQuery:Kart", "Kart"),
    ("BAAI/bge-m3", "plain", "Kart", "Kart"),
])
def test_embedding_family_format_matches_model_contract(settings, model, profile, query, passage):
    settings.embedding_model = model
    settings.embedding_query_instruction = "Find banking intents."
    embeddings = Embeddings(settings)
    assert settings.resolved_embedding_profile == profile
    assert embeddings.prepare_texts(["Kart"], query=True) == [query]
    assert embeddings.prepare_texts(["Kart"]) == [passage]


def test_local_encoding_does_not_apply_model_prompt_twice(settings):
    settings.embedding_mode = "local"
    embeddings = Embeddings(settings)
    class LocalModel:
        def encode(self, texts, **kwargs):
            assert texts == [f"Instruct: {settings.embedding_query_instruction}\nQuery:Kart"]
            assert kwargs["prompt"] == ""
            return np.array([[3., 4.]])
    embeddings.model = LocalModel()
    np.testing.assert_allclose(embeddings.encode(["Kart"], query=True), [[.6, .8]])


@pytest.mark.parametrize("status,word", [(401, "API key"), (402, "credits"), (429, "rate limit"), (503, "unavailable")])
def test_provider_errors_are_actionable_and_do_not_leak_payloads(settings, status, word):
    def respond(request):
        return httpx.Response(status, json={"error": {"code": status, "message": "private-request-and-api-secret"}})
    for operation in [
        lambda: Selector(settings, httpx.MockTransport(respond)).select("test", {}, [], {}),
        lambda: Embeddings(settings, httpx.MockTransport(respond)).encode(["test"]),
    ]:
        with pytest.raises(ModelUnavailable, match=word) as exc:
            operation()
        assert "private-request" not in str(exc.value)


def test_openrouter_http200_error_and_truncated_completion_are_not_decisions(settings):
    for response in [
        httpx.Response(200, json={"error": {"code": 429, "message": "upstream failure"}}),
        completion_response(finish_reason="length"),
    ]:
        with pytest.raises(ModelUnavailable):
            Selector(settings, httpx.MockTransport(lambda request: response)).select("test", {}, *selector_input(settings))


@pytest.mark.parametrize("rows", [
    [{"index": 0, "embedding": [1., 0.]}, {"index": 0, "embedding": [1., 0.]}],
    [{"index": 1, "embedding": [1., 0.]}],
    [{"index": 0, "embedding": [0., 0.]}],
    [{"index": 0, "embedding": []}],
])
def test_bad_embedding_index_or_vector_is_rejected(settings, rows):
    embeddings = Embeddings(settings, httpx.MockTransport(lambda request: httpx.Response(200, json={"data": rows})))
    with pytest.raises(ModelUnavailable):
        embeddings.encode(["test"])


def test_openrouter_route_integration_and_embedding_metadata(settings):
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        def embedding_response(request):
            texts = json.loads(request.content)["input"]
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [1., .5]} for i, _ in enumerate(texts)]})
        studio.embeddings.transport = httpx.MockTransport(embedding_response)
        studio.selector.transport = httpx.MockTransport(lambda request: completion_response())
        status = client.get("/v1/status")
        assert settings.openrouter_api_key not in status.text
        assert status.json()["embedding_configured"] and status.json()["llm_configured"]
        sid = client.post("/v1/sessions").json()["session_id"]
        response = client.post("/v1/route", json={"session_id": sid, "turn_revision": 1, "user_text": "I want to increase my credit card limit", "method": "hybrid_llm"})
        assert response.status_code == 202
        for _ in range(200):
            job = client.get("/v1/requests/" + response.json()["request_id"]).json()
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(.01)
        assert job["status"] == "completed", job
        assert job["result"]["intent_id"] == "card.limit.change"
        assert job["result"]["embedding"]["model"] == "qwen/qwen3-embedding-4b"
        assert job["result"]["embedding"]["profile"] == "qwen3"
