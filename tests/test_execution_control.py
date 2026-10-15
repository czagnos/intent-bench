import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.contracts import Candidate, Intent
from app.execution import (
    EvaluationController, EvaluationStopped, ExecutionLimits,
    activate_execution, execution_checkpoint, execution_stage,
)
from app.providers import ModelUnavailable, OPENROUTER_BASE_URL, TYPESAFE_BASE_URL
from app.reranker import Reranker
from app.retrieval import Embeddings, Retriever
from app.selector import Selector


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, data_dir=tmp_path, model_credentials_file=tmp_path / "credentials.env",
        embedding_mode="http", embedding_base_url=OPENROUTER_BASE_URL,
        embedding_model="test-embedding", embedding_batch_size=1,
        llm_base_url=OPENROUTER_BASE_URL, llm_model="test-selector",
        openrouter_api_key="synthetic-key",
    )


def embedding_response(request):
    body = json.loads(request.content)
    return httpx.Response(200, json={"data": [
        {"index": index, "embedding": [1.0, 0.0]}
        for index in range(len(body["input"]))
    ]})


def test_request_limit_reserves_each_batch_and_never_sends_excess(settings):
    sent = []

    def respond(request):
        sent.append(request)
        return embedding_response(request)

    embeddings = Embeddings(settings, httpx.MockTransport(respond))
    controller = EvaluationController(ExecutionLimits(max_provider_requests=1))
    with activate_execution(controller), pytest.raises(EvaluationStopped) as stopped:
        embeddings.encode(["first", "second"])
    assert stopped.value.stop_reason == "request_limit"
    assert len(sent) == 1
    assert controller.accounting().provider_requests == 1
    # Activation resets even when a provider operation is interrupted.
    assert embeddings.encode(["outside"]).shape == (1, 2)
    assert len(sent) == 2
    assert controller.accounting().provider_requests == 1


@pytest.mark.parametrize("limits", [
    {"max_provider_requests": True}, {"max_provider_requests": -1},
    {"max_provider_requests": 100001}, {"max_provider_requests": 1.0},
    {"max_duration_seconds": True}, {"max_duration_seconds": 0},
    {"max_duration_seconds": 86401}, {"max_duration_seconds": float("inf")},
    {"max_reported_cost_usd": True}, {"max_reported_cost_usd": 0},
    {"max_reported_cost_usd": -1}, {"max_reported_cost_usd": float("nan")},
    {"max_reported_cost_usd": 10001}, {"unknown": 1},
])
def test_limits_reject_invalid_or_unknown_fields(limits):
    with pytest.raises(ValidationError):
        ExecutionLimits.model_validate(limits)


def test_nested_activation_and_other_threads_are_isolated(settings):
    embeddings = Embeddings(settings, httpx.MockTransport(embedding_response))
    outer = EvaluationController(ExecutionLimits(max_provider_requests=0))
    inner = EvaluationController(ExecutionLimits(max_provider_requests=1))
    with activate_execution(outer):
        with activate_execution(inner):
            embeddings.encode(["inner"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(embeddings.encode, ["unbound thread"]).result().shape == (1, 2)
        with pytest.raises(EvaluationStopped, match="request_limit"):
            embeddings.encode(["outer"])
    assert outer.accounting().provider_requests == 0
    assert inner.accounting().provider_requests == 1
    execution_checkpoint()


def selection_input():
    intent = Intent(intent_id="card.lost", name="Lost card", domain="Cards",
                    description="Report a missing card", examples=["My card is missing"],
                    workflow_id="workflow.card.lost")
    candidate = Candidate(intent_id=intent.intent_id, name=intent.name, domain=intent.domain,
                          evidence=intent.examples[0], score=1, score_type="fixture")
    return [candidate], {intent.intent_id: intent}


def completion_response():
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps({"decision": "route", "intent_id": "card.lost"})}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50, "cost": .02},
    })


