import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.calibration import question_hash
from app.catalog_scope import required_ids, select_catalogs
from app.config import ROOT, Settings
from app.contracts import Intent, RetrievalProfile
from app.demo_taxonomy import revise_catalog
from app.main import create_app
from app.policy import explicit_workflow_slots
from app.providers import ModelUnavailable
from app.retrieval import Embeddings, Retriever
from app.selector import PROMPT_VERSION, Selector
from app.service import Studio
from app.store import Store, fingerprint


def demo(name):
    return json.loads((ROOT / "data/demo" / name).read_text())


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled",
                    llm_base_url="http://llm.test/v1", llm_api_key="", openrouter_api_key="")


def migration_fixture(store):
    legacy = json.loads((ROOT / "tests/fixtures/taxonomy-v1.json").read_text())
    old_catalog = [Intent.model_validate(i).model_dump() for i in legacy["intents"]]
    ids = {i["intent_id"] for i in old_catalog}
    new_catalog = [Intent.model_validate(i).model_dump() for i in demo("catalog.json") if i["intent_id"] in ids]
    # Only the two affected cases belong to this compact catalog fixture.
    old_cases = [c for c in legacy["cases"] if c["case_id"] != "seed-020"]
    case_ids = {c["case_id"] for c in old_cases}
    new_cases = [c for c in demo("cases.json") if c["case_id"] in case_ids]
    manifest = demo("migrations/taxonomy-v2.json")
    assert all(fingerprint(i) == manifest["previous_catalog_hashes"][i["intent_id"]] for i in old_catalog)
    assert all(fingerprint(c) == manifest["previous_case_hashes"][c["case_id"]] for c in old_cases)
    version = store.save_catalog("demo", old_catalog)
    store.save_cases("demo", old_cases)
    return manifest, old_catalog, new_catalog, old_cases, new_cases, version


def test_demo_revision_archives_labels_catalog_and_jobs_and_is_idempotent(settings):
    store = Store(settings.data_dir)
    manifest, old, new, old_cases, new_cases, version = migration_fixture(store)
    job = store.create_job("demo", "evaluation", {"status": "completed", "catalog_version": version,
                                                "cases": old_cases, "accuracy": .5})
    customer = {**old_cases[0], "case_id": "customer-1", "source": "customer"}
    store.save_cases("demo", [customer])
    for _ in range(2):
        store.revise_demo("demo", manifest, new, new_cases, {"card.pin", "transfer.status"})
    assert store.catalog("demo")["intents"] == new
    assert store.catalog("demo", version)["intents"] == old
    assert len(store.catalog_versions("demo")) == 2
    assert store.cases("demo", "seed") == new_cases
    assert store.cases("demo", "customer") == [customer]
    assert store.job("demo", job["id"]) == job
    for before, after in zip(old_cases, new_cases):
        history = store.case_versions("demo", before["case_id"])
        assert [v["case"] for v in history["versions"]] == [before, after]
    report, = store.migration_reports("demo")
    assert len(report["relabeled_cases"]) == 2 and not report["preserved_cases"]
    assert store.migration_reports("other") == []


@pytest.mark.parametrize("edit", ["parent", "child", "case", "review"])
def test_revision_preserves_human_edits_and_dependent_labels(settings, edit):
    store = Store(settings.data_dir)
    manifest, old, new, old_cases, new_cases, _ = migration_fixture(store)
    if edit in ("parent", "child"):
        iid = "card.pin" if edit == "parent" else "bank.card.debit.pin_reset"
        next(i for i in old if i["intent_id"] == iid)["selection_rule"] = "Kullanıcının özel seçim kuralı."
        store.save_catalog("demo", old)
    elif edit == "review":
        store.review_case("demo", "seed-007", {"expected_intent_id": "card.pin", "split": "test"})
    else:
        with store.connect() as db:
            changed = {**old_cases[0], "question": "Kullanıcının düzenlediği soru"}
            db.execute("UPDATE cases SET payload=? WHERE workspace='demo' AND case_id='seed-007'", (json.dumps(changed),))
    preserved = store.case_versions("demo", "seed-007")["current"]
    store.revise_demo("demo", manifest, new, new_cases, {"card.pin", "transfer.status"})
    assert store.case_versions("demo", "seed-007")["current"] == preserved
    assert store.case_versions("demo", "seed-011")["current"]["expected_intent_id"] == "bank.transfer.eft.status"
    report, = store.migration_reports("demo")
    assert report["preserved_cases"] == ["seed-007"]
    if edit in ("parent", "child"):
        assert next(i for i in store.catalog("demo")["intents"] if i["intent_id"] == iid)["selection_rule"] == "Kullanıcının özel seçim kuralı."


