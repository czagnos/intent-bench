"""Operator commands exercise real catalogs and indexes with an HTTP boundary."""
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from app.config import ROOT, Settings
from app.contracts import Intent
from app.model_registry import ModelRegistry, Registration
from app.store import Store


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reindex = load_script("reindex")
warm_models = load_script("warm_models")


def settings_for(directory: Path) -> Settings:
    return Settings(_env_file=None, data_dir=directory, model_credentials_file=directory / "keys.env",
                    embedding_mode="http", embedding_base_url="https://default.example/v1",
                    embedding_model="default-model", embedding_profile="e5",
                    embedding_api_key="default-private-key", openrouter_api_key="unused-private-key")


def intents() -> list[Intent]:
    return [Intent(intent_id="card.limit", name="Card limit", domain="card",
                   description="Change card limit", examples=["Raise my limit", "Lower my limit"],
                   workflow_id="card_limit"),
            Intent(intent_id="account.balance", name="Account balance", domain="account",
                   description="Show balance", examples=["What is my balance?"],
                   workflow_id="account_balance")]


def respond(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/embeddings", "Index commands must never call an LLM"
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": n, "embedding": [1., float(n + 1)]}
                                                 for n in range(len(texts))]})
    return httpx.MockTransport(handler)


def test_reindex_selects_registered_embedding_and_pinned_catalog_without_query(tmp_path, capsys):
    settings = settings_for(tmp_path)
    store = Store(tmp_path)
    original = intents()
    version = store.save_catalog("bank", [i.model_dump() for i in original])
    current = store.save_catalog("bank", [original[0].model_dump()])
    settings.model_credentials_file.write_text("INTENT_MODEL_KEY_TEST=registered-private-key\n")
    record = ModelRegistry(settings, store).save("bank", Registration(
        kind="embedding", name="Bank encoder", model="bank-model", connection="onprem",
        base_url="https://bank.example/v1", auth="env", credential_env="INTENT_MODEL_KEY_TEST", profile="e5"))
    requests: list[httpx.Request] = []

    result = reindex.main(["--workspace", "bank", "--embedding-id", record["id"],
                           "--catalog-version", version, "--representation", "separate"],
                          settings=settings, transport=respond(requests))

    assert result == 0
    assert len(requests) == 1, "A full reindex must send all corpus documents to the selected encoder"
    request = requests[0]
    assert str(request.url) == "https://bank.example/v1/embeddings"
    assert request.headers["Authorization"] == "Bearer registered-private-key"
    assert json.loads(request.content)["model"] == "bank-model"
    assert json.loads(request.content)["input"] == [
        "passage: Raise my limit", "passage: Lower my limit", "passage: What is my balance?",
        "passage: Card limit. Change card limit", "passage: Account balance. Show balance"]
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["workspace"] == "bank"
    assert summary["catalog_version"] == version
    assert summary["embedding_id"] == record["id"]
    assert summary["model"] == "bank-model"
    assert summary["representation"] == "separate"
    assert summary["intent_count"] == 2
    assert summary["document_count"] == 5
    assert summary["dimensions"] == 2
    assert summary["source"] == "rebuilt"
    assert summary["generation"]
    assert summary["elapsed_ms"] >= 0
    assert Path(summary["path"]).is_file()
    assert "private-key" not in output
    assert store.catalog("bank")["version"] == current
    assert store.catalog("demo") is None


@pytest.mark.parametrize("arguments", [
    ["--workspace", "missing"],
    ["--catalog-version", "missing-version"],
    ["--embedding-id", "missing-model"],
])
@pytest.mark.parametrize("command", [reindex.main, warm_models.main])
def test_index_commands_reject_missing_selection_without_seeding_or_inference(tmp_path, capsys, arguments, command):
    settings = settings_for(tmp_path)
    store = Store(tmp_path)
    version = store.save_catalog("demo", [i.model_dump() for i in intents()])
    requests: list[httpx.Request] = []

    assert command(arguments, settings=settings, transport=respond(requests)) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]
    assert requests == []
    assert store.catalog("missing") is None
    assert store.catalog("demo")["version"] == version
    assert not list((tmp_path / "vector-indexes").glob("*.npz"))


def test_warm_reports_corruption_until_explicit_reindex_repairs_it(tmp_path, capsys):
    settings = settings_for(tmp_path)
    Store(tmp_path).save_catalog("demo", [i.model_dump() for i in intents()])
    requests: list[httpx.Request] = []
    assert reindex.main([], settings=settings, transport=respond(requests)) == 0
    summary = json.loads(capsys.readouterr().out)
    path = Path(summary["path"])
    path.write_bytes(b"invalid-private-file-content")
    requests.clear()

    assert warm_models.main([], settings=settings, transport=respond(requests)) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "reindex" in json.loads(output.err)["error"]
    assert "invalid-private-file-content" not in output.err
    assert requests == []

    assert reindex.main([], settings=settings, transport=respond(requests)) == 0
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["generation"] != summary["generation"]
    assert rebuilt["source"] == "rebuilt"
    assert len(requests) == 1
    requests.clear()
    assert warm_models.main([], settings=settings, transport=respond(requests)) == 0
    assert json.loads(capsys.readouterr().out)["generation"] == rebuilt["generation"]
    assert requests == []


def test_reindex_replaces_entire_generation_and_failed_rebuild_preserves_it(tmp_path, capsys):
    settings = settings_for(tmp_path)
    version = Store(tmp_path).save_catalog("demo", [i.model_dump() for i in intents()])
    requests: list[httpx.Request] = []
    transport = respond(requests)

    assert reindex.main([], settings=settings, transport=transport) == 0
    first = json.loads(capsys.readouterr().out)
    assert reindex.main([], settings=settings, transport=transport) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["workspace"] == "demo"
    assert second["embedding_id"] == "default"
    assert second["catalog_version"] == version
    assert second["representation"] == "combined"
    assert second["generation"] != first["generation"]
    assert second["path"] == first["path"]
    assert len(requests) == 2
    assert [json.loads(r.content)["input"] for r in requests] == [[
        "passage: Card limit. Change card limit Raise my limit",
        "passage: Card limit. Change card limit Lower my limit",
        "passage: Account balance. Show balance What is my balance?"]]*2
    path = Path(second["path"])
    original = path.read_bytes()

    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "provider-private-key"}})

    assert reindex.main([], settings=settings, transport=httpx.MockTransport(unavailable)) == 1
    failure = capsys.readouterr()
    assert failure.out == ""
    assert json.loads(failure.err)["error"]
    assert "private-key" not in failure.err
    assert path.read_bytes() == original
    assert len(list(path.parent.glob("*.npz"))) == 1


def test_warm_builds_once_and_fresh_invocation_loads_disk_without_query(tmp_path, capsys):
    settings = settings_for(tmp_path)
    settings.retrieval_representation = "separate"
    Store(tmp_path).save_catalog("demo", [i.model_dump() for i in intents()])
    requests: list[httpx.Request] = []

    assert warm_models.main([], settings=settings, transport=respond(requests)) == 0
    assert len(requests) == 1, "Warming must prepare only the corpus, with no throwaway query"
    first = json.loads(capsys.readouterr().out)
    assert first["source"] == "built"
    assert first["document_count"] == 5
    assert first["representation"] == "separate"
    requests.clear()

    assert warm_models.main([], settings=settings, transport=respond(requests)) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["source"] == "disk"
    assert second["generation"] == first["generation"]
    assert second["path"] == first["path"]
    assert requests == []