def test_accounting_tracks_batches_services_stages_and_persists_safe_snapshots(settings):
    snapshots = []
    controller = EvaluationController(ExecutionLimits(), on_checkpoint=snapshots.append)

    def respond(request):
        data = embedding_response(request).json()
        data["usage"] = {"prompt_tokens": 7, "total_tokens": 7, "cost": .001,
                         "private_field": "not-in-ledger"}
        return httpx.Response(200, json=data)

    with activate_execution(controller):
        with execution_stage("index"):
            Embeddings(settings, httpx.MockTransport(respond)).encode(["first", "second"])
        with execution_stage("cases"):
            _, usage = Selector(settings, httpx.MockTransport(lambda request: completion_response())).select(
                "lost card", {}, *selection_input())
    accounting = controller.accounting()
    assert accounting.provider_requests == 3
    assert accounting.known_prompt_tokens == 54
    assert accounting.known_completion_tokens == 10
    assert accounting.known_total_tokens == 64
    assert accounting.unknown_prompt_token_requests == 0
    assert accounting.unknown_completion_token_requests == 2
    assert accounting.unknown_total_token_requests == 0
    assert accounting.known_cost_usd == pytest.approx(.022)
    assert accounting.reported_cost_usd == pytest.approx(.022)
    assert accounting.unknown_cost_requests == 0
    assert [(row.service, row.stage, row.provider_requests) for row in accounting.by_service_stage] == [
        ("embedding", "index", 2), ("llm", "cases", 1),
    ]
    assert usage == {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
    assert len(snapshots) == 6  # Reserved and completed HTTP attempts are separately persisted.
    assert snapshots[0].provider_requests == 1 and snapshots[0].unknown_cost_requests == 1
    assert snapshots[-1] == accounting
    assert "not-in-ledger" not in accounting.model_dump_json()
    assert "synthetic-key" not in accounting.model_dump_json()
    assert OPENROUTER_BASE_URL not in accounting.model_dump_json()


@pytest.mark.parametrize("status", [200, 429])
def test_usage_is_accounted_before_rejecting_malformed_or_error_selection(settings, status):
    def respond(request):
        payload = {
            "choices": [{"message": {"content": "invalid-json-private-text"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15, "cost": .004},
        }
        if status != 200:
            payload["error"] = {"code": status, "message": "private-provider-error"}
        return httpx.Response(status, json=payload)

    controller = EvaluationController(ExecutionLimits())
    with activate_execution(controller), pytest.raises(ModelUnavailable):
        Selector(settings, httpx.MockTransport(respond)).select("lost card", {}, *selection_input())
    accounting = controller.accounting()
    assert accounting.provider_requests == 1
    assert accounting.known_total_tokens == 15
    assert accounting.reported_cost_usd == .004
    assert "private" not in accounting.model_dump_json()


def test_typesafe_accounts_native_tokens_before_answer_validation(settings):
    settings.llm_base_url = TYPESAFE_BASE_URL
    settings.llm_protocol = "typesafe"
    settings.llm_api_key = "synthetic-typesafe-key"
    controller = EvaluationController(ExecutionLimits())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "model": "test", "answers": {}, "usage": {"input_tokens": 50, "output_tokens": 9, "cost": .5},
    }))
    with activate_execution(controller), pytest.raises(ModelUnavailable):
        Selector(settings, transport).select("lost card", {}, *selection_input())
    accounting = controller.accounting()
    assert accounting.provider_requests == 1
    assert (accounting.known_prompt_tokens, accounting.known_completion_tokens, accounting.known_total_tokens) == (50, 9, 59)
    assert accounting.unknown_total_token_requests == 0
    assert accounting.known_cost_usd == 0
    assert accounting.unknown_cost_requests == 1 and accounting.reported_cost_usd is None
    assert accounting.by_service_stage[0].service == "typesafe"


