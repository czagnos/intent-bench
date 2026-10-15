"""Custom intents are added atomically without changing existing catalog content."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_mode="http",
                        embedding_base_url="http://embeddings.test/v1", embedding_api_key="",
                        llm_base_url="", llm_api_key="", openrouter_api_key="")
    with TestClient(create_app(settings)) as current:
        def reject_model_call(request):
            pytest.fail("Adding a definition must not call a model provider")
        current.app.state.studio.embeddings.transport = httpx.MockTransport(reject_model_call)
        yield current


def definition():
    return {"intent_id": "custom.lounge.reserve", "name": "Reserve lounge access",
            "domain": "Airport services", "description": "Request a reservation for airport lounge access.",
            "examples": ["Reserve the lounge for my upcoming trip"], "workflow_id": "workflow.custom.lounge.reserve",
            "required_slots": ["booking_reference"],
            "slot_questions": {"booking_reference": "What is your booking reference?"},
            "confusable_with": ["service.human"], "selection_rule": "Select for an explicit lounge reservation request."}


def test_add_intent_preserves_catalog_and_versions_without_provider_calls(client):
    previous = client.get("/v1/catalog?workspace=airline").json()
    other = client.get("/v1/catalog?workspace=insurance").json()
    response = client.post("/v1/catalog/intents?workspace=airline",
                           json={"expected_version": previous["version"], "intent": definition()})
    assert response.status_code == 201, response.text
    result = response.json()
    current = client.get("/v1/catalog?workspace=airline").json()
    assert current["intents"] == previous["intents"] + [result["intent"]]
    assert current["version"] == result["version"] != previous["version"]
    assert result["intent_count"] == len(current["intents"])
    assert client.get("/v1/catalog", params={"workspace": "airline", "version": previous["version"]}).json() == previous
    assert client.get("/v1/catalog?workspace=insurance").json() == other


@pytest.mark.parametrize("changes", [
    {"intent_id": "service.human"},
    {"confusable_with": ["missing.intent"]},
    {"confusable_with": ["custom.lounge.reserve"]},
    {"slot_questions": {}},
    {"slot_questions": {"booking_reference": "   "}},
    {"required_slots": ["booking_reference", "booking_reference"]},
    {"channels": []},
    {"channels": ["unsupported_channel"]},
])
def test_invalid_addition_never_changes_catalog(client, changes):
    previous = client.get("/v1/catalog?workspace=airline").json()
    versions = client.get("/v1/catalog/versions?workspace=airline").json()
    response = client.post("/v1/catalog/intents?workspace=airline", json={
        "expected_version": previous["version"], "intent": {**definition(), **changes},
    })
    assert response.status_code == 422, response.text
    assert client.get("/v1/catalog?workspace=airline").json() == previous
    assert client.get("/v1/catalog/versions?workspace=airline").json() == versions


def test_stale_creation_preserves_both_the_original_and_other_edit(client):
    previous = client.get("/v1/catalog?workspace=airline").json()
    body = {"expected_version": previous["version"], "intent": definition()}
    assert client.post("/v1/catalog/intents?workspace=airline", json=body).status_code == 201
    current = client.get("/v1/catalog?workspace=airline").json()
    body["intent"]["intent_id"] = "custom.other.reserve"
    assert client.post("/v1/catalog/intents?workspace=airline", json=body).status_code == 409
    assert client.get("/v1/catalog?workspace=airline").json() == current


def test_creation_rejects_catalog_capacity_without_truncating(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled",
                        llm_base_url="", llm_api_key="", openrouter_api_key="")
    with TestClient(create_app(settings)) as current:
        intents = [{**definition(), "intent_id": f"custom.item_{index}", "confusable_with": []} for index in range(2000)]
        assert current.post("/v1/catalog/import?workspace=capacity", json=intents).status_code == 200
        previous = current.get("/v1/catalog?workspace=capacity").json()
        response = current.post("/v1/catalog/intents?workspace=capacity", json={
            "expected_version": previous["version"], "intent": {**definition(), "confusable_with": []},
        })
        assert response.status_code == 422
        assert current.get("/v1/catalog?workspace=capacity").json() == previous
