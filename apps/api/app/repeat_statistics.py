"""Run-level summaries for repetitions over one frozen evaluation cohort."""

from collections.abc import Sequence
from math import isfinite
from statistics import mean, stdev
from typing import Literal, TypedDict


Decision = Literal["route", "continue", "cancel", "clarify", "out_of_scope", "handoff", "error"]


class RepeatRecord(TypedDict):
    case_id: str
    decision: Decision
    intent_id: str | None


class RepeatLatency(TypedDict):
    p95: float | None


class RepeatMetrics(TypedDict):
    routing_accuracy: float | None
    decision_accuracy: float | None
    macro_f1: float | None
    recall_at_k: float | None
    latency_ms: RepeatLatency
    errors: int
    total: int


class RepeatResult(TypedDict):
    """Normalized run boundary; repeat_index is one-based within group_id."""

    group_id: str
    repeat_index: int
    complete: bool
    completed_count: int
    selected_count: int
    metrics: RepeatMetrics
    records: list[RepeatRecord]


class MetricSummary(TypedDict):
    count: int
    mean: float | None
    sample_sd: float | None
    min: float | None
    max: float | None


class GroupMetrics(TypedDict):
    routing_accuracy: MetricSummary
    decision_accuracy: MetricSummary
    macro_f1: MetricSummary
    recall_at_k: MetricSummary
    latency_p95_ms: MetricSummary
    technical_error_rate: MetricSummary


class CaseDisagreement(TypedDict):
    case_id: str
    distinct_outcome_count: int
    disagrees: bool


class DisagreementSummary(TypedDict):
    compared_repeat_count: int
    eligible_case_count: int
    excluded_technical_error_case_count: int
    disagreeing_case_count: int
    disagreement_rate: float | None
    cases: list[CaseDisagreement]


class RepeatGroupSummary(TypedDict):
    group_id: str
    planned_count: int
    complete_count: int
    partial_count: int
    missing_count: int
    metrics: GroupMetrics
    latency_label: str
    disagreement: DisagreementSummary


def summarize_repeats(
    results: Sequence[RepeatResult], *, group_ids: Sequence[str], planned_repetitions: int
) -> list[RepeatGroupSummary]:
    """Summarize completed repeats without pooling their case observations.

    Supply every planned group, including groups with no results. A present result
    is partial unless it is marked complete and contains its full selected cohort.
    Complete repeats within a group must have identical case IDs, in any order.
    Technical errors remain in run metrics but exclude the affected case from
    disagreement across all compared repeats. These statistics describe observed
    variability of the same cases, not independent held-out observations.
    """
    _validate_results(results, group_ids, planned_repetitions)
    summaries: list[RepeatGroupSummary] = []
    for group_id in group_ids:
        present = [result for result in results if result["group_id"] == group_id]
        group = [result for result in present
                 if result["complete"] and result["completed_count"] == result["selected_count"]]
        summaries.append({
            "group_id": group_id,
            "planned_count": planned_repetitions,
            "complete_count": len(group),
            "partial_count": len(present) - len(group),
            "missing_count": planned_repetitions - len(present),
            "metrics": {
                "routing_accuracy": _metric_summary([run["metrics"]["routing_accuracy"] for run in group]),
                "decision_accuracy": _metric_summary([run["metrics"]["decision_accuracy"] for run in group]),
                "macro_f1": _metric_summary([run["metrics"]["macro_f1"] for run in group]),
                "recall_at_k": _metric_summary([run["metrics"]["recall_at_k"] for run in group]),
                "latency_p95_ms": _metric_summary([run["metrics"]["latency_ms"]["p95"] for run in group]),
                "technical_error_rate": _metric_summary([
                    run["metrics"]["errors"] / run["metrics"]["total"] if run["metrics"]["total"] else None
                    for run in group
                ]),
            },
            "latency_label": "Mean of per-run p95 latency (ms)",
            "disagreement": _disagreement(group),
        })
    return summaries


