"""Typed views at the evaluation checkpoint boundary.

Legacy result artifacts carry additional metadata. These structural views describe
what evaluation progress needs, without validating or rewriting older artifacts.
"""
from typing import Literal, TypedDict

from .contracts import DecisionType
from .execution import ExecutionAccounting
from .vector_index import IndexSource

EvaluationPhase = Literal["index", "calibration", "cases"]
EvaluationTerminalStatus = Literal["completed", "stopped", "failed"]


class EvaluationRecord(TypedDict):
    case_id: str
    decision: DecisionType
    intent_id: str | None
    correct: bool


class EvaluationLatency(TypedDict):
    p50: float | None
    p95: float | None
    p99: float | None


class EvaluationMetrics(TypedDict):
    total: int
    errors: int
    routing_accuracy: float | None
    decision_accuracy: float | None
    macro_f1: float | None
    recall_at_k: float | None
    latency_ms: EvaluationLatency


class EvaluationScaling(TypedDict):
    baseline_intent_count: int | None
    accuracy_delta_pp: float | None
    p95_ratio: float | None


class CalibrationSummary(TypedDict):
    mode: Literal["calibrated", "off"]
    calibrated: bool


class CalibrationRecord(TypedDict):
    case_id: str
    question: str
    score: float
    in_scope: bool
    nearest_intent_id: str


class CalibrationFit(CalibrationSummary):
    id: str
    created: float
    sample_count: int
    threshold: float
    records: list[CalibrationRecord]
    question_hashes: list[str]


class IndexPreparationData(TypedDict):
    source: IndexSource
    generation: str | None
    document_count: int
    dimensions: int
    elapsed_ms: float


class EvaluationResult(TypedDict):
    complete: bool
    completed_count: int
    selected_count: int
    records: list[EvaluationRecord]
    metrics: EvaluationMetrics
    scaling: EvaluationScaling
    model: str | None
    calibration: CalibrationSummary | None
    calibration_build_ms: float
    reranker_prepare_ms: float
    index_preparation: IndexPreparationData | None
    index_build_ms: float
    index_cache_hit: bool
    index_error: str | None
    preparation_error: str | None


class EvaluationCheckpoint(TypedDict, total=False):
    """Worker updates only; lifecycle state is owned by atomic Store transitions."""
    progress: int
    results: dict[str, EvaluationResult]
    accounting: ExecutionAccounting
    active_variant: str
    phase: EvaluationPhase
    calibrations: dict[str, CalibrationSummary | None]
    calibration_fits: list[CalibrationFit]
