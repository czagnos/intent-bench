"""Public behavior of the bundled sector workspaces and custom catalog additions."""
import copy
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.catalog_presets import workspace_preset
from app.config import ROOT, Settings
from app.contracts import Intent
from app.store import Store
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled",
                    llm_base_url="", llm_api_key="", openrouter_api_key="")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as current:
        yield current


def test_presets_are_english_coherent_and_workspace_isolated(client):
    response = client.get("/v1/catalog/presets")
    assert response.status_code == 200
    presets = response.json()
    assert {p["id"] for p in presets} == {"banking", "airline", "insurance", "ecommerce"}
    assert {p["workspace"] for p in presets} == {"demo", "airline", "insurance", "ecommerce"}
    for preset in presets:
        workspace = preset["workspace"]
        catalog = client.get("/v1/catalog", params={"workspace": workspace}).json()
        ids = {i["intent_id"] for i in catalog["intents"]}
        assert len(ids) == preset["intent_count"] >= 50
        assert "service.human" in ids
        assert not any(char in json.dumps(catalog, ensure_ascii=False) for char in "ğşİıçüöĞŞÇÜÖ")
        for item in catalog["intents"]:
            intent = Intent.model_validate(item)
            assert intent.selection_rule and intent.exclusions
            assert set(intent.confusable_with) <= ids
        cases = client.app.state.studio.store.cases(workspace)
        assert all(c.get("expected_intent_id") is None or c["expected_intent_id"] in ids for c in cases)
        calibration = [c for c in cases if c["split"] == "calibration"]
        assert sum(c["expected_decision"] == "route" for c in calibration) >= 10
        assert sum(c["expected_decision"] == "out_of_scope" for c in calibration) >= 10
        examples = {e.casefold().strip() for i in catalog["intents"] for e in i["examples"]}
        questions = {c["question"].casefold().strip() for c in cases if c["split"] == "test"}
        calibration_questions = {c["question"].casefold().strip() for c in calibration}
        assert not calibration_questions & (examples | questions)
        assert client.get("/v1/status", params={"workspace": workspace}).json()["catalog_min_size"] >= 1
    assert client.get("/v1/catalog").json()["intents"][0]["intent_id"] == "card.limit.change"


def test_english_core_upgrade_adds_english_entries_in_one_version(settings):
    store = Store(settings.data_dir)
    core = [Intent.model_validate(i).model_dump() for i in json.loads((ROOT / "data/demo/catalog-core.json").read_text())]
    core[0]["name"] = "My team's card limit intent"
    previous = store.save_catalog("demo", core)
    with TestClient(create_app(settings)) as current:
        catalog = current.get("/v1/catalog").json()
        assert len(catalog["intents"]) == 800
        assert catalog["intents"][0]["name"] == core[0]["name"]
        assert current.get("/v1/catalog", params={"version": previous}).json()["intents"] == core
        assert len(current.get("/v1/catalog/versions").json()) == 2


def historical_seed():
    return json.loads((ROOT / "data/demo/migrations/taxonomy-v2-targets.json").read_text())


@pytest.mark.parametrize("revision", ["v1", "v2"])
def test_pristine_legacy_seed_migrates_in_order_and_preserves_history(settings, revision):
    historical = historical_seed()
    if revision == "v1":
        fixture = json.loads((ROOT / "tests/fixtures/taxonomy-v1.json").read_text())
        old_intents = {i["intent_id"]: Intent.model_validate(i).model_dump() for i in fixture["intents"]}
        old_cases = {c["case_id"]: c for c in fixture["cases"]}
        historical["intents"] = [old_intents.get(i["intent_id"], i) for i in historical["intents"]]
        historical["cases"] = [old_cases.get(c["case_id"], c) for c in historical["cases"]]
    store = Store(settings.data_dir)
    previous = store.save_catalog("demo", historical["intents"])
    store.save_cases("demo", historical["cases"])
    job = store.create_job("demo", "evaluation", {"status": "completed", "catalog_version": previous, "result": "historical"})
    with TestClient(create_app(settings)) as current:
        expected = [Intent.model_validate(i).model_dump() for i in json.loads((ROOT / "data/demo/catalog.json").read_text())]
        assert current.get("/v1/catalog").json()["intents"] == expected
        assert current.get("/v1/catalog", params={"version": previous}).json()["intents"] == historical["intents"]
        assert store.job("demo", job["id"]) == job
        expected_cases = [json.loads(case.payload) for case in workspace_preset("demo").cases() + workspace_preset("demo").benchmark_cases()]
        assert store.cases("demo") == expected_cases
        reports = current.get("/v1/catalog/migrations").json()
        assert [report["id"] for report in reports] == ["demo-taxonomy-v2", "demo-english-v3", "banking-case-depth-v1"]
        if revision == "v1":
            first = store.catalog("demo", reports[0]["to_catalog_version"])
            assert first["intents"] == historical_seed()["intents"]
        history = store.case_versions("demo", "seed-007")
        assert history["versions"][0]["case"] == next(c for c in historical["cases"] if c["case_id"] == "seed-007")
        assert history["current"]["question"] == "I forgot the PIN for my debit card"
        count = len(store.catalog_versions("demo"))
    with TestClient(create_app(settings)) as restarted:
        assert len(restarted.get("/v1/catalog/versions").json()) == count
        assert len(store.migration_reports("demo")) == 3


