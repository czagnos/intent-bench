"""Latency includes inference, but excludes evaluation control persistence."""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time

import httpx
import pytest

from app.config import Settings
from app.contracts import EvaluationRequest, Intent
from app.execution import EvaluationController, ExecutionLimits, activate_execution
from app.service import Studio


@dataclass
class BoundaryClock:
    seconds: float = 1000.0

    def now(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds

    def database_statement(self, statement: str) -> None:
        # Real SQLite still executes every statement. Only elapsed time is synthetic.
        normalized = statement.upper()
        if normalized.startswith("SELECT") and "FROM JOBS" in normalized:
            self.advance(.2)
        elif normalized.startswith("UPDATE JOBS"):
            self.advance(.3)

    def provider_response(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            self.advance(.04)
            return httpx.Response(200, json={
                "data": [{"index": index, "embedding": [1., 0.]}
                         for index in range(len(payload["input"]))],
            })
        if request.url.path.endswith("/rerank"):
            self.advance(.02)
            return httpx.Response(200, json={
                "results": [{"index": index, "relevance_score": 1. / (index + 1)}
                            for index in range(len(payload["documents"]))],
            })
        self.advance(.06)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "decision": "route", "intent_id": "card.limit.change",
            })}}],
        })


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> BoundaryClock:
    clock = BoundaryClock()
    connect = sqlite3.connect

    def connect_with_elapsed_time(database: str | Path, timeout: float = 5.0) -> sqlite3.Connection:
        connection = connect(database, timeout=timeout)
        connection.set_trace_callback(clock.database_statement)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect_with_elapsed_time)
    monkeypatch.setattr(time, "perf_counter", clock.now)
    monkeypatch.setattr(time, "monotonic", clock.now)
    monkeypatch.setattr(time, "time", clock.now)
    return clock


@pytest.fixture
def studio(tmp_path: Path, clock: BoundaryClock):
    settings = Settings(
        _env_file=None, data_dir=tmp_path, model_credentials_file=tmp_path / "absent.env",
        openrouter_api_key="", embedding_api_key="", llm_api_key="", reranker_api_key="",
        embedding_mode="http", embedding_base_url="https://synthetic.invalid/v1",
        embedding_model="timing-embedding", embedding_profile="plain", embedding_batch_size=256,
        llm_base_url="https://synthetic.invalid/v1", llm_model="timing-selector",
        reranker_mode="http", reranker_base_url="https://synthetic.invalid/v1",
        reranker_model="timing-reranker", reranker_protocol="cohere",
    )
    studio = Studio(settings)
    transport = httpx.MockTransport(clock.provider_response)
    studio.embeddings.transport = studio.selector.transport = studio.reranker.transport = transport
    studio.store.save_catalog("demo", [Intent(
        intent_id="card.limit.change", name="Change card limit", domain="banking",
        description="Change the credit card spending limit.",
        examples=["Increase my credit card limit"], workflow_id="card.limit.change",
    ).model_dump()])
    studio.store.save_cases("demo", [{
        "case_id": f"timing-{index}", "source": "customer", "dataset_version": "synthetic-timing",
        "reviewed": True, "split": "test", "question": "Increase my credit card limit",
        "expected_decision": "route", "expected_intent_id": "card.limit.change", "context": {},
    } for index in range(3)])
    try:
        yield studio
    finally:
        studio.close()


def test_exported_latency_and_repeat_statistics_exclude_control_database_time(studio: Studio):
    queued = studio.start_evaluation("demo", EvaluationRequest(
        methods=["hybrid_llm"], source="customer", repetitions=2,
        retrieval_profiles=[{"reranker_id": "default"}],
    ))
    studio.close()  # Drain the real worker without polling additional database reads.
    job = studio.store.job("demo", queued["id"])

    assert job["status"] == "completed" and job["progress"] == 6
    assert job["latency_protocol"] == "sequential-warm-index-v3"
    assert job["accounting"]["provider_requests"] == 19
    for index, result in enumerate(job["results"].values()):
        assert result["metrics"]["errors"] == 0
        assert result["index_build_ms"] == (40. if index == 0 else 0.)
        assert result["index_preparation"]["elapsed_ms"] == (40. if index == 0 else 0.)
        assert result["reranker_prepare_ms"] == 0.
        for record in result["records"]:
            assert record["timings_ms"]["retrieval"] == 40.
            assert record["timings_ms"]["reranking"] == 20.
            assert record["timings_ms"]["selection"] == 60.
            assert record["total_ms"] == record["timings_ms"]["compute_total"] == 120.
        assert result["metrics"]["latency_ms"]["p95"] == 120.
    assert job["group_summaries"][0]["metrics"]["latency_p95_ms"] == {
        "count": 2, "mean": 120., "sample_sd": 0., "min": 120., "max": 120.,
    }
    assert job["elapsed_ms"] > 720.  # Wall duration still includes database control work.


