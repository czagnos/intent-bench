import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import Candidate, Intent
from app.main import create_app
from app.providers import ModelUnavailable
from app.selector import Selector


BASE_URL = "https://api.typesafe.ai/v1"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("INTENT_TYPESAFE_API_KEY", raising=False)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", model_credentials_file=tmp_path / "model.env",
                        embedding_mode="disabled", llm_base_url="", openrouter_api_key="openrouter-secret")
    with TestClient(create_app(settings)) as client:
        yield client


def registration(**changes):
    return {"kind": "llm", "name": "TypeSafe Jev", "model": "jev-1.13.0", "connection": "typesafe",
            "base_url": BASE_URL, "auth": "env", "credential_env": "INTENT_TYPESAFE_API_KEY", **changes}


def add(client, **changes):
    response = client.post("/v1/model-registry", json=registration(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def selection_input():
    intents = [Intent(intent_id=key, name=name, domain="Kartlar", description=description,
                      examples=[description], exclusions=["Diğer işlem"], selection_rule="Açık işlem eşleşmesini seç.",
                      workflow_id="workflow." + key) for key, name, description in [
        ("card.lost", "Kayıp kart", "Kayıp kartı bildirme"),
        ("card.cancel", "Kart iptali", "Kartı kalıcı iptal etme"),
        ("service.human", "Temsilci", "Müşteri temsilcisine bağlanma"),
    ]]
    return [Candidate(intent_id=i.intent_id, name=i.name, domain=i.domain, score=1, score_type="fixture",
                      evidence=i.examples[0]) for i in intents], {i.intent_id: i for i in intents}


def native_response(request, routing="card.lost", first="@none", second="@none"):
    payload = json.loads(request.content)
    selections = {"routing": routing, "clarification_first": first, "clarification_second": second}
    return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
        key: {"type": "choice", "choice": selections[key], "confidence": 1.0,
              "probabilities": {option: float(option == selections[key]) for option in question["criteria"]}}
        for key, question in payload["questions"].items()
    }, "usage": {"input_tokens": 50, "output_tokens": 9}})


