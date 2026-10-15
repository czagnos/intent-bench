"""Published benchmark content and additive workspace upgrades preserve user data."""
import copy
import json
import sqlite3
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.calibration import question_hash
from app.catalog_presets import workspace_preset
from app.config import ROOT, Settings
from app.main import create_app
from app.store import Store


WORKSPACES = ("demo", "airline", "insurance", "ecommerce")
HARD_CATEGORIES = {"negation", "correction", "noisy_transcript", "ambiguity", "out_of_scope", "handoff"}


def read_json(path):
    return json.loads(path.read_text())


def supplemental(workspace):
    path = workspace_preset(workspace).directory / "benchmark-cases.json"
    return read_json(path) if path.exists() else []


def test_banking_depth_covers_each_core_operation_and_independent_challenges():
    directory = ROOT / "data/demo"
    additions = supplemental("demo")
    base = read_json(directory / "cases.json")
    calibration = read_json(directory / "calibration-cases.json")
    core = {item["intent_id"] for item in read_json(directory / "catalog-core.json")} - {"service.human"}
    counts = Counter(case["expected_intent_id"] for case in base + additions if case["expected_decision"] == "route")
    assert len(core) == 47
    assert all(counts[intent_id] >= 2 for intent_id in core), {iid: counts[iid] for iid in sorted(core) if counts[iid] < 2}
    hard = [case for case in additions if case["challenge"] != "paraphrase"]
    assert len(hard) >= 24
    assert HARD_CATEGORIES <= {case["challenge"] for case in hard}
    catalog = read_json(directory / "catalog.json")
    intent_ids = {item["intent_id"] for item in catalog}
    forbidden = {question_hash(case["question"]) for case in base + calibration}
    forbidden.update(question_hash(example) for intent in catalog for example in intent["examples"])
    observed = set()
    for case in additions:
        assert case["case_id"].startswith("banking-depth-v1-")
        assert case["source"] == "seed" and case["split"] == "test" and case["reviewed"] is True
        assert case["dataset_version"] == "banking-benchmark-depth-v1"
        assert case["label_origin"] == "curated_synthetic"
        assert isinstance(case["context"], dict)
        assert case["expected_decision"] in {"route", "clarify", "out_of_scope", "handoff"}
        if case["expected_decision"] == "route":
            assert case["expected_intent_id"] in intent_ids
        else:
            assert case["expected_intent_id"] is None
        references = set(case["context"].get("clarification_options", []))
        if case["context"].get("active_intent"):
            references.add(case["context"]["active_intent"])
        assert references <= intent_ids
        normalized = question_hash(case["question"])
        assert normalized not in forbidden | observed, case["case_id"]
        observed.add(normalized)
    assert len({case["case_id"] for case in base + calibration + additions}) == len(base + calibration + additions)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled",
                    llm_base_url="", llm_api_key="", openrouter_api_key="")


def revision_id(workspace):
    return f"{workspace_preset(workspace).id}-case-depth-v1"


def base_data(workspace):
    preset = workspace_preset(workspace)
    return [item.model_dump() for item in preset.intents()], [json.loads(case.payload) for case in preset.cases()]


def mark_previous_releases(store, workspace):
    previous = (["demo-800-v1", "demo-taxonomy-v2", "demo-english-v3"] if workspace_preset(workspace).id == "banking"
                else [f"{workspace}-expansion-v2"])
    with store.connect() as db:
        for migration in previous:
            db.execute("INSERT INTO seed_migrations VALUES(?,?)", (workspace, migration))


def seed_current(store, workspace):
    intents, cases = base_data(workspace)
    version = store.save_catalog(workspace, intents)
    store.save_cases(workspace, cases)
    mark_previous_releases(store, workspace)
    return version


