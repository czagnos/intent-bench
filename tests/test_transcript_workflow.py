"""Transcript behavior through real API, storage, workers, and HTTP boundaries."""
import json
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from test_transcript_import import source_turn, transcript_csv
from test_studio import wait_job
from test_evaluation_controls import embedding_response, settings as remote_settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, model_credentials_file=tmp_path / "absent.env",
                        openrouter_api_key="", llm_base_url="", llm_api_key="", embedding_mode="disabled")
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def upload(client, rows, workspace="demo", filename="transcript.csv"):
    return client.post("/v1/cases/import", params={"workspace": workspace},
                       files={"file": (filename, transcript_csv(rows), "text/csv")})


def customer_cases(client, workspace="demo"):
    return client.get("/v1/cases", params={"workspace": workspace, "source": "customer", "limit": 100}).json()["items"]


def test_api_import_preserves_context_sources_and_reimported_human_review(client):
    context = {"active_intent": "card.limit.change", "pending_slot": "new_limit",
               "messages": [{"role": "assistant", "content": "What should the new limit be?"}]}
    row = source_turn(Context=json.dumps(context), Answer="REFERENCE_ONLY", Split="test")
    first = upload(client, [row, row])
    assert first.status_code == 200, first.text
    assert first.json().get("inserted") == 1 and first.json().get("already_present") == 0
    assert first.json()["duplicates"] == 1
    case = customer_cases(client)[0]
    assert case["context"] == context and not case["reviewed"]
    assert [case[key] for key in ("source_dataset_id", "source_session_id", "source_message_id")] == [
        "synthetic-source-v1", "session-1", "turn-1"]
    reviewed = client.patch(f"/v1/cases/{case['case_id']}/review", json={
        "expected_decision": "route", "expected_intent_id": "card.limit.change", "split": "dev"})
    assert reviewed.status_code == 200, reviewed.text
    before = client.get(f"/v1/cases/{case['case_id']}/versions").json()
    replay = upload(client, [row], filename="different-file.csv")
    assert replay.status_code == 200, replay.text
    assert replay.json()["inserted"] == 0 and replay.json()["already_present"] == 1
    after = client.get(f"/v1/cases/{case['case_id']}/versions").json()
    assert after == before and after["current"]["split"] == "dev"
    assert after["current"]["reviewed"] is True


@pytest.mark.parametrize("context", [
    {"active_intent": "outside.workspace"},
    {"clarification_options": ["outside.workspace"]},
    {"active_intent": "card.limit.change", "pending_slot": "unsupported_slot"},
])
def test_import_validates_entire_file_against_workspace_catalog_before_writes(client, context):
    before = client.app.state.studio.store.imports("demo")
    response = upload(client, [source_turn(), source_turn(BenchmarkSessionMessageId="bad",
                                                        Context=json.dumps(context))])
    assert response.status_code == 422, response.text
    assert customer_cases(client) == []
    assert client.app.state.studio.store.imports("demo") == before


def test_shared_import_service_uses_target_workspace_catalog(client):
    studio = client.app.state.studio
    studio.ensure_workspace("other")
    only_intent = next(item for item in studio.store.catalog("other")["intents"]
                       if item["intent_id"] != "card.limit.change")
    studio.store.save_catalog("other", [only_intent])
    content = transcript_csv([source_turn(Context='{"active_intent":"card.limit.change"}')])
    with pytest.raises(ValueError, match="workspace catalog"):
        studio.import_benchmark("other", content)
    assert studio.store.cases("other", source="customer") == []
    assert studio.store.imports("other") == []
    assert studio.import_benchmark("demo", content)["inserted"] == 1


