import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_base_url="",
                        embedding_mode="disabled", model_credentials_file=tmp_path / "model.env")
    with TestClient(create_app(settings)) as client:
        yield client


def test_public_model_connections_accept_only_supported_protocols_and_external_credentials(client):
    schema = client.get("/openapi.json").json()
    registration = schema["components"]["schemas"]["Registration"]["properties"]
    assert set(registration["connection"]["enum"]) == {"openrouter", "onprem", "typesafe"}
    assert set(registration["auth"]["enum"]) == {"shared_openrouter", "env", "none"}
    assert "/v1/model-registry/{model_id}/credential" not in schema["paths"]
    assert client.post("/v1/model-registry/model_" + "a" * 32 + "/credential",
                       json={"api_key": "synthetic-secret"}).status_code == 404
    unsupported = {"kind": "llm", "name": "Unsupported model", "model": "unavailable-model",
                   "connection": "unsupported", "auth": "none", "base_url": "https://model.example/v1"}
    assert client.post("/v1/model-registry", json=unsupported).status_code == 422
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_protocol="unsupported")


@pytest.mark.parametrize("retired_settings", [
    {"connection": "unsupported"},
    {"auth": "stored"},
    {"connection": "unsupported", "auth": "stored"},
])
def test_unsupported_saved_connection_is_hidden_and_unusable_without_deleting_private_data(client, retired_settings):
    body = {"kind": "llm", "name": "Local model", "model": "local-model", "connection": "onprem",
            "auth": "none", "base_url": "http://localhost:8001/v1"}
    created = client.post("/v1/model-registry", json=body)
    assert created.status_code == 201
    model_id = created.json()["id"]
    studio = client.app.state.studio
    record = studio.store.model_registration("demo", model_id)
    record.update(**retired_settings, name="Private archived model", model="archived-model",
                  base_url="https://private.example/v1", description="Private archived connection metadata")
    studio.store.save_model_registration("demo", record, update=True)

    for path in ("/v1/model-registry", "/v1/models", "/v1/methods", "/v1/status"):
        response = client.get(path)
        assert response.status_code == 200
        for private_value in (model_id, record["name"], record["model"], record["base_url"], record["description"]):
            assert private_value not in response.text
    assert client.post(f"/v1/model-registry/{model_id}/check").status_code == 404
    assert client.patch(f"/v1/model-registry/{model_id}", json=body).status_code == 404
    with pytest.raises(ValueError, match="Unknown"):
        studio.model_catalog.resolve("llm", model_id)
    assert studio.store.model_registration("demo", model_id) == record