def test_revision_failure_rolls_back_all_records(settings, monkeypatch):
    store = Store(settings.data_dir)
    manifest, old, new, old_cases, new_cases, version = migration_fixture(store)
    def fail(*args):
        raise RuntimeError("archive failure")
    monkeypatch.setattr(store, "_archive_case", fail)
    with pytest.raises(RuntimeError):
        store.revise_demo("demo", manifest, new, new_cases, {"card.pin", "transfer.status"})
    assert store.catalog("demo") == {"version": version, "intents": old}
    assert store.cases("demo") == old_cases
    assert store.migration_reports("demo") == []


def test_case_history_and_migration_report_are_workspace_scoped(settings):
    with TestClient(create_app(settings)) as client:
        report, = client.get("/v1/catalog/migrations").json()
        assert report["id"] == "demo-taxonomy-v2" and report["applicable"]
        assert len(report["case_changes"]) == 17
        before = client.get("/v1/cases/seed-007/versions").json()["current"]
        client.patch("/v1/cases/seed-007/review", json={"expected_decision": "route", "expected_intent_id": "card.pin", "split": "test"})
        versions = client.get("/v1/cases/seed-007/versions").json()
        assert versions["versions"][0]["case"] == before
        assert versions["current"]["expected_intent_id"] == "card.pin"
        other = client.get("/v1/cases/seed-007/versions?workspace=other").json()
        assert other["current"]["expected_intent_id"] == "bank.card.debit.pin_reset" and not other["versions"]
        assert client.get("/v1/cases/absent/versions").status_code == 404


def test_new_taxonomy_has_explicit_boundaries_and_disjoint_calibration():
    catalog = demo("catalog.json")
    assert revise_catalog(catalog) == catalog
    by_id = {i["intent_id"]: Intent.model_validate(i) for i in catalog}
    assert all(i.selection_rule for i in by_id.values())
    assert by_id["bank.transfer.eft.status"].required_slots == by_id["transfer.status"].required_slots == ["transfer_reference"]
    assert by_id["bank.card.debit.lost"].required_slots == ["card_last4"]
    assert "SIM" in by_id["bank.digital.phone.sim_lock"].selection_rule
    questions = {question_hash(c["question"]) for c in demo("calibration-cases.json")}
    assert not questions & {question_hash(c["question"]) for c in demo("cases.json")}
    assert not questions & {question_hash(e) for i in catalog for e in i["examples"]}
    cases = {c["case_id"]: c for c in demo("cases.json")}
    assert cases["seed-020"]["expected_intent_id"] == "digital.device"
    assert cases["seed-022"]["expected_intent_id"] == "deposit.rate"
    assert sum("label_revision" in c for c in cases.values()) == 5


def test_specific_gold_ids_survive_all_catalog_sizes_without_relabeling():
    intents, cases = demo("catalog.json"), demo("cases.json")
    before = copy.deepcopy(cases)
    scopes = select_catalogs({"version": fingerprint(intents), "intents": intents}, [48, 200, 800], cases)
    assert all(required_ids(cases) <= set(s["metadata"]["intent_ids"]) for s in scopes)
    assert [len(s["intents"]) for s in scopes] == [48, 200, 800]
    assert cases == before
    assert all(s["metadata"]["selection_protocol"] == "fixed-cohort-nested-domain-v2" for s in scopes)


def selector_fixture(settings, response):
    intents = [Intent.model_validate(i) for i in demo("catalog.json") if i["intent_id"] in {"card.limit.change", "card.cancel", "card.temporary_block"}]
    retriever = Retriever(intents, "fixture", Embeddings(settings))
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]})
    return Selector(settings, httpx.MockTransport(respond)), retriever, calls