def test_store_import_rejects_stale_validated_catalog_without_cases_or_report(client):
    from app.importer import import_benchmark

    store = client.app.state.studio.store
    validated = store.catalog("demo")
    parsed, report = import_benchmark(transcript_csv([source_turn(Context='{"active_intent":"card.limit.change"}')]))
    store.save_catalog("demo", [item for item in validated["intents"] if item["intent_id"] != "card.limit.change"])
    with pytest.raises(ValueError, match="catalog changed"):
        store.import_cases("demo", parsed, report, expected_catalog_version=validated["version"])
    assert store.cases("demo", source="customer") == [] and store.imports("demo") == []


def test_whole_conversation_split_api_preserves_reviews_and_controls_future_imports(client):
    rows = [source_turn(Split="test"), source_turn(BenchmarkSessionMessageId="two", Split="test")]
    assert upload(client, rows).status_code == 200
    assert upload(client, rows, workspace="other").status_code == 200
    cases = customer_cases(client)
    case_id, conversation_id = cases[0]["case_id"], cases[0]["conversation_id"]
    assert client.patch(f"/v1/cases/{case_id}/review", json={"expected_decision": "handoff"}).status_code == 200
    before = [client.get(f"/v1/cases/{case['case_id']}/versions").json() for case in cases]
    path = f"/v1/conversations/{conversation_id}/split"
    moved = client.patch(path, json={"split": "dev"})
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"conversation_id": conversation_id, "split": "dev", "updated_count": 2}
    for case, original in zip(cases, before):
        history = client.get(f"/v1/cases/{case['case_id']}/versions").json()
        assert history["current"] == {**original["current"], "split": "dev"}
        assert len(history["versions"]) >= len(original["versions"]) + 1
    assert all(case["split"] == "test" for case in customer_cases(client, "other"))
    assert client.patch(path, json={"split": "dev"}).json()["updated_count"] == 0
    assert upload(client, rows).json()["already_present"] == 2
    implicit = source_turn(BenchmarkSessionMessageId="three")
    assert upload(client, [implicit]).json()["inserted"] == 1
    assert all(case["split"] == "dev" for case in customer_cases(client))
    reports = client.app.state.studio.store.imports("demo")
    conflict = upload(client, [source_turn(BenchmarkSessionMessageId="four", Split="test"),
                               source_turn(BenchmarkSessionId="independent")])
    assert conflict.status_code == 422 and "whole-conversation" in conflict.json()["detail"]
    assert len(customer_cases(client)) == 3 and client.app.state.studio.store.imports("demo") == reports
    for target in (path + "?workspace=missing", "/v1/conversations/absent/split"):
        assert client.patch(target, json={"split": "dev"}).status_code == 404
    for body in ({"split": "train"}, {"split": "test", "reviewed": True}, {}):
        assert client.patch(path, json=body).status_code == 422


