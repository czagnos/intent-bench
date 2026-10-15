"""Expanded sector presets upgrade only recognized, untouched starter records."""
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.catalog_presets import SeedCase, workspace_preset
from app.config import ROOT, Settings
from app.main import create_app
from app.store import Store


SECTORS = ("airline", "insurance", "ecommerce")


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled",
                    llm_base_url="", llm_api_key="", openrouter_api_key="")


def baseline(sector):
    return json.loads((ROOT / f"tests/fixtures/{sector}-preset-v1.json").read_text())


def targets(sector):
    preset = workspace_preset(sector)
    return {"intents": [i.model_dump() for i in preset.intents()],
            "cases": [json.loads(c.payload) for c in preset.cases()]}


def depth_cases(sector):
    return [json.loads(case.payload) for case in workspace_preset(sector).benchmark_cases()]


def seed(store, sector, data):
    version = store.save_catalog(sector, data["intents"])
    store.save_cases(sector, data["cases"])
    return version


@pytest.mark.parametrize("sector", SECTORS)
def test_pristine_sector_upgrade_and_restart_preserve_catalog_history(settings, sector):
    store = Store(settings.data_dir)
    old = baseline(sector)
    previous = seed(store, sector, old)
    job = store.create_job(sector, "evaluation", {"status": "completed", "catalog_version": previous})
    store.save_catalog_snapshot(sector, {"version": "archived-experiment", "intents": old["intents"]})
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/catalog", params={"workspace": sector})
        assert response.status_code == 200
        assert response.json()["intents"] == targets(sector)["intents"]
        assert len(response.json()["intents"]) == 200
        reports = client.get("/v1/catalog/migrations", params={"workspace": sector}).json()
        assert [report["id"] for report in reports] == [f"{sector}-expansion-v2", f"{sector}-case-depth-v1"]
        assert reports[0]["applicable"] is True
        assert len(reports[0]["updated_cases"]) == 237
        assert len(store.cases(sector)) == 510
        assert {c["case_id"]: c for c in store.cases(sector)} == {c["case_id"]: c for c in targets(sector)["cases"] + depth_cases(sector)}
        assert len(reports[1]["updated_cases"]) == 225
        assert reports[1]["from_catalog_version"] == reports[1]["to_catalog_version"]
        assert len(store.catalog_versions(sector)) == 2
        assert store.catalog(sector, previous)["intents"] == old["intents"]
        assert store.catalog(sector, "archived-experiment")["intents"] == old["intents"]
        assert store.job(sector, job["id"]) == job
        expected = response.json()
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": sector}).json() == expected
        assert len(store.catalog_versions(sector)) == 2
        assert store.migration_reports(sector) == reports
        assert len(store.cases(sector)) == 510