def test_reranker_attempts_and_unknown_cost_are_accounted(settings):
    settings.reranker_mode = "http"
    settings.reranker_base_url = "https://rerank.example/v1"
    controller = EvaluationController(ExecutionLimits())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "results": [{"index": 0, "relevance_score": .8}],
        "usage": {"total_tokens": 8, "cost": 5},
    }))
    with activate_execution(controller):
        assert Reranker(settings, transport).scores("question", ["document"]) == [.8]
    accounting = controller.accounting()
    assert accounting.provider_requests == 1 and accounting.known_total_tokens == 8
    assert accounting.unknown_prompt_token_requests == 1
    assert accounting.unknown_completion_token_requests == 1
    assert accounting.known_cost_usd == 0 and accounting.reported_cost_usd is None
    assert accounting.by_service_stage[0].service == "reranker"


@pytest.mark.parametrize("failure", ["timeout", "connection", "invalid_json"])
def test_failed_http_attempt_is_counted_once_with_unknown_usage(settings, failure):
    sent = []

    def respond(request):
        sent.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-timeout", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private-connection", request=request)
        return httpx.Response(200, content="not json")

    controller = EvaluationController(ExecutionLimits())
    with activate_execution(controller), pytest.raises(ModelUnavailable):
        Embeddings(settings, httpx.MockTransport(respond)).encode(["first"])
    accounting = controller.accounting()
    assert len(sent) == accounting.provider_requests == 1
    assert accounting.known_total_tokens == 0 and accounting.unknown_total_token_requests == 1
    assert accounting.known_cost_usd == 0 and accounting.unknown_cost_requests == 1
    assert accounting.reported_cost_usd is None


@pytest.mark.parametrize("cost", [None, -1, float("nan"), float("inf"), True, "0.01"])
def test_invalid_or_missing_cost_stops_before_another_request(settings, cost):
    sent = []

    def respond(request):
        sent.append(request)
        data = embedding_response(request).json()
        data["usage"] = {"total_tokens": 4, "cost": cost}
        # Raw JSON permits exercising NaN/Infinity, which compliant JSON writers reject.
        return httpx.Response(200, content=json.dumps(data), headers={"Content-Type": "application/json"})

    controller = EvaluationController(ExecutionLimits(max_reported_cost_usd=.1))
    embeddings = Embeddings(settings, httpx.MockTransport(respond))
    with activate_execution(controller):
        assert embeddings.encode(["completed"]).shape == (1, 2)
        with pytest.raises(EvaluationStopped) as stopped:
            embeddings.encode(["must not send"])
    assert stopped.value.stop_reason == "reported_cost_unknown"
    assert len(sent) == controller.accounting().provider_requests == 1
    assert controller.accounting().known_total_tokens == 4
    assert controller.accounting().unknown_cost_requests == 1


def test_known_cost_threshold_is_soft_and_shared_across_model_services(settings):
    snapshots = []
    controller = EvaluationController(ExecutionLimits(max_reported_cost_usd=.01), on_checkpoint=snapshots.append)
    with activate_execution(controller):
        # The completed response survives an overshoot; the next request is prevented.
        proposal, _ = Selector(settings, httpx.MockTransport(lambda request: completion_response())).select(
            "lost card", {}, *selection_input())
        assert proposal.intent_id == "card.lost"
        with pytest.raises(EvaluationStopped) as stopped:
            Embeddings(settings, httpx.MockTransport(embedding_response)).encode(["blocked"])
    assert stopped.value.stop_reason == "reported_cost_limit"
    assert snapshots[-1].reported_cost_usd == .02
    assert controller.accounting().provider_requests == 1


