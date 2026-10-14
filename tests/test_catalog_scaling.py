import copy
import json
import math
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.calibration import question_hash
from app.catalog_scope import core_ids, select_catalogs
from app.config import ROOT, Settings
from app.contracts import Intent
from app.main import create_app
from app.store import Store


def catalog_file(name="catalog.json"):
    return [Intent.model_validate(i).model_dump() for i in json.loads((ROOT / "data/demo" / name).read_text())]


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled", llm_base_url="", llm_api_key="", openrouter_api_key="")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def wait(client, response):
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get("/v1/evaluations/" + response.json()["id"]).json()
        if job["status"] not in ("queued", "running"):
            assert job["status"] == "completed", job.get("error")
            return job
        time.sleep(.02)
    pytest.fail("Catalog experiment timed out")


def test_catalog_has_800_distinct_intents_and_unchanged_core():
    expanded, core = catalog_file(), catalog_file("catalog-core.json")
    assert len(expanded) == len({i["intent_id"] for i in expanded}) == 800
    assert expanded[:48] == core
    assert len({i["name"] for i in expanded}) == 800
    assert len({question_hash(e) for i in expanded for e in i["examples"]}) == sum(len(i["examples"]) for i in expanded)
    ids = {i["intent_id"] for i in expanded}
    assert all(set(i["confusable_with"]) <= ids for i in expanded)
    assert not any(i["intent_id"].startswith("bank.card.virtual.") and i["intent_id"].endswith((".delivery", ".damaged")) for i in expanded)


def test_existing_demo_migrates_once_preserving_edits_cases_and_history(settings):
    store = Store(settings.data_dir)
    old = catalog_file("catalog-core.json")
    old[0]["name"] = "Müşterinin düzenlediği ad"
    version = store.save_catalog("demo", old)
    case = {"case_id": "customer-reviewed", "source": "customer", "dataset_version": "original", "reviewed": True,
            "split": "test", "question": "Özel müşteri sorusu", "expected_decision": "route", "expected_intent_id": old[0]["intent_id"]}
    store.save_cases("demo", [case])
    with TestClient(create_app(settings)) as client:
        current = client.get("/v1/catalog").json()
        assert len(current["intents"]) == 800
        assert current["intents"][0]["name"] == old[0]["name"]
        assert client.app.state.studio.store.catalog("demo", version)["intents"] == old
        assert client.app.state.studio.store.cases("demo", source="customer") == [case]
        assert len(client.app.state.studio.store.catalog_versions("demo")) == 2
    with TestClient(create_app(settings)) as restarted:
        assert len(restarted.get("/v1/catalog/versions").json()) == 2


def test_custom_catalog_is_not_replaced_on_restart(settings):
    store = Store(settings.data_dir)
    custom = catalog_file("catalog-core.json")[:2]
    version = store.save_catalog("demo", custom)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog").json() == {"version": version, "intents": custom}


def test_subsets_are_exact_nested_and_reproducible(client):
    catalog = client.get("/v1/catalog").json()
    scopes = select_catalogs(catalog, [800, 100, 48, 100], [], seed=42)
    assert [len(s["intents"]) for s in scopes] == [48, 100, 800]
    sets = [set(s["metadata"]["intent_ids"]) for s in scopes]
    assert sets[0] == core_ids() and sets[0] < sets[1] < sets[2]
    assert scopes == select_catalogs(catalog, [48, 100, 800], [], seed=42)
    assert scopes[1]["version"] != select_catalogs(catalog, [100], [], seed=43)[0]["version"]
    assert scopes[-1]["version"] == catalog["version"]


def test_protects_customer_gold_and_context_intents_without_dropping_cases(client):
    catalog = client.get("/v1/catalog").json()
    extra = catalog["intents"][48:51]
    cases = [{"expected_intent_id": extra[0]["intent_id"], "context": {"active_intent": extra[1]["intent_id"], "clarification_options": [{"intent_id": extra[2]["intent_id"]}]}}]
    with pytest.raises(ValueError, match="6 ile 800"):
        select_catalogs(catalog, [5], cases)
    scope = select_catalogs(catalog, [48], cases)[0]
    assert {i["intent_id"] for i in extra} <= set(scope["metadata"]["intent_ids"])