def _validate_results(
    results: Sequence[RepeatResult], group_ids: Sequence[str], planned_repetitions: int,
) -> None:
    if type(planned_repetitions) is not int or not 1 <= planned_repetitions <= 5:
        raise ValueError("planned_repetitions must be an integer from 1 to 5")
    groups = set(group_ids)
    if len(groups) != len(group_ids) or any(not group_id.strip() for group_id in group_ids):
        raise ValueError("group_ids must be unique nonblank identifiers")
    seen: set[tuple[str, int]] = set()
    cohorts: dict[str, set[str]] = {}
    for result in results:
        if result["group_id"] not in groups:
            raise ValueError("Every result group_id must appear in group_ids")
        index = result["repeat_index"]
        identity = (result["group_id"], index)
        if type(index) is not int or not 1 <= index <= planned_repetitions or identity in seen:
            raise ValueError("repeat_index must be unique within its group and within the planned range")
        seen.add(identity)
        counts = (result["completed_count"], result["selected_count"], result["metrics"]["total"])
        if (any(type(count) is not int or count < 0 for count in counts)
                or result["completed_count"] != len(result["records"])
                or result["metrics"]["total"] != result["completed_count"]
                or result["completed_count"] > result["selected_count"]):
            raise ValueError("Result counts must match the records and selected cohort")
        case_ids = {record["case_id"] for record in result["records"]}
        if len(case_ids) != len(result["records"]) or any(not case_id.strip() for case_id in case_ids):
            raise ValueError("case_id must be unique and nonblank within a repeat")
        _validate_metrics(result)
        if result["complete"] and result["completed_count"] == result["selected_count"]:
            cohort = cohorts.setdefault(result["group_id"], case_ids)
            if cohort != case_ids:
                raise ValueError("Complete repeats must contain the same case_id cohort")


def _validate_metrics(result: RepeatResult) -> None:
    metrics = result["metrics"]
    errors = metrics["errors"]
    if type(errors) is not int or errors != sum(record["decision"] == "error" for record in result["records"]):
        raise ValueError("Metric errors must match technical-error records")
    fractions = (metrics["routing_accuracy"], metrics["decision_accuracy"], metrics["macro_f1"], metrics["recall_at_k"])
    if any(value is not None and (isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 1)
           for value in fractions):
        raise ValueError("Accuracy and recall metrics must be finite fractions or null")
    p95 = metrics["latency_ms"]["p95"]
    if p95 is not None and (isinstance(p95, bool) or not isfinite(p95) or p95 < 0):
        raise ValueError("p95 latency must be finite and nonnegative or null")


def _metric_summary(values: Sequence[float | None]) -> MetricSummary:
    defined = [value for value in values if value is not None]
    return {
        "count": len(defined),
        "mean": mean(defined) if defined else None,
        "sample_sd": stdev(defined) if len(defined) >= 2 else None,
        "min": min(defined) if defined else None,
        "max": max(defined) if defined else None,
    }


def _disagreement(runs: Sequence[RepeatResult]) -> DisagreementSummary:
    summary: DisagreementSummary = {
        "compared_repeat_count": len(runs),
        "eligible_case_count": 0,
        "excluded_technical_error_case_count": 0,
        "disagreeing_case_count": 0,
        "disagreement_rate": None,
        "cases": [],
    }
    if len(runs) < 2:
        return summary

    cases: dict[str, list[RepeatRecord]] = {}
    for run in runs:
        for record in run["records"]:
            cases.setdefault(record["case_id"], []).append(record)

    for case_id, records in sorted(cases.items()):
        if any(record["decision"] == "error" for record in records):
            summary["excluded_technical_error_case_count"] += 1
            continue
        outcomes = {
            (record["decision"], record["intent_id"]
             if record["decision"] in ("route", "continue", "cancel") else None)
            for record in records
        }
        disagrees = len(outcomes) > 1
        summary["cases"].append({
            "case_id": case_id, "distinct_outcome_count": len(outcomes), "disagrees": disagrees,
        })
        summary["eligible_case_count"] += 1
        summary["disagreeing_case_count"] += disagrees

    if summary["eligible_case_count"]:
        summary["disagreement_rate"] = summary["disagreeing_case_count"] / summary["eligible_case_count"]
    return summary