def test_template_is_fixed_synthetic_banking_csv_without_seeding_cases(client):
    before = client.app.state.studio.store.cases("demo")
    response = client.get("/v1/cases/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="synthetic-demo-banking-transcripts.csv"' == response.headers["content-disposition"]
    assert response.content == (ROOT / "data/demo/transcript-example.csv").read_bytes()
    assert b"Synthetic example" in response.content
    assert client.app.state.studio.store.cases("demo") == before
    uploaded = client.post("/v1/cases/import", files={"file": ("example.csv", response.content, "text/csv")})
    assert uploaded.status_code == 200 and uploaded.json()["inserted"] == 4
    assert all(not case["reviewed"] for case in customer_cases(client))


@pytest.mark.parametrize("decision", ["continue", "cancel"])
def test_review_context_decisions_require_matching_valid_active_intent(client, decision):
    context = {"active_intent": "card.limit.change", "pending_slot": "new_limit"}
    assert upload(client, [source_turn(Context=json.dumps(context))]).status_code == 200
    case = customer_cases(client)[0]
    path = f"/v1/cases/{case['case_id']}/review"
    valid = {"expected_decision": decision, "expected_intent_id": "card.limit.change", "split": "test"}
    response = client.patch(path, json=valid)
    assert response.status_code == 200, response.text
    assert response.json()["reviewed"] and response.json()["expected_decision"] == decision
    saved = client.get(f"/v1/cases/{case['case_id']}/versions").json()
    for intent in (None, "account.balance", "outside.workspace"):
        rejected = client.patch(path, json={**valid, "expected_intent_id": intent})
        assert rejected.status_code == 422, rejected.text
        assert client.get(f"/v1/cases/{case['case_id']}/versions").json() == saved
    # Catalog edits can make a previously valid stored context stale.
    catalog = client.app.state.studio.store.catalog("demo")
    intents = [item for item in catalog["intents"] if item["intent_id"] != "card.limit.change"]
    client.app.state.studio.store.save_catalog("demo", intents)
    assert client.patch(path, json=valid).status_code == 422


@pytest.mark.parametrize("context", [{}, {"active_intent": "account.balance", "pending_slot": "new_limit"},
                                      {"active_intent": "card.limit.change", "future": True}])
def test_review_revalidates_legacy_context_and_requires_an_active_intent(client, context):
    case = {"case_id": "legacy-review", "source": "customer", "dataset_version": "old",
            "reviewed": False, "split": "test", "question": "Cancel", "context": context,
            "expected_decision": None, "expected_intent_id": None}
    client.app.state.studio.store.save_cases("demo", [case])
    response = client.patch("/v1/cases/legacy-review/review", json={
        "expected_decision": "cancel", "expected_intent_id": "card.limit.change"})
    assert response.status_code == 422
    assert client.app.state.studio.store.case_versions("demo", "legacy-review")["current"] == case


def test_review_rejects_sibling_split_without_writes_and_missing_rows_are_404(client):
    assert upload(client, [source_turn(), source_turn(BenchmarkSessionMessageId="two")]).status_code == 200
    case = customer_cases(client)[0]
    path = f"/v1/cases/{case['case_id']}/review"
    before = client.app.state.studio.store.case_versions("demo", case["case_id"])
    response = client.patch(path, json={"expected_decision": "handoff", "split": "dev"})
    assert response.status_code == 422 and "whole-conversation split" in response.json()["detail"]
    assert client.app.state.studio.store.case_versions("demo", case["case_id"]) == before
    for target in (path + "?workspace=other", "/v1/cases/missing/review"):
        assert client.patch(target, json={"expected_decision": "continue", "expected_intent_id": "card.limit.change"}).status_code == 404
    for decision in ("clarify", "out_of_scope", "handoff"):
        assert client.patch(path, json={"expected_decision": decision, "expected_intent_id": "card.limit.change"}).status_code == 422
        assert client.patch(path, json={"expected_decision": decision}).status_code == 200
    assert client.patch(path, json={"expected_decision": "route", "expected_intent_id": "outside.workspace"}).status_code == 422


@pytest.mark.parametrize("action", ["versions", "review", "split"])
def test_legacy_ids_with_reserved_path_characters_remain_addressable(client, action):
    row = source_turn(SourceDatasetId="", BenchmarkSessionId="legacy/session?one",
                      BenchmarkSessionMessageId="turn/one?revision")
    assert upload(client, [row]).status_code == 200
    case = customer_cases(client)[0]
    assert "legacy/session?one" in case["conversation_id"] and "turn/one?revision" in case["case_id"]
    if action == "split":
        path = f"/v1/conversations/{quote(case['conversation_id'], safe='')}/split"
        response = client.patch(path, json={"split": "dev"})
    else:
        path = f"/v1/cases/{quote(case['case_id'], safe='')}/{action}"
        response = client.get(path) if action == "versions" else client.patch(path, json={"expected_decision": "handoff"})
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id" if action == "split" else "case_id"] == case["conversation_id" if action == "split" else "case_id"]
    isolated = client.get(path + "?workspace=other") if action == "versions" else client.patch(
        path + "?workspace=other", json={"split": "dev"} if action == "split" else {"expected_decision": "handoff"})
    assert isolated.status_code == 404
    assert client.get("/v1/cases/template").status_code == 200
    assert client.get("/v1/cases/..%2F..%2Fsecret/versions").status_code == 404


def manual_case(case_id, conversation_id, split, *, source="customer", reviewed=True):
    return {"case_id": case_id, "conversation_id": conversation_id, "split": split,
            "source": source, "reviewed": reviewed, "dataset_version": "legacy",
            "question": f"Synthetic independent utterance {case_id}", "context": {},
            "expected_decision": "handoff", "expected_intent_id": None}


@pytest.mark.parametrize("sibling_conversation", ["selected", "unrelated"])
def test_evaluation_preflight_checks_only_selected_conversations_before_snapshots(client, sibling_conversation):
    studio = client.app.state.studio
    studio.store.save_cases("demo", [manual_case("selected", "selected", "test"),
                                     manual_case("unrelated-test", "unrelated", "test"),
                                     manual_case("sibling", sibling_conversation, "dev", source="seed", reviewed=False)])
    response = client.post("/v1/evaluations", json={"source": "customer", "methods": ["lexical"], "limit": 1})
    if sibling_conversation == "selected":
        assert response.status_code == 422 and "conversation" in response.json()["detail"], response.text
        assert studio.store.jobs("demo") == []
        with studio.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM catalog_snapshots").fetchone()[0] == 0
    else:
        assert response.status_code == 202, response.text
        job = wait_job(client, "/v1/requests/" + response.json()["id"])
        assert job["status"] == "completed" and job["selected_count"] == 1


@pytest.mark.parametrize("decision,text,context", [
    ("continue", "5000", {"active_intent": "card.limit.change", "pending_slot": "new_limit"}),
    ("cancel", "Cancel this", {"active_intent": "card.limit.change"}),
])
def test_full_decision_accuracy_compares_context_intent_ids_without_route_metric_support(client, decision, text, context):
    wrong = {**manual_case("wrong", "wrong", "test"), "question": text, "context": context,
             "expected_decision": decision, "expected_intent_id": "account.balance"}
    correct = {**wrong, "case_id": "correct", "conversation_id": "correct", "expected_intent_id": "card.limit.change"}
    route = {**manual_case("route", "route", "test"), "question": "Set my card limit to 7000",
             "expected_decision": "route", "expected_intent_id": "card.limit.change"}
    client.app.state.studio.store.save_cases("demo", [wrong, correct, route])
    response = client.post("/v1/evaluations", json={"source": "customer", "methods": ["lexical"]})
    assert response.status_code == 202, response.text
    job = wait_job(client, "/v1/requests/" + response.json()["id"])
    assert job["status"] == "completed"
    result = job["results"]["lexical"]
    records = {record["case_id"]: record for record in result["records"]}
    assert records["wrong"]["decision"] == decision and records["wrong"]["intent_id"] == "card.limit.change"
    assert records["wrong"]["correct"] is False
    assert records["correct"]["correct"] is True and records["route"]["correct"] is True
    assert result["metrics"]["decision_accuracy"] == 2 / 3
    assert result["metrics"]["routing_accuracy"] == result["metrics"]["macro_f1"] == 1


@pytest.fixture
def remote_client(remote_settings):
    with TestClient(create_app(remote_settings), raise_server_exceptions=False) as client:
        requests = []
        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/embeddings"):
                return embedding_response(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "decision": "continue", "intent_id": "card.limit.change", "reason_code": "continue_flow",
                "mentioned_intent_ids": [],
            })}, "finish_reason": "stop"}]})
        studio = client.app.state.studio
        studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
        yield client, requests