@pytest.mark.parametrize("workspace", WORKSPACES)
def test_current_workspace_gains_only_supplement_and_preserves_history(settings, workspace):
    store = Store(settings.data_dir)
    previous = seed_current(store, workspace)
    originals = store.cases(workspace)
    store.save_catalog_snapshot(workspace, {"version": "historical-scope", "intents": store.catalog(workspace)["intents"][:3]})
    job = store.create_job(workspace, "evaluation", {"status": "completed", "catalog_version": previous})
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/catalog", params={"workspace": workspace})
        assert response.status_code == 200 and response.json()["version"] == previous
        actual = {case["case_id"]: case for case in store.cases(workspace)}
        expected = {case["case_id"]: case for case in originals + supplemental(workspace)}
        assert len(supplemental(workspace)) >= 24
        assert actual == expected
        assert len(store.catalog_versions(workspace)) == 1
        assert store.job(workspace, job["id"]) == job
        assert len(store.catalog(workspace, "historical-scope")["intents"]) == 3
        reports = client.get("/v1/catalog/migrations", params={"workspace": workspace}).json()
        assert [report["id"] for report in reports] == [revision_id(workspace)]
        assert reports[0]["applicable"] is True
        assert set(reports[0]["updated_cases"]) == {case["case_id"] for case in supplemental(workspace)}
        assert reports[0]["updated_intents"] == []
        assert reports[0]["from_catalog_version"] == reports[0]["to_catalog_version"] == previous
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/v1/catalog", params={"workspace": workspace}).json() == response.json()
        assert store.migration_reports(workspace) == reports
        assert {case["case_id"]: case for case in store.cases(workspace)} == expected


@pytest.mark.parametrize("workspace", WORKSPACES)
def test_additive_depth_preserves_custom_definitions_reviews_collisions_and_deleted_base(settings, workspace):
    store = Store(settings.data_dir)
    seed_current(store, workspace)
    intents, base = base_data(workspace)
    additions = supplemental(workspace)
    assert additions
    edited_id = next(case["expected_intent_id"] for case in additions if case["expected_decision"] == "route")
    edited = next(item for item in intents if item["intent_id"] == edited_id)
    edited["description"] = "An organization-specific definition that must remain untouched."
    custom = {**copy.deepcopy(edited), "intent_id": "custom.depth.operation", "workflow_id": "workflow.custom.depth.operation"}
    intents.append(custom)
    previous = store.save_catalog(workspace, intents)
    deleted_id = base[0]["case_id"]
    with store.connect() as db:
        db.execute("DELETE FROM cases WHERE workspace=? AND case_id=?", (workspace, deleted_id))
    collision = {**copy.deepcopy(additions[-1]), "source": "customer", "question": "An imported customer record occupying this ID."}
    reviewed = {**copy.deepcopy(additions[-2]), "question": "A human-maintained case occupying this ID."}
    store.save_cases(workspace, [collision, reviewed])
    store.review_case(workspace, reviewed["case_id"], {"expected_decision": "out_of_scope", "expected_intent_id": None, "split": "dev"})
    history = store.case_versions(workspace, reviewed["case_id"])
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": workspace}).json() == {"version": previous, "intents": intents}
        cases = {case["case_id"]: case for case in store.cases(workspace)}
        assert deleted_id not in cases
        assert cases[collision["case_id"]] == collision
        assert store.case_versions(workspace, reviewed["case_id"]) == history
        assert cases[reviewed["case_id"]] == history["current"]
        unsafe = {case["case_id"] for case in additions if case["expected_intent_id"] == edited_id}
        assert unsafe and not (unsafe - {collision["case_id"], reviewed["case_id"]}) & cases.keys()
        report = store.migration_reports(workspace)[-1]
        assert edited_id in report["preserved_intents"]
        assert {collision["case_id"], reviewed["case_id"]} <= set(report["preserved_cases"])
        assert len(store.catalog_versions(workspace)) == 2


@pytest.mark.parametrize("workspace", WORKSPACES)
def test_depth_skips_cases_referencing_customized_context_and_human_definitions(settings, workspace):
    store = Store(settings.data_dir)
    seed_current(store, workspace)
    intents, _ = base_data(workspace)
    additions = supplemental(workspace)
    contextual = next(case for case in additions if case["context"].get("clarification_options"))
    unsafe_id = contextual["context"]["clarification_options"][0]
    for intent in intents:
        if intent["intent_id"] in {unsafe_id, "service.human"}:
            intent["description"] = "Customized behavior: bundled labels no longer apply."
    previous = store.save_catalog(workspace, intents)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": workspace}).json()["version"] == previous
        case_ids = {case["case_id"] for case in store.cases(workspace)}
        assert contextual["case_id"] not in case_ids
        handoffs = {case["case_id"] for case in additions if case["expected_decision"] == "handoff"}
        assert handoffs and not handoffs & case_ids
        skipped = set(store.migration_reports(workspace)[-1]["skipped_cases"])
        assert {contextual["case_id"], *handoffs} <= skipped


