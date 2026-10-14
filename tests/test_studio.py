import copy
import csv
import io
import json
import time

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.contracts import Intent, Proposal
from app.evaluation import summarize, wilson
from app.importer import import_benchmark
from app.main import create_app
from app.policy import amount, apply_decision, context_decision
from app.retrieval import Embeddings, ModelUnavailable, Retriever
from app.selector import Selector
from app.store import Store
from app.service import Studio


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, llm_base_url="", llm_api_key="", embedding_mode="disabled")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def csv_fixture():
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["BenchmarkSessionId", "BenchmarkSessionMessageId", "Question", "Answer", "Message Flow", "TRUE/FALSE", "", ""])
    writer.writerow(["1", "1", "Kart limitimi artırmak istiyorum", "Kaynak yanıt;\niki satır", json.dumps({"metadata": {"total_elapsed_time": 12}, "steps": [{"step": "intent_detection", "action": "banking_product_and_service_search", "reasoning": "DO_NOT_USE_AS_GOLD"}]}), "TRUE", "", ""])
    writer.writerow(["", "", "", "", "unused-trace-only", "", "", ""])
    writer.writerow(["2", "1", "Beni temsilciye bağlar mısın?", "Yanıt", "", "FALSE", "", ""])
    return stream.getvalue().encode("utf-8-sig")


def wait_job(client, route, max_seconds=4):
    started = time.monotonic()
    while time.monotonic()-started < max_seconds:
        response = client.get(route)
        assert response.status_code == 200
        job = response.json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(.01)
    pytest.fail("Job did not finish within test deadline")


def route(client, session_id, revision, text):
    response = client.post("/v1/route", json={"session_id": session_id, "turn_revision": revision, "user_text": text, "method": "lexical"})
    assert response.status_code == 202, response.text
    return wait_job(client, "/v1/requests/" + response.json()["request_id"])


def test_csv_multiline_large_trace_and_missing_gold():
    cases, report = import_benchmark(csv_fixture())
    assert report["imported"] == 2
    assert report["skipped_empty_question"] == 1
    assert report["source_flags"] == {"TRUE": 1, "FALSE": 1}
    assert cases[0]["reference_answer"] == "Kaynak yanıt;\niki satır"
    assert all(c["expected_intent_id"] is None and not c["reviewed"] for c in cases)
    assert "DO_NOT_USE_AS_GOLD" not in json.dumps(cases)
    assert cases[0]["historical_trace"]["action"] == "banking_product_and_service_search"


def test_unreviewed_customer_data_cannot_produce_accuracy(client):
    response = client.post("/v1/cases/import", files={"file": ("benchmark.csv", csv_fixture(), "text/csv")})
    assert response.status_code == 200
    assert client.get("/v1/status").json()["customer_case_count"] == 2
    evaluation = client.post("/v1/evaluations", json={"source": "customer", "methods": ["lexical"]})
    assert evaluation.status_code == 422
    cases = client.get("/v1/cases?source=customer").json()["items"]
    assert len(cases) == 2
    first = cases[0]["case_id"]
    reviewed = client.patch("/v1/cases/" + first + "/review", json={"expected_decision": "route", "expected_intent_id": "card.limit.change", "split": "test"})
    assert reviewed.status_code == 200
    client.post("/v1/cases/import", files={"file": ("benchmark.csv", csv_fixture(), "text/csv")})
    assert client.get("/v1/status").json()["reviewed_customer_count"] == 1
    response = client.post("/v1/evaluations", json={"source": "customer", "methods": ["lexical"]})
    job = wait_job(client, "/v1/evaluations/" + response.json()["id"])
    assert job["selected_count"] == 1 and job["unreviewed_excluded"] == 1
    assert job["status"] == "completed"


def test_workspace_isolation(client):
    client.post("/v1/cases/import?workspace=bank_a", files={"file": ("benchmark.csv", csv_fixture(), "text/csv")})
    assert client.get("/v1/status?workspace=bank_b").json()["customer_case_count"] == 0
    case_id = client.get("/v1/cases?workspace=bank_a&source=customer").json()["items"][0]["case_id"]
    assert client.patch("/v1/cases/" + case_id + "/review?workspace=bank_b", json={"expected_decision": "out_of_scope"}).status_code == 404


