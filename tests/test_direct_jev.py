import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from app.config import ROOT, Settings
from app.contracts import Intent
from app.model_catalog import llm_metadata
from app.model_registry import ModelRegistry, Registration
from app.store import Store, fingerprint


spec = importlib.util.spec_from_file_location("direct_jev", ROOT / "scripts/evaluate_direct_jev.py")
direct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = direct
spec.loader.exec_module(direct)


@pytest.fixture
def catalog():
    return tuple(Intent(intent_id=f"intent.{i:04}", name=f"Intent {i}", domain="Test",
                        description=f"Test operation number {i}", examples=[f"Fixed example {i}", "Unused example"],
                        exclusions=["Excluded operation"], selection_rule="Use only an explicit match.",
                        workflow_id=f"workflow.intent.{i:04}") for i in reversed(range(800)))


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("INTENT_TYPESAFE_API_KEY", raising=False)
    return Settings(_env_file=None, data_dir=tmp_path, model_credentials_file=tmp_path / "keys.env",
                    llm_protocol="typesafe", llm_base_url="https://api.typesafe.ai/v1", llm_model="jev-1.13.0",
                    llm_api_key="private-typesafe-key", openrouter_api_key="must-not-use-this", embedding_mode="disabled")


def reply(body):
    answers = {}
    for key, question in body["questions"].items():
        options = list(question["criteria"])
        choice = "intent.0000" if key == "routing" else "@none"
        probabilities = {option: float(option == choice) for option in options}
        if key.startswith("group_"):
            ids = sorted(i for i in options if i != "@none")
            probabilities = {option: 0.0 for option in options}
            probabilities["@none"] = .9
            for iid in ids[:5]:
                probabilities[iid] = .02
        answers[key] = {"type": "choice", "choice": choice, "confidence": .8, "probabilities": probabilities}
    return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers,
                                    "usage": {"input_tokens": 100, "output_tokens": 10}})


def test_two_stage_call_covers_all_800_once_and_keeps_five_per_group_without_embeddings(catalog, settings):
    requests = []
    def respond(request):
        requests.append(request)
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == "Bearer private-typesafe-key"
        body = json.loads(request.content)
        assert "expected" not in request.content.decode() and "reference_answer" not in request.content.decode()
        assert body["model"] == "jev-1.13.0"
        assert all(len(q["criteria"]) <= 255 for q in body["questions"].values())
        if len(requests) == 1:
            assert len(body["questions"]) == 4
            assert not body["state"].get("candidates")
            option_lists = [[i for i in q["criteria"] if i != "@none"] for q in body["questions"].values()]
            assert all(len(ids) == 200 for ids in option_lists)
            assert [iid for ids in option_lists for iid in ids] == sorted(i.intent_id for i in catalog)
            rubric = next(iter(body["questions"].values()))["criteria"]["intent.0000"]
            assert rubric == "Intent 0 — Test operation number 0"
            assert "Fixed example" not in rubric and "Excluded operation" not in rubric
        else:
            ids = [i["intent_id"] for i in body["state"]["candidates"]]
            assert len(ids) == 20
            assert ids == [f"intent.{i:04}" for start in range(0, 800, 200) for i in range(start, start + 5)]
            assert set(body["questions"]) == {"routing", "clarification_first", "clarification_second"}
        return reply(body)
    result = direct.classify("Test message", {}, catalog, settings, httpx.MockTransport(respond))
    assert len(requests) == 2
    assert result.proposal.intent_id == "intent.0000" and result.proposal.decision == "route"
    assert result.usage == {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}


