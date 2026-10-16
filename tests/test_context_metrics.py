from typing import Literal, TypedDict

import pytest

from app.evaluation import summarize


Decision = Literal["route", "continue", "cancel"]


class MetricRecord(TypedDict):
    expected_decision: Decision
    expected_intent_id: str
    decision: Decision
    intent_id: str
    candidate_hit: bool
    total_ms: float
    correct: bool


def record(expected_decision: Decision, expected_intent_id: str,
           decision: Decision, intent_id: str) -> MetricRecord:
    return {
        "expected_decision": expected_decision,
        "expected_intent_id": expected_intent_id,
        "decision": decision,
        "intent_id": intent_id,
        "candidate_hit": True,
        "total_ms": 1.0,
        "correct": expected_decision == decision and expected_intent_id == intent_id,
    }


def test_correct_context_decisions_do_not_add_route_support_or_false_negatives():
    context = [
        record("continue", "alpha", "continue", "alpha"),
        record("cancel", "beta", "cancel", "beta"),
        record("continue", "context-only", "continue", "context-only"),
    ]
    metrics = summarize([
        record("route", "alpha", "route", "alpha"),
        record("route", "beta", "route", "alpha"),
        *context,
    ])

    assert metrics["per_intent"] == [
        {"intent_id": "alpha", "support": 1, "recall": 1.0, "f1": pytest.approx(2 / 3)},
        {"intent_id": "beta", "support": 1, "recall": 0.0, "f1": 0.0},
    ]
    assert metrics["macro_f1"] == pytest.approx(1 / 3)
    assert metrics["routing_total"] == 2
    assert metrics["routing_accuracy"] == 0.5
    assert metrics["recall_at_k"] == 1.0
    assert metrics["intent_count"] == 2
    assert metrics["decision_accuracy"] == 0.8

    context_only_metrics = summarize(context)
    assert context_only_metrics["routing_total"] == 0
    assert context_only_metrics["routing_accuracy"] is None
    assert context_only_metrics["macro_f1"] is None
    assert context_only_metrics["recall_at_k"] is None
    assert context_only_metrics["per_intent"] == []
    assert context_only_metrics["intent_count"] == 0
    assert context_only_metrics["decision_accuracy"] == 1.0


def test_routing_on_context_decisions_is_a_false_positive_even_for_matching_ids():
    context = [
        record("continue", "alpha", "route", "alpha"),
        record("cancel", "beta", "route", "beta"),
        record("continue", "context-only", "route", "alpha"),
    ]
    metrics = summarize([
        record("route", "alpha", "route", "alpha"),
        record("route", "beta", "route", "beta"),
        *context,
    ])

    assert metrics["per_intent"] == [
        {"intent_id": "alpha", "support": 1, "recall": 1.0, "f1": 0.5},
        {"intent_id": "beta", "support": 1, "recall": 1.0, "f1": pytest.approx(2 / 3)},
    ]
    assert metrics["macro_f1"] == pytest.approx(7 / 12)
    assert metrics["routing_total"] == 2
    assert metrics["routing_accuracy"] == 1.0
    assert metrics["intent_count"] == 2
    assert metrics["decision_accuracy"] == 0.4
    assert metrics["routed_precision"] == 0.4

    context_only_metrics = summarize(context)
    assert context_only_metrics["routing_total"] == 0
    assert context_only_metrics["macro_f1"] is None
    assert context_only_metrics["per_intent"] == []
    assert context_only_metrics["decision_accuracy"] == 0.0