@pytest.mark.parametrize("workspace", WORKSPACES)
@pytest.mark.parametrize("kind", ["trimmed", "unrelated"])
def test_depth_leaves_unrecognized_current_catalogs_untouched(settings, workspace, kind):
    store = Store(settings.data_dir)
    seed_current(store, workspace)
    intents, original_cases = base_data(workspace)
    if kind == "trimmed":
        intents = intents[:-1]
    else:
        for item in intents:
            if item["intent_id"] != "service.human":
                item["description"] = "Completely redefined by this organization."
    previous = store.save_catalog(workspace, intents)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/catalog", params={"workspace": workspace}).json() == {"version": previous, "intents": intents}
        assert store.cases(workspace) == original_cases
        report = store.migration_reports(workspace)[-1]
        assert report["id"] == revision_id(workspace)
        assert report["applicable"] is False and report["skipped_reason"] == "unrecognized_catalog"


@pytest.mark.parametrize("workspace", WORKSPACES)
def test_completed_depth_never_resurrects_deleted_supplement(settings, workspace):
    store = Store(settings.data_dir)
    deleted_id = supplemental(workspace)[0]["case_id"]
    with TestClient(create_app(settings)) as client:
        client.get("/v1/catalog", params={"workspace": workspace}).raise_for_status()
        original_count = len(store.cases(workspace))
        with store.connect() as db:
            db.execute("DELETE FROM cases WHERE workspace=? AND case_id=?", (workspace, deleted_id))
    with TestClient(create_app(settings)) as restarted:
        restarted.get("/v1/catalog", params={"workspace": workspace}).raise_for_status()
        assert len(store.cases(workspace)) == original_count - 1
        assert deleted_id not in {case["case_id"] for case in store.cases(workspace)}
        assert len(store.catalog_versions(workspace)) == 1


@pytest.mark.parametrize("workspace", WORKSPACES)
@pytest.mark.parametrize("starting_state", ["current", "empty"])
def test_depth_case_failure_rolls_back_and_same_process_retry_recovers(settings, workspace, starting_state):
    # The default demo is initialized while constructing the app. A separate banking
    # workspace lets this exercise request-time failure and retry in the same server.
    workspace = "banking-depth-retry" if workspace == "demo" else workspace
    store = Store(settings.data_dir)
    if starting_state == "current":
        seed_current(store, workspace)
    before_catalog, before_cases = store.catalog(workspace), store.cases(workspace)
    failing_id = supplemental(workspace)[1]["case_id"]
    # A real SQLite boundary failure occurs after at least one supplemental insert.
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_depth BEFORE INSERT ON cases
            WHEN NEW.workspace = '{workspace}' AND NEW.case_id = '{failing_id}'
            BEGIN SELECT RAISE(ABORT, 'injected depth failure'); END""")
    with TestClient(create_app(settings)) as client:
        with pytest.raises(sqlite3.IntegrityError, match="injected depth failure"):
            client.get("/v1/catalog", params={"workspace": workspace})
        assert store.catalog(workspace) == before_catalog
        assert store.cases(workspace) == before_cases
        assert store.migration_reports(workspace) == []
        with store.connect() as db:
            db.execute("DROP TRIGGER reject_depth")
        response = client.get("/v1/catalog", params={"workspace": workspace})
        assert response.status_code == 200
        assert len(store.cases(workspace)) == len(base_data(workspace)[1]) + len(supplemental(workspace))
        assert len(store.catalog_versions(workspace)) == 1
        assert store.migration_reports(workspace)[-1]["id"] == revision_id(workspace)