def source_fixture(tmp_path, settings, catalog):
    store = Store(settings.data_dir)
    settings.model_credentials_file.write_text("INTENT_TYPESAFE_API_KEY=private-typesafe-key\n")
    registry = ModelRegistry(settings, store)
    record = registry.save("demo", Registration(kind="llm", name="TypeSafe Jev", model="jev-1.13.0",
        connection="typesafe", auth="env", credential_env="INTENT_TYPESAFE_API_KEY"))
    resolved = registry.resolve(settings.model_copy(deep=True), record)
    raw_intents = [i.model_dump() for i in catalog]
    version = store.save_catalog("demo", raw_intents)
    cases = [{"case_id": f"seed-{i}", "source": "seed", "split": "test", "reviewed": True,
              "dataset_version": "fixture-v1", "question": f"Test message {i}", "context": {},
              "expected_decision": "route", "expected_intent_id": "intent.0000", "reference_answer": "private-gold-only"}
             for i in range(2)]
    store.save_cases("demo", cases)
    source = {"id": "original-evaluation", "kind": "evaluation", "status": "completed",
              "catalog_version": version, "dataset_fingerprint": fingerprint(cases), "selected_count": 2,
              "options": {"methods": ["hybrid_llm"], "llm_ids": [record["id"]], "source": "seed", "split": "test"},
              "results": {"original": {"llm_id": record["id"], "llm": llm_metadata(resolved), "model": "jev-1.13.0",
                  "prompt_version": direct.PROMPT_VERSION,
                  "catalog": {"version": version, "intent_count": 800, "intent_ids": [i.intent_id for i in catalog]},
                  "records": [{k: c[k] for k in ("case_id", "question", "expected_decision", "expected_intent_id")} for c in cases]}}}
    path = tmp_path / "source-evaluation.json"
    path.write_text(json.dumps(source))
    return path, store, source


def test_source_validation_freezes_original_catalog_cohort_and_model_before_running(tmp_path, settings, catalog):
    path, store, source = source_fixture(tmp_path, settings, catalog)
    prepared = direct.load_experiment(path, settings)
    assert len(prepared.catalog) == 800 and len(prepared.cases) == 2
    assert prepared.source.dataset_fingerprint == source["dataset_fingerprint"]
    store.review_case("demo", "seed-0", {"expected_intent_id": "intent.0777", "expected_decision": "route", "split": "test"})
    assert prepared.cases[0].expected_intent_id == "intent.0000"
    calls = []
    def respond(request):
        calls.append(request)
        assert "private-gold-only" not in request.content.decode()
        return reply(json.loads(request.content))
    output = tmp_path / "checkpoint.json"
    summary = direct.run_experiment(prepared, output, limit=1, transport=httpx.MockTransport(respond))
    assert summary["status"] == "completed" and len(calls) == 2
    saved = json.loads(output.read_text())
    assert saved["selected_count"] == 1 and saved["provenance"]["source_cohort_count"] == 2
    assert saved["provenance"]["subset"] is True and saved["provenance"]["embedding_used"] is False
    assert saved["provenance"]["first_stage_catalog_fields"] == ["intent_id", "name", "description"]
    assert saved["provenance"]["first_stage_omitted_fields"] == ["examples", "exclusions", "selection_rule"]
    assert saved["metrics"]["routing_accuracy"] == 1 and saved["model_shortlist"]["recall"] == 1
    assert saved["records"][0]["expected_intent_id"] == "intent.0000"
    assert "private-typesafe-key" not in output.read_text() and "api.typesafe.ai" not in output.read_text()
    with pytest.raises(ValueError, match="fingerprint"):
        direct.load_experiment(path, settings)


@pytest.mark.parametrize("failed_call", [1, 2])
def test_failures_checkpoint_completed_stage_costs_and_stop_without_retry(tmp_path, settings, catalog, failed_call):
    path, _, _ = source_fixture(tmp_path, settings, catalog)
    prepared = direct.load_experiment(path, settings)
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == failed_call:
            return httpx.Response(429, json={"error": {"message": "private-error-body"}})
        return reply(json.loads(request.content))
    output = tmp_path / "failed-checkpoint.json"
    report = direct.run_experiment(prepared, output, transport=httpx.MockTransport(respond))
    assert report["status"] == "failed" and report["progress"] == 1 and len(calls) == failed_call
    record = report["records"][0]
    assert record["decision"] == "error" and record["error_stage"] == ("shortlisting" if failed_call == 1 else "selection")
    assert record["diagnostics"]["http_status"] == 429
    assert record["usage"]["total_tokens"] == (0 if failed_call == 1 else 110)
    assert record["usage_complete"] is False and record["first_stage_completed"] == (failed_call == 2)
    assert record["timings_ms"]["shortlisting"] > 0
    assert len(record["shortlist_ids"]) == (0 if failed_call == 1 else 20)
    assert json.loads(output.read_text())["status"] == "failed"
    assert "private-error-body" not in output.read_text() and "private-typesafe-key" not in output.read_text()