def test_reported_decimal_cost_sum_stops_at_exact_threshold_across_services_and_stages(settings):
    sent = []

    def respond(request):
        sent.append(request)
        response = embedding_response(request) if request.url.path.endswith("embeddings") else completion_response()
        payload = response.json()
        payload["usage"] = {"cost": .01}
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(respond)
    embeddings = Embeddings(settings, transport)
    selector = Selector(settings, transport)
    controller = EvaluationController(ExecutionLimits(max_reported_cost_usd=.1))
    with activate_execution(controller):
        for _ in range(5):
            with execution_stage("index"):
                embeddings.encode(["document"])
            with execution_stage("cases"):
                selector.select("lost card", {}, *selection_input())
        with pytest.raises(EvaluationStopped) as stopped:
            embeddings.encode(["must not make an eleventh request"])
    assert stopped.value.stop_reason == "reported_cost_limit"
    assert len(sent) == controller.accounting().provider_requests == 10
    assert controller.accounting().reported_cost_usd == .1
    assert [(row.service, row.stage, row.reported_cost_usd) for row in controller.accounting().by_service_stage] == [
        ("embedding", "index", .05), ("llm", "cases", .05),
    ]


def test_reported_cost_just_below_threshold_does_not_stop_early(settings):
    sent = []

    def respond(request):
        sent.append(request)
        payload = embedding_response(request).json()
        payload["usage"] = {"cost": .0099999999999999}
        return httpx.Response(200, json=payload)

    embeddings = Embeddings(settings, httpx.MockTransport(respond))
    controller = EvaluationController(ExecutionLimits(max_reported_cost_usd=.1))
    with activate_execution(controller):
        for _ in range(10):
            embeddings.encode(["document"])
        assert controller.accounting().reported_cost_usd < .1
        embeddings.encode(["eleventh request is still permitted"])
        with pytest.raises(EvaluationStopped) as stopped:
            embeddings.encode(["twelfth request is blocked"])
    assert stopped.value.stop_reason == "reported_cost_limit"
    assert len(sent) == controller.accounting().provider_requests == 11


def test_known_subtotal_is_not_presented_as_complete_when_a_later_cost_is_unknown(settings):
    controller = EvaluationController(ExecutionLimits())
    with activate_execution(controller):
        Selector(settings, httpx.MockTransport(lambda request: completion_response())).select(
            "lost card", {}, *selection_input())
        Embeddings(settings, httpx.MockTransport(embedding_response)).encode(["missing usage"])
    accounting = controller.accounting()
    assert accounting.provider_requests == 2
    assert accounting.known_cost_usd == .02 and accounting.unknown_cost_requests == 1
    assert accounting.reported_cost_usd is None


@pytest.mark.parametrize("base_url", [
    "http://openrouter.ai/api/v1", "https://openrouter.ai.example/api/v1",
    "https://openrouter.ai/api/v1/custom", "https://another.example/v1",
])
def test_only_exact_openrouter_inference_endpoints_report_usd(settings, base_url):
    settings.llm_base_url = base_url
    controller = EvaluationController(ExecutionLimits())
    with activate_execution(controller):
        Selector(settings, httpx.MockTransport(lambda request: completion_response())).select(
            "lost card", {}, *selection_input())
    assert controller.accounting().known_total_tokens == 50
    assert controller.accounting().known_cost_usd == 0
    assert controller.accounting().unknown_cost_requests == 1