def test_limit_workflow_slot_correction_and_confirmation(client):
    sid = client.post("/v1/sessions").json()["session_id"]
    first = route(client, sid, 1, "Kart limitimi artırmak istiyorum")
    assert first["result"]["intent_id"] == "card.limit.change"
    second = route(client, sid, 2, "iki bin")
    assert second["result"]["decision"] == "continue"
    assert second["result"]["slots"]["new_limit"] == "2000"
    corrected = route(client, sid, 3, "Yok, iki bin değil üç bin.")
    assert corrected["result"]["slots"]["new_limit"] == "3000"
    assert first["result"]["pending_confirmation"] is False
    assert second["result"]["pending_confirmation"] is True
    assert corrected["result"]["pending_confirmation"] is True
    confirmed = route(client, sid, 4, "onaylıyorum")
    assert confirmed["result"]["simulation_complete"] is True
    assert confirmed["result"]["pending_confirmation"] is False
    assert "Gerçek banka işlemi yapılmadı" in confirmed["result"]["message"]


@pytest.mark.parametrize("text,intent,slot,value", [
    ("Gönderdiğim havale karşıya ulaşmadı", "transfer.status", "transfer_reference", "TR12345"),
    ("Cüzdanım çalındı kartım içinde", "card.lost", "card_last4", "1234"),
])
def test_other_simulation_flows(client, text, intent, slot, value):
    sid = client.post("/v1/sessions").json()["session_id"]
    assert route(client, sid, 1, text)["result"]["intent_id"] == intent
    result = route(client, sid, 2, value)["result"]
    assert result["slots"][slot] == value
    assert route(client, sid, 3, "evet")["result"]["simulation_complete"]


def test_ambiguity_then_clarification(client):
    sid = client.post("/v1/sessions").json()["session_id"]
    first = route(client, sid, 1, "Kartımı kapatmak istiyorum")["result"]
    assert first["decision"] == "clarify"
    second = route(client, sid, 2, "geçici olarak")["result"]
    assert second["intent_id"] == "card.temporary_block"


def test_cancellation_is_scoped_to_active_flow(client):
    sid = client.post("/v1/sessions").json()["session_id"]
    route(client, sid, 1, "Kart limitimi artırmak istiyorum")
    assert route(client, sid, 2, "iptal et")["result"]["decision"] == "cancel"
    assert context_decision("kartımı iptal et", {"active_intent": "card.limit.change"}) is None


def test_stale_turn_cannot_overwrite_newer_state(settings):
    store = Store(settings.data_dir)
    state = store.create_session("demo")
    old = store.claim_turn("demo", state["session_id"], 1)
    new = store.claim_turn("demo", state["session_id"], 2)
    new["slots"] = {"new_limit": "3000"}
    assert store.finish_turn("demo", new, 2)
    old["slots"] = {"new_limit": "1000"}
    assert store.finish_turn("demo", old, 1) is False
    assert store.claim_turn("demo", state["session_id"], 3)["slots"] == {"new_limit": "3000"}


def test_request_idempotency_and_old_revision(client):
    sid = client.post("/v1/sessions").json()["session_id"]
    body = {"request_id": "same-request", "session_id": sid, "turn_revision": 1, "user_text": "Hesap bakiyemi öğrenmek istiyorum"}
    assert client.post("/v1/route", json=body).status_code == 202
    wait_job(client, "/v1/requests/same-request")
    assert client.post("/v1/route", json=body).status_code == 202
    assert client.post("/v1/route", json={**body, "user_text": "Başka istek"}).status_code == 409
    assert client.post("/v1/route", json={**body, "request_id": "new-request"}).status_code == 409


def test_sse_replays_completed_result(client):
    sid = client.post("/v1/sessions").json()["session_id"]
    job = route(client, sid, 1, "Kredi kartı borcumu ödemek istiyorum")
    response = client.get("/v1/requests/" + job["id"] + "/events")
    assert response.status_code == 200
    assert "event: stage" in response.text and "event: result" in response.text
    retrieval = next(event for event in job["events"] if event["stage"] == "retrieval")
    assert retrieval["catalog_version"] == job["catalog_version"]
    assert retrieval["candidates"] == job["result"]["candidates"]
    assert retrieval["at"] >= job["created"]
    replayed = [json.loads(block.split("data: ", 1)[1]) for block in response.text.split("\n\n") if "event: stage\n" in block]
    assert retrieval in replayed