def test_upgrade_preserves_edits_custom_definitions_case_collisions_reviews_and_deletions(settings):
    sector = "airline"
    store = Store(settings.data_dir)
    old, target = baseline(sector), targets(sector)
    old_ids = {i["intent_id"] for i in old["intents"]}
    old_case_ids = {c["case_id"] for c in old["cases"]}
    added_cases = [c for c in target["cases"] if c["case_id"] not in old_case_ids]
    edited_id = next(c["expected_intent_id"] for c in added_cases if c["expected_intent_id"] in old_ids)
    edited = next(i for i in old["intents"] if i["intent_id"] == edited_id)
    edited["description"] = "Our custom routing policy must survive the bundled expansion."
    collision = copy.deepcopy(next(i for i in target["intents"] if i["intent_id"] not in old_ids))
    collision["description"] = "A user already owns this newly introduced intent ID."
    custom = {**copy.deepcopy(collision), "intent_id": "custom.travel", "workflow_id": "workflow.custom.travel"}
    old["intents"] += [collision, custom]
    previous = seed(store, sector, old)
    reviewed_id = old["cases"][0]["case_id"]
    store.review_case(sector, reviewed_id, {"expected_decision": "out_of_scope", "expected_intent_id": None, "split": "dev"})
    reviewed = store.case_versions(sector, reviewed_id)
    deleted_id = old["cases"][1]["case_id"]
    with store.connect() as db:
        db.execute("DELETE FROM cases WHERE workspace=? AND case_id=?", (sector, deleted_id))
    customer = {**copy.deepcopy(added_cases[-1]), "source": "customer", "question": "A preserved customer import."}
    store.save_cases(sector, [customer])
    imported = {"dataset_version": "customer-import", "filename": "customers.csv"}
    store.save_import(sector, imported)
    with TestClient(create_app(settings)) as client:
        catalog = client.get("/v1/catalog", params={"workspace": sector}).json()
        by_id = {i["intent_id"]: i for i in catalog["intents"]}
        assert len(by_id) == 201
        assert by_id[edited_id] == edited
        assert by_id[collision["intent_id"]] == collision
        assert by_id[custom["intent_id"]] == custom
        assert store.catalog(sector, previous)["intents"] == old["intents"]
        assert store.case_versions(sector, reviewed_id) == reviewed
        assert store.imports(sector) == [imported]
        cases = {c["case_id"]: c for c in store.cases(sector)}
        assert deleted_id not in cases
        assert cases[customer["case_id"]] == customer
        unsafe_cases = {c["case_id"] for c in added_cases if c["expected_intent_id"] in {edited_id, collision["intent_id"]}}
        assert unsafe_cases and not unsafe_cases & cases.keys()
        report = store.migration_reports(sector)[0]
        assert {edited_id, collision["intent_id"]} <= set(report["preserved_intents"])
        assert {reviewed_id, customer["case_id"]} <= set(report["preserved_cases"])


@pytest.mark.parametrize("kind", ["trimmed", "unrelated"])
def test_upgrade_skips_trimmed_and_unrelated_catalogs_even_with_shared_human_intent(settings, kind):
    sector = "insurance"
    store = Store(settings.data_dir)
    old = baseline(sector)
    if kind == "trimmed":
        old["intents"] = old["intents"][1:]
    else:
        for intent in old["intents"]:
            if intent["intent_id"] != "service.human":
                intent["description"] = "This is a fully customized company-specific routing definition."
    version = seed(store, sector, old)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": sector}).json() == {"version": version, "intents": old["intents"]}
        assert store.cases(sector) == old["cases"]
        report = store.migration_reports(sector)[0]
        assert report["applicable"] is False
        assert report["skipped_reason"] == "unrecognized_catalog"
        assert len(store.catalog_versions(sector)) == 1


def test_capacity_limit_skips_entire_upgrade_and_records_reason(settings):
    sector = "ecommerce"
    store = Store(settings.data_dir)
    old = baseline(sector)
    exemplar = old["intents"][0]
    old["intents"] += [{**copy.deepcopy(exemplar), "intent_id": f"custom.operation_{n}", "workflow_id": f"workflow.custom.operation_{n}"}
                       for n in range(2000 - len(old["intents"]))]
    version = seed(store, sector, old)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": sector}).json() == {"version": version, "intents": old["intents"]}
        assert store.cases(sector) == old["cases"]
        report = store.migration_reports(sector)[0]
        assert report["applicable"] is True
        assert report["skipped_reason"] == "capacity_exceeded"
        assert report["updated_intents"] == report["updated_cases"] == []
        assert len(store.catalog_versions(sector)) == 1