def test_english_migration_preserves_user_edits_reviews_and_customer_cases(settings):
    historical = historical_seed()
    edited = historical["intents"][0]
    edited["description"] = "Our team's customized description, kept exactly as written."
    custom = {**copy.deepcopy(edited), "intent_id": "custom.balance", "name": "Custom balance", "workflow_id": "workflow.custom.balance"}
    historical["intents"].append(custom)
    store = Store(settings.data_dir)
    store.save_catalog("demo", historical["intents"])
    store.save_cases("demo", historical["cases"])
    store.review_case("demo", "seed-007", {"expected_decision": "route", "expected_intent_id": "card.pin", "split": "test"})
    reviewed = store.case_versions("demo", "seed-007")["current"]
    customer = {**historical["cases"][0], "case_id": "customer-preserved", "source": "customer", "question": "My private user question"}
    store.save_cases("demo", [customer])
    with TestClient(create_app(settings)) as current:
        catalog = current.get("/v1/catalog").json()["intents"]
        assert catalog[0] == edited and catalog[-1] == custom
        assert store.case_versions("demo", "seed-007")["current"] == reviewed
        assert store.cases("demo", "customer") == [customer]
        assert store.case_versions("demo", "seed-001")["current"] == historical["cases"][0]
        assert store.case_versions("demo", "seed-002")["current"]["question"] == "I will pay the entire outstanding credit card balance"


@pytest.mark.parametrize("workspace", ["demo", "airline", "custom_workspace"])
def test_existing_custom_catalog_gets_no_seed_cases_or_replacement(settings, workspace):
    store = Store(settings.data_dir)
    custom = historical_seed()["intents"][:1]
    previous = store.save_catalog(workspace, custom)
    with TestClient(create_app(settings)) as current:
        assert current.get("/v1/catalog", params={"workspace": workspace}).json() == {"version": previous, "intents": custom}
        assert store.cases(workspace) == []


def test_new_sector_calibration_is_valid_for_its_workspace(client):
    for workspace in ("airline", "insurance", "ecommerce"):
        catalog = client.get("/v1/catalog", params={"workspace": workspace}).json()
        studio = client.app.state.studio
        studio.calibrator.validate_cases(workspace, studio.calibrator.cases(workspace, "seed"), catalog)


def test_seed_failure_rolls_back_catalog_and_cases_then_retry_recovers(client):
    store = client.app.state.studio.store
    with store.connect() as db:
        db.executescript("""
            CREATE TRIGGER reject_airline_seed BEFORE INSERT ON cases
            WHEN NEW.workspace = 'airline' AND NEW.case_id = 'airline-calibration-v1-001'
            BEGIN SELECT RAISE(ABORT, 'injected seed storage failure'); END;
        """)
    with pytest.raises(sqlite3.IntegrityError, match="injected seed storage failure"):
        client.get("/v1/catalog", params={"workspace": "airline"})
    assert store.catalog("airline") is None
    assert store.cases("airline") == []
    with store.connect() as db:
        db.execute("DROP TRIGGER reject_airline_seed")
    response = client.get("/v1/catalog", params={"workspace": "airline"})
    assert response.status_code == 200
    assert len(response.json()["intents"]) == 200
    assert len(store.cases("airline")) == 510
    assert len(store.catalog_versions("airline")) == 1