def test_candidates_are_emitted_before_llm_selection(settings, monkeypatch):
    studio = Studio(settings)
    try:
        studio.ensure_workspace("demo")
        retriever = studio.retriever("demo")
        candidates = retriever.search("Kart limitimi artırmak istiyorum", "lexical", 5)
        events = []
        monkeypatch.setattr(retriever, "search_with_trace", lambda *args, **kwargs: (candidates, {"executed": True, "completed": True}))

        def select(*args):
            # The live map can show these IDs while the selector is still running.
            assert events[-1]["stage"] == "retrieval"
            assert events[-1]["candidates"] == [candidate.model_dump() for candidate in candidates]
            assert not any(event["stage"] == "selection" for event in events)
            return Proposal(decision="route", intent_id="card.limit.change"), {}

        monkeypatch.setattr(studio.selector, "select", select)
        state = studio.store.create_session("demo")
        result, _ = studio.compute("Kart limitimi artırmak istiyorum", state, "hybrid_llm", retriever,
            emit=lambda stage, label, **data: events.append({"stage": stage, **data}))
        assert result["intent_id"] == "card.limit.change"
        assert [event["stage"] for event in events] == ["context", "retrieval", "selection", "policy"]
        assert all("decision" not in event for event in events)
    finally:
        studio.close()


def test_live_map_catalog_snapshot_is_versioned_and_workspace_scoped(client):
    store = client.app.state.studio.store
    original = client.get("/v1/catalog").json()["intents"]
    custom = copy.deepcopy(original)
    custom[0]["description"] += " Demo workspace only."
    pinned = store.save_catalog("demo", custom)
    sid = client.post("/v1/sessions").json()["session_id"]
    response = client.post("/v1/route", json={"session_id": sid, "turn_revision": 1, "user_text": "Kart limitimi artırmak istiyorum"})
    assert response.json()["catalog_version"] == pinned
    newer = copy.deepcopy(custom)
    newer[0]["name"] += " Updated"
    store.save_catalog("demo", newer)
    job = wait_job(client, "/v1/requests/" + response.json()["request_id"])
    assert job["catalog_version"] == pinned
    snapshot = client.get("/v1/catalog", params={"version": pinned})
    assert snapshot.status_code == 200
    assert snapshot.json()["intents"] == custom
    assert client.get("/v1/catalog").json()["intents"] == newer
    assert client.get("/v1/catalog", params={"version": pinned, "workspace": "another_workspace"}).status_code == 404
    assert client.get("/v1/catalog", params={"version": "missing-version"}).status_code == 404


def test_missing_model_is_explicit_not_fake_fallback(client):
    sid = client.post("/v1/sessions").json()["session_id"]
    response = client.post("/v1/route", json={"session_id": sid, "turn_revision": 1, "user_text": "Kart borcu", "method": "hybrid_llm"})
    assert response.status_code == 409


def test_selector_constrains_ids_and_never_receives_gold(settings):
    settings.llm_base_url = "https://model.example/v1"
    settings.llm_api_key = "test-secret"
    catalog = [Intent.model_validate(x) for x in json.loads((ROOT/"data/demo/catalog.json").read_text())]
    retriever = Retriever(catalog, "test", Embeddings(settings))
    candidates = retriever.search("Kart limitimi artıracağım", k=5)
    def respond(request):
        body = json.loads(request.content)
        assert "GOLD_SHOULD_NOT_LEAK" not in json.dumps(body)
        assert body["response_format"]["json_schema"]["schema"]["properties"]["intent_id"]["enum"] == [c.intent_id for c in candidates] + [None]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"decision": "route", "intent_id": "invented.execute", "slots": {}})}}]})
    selector = Selector(settings, httpx.MockTransport(respond))
    with pytest.raises(ModelUnavailable, match="aday listesinde olmayan"):
        selector.select("Kart limitimi artıracağım", {"expected_intent_id": "GOLD_SHOULD_NOT_LEAK", "messages": []}, candidates, retriever.intents)


def test_provider_timeout_is_technical_error(settings):
    settings.llm_base_url = "https://model.example/v1"
    def timeout(request):
        raise httpx.ReadTimeout("test", request=request)
    with pytest.raises(ModelUnavailable, match="süre sınırını"):
        Selector(settings, httpx.MockTransport(timeout)).select("test", {}, [], {})


def test_valid_selector_contract_and_usage(settings):
    settings.llm_base_url = "https://model.example/v1"
    catalog = [Intent.model_validate(x) for x in json.loads((ROOT/"data/demo/catalog.json").read_text())]
    retriever = Retriever(catalog, "test", Embeddings(settings))
    candidates = retriever.search("Kart limitimi artıracağım", k=5)
    def respond(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"decision": "route", "intent_id": "card.limit.change", "slots": {}, "question": None, "reason_code": "model_selection"})}}], "usage": {"total_tokens": 100}})
    proposal, usage = Selector(settings, httpx.MockTransport(respond)).select("Kart limitimi artıracağım", {}, candidates, retriever.intents)
    assert proposal.intent_id == "card.limit.change" and usage["total_tokens"] == 100