def test_failed_case_insert_rolls_back_upgrade_and_retry_succeeds(settings):
    sector = "airline"
    store = Store(settings.data_dir)
    old = baseline(sector)
    version = seed(store, sector, old)
    previous_ids = {c["case_id"] for c in old["cases"]}
    added_id = next(c["case_id"] for c in targets(sector)["cases"] if c["case_id"] not in previous_ids)
    # SQLite triggers provide a real storage failure after the catalog write.
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_sector_growth BEFORE INSERT ON cases
            WHEN NEW.workspace = 'airline' AND NEW.case_id = '{added_id}'
            BEGIN SELECT RAISE(ABORT, 'injected upgrade failure'); END""")
    with TestClient(create_app(settings)) as client:
        with pytest.raises(sqlite3.IntegrityError, match="injected upgrade failure"):
            client.get("/v1/catalog", params={"workspace": sector})
        assert store.catalog(sector) == {"version": version, "intents": old["intents"]}
        assert store.cases(sector) == old["cases"]
        assert store.migration_reports(sector) == []
        assert len(store.catalog_versions(sector)) == 1
        with store.connect() as db:
            db.execute("DROP TRIGGER reject_sector_growth")
        assert len(client.get("/v1/catalog", params={"workspace": sector}).json()["intents"]) == 200
        assert len(store.cases(sector)) == 510
        assert len(store.migration_reports(sector)) == 2
        assert len(store.catalog_versions(sector)) == 2


@pytest.mark.parametrize("starting_state", ["old", "empty"])
def test_concurrent_app_instances_publish_one_complete_revision(settings, starting_state):
    sector = "insurance"
    store = Store(settings.data_dir)
    if starting_state == "old":
        seed(store, sector, baseline(sector))
    with TestClient(create_app(settings)) as first, TestClient(create_app(settings)) as second:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.get, "/v1/catalog", params={"workspace": sector}) for client in (first, second)]
            responses = [future.result().json() for future in futures]
        assert responses[0] == responses[1]
        assert len(responses[0]["intents"]) == 200
        assert len(store.cases(sector)) == 510
        assert len(store.catalog_versions(sector)) == (2 if starting_state == "old" else 1)
        assert len(store.migration_reports(sector)) == 2


def test_upgrade_only_adds_cases_whose_expected_and_context_intents_remain_safe(settings):
    sector = "insurance"
    store = Store(settings.data_dir)
    old = baseline(sector)
    edited = old["intents"][0]
    edited["description"] = "An edited definition whose seed labels are no longer known to match."
    edited_id = edited["intent_id"]
    safe_id = old["intents"][1]["intent_id"]
    seed(store, sector, old)
    variants = [
        ("unsafe-expected", "route", edited_id, {}),
        ("unsafe-active", "route", safe_id, {"active_intent": edited_id}),
        ("unsafe-options", "clarify", None, {"clarification_options": [safe_id, edited_id]}),
        ("safe-context", "route", safe_id, {"active_intent": safe_id, "clarification_options": [safe_id]}),
        ("safe-oos", "out_of_scope", None, {}),
    ]
    cases = []
    for case_id, decision, intent_id, context in variants:
        payload = {**old["cases"][0], "case_id": case_id, "expected_decision": decision,
                   "expected_intent_id": intent_id, "context": context}
        cases.append(SeedCase(case_id=case_id, source="seed", dataset_version="test-v2",
                              reviewed=True, split="test", payload=json.dumps(payload)))
    preset = workspace_preset(sector)
    store.expand_preset(sector, preset.revisions()[0], preset.intents(), cases)
    by_id = {case["case_id"]: case for case in store.cases(sector)}
    assert all(case_id not in by_id for case_id in ("unsafe-expected", "unsafe-active", "unsafe-options"))
    assert {"safe-context", "safe-oos"} <= by_id.keys()
    report = store.migration_reports(sector)[0]
    assert set(report["updated_cases"]) == {"safe-context", "safe-oos"}
    assert set(report["skipped_cases"]) == {"unsafe-expected", "unsafe-active", "unsafe-options"}
    assert report["preserved_cases"] == []


def test_normalized_legacy_definitions_upgrade_without_restoring_missing_old_cases(settings):
    sector = "ecommerce"
    store = Store(settings.data_dir)
    old = baseline(sector)
    for intent in old["intents"]:
        # These omitted optional fields have the same public meaning as v1 defaults.
        intent.pop("channels")
        intent.pop("required_slots")
        intent.pop("slot_questions")
    store.save_catalog(sector, old["intents"])
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": sector}).json()["intents"] == targets(sector)["intents"]
        cases = store.cases(sector)
        old_case_ids = {case["case_id"] for case in old["cases"]}
        assert len(cases) == 462
        assert not old_case_ids & {case["case_id"] for case in cases}
