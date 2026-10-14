import copy
import json
import math
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.calibration import calibration_identity, fit_threshold, question_hash
from app.config import Settings
from app.contracts import Candidate
from app.evaluation import summarize
from app.main import create_app
from app.policy import baseline_decision, context_decision
from app.providers import OPENROUTER_BASE_URL


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, openrouter_api_key="calibration-test-secret",
                    llm_base_url=OPENROUTER_BASE_URL, llm_model="qwen/qwen3.5-35b-a3b",
                    embedding_mode="http", embedding_base_url=OPENROUTER_BASE_URL,
                    embedding_model="qwen/qwen3-embedding-8b", embedding_provider_only=["nebius"])


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        client.get("/v1/status")
        yield client


def wait_job(client, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get("/v1/requests/" + job_id).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(.01)
    pytest.fail("Calibration/evaluation job timed out")


def install_embeddings(client, fail_model=None, partial_failure=False):
    studio = client.app.state.studio
    known = {c["question"]: c["expected_decision"] != "out_of_scope" for c in studio.store.cases("demo")}
    known["Mutfaktaki fırınımı nasıl temizleyebilirim?"] = False
    requests, scored = [], []

    def respond(request):
        assert request.url.path.endswith("/embeddings"), "Calibration and semantic rejection must never call an LLM"
        body = json.loads(request.content)
        assert "reference_answer" not in body and "expected_intent_id" not in body
        requests.append(body)
        model = body["model"]
        if model == fail_model:
            if not partial_failure or len(scored) >= 5:
                return httpx.Response(429, json={"error": {"code": 429}})
        vectors = []
        for text in body["input"]:
            question = text.split("\nQuery:")[-1].lstrip().removeprefix("query: ")
            if question in known:
                scored.append(question)
                inside = known[question]
                high, low = (.7, .4) if model == "baai/bge-m3" else (.9, .1)
                score = high if inside else low
                vectors.append([score, math.sqrt(1-score*score)])
            else:
                vectors.append([1., 0.])
        return httpx.Response(200, json={"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})

    studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
    return requests, scored


def calibrate(client, models=None):
    response = client.post("/v1/calibrations", json={"embedding_ids": models or ["default"]})
    assert response.status_code == 202, response.text
    return wait_job(client, response.json()["id"])


def records(inside, outside):
    return [{"score": s, "in_scope": True} for s in inside] + [{"score": s, "in_scope": False} for s in outside]


def test_fit_maximizes_retention_under_empirical_false_accept_limit():
    data = records([.9] * 10 + [.55] * 10, [.1] * 19 + [.6])
    fit = fit_threshold(data, .05)
    assert .1 < fit["threshold"] < .55
    assert fit["in_scope_accept_rate"] == 1 and fit["oos_false_accept_rate"] == .05
    strict = fit_threshold(data, 0)
    assert .6 < strict["threshold"] < .9
    assert strict["in_scope_false_reject_rate"] == .5 and strict["low_retention"]
    assert fit_threshold(list(reversed(data)), .05) == fit


def test_indistinguishable_scores_are_reported_as_low_retention_not_fake_success():
    fit = fit_threshold(records([.5] * 10, [.5] * 10), .05)
    assert fit["threshold"] > .5
    assert fit["oos_false_accept_rate"] == 0 and fit["in_scope_accept_rate"] == 0
    assert fit["low_retention"]


@pytest.mark.parametrize("data,target", [
    (records([.9] * 9, [.1] * 10), .05),
    (records([.9] * 10, [.1] * 9), .05),
    (records([float("nan")] * 10, [.1] * 10), .05),
    (records([float("inf")] * 10, [.1] * 10), .05),
    (records([.9] * 10, [.1] * 10), .51),
])
def test_fit_rejects_insufficient_or_invalid_data(data, target):
    with pytest.raises(ValueError):
        fit_threshold(data, target)


def test_seed_calibration_is_disjoint_and_does_not_inflate_test_counts(client, settings):
    studio = client.app.state.studio
    counts = client.get("/v1/status").json()
    assert counts["seed_case_count"] == 29
    assert client.get("/v1/cases?split=calibration").json()["total"] == 72
    cases = studio.calibrator.cases("demo", "seed")
    studio.calibrator.validate_cases("demo", cases, studio.store.catalog("demo"))
    assert len(cases) == 72
    assert client.get("/v1/calibrations").json()["datasets"]["seed"] == {"total": 72, "in_scope": 48, "oos": 24}
    # Existing workspaces seed the added split on restart without overwriting human labels.
    first = cases[0]
    studio.store.review_case("demo", first["case_id"], {"expected_decision": "out_of_scope", "expected_intent_id": None, "split": "calibration"})
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/v1/status").json()["seed_case_count"] == 29
        saved = restarted.app.state.studio.store.cases("demo", split="calibration")
        assert len(saved) == 72 and saved[0]["expected_decision"] == "out_of_scope"


def test_models_fit_separate_thresholds_using_only_calibration_questions(client):
    requests, scored = install_embeddings(client)
    job = calibrate(client, ["default", "qwen3-8b", "bge-m3"])
    assert job["status"] == "completed" and job["progress"] == job["total"] == 144
    assert len(job["results"]) == 2  # Alias uses the same model, provider and preprocessing.
    fits = [r["calibration"] for r in job["results"].values()]
    assert {round(f["threshold"], 4) for f in fits} == {.5, .55}
    assert all(f["sample_count"] == 72 and f["metrics"]["in_scope_accept_rate"] == 1 for f in fits)
    studio = client.app.state.studio
    expected = {c["question"] for c in studio.calibrator.cases("demo", "seed")}
    assert set(scored) == expected and len(scored) == 144
    assert all(f["split"] == "calibration" and "records" not in f and "question_hashes" not in f for f in fits)
    assert "calibration-test-secret" not in json.dumps(job)
    assert requests


def test_calibration_required_before_claim_and_off_remains_explicit_baseline(client):
    install_embeddings(client)
    sid = client.post("/v1/sessions").json()["session_id"]
    body = {"session_id": sid, "turn_revision": 1, "method": "e5", "user_text": "Mutfaktaki fırınımı nasıl temizleyebilirim?"}
    assert client.post("/v1/route", json=body).status_code == 422
    accepted = client.post("/v1/route", json={**body, "semantic_rejection": "off"})
    assert accepted.status_code == 202  # Missing calibration did not consume the revision.
    result = wait_job(client, accepted.json()["request_id"])["result"]
    assert result["decision"] == "route" and result["calibration"] == {"mode": "off", "calibrated": False}


def test_calibrated_semantic_route_rejects_oos_with_no_additional_model_call(client):
    requests, _ = install_embeddings(client)
    fit = calibrate(client)["results"]["default"]["calibration"]
    before = len(requests)
    sid = client.post("/v1/sessions").json()["session_id"]
    response = client.post("/v1/route", json={"session_id": sid, "turn_revision": 1, "method": "e5", "user_text": "Mutfaktaki fırınımı nasıl temizleyebilirim?"})
    assert response.status_code == 202, response.text
    result = wait_job(client, response.json()["request_id"])["result"]
    assert result["decision"] == "out_of_scope"
    assert result["reason_code"] == "calibrated_semantic_rejection"
    assert result["intent_id"] is None and result["workflow_id"] is None
    assert result["rejection_score"] == .1 and result["calibration"]["id"] == fit["id"]
    assert len(requests) == before + 1 and result["llm"] is None and not result["usage"]


@pytest.mark.parametrize("change", ["model", "provider", "instruction", "catalog", "labels", "workspace"])
def test_changed_calibration_identity_or_labels_cannot_reuse_threshold(client, change):
    install_embeddings(client)
    calibrate(client)
    studio = client.app.state.studio
    version = studio.store.catalog("demo")["version"]
    variant = studio.model_catalog.variant("e5")
    workspace = "demo"
    if change == "model":
        variant = studio.model_catalog.variant("e5", "bge-m3")
    elif change == "provider":
        variant.settings.embedding_provider_only = []
    elif change == "instruction":
        variant.settings.embedding_query_instruction = "A different task"
    elif change == "catalog":
        version = "another-catalog"
    elif change == "labels":
        case = studio.calibrator.cases("demo", "seed")[0]
        studio.store.review_case("demo", case["case_id"], {"expected_decision": "out_of_scope", "expected_intent_id": None, "split": "calibration"})
    else:
        workspace = "another-bank"
        studio.ensure_workspace(workspace)
    with pytest.raises(ValueError, match="Kalibrasyon|kalibrasyon"):
        studio.calibrator.resolve(workspace, variant, version, "calibrated")


@pytest.mark.parametrize("overlap", ["test", "catalog", "duplicate"])
def test_overlap_in_calibration_is_rejected(client, overlap):
    studio = client.app.state.studio
    cases = copy.deepcopy(studio.calibrator.cases("demo", "seed"))
    catalog = studio.store.catalog("demo")
    text = studio.store.cases("demo", split="test")[0]["question"] if overlap == "test" else catalog["intents"][0]["examples"][0] if overlap == "catalog" else cases[1]["question"]
    cases[0]["question"] = text + " !!!"
    assert question_hash(cases[0]["question"]) == question_hash(text)
    with pytest.raises(ValueError):
        studio.calibrator.validate_cases("demo", cases, catalog)


def test_calibration_split_cannot_be_reported_as_test_accuracy(client):
    install_embeddings(client)
    calibrate(client)
    response = client.post("/v1/evaluations", json={"methods": ["e5"], "split": "calibration"})
    assert response.status_code == 422 and "aynı eşikle test edilemez" in response.json()["detail"]
    response = client.post("/v1/evaluations", json={"methods": ["e5"]})
    assert response.status_code == 202
    job = wait_job(client, response.json()["id"])
    result = job["results"]["e5"]
    assert job["selected_count"] == 29 and result["metrics"]["oos_total"] == 3
    assert result["metrics"]["oos_false_accept_rate"] == 0
    assert all(r["rejection_score"] is not None for r in result["records"])
    assert result["calibration"]["id"]


def test_failed_model_never_publishes_partial_fit_and_other_model_continues(client):
    _, scored = install_embeddings(client, fail_model="qwen/qwen3-embedding-8b", partial_failure=True)
    job = calibrate(client, ["default", "bge-m3"])
    assert job["status"] == "completed" and job["progress"] == job["total"] == 144
    assert job["results"]["default"]["status"] == "failed"
    assert job["results"]["bge-m3"]["status"] == "completed"
    studio = client.app.state.studio
    assert studio.store.latest_calibration("demo", calibration_identity(studio.settings, studio.store.catalog("demo")["version"])) is None
    assert len(scored) == 77


def test_rejection_preserves_active_flow_slot_answers_and_penalizes_false_rejects():
    proposal = context_decision("2000", {"active_intent": "card.limit.change", "pending_slot": "new_limit"})
    assert proposal.decision == "continue" and proposal.slots == {"new_limit": "2000"}
    candidate = Candidate(intent_id="account.balance", name="Balance", domain="Banking", score=.4, score_type="cosine_similarity", evidence="sample", semantic_score=.4)
    rejected = baseline_decision("Hesabımdaki bakiyeyi öğrenmek istiyorum", [candidate], {}, semantic=True, rejection_threshold=.5)
    assert rejected.decision == "out_of_scope"
    accepted = baseline_decision("Hesabımdaki bakiyeyi öğrenmek istiyorum", [candidate], {}, semantic=True, rejection_threshold=.4)
    assert accepted.decision == "route"  # Exactly at threshold is accepted, same as fit.
    row = {"expected_decision": "route", "expected_intent_id": "account.balance", "decision": "out_of_scope", "intent_id": None, "correct": False, "candidate_hit": True, "total_ms": 1}
    metrics = summarize([row])
    assert metrics["routing_accuracy"] == 0 and metrics["in_scope_false_reject_rate"] == 1


def test_queued_evaluation_freezes_the_threshold_it_was_started_with(client):
    import threading
    from uuid import uuid4
    install_embeddings(client)
    fit = calibrate(client)["results"]["default"]["calibration"]
    studio = client.app.state.studio
    release = threading.Event()
    blocker = studio.evaluation_pool.submit(release.wait, 5)
    try:
        response = client.post("/v1/evaluations", json={"methods": ["e5"], "limit": 1})
        assert response.status_code == 202
        changed = studio.store.latest_calibration("demo", fit["identity"])
        changed.update(id=str(uuid4()), created=time.time()+1, threshold=.99)
        studio.store.save_calibration("demo", changed)
    finally:
        release.set()
    blocker.result()
    result = wait_job(client, response.json()["id"])["results"]["e5"]
    assert result["calibration"]["id"] == fit["id"]
    assert result["calibration"]["threshold"] == .5


@pytest.mark.parametrize("change", ["labels", "catalog"])
def test_data_changes_while_fitting_prevent_publication(client, monkeypatch, change):
    import app.calibration as module
    install_embeddings(client)
    studio = client.app.state.studio
    original = module.fit_threshold
    def changed_fit(*args):
        result = original(*args)
        if change == "labels":
            case = studio.calibrator.cases("demo", "seed")[0]
            studio.store.review_case("demo", case["case_id"], {"expected_decision": "out_of_scope", "expected_intent_id": None, "split": "calibration"})
        else:
            intents = studio.store.catalog("demo")["intents"]
            intents[0]["description"] += " Updated catalog."
            studio.store.save_catalog("demo", intents)
        return result
    monkeypatch.setattr(module, "fit_threshold", changed_fit)
    identity = calibration_identity(studio.settings, studio.store.catalog("demo")["version"])
    job = calibrate(client)
    assert job["status"] == "failed"
    assert "veri veya katalog değişti" in job["results"]["default"]["error"]
    assert studio.store.latest_calibration("demo", identity) is None


def test_legacy_request_retry_remains_idempotent_after_upgrade(client):
    from app.contracts import RouteRequest
    from app.store import fingerprint
    sid = client.post("/v1/sessions").json()["session_id"]
    body = {"request_id": "legacy-request", "session_id": sid, "turn_revision": 1, "method": "e5", "user_text": "Eski bir istek"}
    parsed = RouteRequest(**body)
    studio = client.app.state.studio
    studio.store.create_job("demo", "route", {"request_hash": fingerprint(parsed.model_dump(exclude_none=True, exclude={"semantic_rejection"}))}, body["request_id"])
    assert client.post("/v1/route", json=body).status_code == 202
    assert client.post("/v1/route", json={**body, "semantic_rejection": "calibrated"}).status_code == 409