@pytest.mark.parametrize("usage,expected", [
    ({"prompt_tokens": 4, "completion_tokens": 2}, (4, 2, 6, 0, 0, 0)),
    ({"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 7}, (4, 2, 7, 0, 0, 0)),
    ({"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "8"}, (0, 0, 0, 1, 1, 1)),
    ({"prompt_tokens": 4, "completion_tokens": 1.5, "total_tokens": 5}, (4, 0, 5, 0, 1, 0)),
    (None, (0, 0, 0, 1, 1, 1)),
])
def test_token_fields_are_independent_and_never_double_counted(settings, usage, expected):
    def respond(request):
        data = embedding_response(request).json()
        data["usage"] = usage
        return httpx.Response(200, json=data)

    controller = EvaluationController(ExecutionLimits())
    with activate_execution(controller):
        Embeddings(settings, httpx.MockTransport(respond)).encode(["example"])
    totals = controller.accounting()
    assert (totals.known_prompt_tokens, totals.known_completion_tokens, totals.known_total_tokens,
            totals.unknown_prompt_token_requests, totals.unknown_completion_token_requests,
            totals.unknown_total_token_requests) == expected


def test_zero_reported_cost_is_known_and_zero_request_limit_allows_local_lexical_work(settings):
    controller = EvaluationController(ExecutionLimits(max_provider_requests=0, max_reported_cost_usd=.01))
    _, catalog = selection_input()
    with activate_execution(controller):
        execution_checkpoint()
        candidates = Retriever(list(catalog.values()), "test", Embeddings(settings)).search("lost card")
        assert candidates[0].intent_id == "card.lost"
        execution_checkpoint()
    accounting = controller.accounting()
    assert accounting.provider_requests == 0 and accounting.reported_cost_usd == 0
    assert accounting.unknown_cost_requests == 0


def test_cancellation_and_duration_checkpoints_use_worker_time_not_request_count(settings, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    cancelled = [False]
    controller = EvaluationController(ExecutionLimits(max_duration_seconds=2), cancel_requested=lambda: cancelled[0])
    with activate_execution(controller):
        execution_checkpoint()
        now[0] = 102.0
        with pytest.raises(EvaluationStopped) as timed_out:
            execution_checkpoint()
        assert timed_out.value.stop_reason == "duration_limit"
    controller = EvaluationController(ExecutionLimits(), cancel_requested=lambda: cancelled[0])
    with activate_execution(controller):
        cancelled[0] = True
        with pytest.raises(EvaluationStopped) as stopped:
            execution_checkpoint()
    assert stopped.value.stop_reason == "user_cancelled"
    assert controller.accounting().provider_requests == 0


@pytest.mark.parametrize("operation", ["embedding", "reranker_load", "reranker_score", "lexical", "index"])
def test_local_operations_checkpoint_before_loading_or_computing(settings, operation):
    settings.embedding_mode = "local"
    settings.reranker_mode = "local"
    settings.embedding_local_files_only = settings.reranker_local_files_only = True
    _, catalog = selection_input()
    controller = EvaluationController(ExecutionLimits(), cancel_requested=lambda: True)
    with activate_execution(controller), pytest.raises(EvaluationStopped) as stopped:
        if operation == "embedding":
            Embeddings(settings).encode(["example"])
        elif operation == "reranker_load":
            Reranker(settings).prepare()
        elif operation == "reranker_score":
            Reranker(settings).scores("question", ["document"])
        else:
            retriever = Retriever(list(catalog.values()), "test", Embeddings(settings))
            if operation == "lexical":
                retriever.search("lost card")
            else:
                retriever.prepare_index()
    assert stopped.value.stop_reason == "user_cancelled"
    assert controller.accounting().provider_requests == 0


@pytest.mark.parametrize("service", ["llm", "typesafe", "reranker"])
def test_stop_exception_escapes_all_provider_handlers_before_network(settings, service):
    def unexpected(request):
        pytest.fail("An exhausted request budget must not send an HTTP request")

    controller = EvaluationController(ExecutionLimits(max_provider_requests=0))
    with activate_execution(controller), pytest.raises(EvaluationStopped) as stopped:
        if service == "reranker":
            settings.reranker_mode = "http"
            settings.reranker_base_url = "https://rerank.example/v1"
            Reranker(settings, httpx.MockTransport(unexpected)).scores("question", ["document"])
        else:
            if service == "typesafe":
                settings.llm_protocol = "typesafe"
                settings.llm_base_url = TYPESAFE_BASE_URL
                settings.llm_api_key = "synthetic-typesafe-key"
            Selector(settings, httpx.MockTransport(unexpected)).select("lost card", {}, *selection_input())
    assert stopped.value.stop_reason == "request_limit"
