import copy
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.catalog_quality import audit_catalog
from app.config import ROOT, Settings
from app.contracts import EvaluationRequest, Intent, Proposal, RetrievalProfile
from app.evaluation import diagnose, summarize
from app.main import create_app
from app.model_catalog import ModelCatalog, embedding_key
from app.model_registry import Registration
from app.providers import ModelUnavailable
from app.reranker import Reranker
from app.retrieval import Embeddings, Retriever
from app.store import Store, fingerprint


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="http", embedding_base_url="http://embedding.test/v1",
                    embedding_model="test-embedding", llm_base_url="http://llm.test/v1", llm_model="test-llm",
                    reranker_mode="http", reranker_base_url="http://reranker.test/v1", reranker_model="test-reranker")


def wait_job(client, job_id):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        job = client.get("/v1/evaluations/"+job_id).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(.01)
    pytest.fail("Evaluation timed out")


def transport(studio, fail_reranker=False):
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append((str(request.url), body))
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [1., .1]} for i in range(len(body["input"]))]})
        if request.url.path.endswith("rerank"):
            assert "expected_intent_id" not in json.dumps(body) and "reference_answer" not in json.dumps(body)
            if fail_reranker:
                return httpx.Response(429, json={"error": {"code": 429}})
            # Deliberately reverse input order: confirms LLM really receives reranked candidates.
            return httpx.Response(200, json={"results": [{"index": i, "relevance_score": i/100} for i in reversed(range(len(body["documents"])))]})
        user = json.loads(body["messages"][1]["content"])
        assert "expected_intent_id" not in user and "reference_answer" not in user
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"decision": "route", "intent_id": user["candidates"][0]["intent_id"]})}}]})
    shared = httpx.MockTransport(respond)
    studio.embeddings.transport = studio.selector.transport = studio.reranker.transport = shared
    return requests


def test_weighted_fusion_changes_ranking_without_duplicating_intents():
    intents = [Intent(intent_id=id, name=id.title(), domain="Test", description="Bağımsız test işlemi", examples=[id], workflow_id="workflow."+id) for id in ["alpha", "beta"]]
    class Vectors:
        def encode(self, texts, query=False):
            return np.array([[1., 0.]]) if query else np.array([[.1, .99], [1., 0.]])
    retriever = Retriever(intents, "test", Vectors())
    equal, trace = retriever.search_with_trace("alpha", "hybrid", 2)
    semantic, weighted_trace = retriever.search_with_trace("alpha", "hybrid", 2, semantic_weight=.8)
    assert equal[0].intent_id == "alpha" and semantic[0].intent_id == "beta"
    assert trace["semantic"] == ["beta", "alpha"] and trace["lexical"] == ["alpha", "beta"]
    assert len(set(weighted_trace["pool"])) == 2


@pytest.mark.parametrize("bad", [{"pool_k": 10}, {"source_k": 10}, {"candidate_k": 41, "pool_k": 50}, {"semantic_weight": 0}, {"semantic_weight": 1}, {"reranker_url": "http://untrusted"}])
def test_invalid_profile_budgets_and_arbitrary_endpoints_are_rejected(bad):
    with pytest.raises(ValidationError):
        RetrievalProfile(**bad)


def test_profile_variants_freeze_models_and_separate_representation_indexes(settings):
    catalog = ModelCatalog(settings)
    profiles = [RetrievalProfile(), RetrievalProfile(id="separate", representation="separate"),
                RetrievalProfile(id="semantic", source="semantic"),
                RetrievalProfile(id="rerank", source_k=60, pool_k=40, candidate_k=8, reranker_id="default")]
    variants = catalog.expand(EvaluationRequest(methods=["hybrid_llm"], retrieval_profiles=profiles))
    assert len({v.id for v in variants}) == 4
    assert embedding_key(variants[0].settings) != embedding_key(variants[1].settings)
    assert embedding_key(variants[0].settings) == embedding_key(variants[2].settings) == embedding_key(variants[3].settings)
    profiles[1].representation = "combined"
    assert variants[1].retrieval.representation == "separate"
    assert variants[3].metadata["reranker"]["model"] == "test-reranker"
    intents = [Intent.model_validate(json.loads((ROOT/"data/demo/catalog.json").read_text())[0])]
    normal = Retriever(intents, "one", Embeddings(variants[0].settings))
    separate = Retriever(intents, "two", Embeddings(variants[1].settings))
    assert len(separate.documents) == len(normal.documents)+1
    assert separate.documents[0][2] == intents[0].examples[0]