@pytest.mark.parametrize("damage", ["fingerprint", "catalog_version", "record_order", "record_label", "model", "prompt"])
def test_source_mismatch_stops_before_any_inference(tmp_path, settings, catalog, damage):
    path, _, source = source_fixture(tmp_path, settings, catalog)
    result = source["results"]["original"]
    if damage == "fingerprint":
        source["dataset_fingerprint"] = "invalid-fingerprint"
    elif damage == "catalog_version":
        source["catalog_version"] = "missing-snapshot"
    elif damage == "record_order":
        result["records"].reverse()
    elif damage == "record_label":
        result["records"][0]["expected_intent_id"] = "intent.0777"
    elif damage == "model":
        result["llm"]["model"] = "jev-latest"
    else:
        result["prompt_version"] = "different-prompt"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        direct.load_experiment(path, settings)


@pytest.mark.parametrize("damage", ["missing_group", "missing_option", "wrong_choice", "negative_probability", "wrong_model"])
def test_malformed_first_stage_never_reaches_second_call(catalog, settings, damage):
    calls = []
    def respond(request):
        calls.append(request)
        body = reply(json.loads(request.content)).json()
        first = body["answers"]["group_1"]
        if damage == "missing_group":
            del body["answers"]["group_4"]
        elif damage == "missing_option":
            del first["probabilities"]["intent.0000"]
        elif damage == "wrong_choice":
            first["choice"] = "intent.0000"
        elif damage == "negative_probability":
            first["probabilities"]["intent.0000"] = -1
        else:
            body["model"] = "different-model"
        return httpx.Response(200, json=body)
    with pytest.raises(direct.DirectInferenceError) as exc:
        direct.classify("Test message", {}, catalog, settings, httpx.MockTransport(respond))
    assert exc.value.stage == "shortlisting" and len(calls) == 1


def test_zero_probability_and_boundary_ties_are_recorded_without_cross_group_ranking(catalog, settings):
    def respond(request):
        body = json.loads(request.content)
        response = reply(body).json()
        for key, answer in response["answers"].items():
            if key.startswith("group_"):
                answer["probabilities"] = {iid: float(iid == "@none") for iid in answer["probabilities"]}
        return httpx.Response(200, json=response)
    result = direct.classify("Test message", {}, catalog, settings, httpx.MockTransport(respond))
    assert all(g.zero_probability_selected == 5 and g.boundary_tie for g in result.groups)
    assert [i.intent_id for i in result.candidates] == [f"intent.{i:04}" for start in range(0, 800, 200) for i in range(start, start + 5)]


def test_invalid_catalog_or_configuration_is_rejected_without_network(catalog, settings):
    def unexpected(request):
        pytest.fail("Invalid local configuration must not send a request")
    for broken_catalog in (catalog[:799], (*catalog[:799], catalog[0])):
        with pytest.raises(ValueError, match="800"):
            direct.classify("Test", {}, broken_catalog, settings, httpx.MockTransport(unexpected))
    with pytest.raises(ValueError, match="configured"):
        direct.classify("Test", {}, catalog, settings.model_copy(update={"llm_api_key": ""}), httpx.MockTransport(unexpected))


def test_token_limit_failure_keeps_only_allowlisted_provider_diagnostic(tmp_path, settings, catalog):
    path, _, _ = source_fixture(tmp_path, settings, catalog)
    prepared = direct.load_experiment(path, settings)
    output = tmp_path / "token-limit.json"
    response = httpx.Response(400, json={"detail": {"error_type": "max_tokens_exceeded", "message": "private-payload-details"}})
    report = direct.run_experiment(prepared, output, limit=1,
                                   transport=httpx.MockTransport(lambda request: response))
    assert report["status"] == "failed"
    assert report["records"][0]["diagnostics"] == {"http_status": 400, "provider_code": "max_tokens_exceeded"}
    assert "private-payload" not in output.read_text()