def calibration_cases():
    return [{**manual_case(f"calibration-{index}", f"calibration-{index}", "calibration"),
             "expected_decision": "route" if index < 10 else "out_of_scope",
             "expected_intent_id": "card.limit.change" if index < 10 else None}
            for index in range(20)]


@pytest.mark.parametrize("entrypoint", ["calibration", "scaling"])
def test_calibration_preflight_rejects_selected_conversation_leakage_before_work(remote_client, entrypoint):
    client, requests = remote_client
    studio = client.app.state.studio
    studio.store.save_cases("demo", [*calibration_cases(),
        manual_case("sibling", "calibration-0", "dev", reviewed=False),
        manual_case("evaluation", "evaluation", "test")])
    if entrypoint == "calibration":
        response = client.post("/v1/calibrations", json={"source": "customer"})
    else:
        response = client.post("/v1/evaluations", json={"source": "customer", "methods": ["e5"],
            "catalog_sizes": [48], "scale_calibration_source": "customer", "execution_limits": {"max_provider_requests": 0}})
    assert response.status_code == 422 and "conversation" in response.json()["detail"], response.text
    assert studio.store.jobs("demo") == [] and requests == []
    with studio.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM catalog_snapshots").fetchone()[0] == 0


def test_unrelated_conversation_leakage_does_not_block_independent_calibration(remote_client):
    client, _ = remote_client
    studio = client.app.state.studio
    studio.store.save_cases("demo", [*calibration_cases(), manual_case("other-dev", "other", "dev"),
                                     manual_case("other-test", "other", "test")])
    response = client.post("/v1/calibrations", json={"source": "customer"})
    assert response.status_code == 202, response.text
    job = wait_job(client, "/v1/requests/" + response.json()["id"], max_seconds=20)
    assert job["status"] == "completed", job