@pytest.mark.parametrize("protocol", ["cohere", "tei"])
def test_reranker_validates_and_reorders_indexed_scores_without_shared_keys(settings, protocol):
    settings.reranker_protocol = protocol
    settings.openrouter_api_key = "must-not-be-sent"
    def respond(request):
        assert "Authorization" not in request.headers
        body = json.loads(request.content)
        assert request.url.path == "/v1/rerank"
        if protocol == "tei":
            assert body["texts"] == ["a", "b"] and body["raw_scores"] is True
            return httpx.Response(200, json=[{"index": 1, "score": 9.}, {"index": 0, "score": -1.}])
        assert body["documents"] == ["a", "b"] and body["top_n"] == 2
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 9.}, {"index": 0, "relevance_score": -1.}]})
    assert Reranker(settings, httpx.MockTransport(respond)).scores("query", ["a", "b"]) == [-1., 9.]


@pytest.mark.parametrize("rows", [[], [{"index": 0, "relevance_score": 1.}],
    [{"index": 0, "relevance_score": 1.}, {"index": 0, "relevance_score": .5}],
    [{"index": -1, "relevance_score": 1.}, {"index": 1, "relevance_score": .5}],
    [{"index": 0, "relevance_score": "NaN"}, {"index": 1, "relevance_score": .5}],
    [{"index": True, "relevance_score": 1.}, {"index": 0, "relevance_score": .5}]])
def test_invalid_reranker_response_is_not_a_routing_decision(settings, rows):
    reranker = Reranker(settings, httpx.MockTransport(lambda _: httpx.Response(200, json={"results": rows})))
    with pytest.raises(ModelUnavailable):
        reranker.scores("query", ["a", "b"])


def test_local_reranker_loads_once_and_batches_query_document_pairs(settings, monkeypatch):
    settings.reranker_mode = "local"
    settings.reranker_local_files_only = True
    calls = []
    class CrossEncoder:
        def __init__(self, model, **kwargs):
            calls.append(("load", model, kwargs))
        def predict(self, pairs, **kwargs):
            calls.append(("predict", pairs, kwargs))
            return np.array([.2, .8])
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=CrossEncoder))
    reranker = Reranker(settings)
    reranker.prepare()
    assert reranker.scores("query", ["first", "second"]) == [.2, .8]
    assert calls == [("load", settings.reranker_model, {"local_files_only": True, "max_length": 512}),
                     ("predict", [["query", "first"], ["query", "second"]],
                      {"batch_size": settings.reranker_batch_size, "show_progress_bar": False})]


def test_model_registry_reranker_credentials_and_workspace_are_isolated(settings, monkeypatch):
    monkeypatch.setenv("INTENT_MODEL_KEY_RANK", "private-rank-key")
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        with pytest.raises(ValidationError):
            Registration(kind="reranker", name="bad", model="some-model", connection="openrouter")
        body = {"kind": "reranker", "name": "Local ranking", "model": "custom-reranker", "connection": "onprem",
                "base_url": "http://rank.test", "auth": "env", "credential_env": "INTENT_MODEL_KEY_RANK", "reranker_protocol": "tei"}
        saved = client.post("/v1/model-registry", json=body)
        assert saved.status_code == 201 and "private-rank-key" not in saved.text
        rid = saved.json()["id"]
        resolved = studio.model_catalog.resolve("reranker", rid)
        assert resolved.reranker_api_key == "private-rank-key" and resolved.reranker_protocol == "tei"
        assert any(r["id"] == rid for r in client.get("/v1/models").json()["reranker"])
        assert "private-rank-key" not in client.get("/v1/models").text
        assert not any(r["id"] == rid for r in client.get("/v1/models?workspace=other").json()["reranker"])
        assert client.get("/v1/model-discovery/openrouter?kind=reranker").status_code == 422


def test_matrix_runs_same_cases_and_llm_only_sees_final_reranked_list(settings):
    with TestClient(create_app(settings)) as client:
        calls = transport(client.app.state.studio)
        profiles = [RetrievalProfile().model_dump(), RetrievalProfile(id="sem", source="semantic").model_dump(),
                    RetrievalProfile(id="rerank", pool_k=40, candidate_k=5, reranker_id="default").model_dump()]
        response = client.post("/v1/evaluations", json={"methods": ["hybrid_llm"], "retrieval_profiles": profiles, "catalog_sizes": [48, 800], "limit": 2})
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()["id"])
        assert job["status"] == "completed" and len(job["results"]) == 6
        cohort = None
        for result in job["results"].values():
            records = result["records"]
            labels = [(r["case_id"], r["expected_intent_id"]) for r in records]
            cohort = cohort or labels
            assert cohort == labels and result["metrics"]["errors"] == 0
            assert result["metrics"]["stage_quality"]["retrieval_completed"] == 2
            if result["retrieval_profile"]["reranker_id"]:
                assert result["metrics"]["stage_latency_ms"]["reranking"]["count"] == 2
                assert result["metrics"]["stage_latency_ms"]["reranking"]["p95"] is not None
            for r in records:
                assert "analysis" in r
                if result["retrieval_profile"]["reranker_id"]:
                    assert r["candidates"][0]["intent_id"] == r["retrieval_candidates"][-1]["intent_id"]
                    assert r["retrieval_trace"]["final"] == [c["intent_id"] for c in r["candidates"]]
                    assert len(r["candidates"]) == 5 and "reranking" in r["timings_ms"]
                    assert r["intent_id"] == r["candidates"][0]["intent_id"]
        llm_calls = [b for url, b in calls if url.endswith("chat/completions")]
        assert len(llm_calls) == 12
        assert sorted(len(json.loads(b["messages"][1]["content"])["candidates"]) for b in llm_calls) == [5]*4+[20]*8