def test_typesafe_registration_selects_native_choice_with_its_own_key(client):
    studio = client.app.state.studio
    studio.settings.model_credentials_file.write_text("INTENT_TYPESAFE_API_KEY=typesafe-secret\n")
    record = add(client)
    settings = studio.model_catalog.resolve("llm", record["id"])
    calls = []
    def respond(request):
        calls.append(request)
        assert str(request.url) == BASE_URL + "/systemone"
        assert request.headers["Authorization"] == "Bearer typesafe-secret"
        body = json.loads(request.content)
        assert set(body) == {"model", "state", "questions"}
        assert body["model"] == "jev-1.13.0"
        assert body["state"]["message"] == "Kartımı kaybettim."
        assert body["state"]["candidates"][0]["selection_rule"] == "Açık işlem eşleşmesini seç."
        assert set(body["questions"]) == {"routing", "clarification_first", "clarification_second"}
        assert body["questions"]["routing"]["type"] == "choice"
        return native_response(request)
    proposal, usage = Selector(settings, httpx.MockTransport(respond)).select("Kartımı kaybettim.", {}, *selection_input())
    assert record["available"] and proposal.decision == "route" and proposal.intent_id == "card.lost"
    assert usage == {"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59}
    assert len(calls) == 1
    assert "typesafe-secret" not in client.get("/v1/models").text + client.get("/v1/model-registry").text


@pytest.mark.parametrize("choice,active,decision,intent,reason,mentions", [
    ("@ambiguous", None, "clarify", None, "ambiguous_intent", ["card.lost", "card.cancel"]),
    ("@multiple", None, "clarify", None, "multiple_intents", ["card.lost", "card.cancel"]),
    ("@missing_context", None, "clarify", None, "missing_context", []),
    ("@candidate_not_found", None, "clarify", None, "candidate_not_found", []),
    ("@out_of_scope", None, "out_of_scope", None, "out_of_scope", []),
    ("service.human", None, "handoff", "service.human", "handoff_requested", []),
    ("@continue", "card.lost", "continue", "card.lost", "continue_flow", []),
    ("@cancel", "card.lost", "cancel", "card.lost", "active_flow_cancel", []),
])
def test_native_choices_preserve_non_route_and_conversation_behavior(client, choice, active, decision, intent, reason, mentions):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret", "llm_model": "jev-1.13.0"})
    def respond(request):
        body = json.loads(request.content)
        assert ("@continue" in body["questions"]["routing"]["criteria"]) == bool(active)
        assert ("@cancel" in body["questions"]["routing"]["criteria"]) == bool(active)
        assert "@handoff" not in body["questions"]["routing"]["criteria"]
        assert body["state"]["prior_turns"] == [{"role": "user", "content": "Kart işlemi"}]
        return native_response(request, choice, "card.lost", "card.cancel")
    proposal, _ = Selector(settings, httpx.MockTransport(respond)).select(
        "Kartla ilgili.", {"active_intent": active, "messages": [{"role": "user", "content": "Kart işlemi"}]}, *selection_input())
    assert (proposal.decision, proposal.intent_id, proposal.reason_code) == (decision, intent, reason)
    assert proposal.mentioned_intent_ids == mentions
    if decision == "clarify":
        assert proposal.question and len(proposal.question) <= 300


@pytest.mark.parametrize("damage", ["missing_question", "extra_question", "missing_option", "extra_option", "wrong_argmax", "unnormalized", "bad_choice"])
def test_malformed_native_distribution_is_a_technical_error_without_response_values(client, damage):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret", "llm_model": "jev-1.13.0"})
    def respond(request):
        body = native_response(request).json()
        answer = body["answers"]["routing"]
        if damage == "missing_question":
            del body["answers"]["clarification_second"]
        elif damage == "extra_question":
            body["answers"]["secret-extra"] = answer.copy()
        elif damage == "missing_option":
            del answer["probabilities"]["card.cancel"]
        elif damage == "extra_option":
            answer["probabilities"]["secret-extra"] = 0
        elif damage == "wrong_argmax":
            answer["choice"] = "card.cancel"
        elif damage == "unnormalized":
            answer["probabilities"]["card.lost"] = .4
        else:
            answer["choice"] = "secret-invalid-option"
        return httpx.Response(200, json=body)
    with pytest.raises(ModelUnavailable) as exc:
        Selector(settings, httpx.MockTransport(respond)).select("private-customer-text", {}, *selection_input())
    assert exc.value.diagnostics == {"service": "llm", "category": "typesafe_contract"}
    assert "secret" not in str(exc.value) and "private-customer" not in str(exc.value)


def test_native_connection_probe_live_route_and_experiment_use_selected_model_and_metadata(client):
    studio = client.app.state.studio
    studio.settings.model_credentials_file.write_text("INTENT_TYPESAFE_API_KEY=typesafe-secret\n")
    jev = add(client)
    embedding_response = client.post("/v1/model-registry", json={
        "kind": "embedding", "name": "Test embedding", "model": "fixture-embedding", "connection": "onprem",
        "base_url": "http://embedding.test/v1", "auth": "none"})
    assert embedding_response.status_code == 201
    embedding = embedding_response.json()
    comparator = client.post("/v1/model-registry", json={"kind": "llm", "name": "OpenRouter reference",
        "model": "qwen/reference", "connection": "openrouter", "auth": "shared_openrouter"}).json()
    calls = []
    def transport(request):
        calls.append(request)
        if request.url.path.endswith("/embeddings"):
            assert "Authorization" not in request.headers
            body = json.loads(request.content)
            return httpx.Response(200, json={"data": [
                {"index": i, "embedding": [1., .5, .2]} for i in range(len(body["input"]))]})
        if request.url.path.endswith("/chat/completions"):
            assert request.headers["Authorization"] == "Bearer openrouter-secret"
            assert json.loads(request.content)["model"] == "qwen/reference"
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"decision": "route", "intent_id": "card.limit.change"})}}]})
        assert str(request.url) == BASE_URL + "/systemone"
        assert request.headers["Authorization"] == "Bearer typesafe-secret"
        assert "expected" not in request.content.decode()
        return native_response(request, routing="card.limit.change")
    studio.selector.transport = studio.embeddings.transport = httpx.MockTransport(transport)
    probe = client.post(f"/v1/model-registry/{jev['id']}/check").json()
    assert probe["ok"] and not probe["accuracy_benchmark"], probe
    assert len(calls) == 1  # A probe never prepares embeddings.
    model = next(m for m in client.get("/v1/models").json()["llm"] if m["id"] == jev["id"])
    assert model["settings"]["provider"] == "typesafe"
    assert model["settings"]["protocol"] == "systemone"
    assert not {"max_tokens", "reasoning", "response_format"} & model["settings"].keys()
    session = client.post("/v1/sessions").json()["session_id"]
    live = client.post("/v1/route", json={"session_id": session, "turn_revision": 1,
        "user_text": "Kart limitimi artırmak istiyorum.", "method": "hybrid_llm",
        "llm_id": jev["id"], "embedding_id": embedding["id"]})
    assert live.status_code == 202, live.text
    live_job = wait_job(client, "/v1/requests/" + live.json()["request_id"])
    assert live_job["status"] == "completed", live_job
    assert live_job["result"]["intent_id"] == "card.limit.change"
    assert live_job["result"]["prompt_version"].startswith("router-en-typesafe-")
    run = client.post("/v1/evaluations", json={"methods": ["hybrid_llm"], "llm_ids": [jev["id"], comparator["id"]],
        "embedding_ids": [embedding["id"]], "semantic_rejection": "off", "limit": 1, "catalog_sizes": [48]})
    assert run.status_code == 202, run.text
    job = wait_job(client, "/v1/evaluations/" + run.json()["id"])
    assert job["status"] == "completed", job
    results = list(job["results"].values())
    assert len(results) == 2 and all(r["metrics"]["errors"] == 0 for r in results)
    assert {r["llm"]["provider"] for r in results} == {"typesafe", "openrouter"}
    assert len({r["embedding_id"] for r in results}) == 1
    assert [r["case_id"] for r in results[0]["records"]] == [r["case_id"] for r in results[1]["records"]]
    result = next(r for r in results if r["llm"]["provider"] == "typesafe")
    assert result["metrics"]["errors"] == 0
    assert result["llm"]["provider"] == "typesafe"
    assert result["embedding"]["model"] == "fixture-embedding"
    assert result["prompt_version"] == live_job["result"]["prompt_version"]
    assert result["metrics"]["usage"] == {"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59}
    assert "typesafe-secret" not in json.dumps(job) and "openrouter-secret" not in json.dumps(job)


def wait_job(client, path):
    for _ in range(300):
        job = client.get(path).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(.01)
    pytest.fail("Job did not finish")


def test_unconfigured_native_selector_never_uses_openrouter_key_or_network(client):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": ""})
    def unexpected(request):
        pytest.fail("Missing TypeSafe key must not make an HTTP request")
    assert not settings.llm_configured and settings.resolved_llm_api_key == ""
    with pytest.raises(ModelUnavailable, match="TypeSafe"):
        Selector(settings, httpx.MockTransport(unexpected)).select("Kartımı kaybettim.", {}, *selection_input())


@pytest.mark.parametrize("changes", [
    {"kind": "embedding"}, {"kind": "reranker"}, {"auth": "none"}, {"auth": "shared_openrouter"},
    {"base_url": "https://other.test/v1"}, {"base_url": "https://api.typesafe.ai.evil.test/v1"},
    {"base_url": "https://api.typesafe.ai/v1?key=private-secret"}, {"provider_only": ["nebius"]},
    {"credential_env": "AWS_SECRET_ACCESS_KEY"}, {"api_key": "private-secret"},
    {"connection": "onprem", "base_url": "https://other.test/v1"},
    {"connection": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
])
def test_native_registration_rejects_unsafe_or_incompatible_settings(client, changes):
    response = client.post("/v1/model-registry", json=registration(**changes))
    assert response.status_code == 422
    assert "private-secret" not in response.text
    assert client.get("/v1/model-registry").json()["items"] == []


def test_native_key_rotation_disable_and_provider_switch_preserve_connection_isolation(client, monkeypatch):
    studio = client.app.state.studio
    record = add(client)
    assert not record["available"]
    with pytest.raises(ValueError, match="API key"):
        studio.model_catalog.resolve("llm", record["id"])
    studio.settings.model_credentials_file.write_text("INTENT_TYPESAFE_API_KEY=first-private-key\nINTENT_MODEL_KEY_CUSTOM=custom-private-key\n")
    old = studio.model_catalog.resolve("llm", record["id"])
    studio.settings.model_credentials_file.write_text("INTENT_TYPESAFE_API_KEY=rotated-private-key\nINTENT_MODEL_KEY_CUSTOM=custom-private-key\n")
    new = studio.model_catalog.resolve("llm", record["id"])
    assert old.resolved_llm_api_key == "first-private-key" and new.resolved_llm_api_key == "rotated-private-key"
    assert old.llm_connection_id == new.llm_connection_id
    monkeypatch.setenv("INTENT_TYPESAFE_API_KEY", "process-private-key")
    assert studio.model_catalog.resolve("llm", record["id"]).resolved_llm_api_key == "process-private-key"
    custom = add(client, credential_env="INTENT_MODEL_KEY_CUSTOM")
    assert studio.model_catalog.resolve("llm", custom["id"]).resolved_llm_api_key == "custom-private-key"
    response = client.patch("/v1/model-registry/" + record["id"], json=registration(enabled=False))
    assert response.status_code == 200 and not response.json()["available"]
    with pytest.raises(ValueError, match="disabled"):
        studio.model_catalog.resolve("llm", record["id"])
    for body in [{"kind": "llm", "name": "Other", "model": "other-model", "connection": "onprem",
                  "base_url": "http://onprem.test/v1", "auth": "none"},
                 {"kind": "llm", "name": "OpenRouter", "model": "qwen/reference", "connection": "openrouter",
                  "base_url": "", "auth": "shared_openrouter"}]:
        saved = client.post("/v1/model-registry", json=body).json()
        settings = studio.model_catalog.resolve("llm", saved["id"], old)
        assert settings.llm_protocol == "openai"
        assert settings.resolved_llm_api_key == ("openrouter-secret" if body["connection"] == "openrouter" else "")
    assert old.resolved_llm_api_key == "first-private-key" and old.llm_protocol == "typesafe"


@pytest.mark.parametrize("field,value", [
    ("confidence", float("nan")), ("confidence", float("inf")), ("confidence", -.1), ("confidence", 1.1),
    ("confidence", "1"), ("confidence", True), ("probability", float("nan")), ("probability", -1),
    ("probability", 1.1), ("probability", "1"), ("probability", True),
    ("input_tokens", -1), ("output_tokens", 1.5), ("input_tokens", True), ("output_tokens", "2"),
    ("type", "noul"),
])
def test_native_response_scalars_are_typed_finite_and_bounded(client, field, value):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret"})
    def respond(request):
        body = native_response(request).json()
        if field == "probability":
            body["answers"]["routing"]["probabilities"]["card.lost"] = value
        elif field.endswith("tokens"):
            body["usage"][field] = value
        else:
            body["answers"]["routing"][field] = value
        return httpx.Response(200, text=json.dumps(body))
    with pytest.raises(ModelUnavailable) as exc:
        Selector(settings, httpx.MockTransport(respond)).select("Kartımı kaybettim.", {}, *selection_input())
    assert exc.value.diagnostics["category"] == "typesafe_contract"


@pytest.mark.parametrize("probabilities,choice", [
    ({"card.lost": .333, "card.cancel": .333, "service.human": .333}, "card.lost"),
    ({"card.lost": .4997, "card.cancel": .5003}, "card.lost"),
])
def test_native_probability_rounding_and_ties_are_accepted_without_confidence_threshold(client, probabilities, choice):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret"})
    def respond(request):
        body = native_response(request, routing=choice).json()
        answer = body["answers"]["routing"]
        answer["confidence"] = 0
        answer["probabilities"] = {key: probabilities.get(key, 0) for key in answer["probabilities"]}
        return httpx.Response(200, json=body)
    proposal, _ = Selector(settings, httpx.MockTransport(respond)).select("Kartımı kaybettim.", {}, *selection_input())
    assert proposal.intent_id == choice and proposal.decision == "route"


@pytest.mark.parametrize("status", [401, 422, 429, 529])
def test_native_provider_errors_preserve_safe_status_and_never_retry(client, status):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret"})
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "3"}, json={"error": {"message": "private-body-and-key"}})
    with pytest.raises(ModelUnavailable) as exc:
        Selector(settings, httpx.MockTransport(respond)).select("Kartımı kaybettim.", {}, *selection_input())
    assert exc.value.diagnostics["http_status"] == status and exc.value.diagnostics["retry_after_seconds"] == 3
    assert "private-body" not in str(exc.value) and len(calls) == 1