@pytest.mark.parametrize("change", ["split", "new_sibling"])
def test_calibration_reuse_rechecks_split_freshness_and_selected_conversation_separation(remote_client, change):
    client, _ = remote_client
    studio = client.app.state.studio
    studio.store.save_cases("demo", calibration_cases())
    response = client.post("/v1/calibrations", json={"source": "customer"})
    assert response.status_code == 202
    job = wait_job(client, "/v1/requests/" + response.json()["id"], max_seconds=20)
    assert job["status"] == "completed", job
    version = studio.store.catalog("demo")["version"]
    variant = studio.model_catalog.variant("e5", workspace="demo")
    assert studio.calibrator.resolve("demo", variant, version, "calibrated")["calibrated"]
    if change == "split":
        moved = client.patch("/v1/conversations/calibration-0/split", json={"split": "dev"})
        assert moved.status_code == 200
    else:
        studio.store.save_cases("demo", [manual_case("later-sibling", "calibration-0", "dev", reviewed=False)])
    with pytest.raises(ValueError, match="changed|conversation"):
        studio.calibrator.resolve("demo", variant, version, "calibrated")


@pytest.mark.parametrize("fields", [
    {"context": {"active_intent": "card.limit.change"}},
    {"expected_decision": "continue"}, {"expected_decision": "cancel"},
])
def test_calibration_remains_context_free_and_excludes_new_review_decisions(remote_client, fields):
    client, requests = remote_client
    cases = calibration_cases()
    cases[0].update(fields)
    client.app.state.studio.store.save_cases("demo", cases)
    response = client.post("/v1/calibrations", json={"source": "customer"})
    assert response.status_code == 422 and "context-free" in response.json()["detail"]
    assert requests == [] and client.app.state.studio.store.jobs("demo") == []