def test_failed_reranker_does_not_fall_back_or_stop_other_strategies(settings):
    with TestClient(create_app(settings)) as client:
        calls = transport(client.app.state.studio, fail_reranker=True)
        profiles = [RetrievalProfile(id="rank", candidate_k=5, reranker_id="default").model_dump(), RetrievalProfile().model_dump()]
        response = client.post("/v1/evaluations", json={"methods": ["hybrid_llm"], "retrieval_profiles": profiles, "limit": 1})
        job = wait_job(client, response.json()["id"])
        assert job["status"] == "completed"
        failed, healthy = list(job["results"].values())
        assert failed["metrics"]["errors"] == 1 and healthy["metrics"]["errors"] == 0
        record = failed["records"][0]
        assert record["analysis"]["category"] == "technical_error" and record["error_stage"] == "reranking"
        assert record["diagnostics"]["http_status"] == 429
        assert len([url for url, _ in calls if url.endswith("chat/completions")]) == 1


def diagnostic_record(**updates):
    return {"expected_decision": "route", "expected_intent_id": "gold", "decision": "route", "intent_id": "other", "correct": False,
            "candidate_hit": True, "total_ms": 12, "retrieval_trace": {"executed": True, "completed": True, "semantic": ["gold"], "lexical": [],
             "pool": ["gold", "other"], "final": ["gold", "other"]}, **updates}


def test_stage_attribution_distinguishes_where_gold_is_lost_and_keeps_errors_in_accuracy():
    first = diagnostic_record()
    assert diagnose(first)["category"] == "selection_error"
    missing = copy.deepcopy(first)
    missing["retrieval_trace"].update(semantic=[], pool=[], final=[])
    assert diagnose(missing)["category"] == "retrieval_miss"
    missing["retrieval_trace"]["semantic"] = ["gold"]
    assert diagnose(missing)["category"] == "fusion_cutoff"
    missing["retrieval_trace"].update(pool=["gold"], reranker_used=True)
    assert diagnose(missing)["category"] == "reranker_cutoff"
    assert diagnose(diagnostic_record(decision="clarify"))["category"] == "unnecessary_clarification"
    assert diagnose(diagnostic_record(decision="out_of_scope"))["category"] == "false_rejection"
    success = diagnostic_record(correct=True, intent_id="gold")
    error = diagnostic_record(decision="error", error_stage="selection")
    context = diagnostic_record(correct=True, intent_id="gold", retrieval_trace={"executed": False, "context_bypass": True}, candidate_hit=False)
    metrics = summarize([success, error, context])
    assert metrics["routing_accuracy"] == pytest.approx(2/3)
    assert metrics["stage_quality"]["candidate_conditioned_accuracy"] == .5
    assert metrics["stage_quality"]["context_bypasses"] == 1
    assert metrics["stage_quality"]["stages"]["final"] == {"hits": 2, "total": 2, "recall": 1.}


def test_catalog_audit_exposes_eft_conflict_without_changing_labels(settings):
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        before = studio.store.cases("demo")
        version = studio.store.catalog("demo")["version"]
        report = client.get("/v1/catalog/audit").json()
        eft = next(i for i in report["issues"] if set(i["intent_ids"]) == {"transfer.status", "bank.transfer.eft.status"})
        assert any(c["case_id"] == "seed-011" for c in eft["cases"])
        assert report["tested_intent_count"] == 26 and report["untested_intent_count"] == 774
        assert report["automatic_label_changes"] is False
        assert studio.store.cases("demo") == before and studio.store.catalog("demo")["version"] == version


def test_versioned_definition_edit_preserves_workflow_labels_and_rejects_stale_writes(settings):
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        original = client.get("/v1/catalog").json()
        before_cases = studio.store.cases("demo")
        intent = copy.deepcopy(original["intents"][0])
        intent["selection_rule"] = "Yalnız kredi kartı toplam limitini değiştirme talebi."
        request = {"expected_version": original["version"], "intent": intent}
        path = "/v1/catalog/intents/"+intent["intent_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: client.patch(path, json=request).status_code, range(2)))
        assert sorted(statuses) == [200, 409]
        latest = client.get("/v1/catalog").json()
        assert latest["version"] != original["version"] and len(latest["intents"]) == 800
        assert client.get("/v1/catalog", params={"version": original["version"]}).json() == original
        assert latest["intents"][1:] == original["intents"][1:]
        assert studio.store.cases("demo") == before_cases
        intent["workflow_id"] = "workflow.not_allowed"
        assert client.patch(path, json={"expected_version": latest["version"], "intent": intent}).status_code == 422