def test_router_routes_without_slots_and_workflow_collects_then_confirms(settings):
    selector, retriever, calls = selector_fixture(settings, {"decision": "route", "intent_id": "card.limit.change", "slots": {"new_limit": "999999"}})
    studio = Studio(settings)
    studio.selector = selector
    try:
        # Use lexical retrieval with a mocked selector call: no embedding/network dependency.
        candidates = retriever.search("Kart limitimi artırmak istiyorum", k=3)
        retriever.search_with_trace = lambda *a, **k: (candidates, {"executed": True, "completed": True})
        result, state = studio.compute("Kart limitimi artırmak istiyorum", {}, "hybrid_llm", retriever, "chat", lambda *a, **k: None)
        assert result["decision"] == "route" and result["slots"] == {}
        assert result["missing_slots"] == ["new_limit"] and state["pending_slot"] == "new_limit"
        payload = calls[0]
        user = json.loads(payload["messages"][1]["content"])
        assert "slots" not in payload["response_format"]["json_schema"]["schema"]["properties"]
        assert all("required_slots" not in c and "selection_rule" in c for c in user["candidates"])
        assert "pending_slot" not in user["conversation"] and "slots" not in user["conversation"]
        result, state = studio.compute("5000", state, "hybrid_llm", retriever, "chat", lambda *a, **k: None)
        assert result["slots"] == {"new_limit": "5000"} and result["pending_confirmation"]
        result, state = studio.compute("evet", state, "hybrid_llm", retriever, "chat", lambda *a, **k: None)
        assert result["simulation_complete"] and len(calls) == 1
        assert result["prompt_version"] == PROMPT_VERSION
    finally:
        studio.close()


@pytest.mark.parametrize("response", [
    {"decision": "clarify", "intent_id": "card.limit.change", "question": "Yeni limit?"},
    {"decision": "clarify", "intent_id": None, "question": "Yeni limit?", "mentioned_intent_ids": ["card.limit.change"]},
    {"decision": "clarify", "intent_id": None},
])
def test_slot_clarification_is_a_contract_error_not_an_automatic_correct_route(settings, response):
    selector, retriever, _ = selector_fixture(settings, response)
    with pytest.raises(ModelUnavailable) as caught:
        selector.select("Limitimi değiştir", {}, retriever.search("limit", k=3), retriever.intents)
    assert caught.value.diagnostics["category"] == "routing_contract"
    assert "Yeni limit" not in json.dumps(caught.value.diagnostics)


def test_real_intent_ambiguity_still_clarifies(settings):
    response = {"decision": "clarify", "intent_id": None, "question": "Geçici kapatma mı kalıcı iptal mi?",
                "reason_code": "ambiguous_intent", "mentioned_intent_ids": ["card.cancel", "card.temporary_block"]}
    selector, retriever, _ = selector_fixture(settings, response)
    proposal, _ = selector.select("Kartımı kapat", {}, retriever.search("kart", k=3), retriever.intents)
    assert proposal.decision == "clarify" and proposal.intent_id is None


@pytest.mark.parametrize("text,expected", [
    ("Kart limitim 50.000 TL olsun", "50000"),
    ("Kart limitimi 5000'e çıkar", "5000"),
    ("Yeni limitim 7000 TL", "7000"),
    ("Kart limitimi 500 TL artır", None),
    ("Yeni limitimi 500 TL artır", None),
    ("Kart limitimi 5000 değil 6000 yap", None),
    ("Kart limitimi 5.50 TL yap", None),
])
def test_workflow_extracts_only_an_explicit_target_amount(text, expected):
    intent = Intent.model_validate(demo("catalog.json")[0])
    assert explicit_workflow_slots(text, intent) == ({"new_limit": expected} if expected else {})


def test_workflow_requires_explicit_card_and_reference_fields():
    intents = {i["intent_id"]: Intent.model_validate(i) for i in demo("catalog.json")}
    assert explicit_workflow_slots("Kaybolan kartın son dört hanesi 1234", intents["bank.card.debit.lost"]) == {"card_last4": "1234"}
    assert explicit_workflow_slots("1234 lira gönderdim", intents["bank.transfer.eft.status"]) == {}
    assert explicit_workflow_slots("EFT referans numarası AB12345", intents["bank.transfer.eft.status"]) == {"transfer_reference": "AB12345"}


def test_controlled_reranker_profiles_differ_only_by_reranker():
    rows = json.loads((ROOT / "data/reranker-comparison-profiles.json").read_text())
    off, on = [RetrievalProfile.model_validate(r).model_dump() for r in rows]
    assert off["reranker_id"] is None and on["reranker_id"] == "default"
    assert {k: v for k, v in off.items() if k not in ("id", "name", "reranker_id")} == {k: v for k, v in on.items() if k not in ("id", "name", "reranker_id")}