def test_import_review_and_repeated_evaluation_send_only_explicit_context_to_provider(remote_client):
    client, requests = remote_client
    context = {"active_intent": "card.limit.change", "clarification_options": ["account.balance"],
               "messages": [{"role": "user", "content": "PAST_USER_CONTEXT"},
                            {"role": "assistant", "content": "PAST_ASSISTANT_CONTEXT"}]}
    response = upload(client, [source_turn(
        Question="Please proceed with the limit adjustment", Context=json.dumps(context),
        Answer="REFERENCE_MUST_NEVER_REACH_PROVIDER", **{"TRUE/FALSE": "SOURCE_FLAG_NOT_GOLD"})])
    assert response.status_code == 200 and response.json()["inserted"] == 1
    case = customer_cases(client)[0]
    unreviewed = client.post("/v1/evaluations", json={"methods": ["hybrid_llm"], "source": "customer"})
    assert unreviewed.status_code == 422
    reviewed = client.patch(f"/v1/cases/{case['case_id']}/review", json={
        "expected_decision": "continue", "expected_intent_id": "card.limit.change"})
    assert reviewed.status_code == 200, reviewed.text
    assert requests == []
    response = client.post("/v1/evaluations", json={"methods": ["hybrid_llm"], "source": "customer", "repetitions": 2})
    assert response.status_code == 202, response.text
    job = wait_job(client, "/v1/requests/" + response.json()["id"], max_seconds=20)
    assert job["status"] == "completed", job
    assert len(job["results"]) == 2
    assert all(result["records"][0]["correct"] for result in job["results"].values())
    selections = [json.loads(request.content) for request in requests if request.url.path.endswith("/chat/completions")]
    assert len(selections) == 2
    for selection in selections:
        user = json.loads(selection["messages"][1]["content"])
        assert user["conversation"] == {"active_intent": "card.limit.change", "clarification_options": ["account.balance"]}
        assert user["prior_turns"] == context["messages"]
        assert user["message"] == "Please proceed with the limit adjustment"
    for request in requests:
        assert all(marker not in request.content.decode() for marker in (
            "REFERENCE_MUST_NEVER_REACH_PROVIDER", "SOURCE_FLAG_NOT_GOLD", "reference_answer", "expected_decision", "expected_intent_id"))
    assert customer_cases(client)[0]["context"] == context


@pytest.mark.parametrize("new_split,expected_status", [("dev", 200), ("test", 422), ("calibration", 422)])
def test_replayed_export_split_does_not_override_current_split_validation_for_new_turns(client, new_split, expected_status):
    old = source_turn(Split="test")
    assert upload(client, [old]).status_code == 200
    original = customer_cases(client)[0]
    case_path = f"/v1/cases/{original['case_id']}"
    assert client.patch(case_path + "/review", json={"expected_decision": "handoff"}).status_code == 200
    assert client.patch(f"/v1/conversations/{original['conversation_id']}/split", json={"split": "dev"}).status_code == 200
    history = client.get(case_path + "/versions").json()
    reports = client.app.state.studio.store.imports("demo")
    response = upload(client, [old, source_turn(BenchmarkSessionMessageId="new-turn", Split=new_split)])
    assert response.status_code == expected_status, response.text
    assert client.get(case_path + "/versions").json() == history
    if expected_status == 200:
        assert response.json()["already_present"] == 1 and response.json()["inserted"] == 1
        assert {case["split"] for case in customer_cases(client)} == {"dev"}
        new = next(case for case in customer_cases(client) if case["source_message_id"] == "new-turn")
        assert not new["reviewed"]
    else:
        assert len(customer_cases(client)) == 1
        assert client.app.state.studio.store.imports("demo") == reports


@pytest.mark.parametrize("second_message", ["turn-1", "turn-2"])
def test_new_conversation_mixed_explicit_splits_reject_atomically(client, second_message):
    response = upload(client, [source_turn(Split="dev"),
                               source_turn(BenchmarkSessionMessageId=second_message, Split="test")])
    assert response.status_code == 422 and "split" in response.json()["detail"]
    assert customer_cases(client) == [] and client.app.state.studio.store.imports("demo") == []


def test_conversation_split_response_is_exposed_as_typed_openapi_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    operation = document["paths"]["/v1/conversations/{conversation_id}/split"]["patch"]
    schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    schema = document["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
    assert set(schema["required"]) == {"conversation_id", "split", "updated_count"}
    assert schema["properties"]["conversation_id"]["type"] == "string"
    assert schema["properties"]["updated_count"]["type"] == "integer"
    assert schema["properties"]["split"]["enum"] == ["dev", "calibration", "test"]