def test_scale_run_keeps_same_denominators_and_does_not_change_live_catalog(client):
    version = client.get("/v1/catalog").json()["version"]
    job = wait(client, client.post("/v1/evaluations", json={"methods": ["lexical"], "catalog_sizes": [48, 100, 800]}))
    assert job["selected_count"] == 29 and job["total"] == 87
    results = list(job["results"].values())
    assert [r["catalog"]["intent_count"] for r in results] == [48, 100, 800]
    assert all(r["metrics"]["routing_total"] == 26 and r["metrics"]["oos_total"] == 3 for r in results)
    assert all([c["case_id"] for c in r["records"]] == [c["case_id"] for c in results[0]["records"]] for r in results)
    assert all(r["scaling"]["baseline_intent_count"] == 48 for r in results)
    assert all(r["metrics"]["stage_latency_ms"]["retrieval"]["count"] == 29 for r in results)
    assert client.get("/v1/catalog").json()["version"] == version
    assert len(client.get("/v1/catalog/versions").json()) == 1
    assert client.get("/v1/status").json()["intent_count"] == 800


@pytest.mark.parametrize("sizes", [[], [0], [801], [20], [True], [48.5], list(range(48, 57))])
def test_invalid_sizes_fail_before_queueing(client, sizes):
    response = client.post("/v1/evaluations", json={"catalog_sizes": sizes})
    assert response.status_code == 422
    assert client.get("/v1/evaluations").json() == []


def test_snapshots_remain_pinned_when_live_catalog_changes(client, monkeypatch):
    studio = client.app.state.studio
    pending = []
    monkeypatch.setattr(studio.evaluation_pool, "submit", lambda f, *args: pending.append((f, args)))
    response = client.post("/v1/evaluations", json={"catalog_sizes": [48, 100], "limit": 2})
    assert response.status_code == 202
    original = studio.store.catalog("demo")
    changed = copy.deepcopy(original["intents"])
    changed[0]["description"] = "Deney kuyruğa alındıktan sonra değişen açıklama."
    new_version = studio.store.save_catalog("demo", changed)
    function, args = pending[0]
    function(*args)
    job = client.get("/v1/evaluations/" + response.json()["id"]).json()
    assert job["status"] == "completed" and job["catalog_version"] == original["version"]
    assert studio.store.catalog("demo")["version"] == new_version
    for result in job["results"].values():
        assert studio.store.catalog("demo", result["catalog"]["version"])["intents"][0]["description"] != changed[0]["description"]


def test_semantic_refits_each_scope_without_llm_or_test_leakage(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_mode="http", embedding_base_url="https://embedding.test/v1",
                        embedding_model="test-model", embedding_profile="plain", llm_base_url="", openrouter_api_key="")
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        known = {c["question"]: c["expected_decision"] != "out_of_scope" for c in studio.store.cases("demo")}
        small, large = select_catalogs(studio.store.catalog("demo"), [48, 100],
                                      studio.store.cases("demo", "seed", split="test")[:2],
                                      studio.calibrator.cases("demo", "seed"))
        small_ids = set(small["metadata"]["intent_ids"])
        distractor = next(i["name"] + "." for i in large["intents"] if i["intent_id"] not in small_ids)
        queries = []
        def respond(request):
            assert request.url.path.endswith("/embeddings")
            body = json.loads(request.content)
            values = []
            for text in body["input"]:
                if text in known:
                    queries.append(text)
                    score = .9 if known[text] else .1
                    values.append([score, math.sqrt(1-score*score)])
                else:
                    values.append([0., 1.] if text.startswith(distractor) else [1., 0.])
            return httpx.Response(200, json={"data": [{"index": i, "embedding": v} for i, v in enumerate(values)]})
        studio.embeddings.transport = httpx.MockTransport(respond)
        job = wait(client, client.post("/v1/evaluations", json={"methods": ["e5"], "catalog_sizes": [48, 100], "limit": 2}))
        fits = job["calibration_fits"]
        assert len(fits) == 2 and fits[0]["threshold"] != fits[1]["threshold"]
        assert fits[0]["metrics"]["in_scope_accept_rate"] == 1
        assert fits[1]["metrics"]["in_scope_accept_rate"] == 0
        calibration_ids = {c["case_id"] for c in studio.calibrator.cases("demo", "seed")}
        for fit, result in zip(fits, job["results"].values()):
            assert {r["case_id"] for r in fit["records"]} == calibration_ids
            assert not calibration_ids & {r["case_id"] for r in result["records"]}
            assert result["calibration"]["catalog_version"] == result["catalog"]["version"]
            assert result["calibration_build_ms"] > 0
        assert len(queries) == 2*(72+2)
        assert studio.store.latest_calibration("demo", "unused") is None


def test_matrix_cap_includes_catalog_sizes(client, monkeypatch):
    studio = client.app.state.studio
    variant = studio.model_catalog.variant("lexical")
    monkeypatch.setattr(studio.model_catalog, "expand", lambda options, workspace="demo": [variant]*5)
    response = client.post("/v1/evaluations", json={"catalog_sizes": [48, 100, 200, 300, 400, 500, 800]})
    assert response.status_code == 422 and "32" in response.json()["detail"]
    assert client.get("/v1/evaluations").json() == []