def test_candidates_are_unique_and_context_retained(settings):
    catalog = [Intent.model_validate(x) for x in json.loads((ROOT/"data/demo/catalog.json").read_text())]
    catalog[0].examples = catalog[0].examples*10
    retriever = Retriever(catalog, "test", Embeddings(settings))
    candidates = retriever.search("kart limiti", k=20, active_intent="account.balance")
    ids = [c.intent_id for c in candidates]
    assert len(ids) == len(set(ids)) == 20
    assert "account.balance" in ids


def test_empty_or_invalid_catalog_does_not_replace_current(client):
    version = client.get("/v1/catalog").json()["version"]
    assert client.post("/v1/catalog/import", json=[]).status_code == 422
    catalog = client.get("/v1/catalog").json()["intents"]
    catalog[0]["confusable_with"] = ["missing.intent"]
    assert client.post("/v1/catalog/import", json=catalog).status_code == 422
    assert client.get("/v1/catalog").json()["version"] == version


def test_metrics_count_abstentions_timeouts_and_false_accepts():
    base = {"expected_decision": "route", "expected_intent_id": "a", "intent_id": "a", "decision": "route", "candidate_hit": True, "total_ms": 10, "correct": True}
    records = [base, {**base, "decision": "clarify", "intent_id": None, "correct": False}, {**base, "decision": "error", "intent_id": None, "correct": False}, {**base, "expected_decision": "out_of_scope", "expected_intent_id": None, "correct": False}]
    metrics = summarize(records)
    assert metrics["routing_accuracy"] == 1/3
    assert metrics["routing_total"] == 3
    assert metrics["decision_accuracy"] == .25
    assert metrics["routed_precision"] == .5
    assert metrics["coverage"] == .5
    assert metrics["oos_false_accept_rate"] == 1
    assert metrics["errors"] == 1
    assert summarize([])["routing_accuracy"] is None
    assert wilson(90, 100)[0] < .9 < wilson(90, 100)[1]


@pytest.mark.parametrize("text,expected", [("iki bin", "2000"), ("35.000 TL", "35000"), ("üç bin beş yüz", "3500"), ("yok iki bin değil üç bin", "3000"), ("kartımın limiti", None), ("-3000", None), ("2.5", None), ("2.000,00", "2000"), ("3.000,50", None)])
def test_turkish_amounts(text, expected):
    assert amount(text) == expected


def test_wrong_continue_cannot_switch_workflow(settings):
    catalog = {x["intent_id"]: Intent.model_validate(x) for x in json.loads((ROOT/"data/demo/catalog.json").read_text())}
    with pytest.raises(ValueError, match="aktif işlem"):
        apply_decision(Proposal(decision="continue", intent_id="card.lost"), {"active_intent": "card.limit.change"}, catalog)


def test_secrets_not_exposed(settings):
    settings.llm_api_key = "never-return-this-secret"
    with TestClient(create_app(settings)) as client:
        assert settings.llm_api_key not in client.get("/v1/status").text


def test_hybrid_fuses_intents_when_best_examples_differ(settings):
    first = Intent(intent_id="alpha", name="Alpha", domain="Test", description="Birinci test sınıfı", examples=["özelkod", "diğer örnek"], workflow_id="workflow.alpha")
    second = Intent(intent_id="beta", name="Beta", domain="Test", description="İkinci test sınıfı", examples=["başka bir şey"], workflow_id="workflow.beta")
    class FakeEmbeddings:
        def encode(self, texts, query=False):
            if query:
                return np.array([[1., 0.]])
            return np.array([[.4, .9165], [.95, .3122], [.8, .6]])
    retriever = Retriever([first, second], "test", FakeEmbeddings())
    found = retriever.search("özelkod", mode="hybrid", k=2)
    assert found[0].intent_id == "alpha"
    assert found[0].score == pytest.approx(2/61, abs=1e-6)


def test_catalog_is_not_published_if_embedding_index_fails(client):
    studio = client.app.state.studio
    original = client.get("/v1/catalog").json()
    replacement = copy.deepcopy(original["intents"])
    replacement[0]["description"] += " Yeni sürüm."
    studio.settings.embedding_mode = "http"
    studio.settings.embedding_base_url = "https://vectors.example/v1"
    studio.embeddings.transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "Unavailable"}))
    assert client.post("/v1/catalog/import", json=replacement).status_code == 503
    assert client.get("/v1/catalog").json()["version"] == original["version"]