def test_native_timeout_is_a_technical_error_without_retry(client):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret"})
    calls = []
    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-provider-details", request=request)
    with pytest.raises(ModelUnavailable, match="timed out") as exc:
        Selector(settings, httpx.MockTransport(respond)).select("Kartımı kaybettim.", {}, *selection_input())
    assert "private-provider" not in str(exc.value) and len(calls) == 1


@pytest.mark.parametrize("choice,first,second", [
    ("@ambiguous", "card.lost", "card.lost"), ("@multiple", "card.lost", "@none"),
    ("service.human", "@none", "@none"), ("@continue", "@none", "@none"), ("@cancel", "@none", "@none"),
])
def test_native_invalid_clarification_and_unoffered_actions_are_rejected(client, choice, first, second):
    settings = client.app.state.studio.settings.model_copy(update={
        "llm_base_url": BASE_URL, "llm_protocol": "typesafe", "llm_api_key": "typesafe-secret"})
    candidates, catalog = selection_input()
    candidates = [c for c in candidates if c.intent_id != "service.human"]
    with pytest.raises(ModelUnavailable):
        Selector(settings, httpx.MockTransport(lambda request: native_response(request, choice, first, second))).select(
            "Kartımla ilgili.", {"active_intent": "service.human"}, candidates, catalog)