def test_duration_limit_includes_control_database_time(studio: Studio):
    queued = studio.start_evaluation("demo", EvaluationRequest(
        methods=["hybrid_llm"], source="customer", execution_limits={"max_duration_seconds": 1.},
    ))
    studio.close()
    job = studio.store.job("demo", queued["id"])

    assert job["status"] == "stopped" and job["stop_reason"] == "duration_limit"
    assert job["elapsed_ms"] >= 1000.
    assert job["progress"] == job["accounting"]["provider_requests"] == 0
    assert next(iter(job["results"].values()))["records"] == []


def test_failed_provider_response_keeps_provider_latency(studio: Studio, clock: BoundaryClock):
    def unavailable(request: httpx.Request) -> httpx.Response:
        clock.advance(.06)
        return httpx.Response(503, json={"error": "Synthetic unavailable provider"})

    studio.selector.transport = httpx.MockTransport(unavailable)
    queued = studio.start_evaluation("demo", EvaluationRequest(
        methods=["hybrid_llm"], source="customer", limit=1,
    ))
    studio.close()
    job = studio.store.job("demo", queued["id"])
    result = next(iter(job["results"].values()))
    record = result["records"][0]

    assert job["status"] == "completed" and result["metrics"]["errors"] == 1
    assert record["decision"] == "error" and record["error_stage"] == "selection"
    assert record["timings_ms"]["retrieval"] == 40.
    assert record["timings_ms"]["selection"] == 60.
    assert record["total_ms"] == 100.
    assert job["accounting"]["provider_requests"] == 3
    assert job["accounting"]["unknown_cost_requests"] == 3


def test_live_compute_without_controller_keeps_ordinary_elapsed_time(studio: Studio, clock: BoundaryClock):
    retriever = studio.retriever("demo")
    retriever.prepare_index()
    started = clock.now()
    output, _ = studio.compute("Increase my credit card limit", {}, "hybrid_llm", retriever)

    assert output["decision"] == "route"
    assert output["timings_ms"]["compute_total"] == 100.
    assert output["timings_ms"]["compute_total"] == pytest.approx((clock.now() - started) * 1000)
    assert output["timings_ms"]["retrieval"] == 40.
    assert output["timings_ms"]["selection"] == 60.


@pytest.mark.parametrize("broken_callback", ["cancellation_read", "accounting_write"])
def test_failing_control_database_callback_is_excluded_and_clock_recovers(
    studio: Studio, broken_callback: str,
):
    retriever = studio.retriever("demo")
    retriever.prepare_index()
    healthy = studio.store.create_job("demo", "evaluation", {})
    damaged = studio.store.create_job("demo", "evaluation", {})
    studio.store.claim_evaluation("demo", healthy["id"])
    studio.store.claim_evaluation("demo", damaged["id"])
    original = studio.store.job("demo", damaged["id"])
    with studio.store.connect() as db:
        # Corrupt persisted data at the SQLite boundary; use real Store/controller code.
        db.execute("UPDATE jobs SET payload=? WHERE job_id=?", ("{", damaged["id"]))
    read_id = damaged["id"] if broken_callback == "cancellation_read" else healthy["id"]
    controller = EvaluationController(
        ExecutionLimits(),
        cancel_requested=lambda: studio.store.job("demo", read_id).get("cancel_requested", False),
        on_checkpoint=lambda accounting: studio.store.checkpoint_evaluation(
            "demo", damaged["id"], {"accounting": accounting}),
    )
    with activate_execution(controller):
        output, _ = studio.compute("Increase my credit card limit", {}, "hybrid_llm", retriever)
        assert output["decision"] == "error" and output["error_stage"] == "retrieval"
        assert output["timings_ms"]["retrieval"] == output["timings_ms"]["compute_total"] == 0.
        with studio.store.connect() as db:
            db.execute("UPDATE jobs SET payload=? WHERE job_id=?", (json.dumps(original), damaged["id"]))
        recovered, _ = studio.compute("Increase my credit card limit", {}, "hybrid_llm", retriever)
        assert recovered["decision"] == "route"
        assert recovered["timings_ms"]["retrieval"] == 40.
        assert recovered["timings_ms"]["selection"] == 60.
        assert recovered["timings_ms"]["compute_total"] == 100.
