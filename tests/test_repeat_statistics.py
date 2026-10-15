import json
import math

import pytest

from app.repeat_statistics import RepeatMetrics, RepeatRecord, RepeatResult, summarize_repeats


def run_result(
    repeat_index: int,
    metrics: RepeatMetrics,
    records: list[RepeatRecord],
    *,
    group_id: str = "lexical",
) -> RepeatResult:
    return {
        "group_id": group_id,
        "repeat_index": repeat_index,
        "complete": True,
        "completed_count": len(records),
        "selected_count": len(records),
        "metrics": metrics,
        "records": records,
    }


def metrics(
    accuracy: float | None, *, errors: int = 0, total: int = 2, p95: float | None = 10.0
) -> RepeatMetrics:
    return {
        "routing_accuracy": accuracy,
        "decision_accuracy": accuracy,
        "macro_f1": accuracy,
        "recall_at_k": accuracy,
        "latency_ms": {"p95": p95},
        "errors": errors,
        "total": total,
    }


def test_summarizes_run_metrics_including_completed_runs_with_technical_errors():
    first = run_result(1, metrics(1.0, p95=10), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
        {"case_id": "b", "decision": "route", "intent_id": "two"},
    ])
    second = run_result(2, metrics(0.5, errors=1, p95=30), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
        {"case_id": "b", "decision": "error", "intent_id": None},
    ])

    summaries = summarize_repeats([first, second], group_ids=["lexical"], planned_repetitions=2)

    assert len(summaries) == 1
    summary = summaries[0]
    assert {key: summary[key] for key in (
        "group_id", "planned_count", "complete_count", "partial_count", "missing_count"
    )} == {
        "group_id": "lexical", "planned_count": 2, "complete_count": 2,
        "partial_count": 0, "missing_count": 0,
    }
    expected_accuracy = {"count": 2, "mean": 0.75, "sample_sd": math.sqrt(0.125), "min": 0.5, "max": 1.0}
    for key in ("routing_accuracy", "decision_accuracy", "macro_f1", "recall_at_k"):
        assert summary["metrics"][key] == pytest.approx(expected_accuracy)
    assert summary["metrics"]["technical_error_rate"] == pytest.approx({
        "count": 2, "mean": 0.25, "sample_sd": math.sqrt(0.125), "min": 0.0, "max": 0.5,
    })
    assert summary["metrics"]["latency_p95_ms"] == pytest.approx({
        "count": 2, "mean": 20.0, "sample_sd": math.sqrt(200), "min": 10.0, "max": 30.0,
    })
    assert summary["latency_label"] == "Mean of per-run p95 latency (ms)"
    assert "ci95" not in json.dumps(summaries)
    json.dumps(summaries, allow_nan=False)

    first["metrics"]["routing_accuracy"] = None
    second["metrics"]["routing_accuracy"] = None
    second["metrics"]["macro_f1"] = None
    nullable = summarize_repeats([first, second], group_ids=["lexical"], planned_repetitions=2)[0]
    assert nullable["metrics"]["routing_accuracy"] == {
        "count": 0, "mean": None, "sample_sd": None, "min": None, "max": None,
    }
    assert nullable["metrics"]["macro_f1"] == {
        "count": 1, "mean": 1.0, "sample_sd": None, "min": 1.0, "max": 1.0,
    }


@pytest.mark.parametrize("complete_flag", [False, True])
def test_excludes_partial_runs_and_reports_missing_repeats_and_entire_groups(complete_flag: bool):
    complete = run_result(1, metrics(0.5), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
        {"case_id": "b", "decision": "route", "intent_id": "two"},
    ])
    partial = run_result(2, metrics(1.0, total=1, p95=999), [
        {"case_id": "a", "decision": "route", "intent_id": "changed"},
    ])
    partial["complete"] = complete_flag
    partial["selected_count"] = 2
    empty_partial = run_result(3, metrics(None, total=0, p95=None), [])
    empty_partial["complete"] = False
    empty_partial["selected_count"] = 2

    summaries = summarize_repeats(
        [empty_partial, complete, partial], group_ids=["lexical", "unstarted"], planned_repetitions=4,
    )

    assert [(summary["group_id"], summary["complete_count"], summary["partial_count"], summary["missing_count"])
            for summary in summaries] == [("lexical", 1, 2, 1), ("unstarted", 0, 0, 4)]
    first, missing = summaries
    assert first["metrics"]["decision_accuracy"] == {
        "count": 1, "mean": 0.5, "sample_sd": None, "min": 0.5, "max": 0.5,
    }
    assert first["metrics"]["latency_p95_ms"]["mean"] == 10
    for metric in missing["metrics"].values():
        assert metric == {"count": 0, "mean": None, "sample_sd": None, "min": None, "max": None}
    for summary, compared in ((first, 1), (missing, 0)):
        assert summary["disagreement"] == {
            "compared_repeat_count": compared, "eligible_case_count": 0,
            "excluded_technical_error_case_count": 0, "disagreeing_case_count": 0,
            "disagreement_rate": None, "cases": [],
        }


def test_reports_case_disagreement_by_relevant_intent_and_excludes_any_technical_error():
    first_records: list[RepeatRecord] = [
        {"case_id": "route", "decision": "route", "intent_id": "one"},
        {"case_id": "continue", "decision": "continue", "intent_id": "one"},
        {"case_id": "cancel", "decision": "cancel", "intent_id": "one"},
        {"case_id": "clarify", "decision": "clarify", "intent_id": "one"},
        {"case_id": "oos", "decision": "out_of_scope", "intent_id": "one"},
        {"case_id": "handoff", "decision": "handoff", "intent_id": "one"},
        {"case_id": "decision", "decision": "route", "intent_id": "one"},
        {"case_id": "excluded", "decision": "route", "intent_id": "one"},
        {"case_id": "stable", "decision": "route", "intent_id": "one"},
    ]
    second_records: list[RepeatRecord] = [dict(record) for record in first_records]
    for record in second_records[:6]:
        record["intent_id"] = "two"
    second_records[6]["decision"] = "continue"
    second_records[7]["intent_id"] = "different"
    third_records: list[RepeatRecord] = [dict(record) for record in reversed(first_records)]
    third_records[1] = {"case_id": "excluded", "decision": "error", "intent_id": None}
    runs = [
        run_result(1, metrics(1.0, total=9), first_records),
        run_result(2, metrics(0.5, total=9), second_records),
        run_result(3, metrics(0.5, errors=1, total=9), third_records),
    ]
    partial = run_result(4, metrics(None, total=0), [])
    partial["complete"] = False
    partial["selected_count"] = 9

    summary = summarize_repeats([*runs, partial], group_ids=["lexical"], planned_repetitions=4)[0]

    disagreement = summary["disagreement"]
    assert disagreement["eligible_case_count"] == 8
    assert disagreement["excluded_technical_error_case_count"] == 1
    assert disagreement["compared_repeat_count"] == 3
    assert disagreement["disagreeing_case_count"] == 4
    assert disagreement["disagreement_rate"] == 0.5
    assert disagreement["cases"] == [
        {"case_id": "cancel", "distinct_outcome_count": 2, "disagrees": True},
        {"case_id": "clarify", "distinct_outcome_count": 1, "disagrees": False},
        {"case_id": "continue", "distinct_outcome_count": 2, "disagrees": True},
        {"case_id": "decision", "distinct_outcome_count": 2, "disagrees": True},
        {"case_id": "handoff", "distinct_outcome_count": 1, "disagrees": False},
        {"case_id": "oos", "distinct_outcome_count": 1, "disagrees": False},
        {"case_id": "route", "distinct_outcome_count": 2, "disagrees": True},
        {"case_id": "stable", "distinct_outcome_count": 1, "disagrees": False},
    ]
    single = summarize_repeats([runs[2]], group_ids=["lexical"], planned_repetitions=3)[0]
    assert single["disagreement"] == {
        "compared_repeat_count": 1, "eligible_case_count": 0,
        "excluded_technical_error_case_count": 0, "disagreeing_case_count": 0,
        "disagreement_rate": None, "cases": [],
    }

    stable = summarize_repeats([runs[0], run_result(2, metrics(1.0, total=9), first_records)],
                               group_ids=["lexical"], planned_repetitions=2)[0]
    assert stable["disagreement"]["disagreement_rate"] == 0.0

    all_errors = [run_result(index, metrics(0.0, total=1, errors=1), [
        {"case_id": "a", "decision": "error", "intent_id": None},
    ]) for index in (1, 2)]
    excluded = summarize_repeats(all_errors, group_ids=["lexical"], planned_repetitions=2)[0]
    assert excluded["disagreement"]["eligible_case_count"] == 0
    assert excluded["disagreement"]["excluded_technical_error_case_count"] == 1
    assert excluded["disagreement"]["disagreement_rate"] is None


@pytest.mark.parametrize("planned_repetitions", [0, 6, True, 1.0])
def test_rejects_invalid_planned_repeat_count(planned_repetitions: int):
    with pytest.raises(ValueError, match="planned_repetitions"):
        summarize_repeats([], group_ids=["lexical"], planned_repetitions=planned_repetitions)


@pytest.mark.parametrize(("group_ids", "repeat_indexes", "message"), [
    (["lexical", "lexical"], [1], "group_ids"),
    (["lexical", ""], [1], "group_ids"),
    (["different"], [1], "group_id"),
    (["lexical"], [1, 1], "repeat_index"),
    (["lexical"], [0], "repeat_index"),
    (["lexical"], [3], "repeat_index"),
    (["lexical"], [True], "repeat_index"),
    (["lexical"], [1.0], "repeat_index"),
])
def test_rejects_invalid_group_or_repeat_identity(
    group_ids: list[str], repeat_indexes: list[int], message: str,
):
    runs = [run_result(index, metrics(1.0, total=1), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
    ]) for index in repeat_indexes]

    with pytest.raises(ValueError, match=message):
        summarize_repeats(runs, group_ids=group_ids, planned_repetitions=2)


@pytest.mark.parametrize("case_ids", [["a", "a"], ["a", " "]])
@pytest.mark.parametrize("complete", [False, True])
def test_rejects_duplicate_or_blank_case_identity(case_ids: list[str], complete: bool):
    run = run_result(1, metrics(1.0), [
        {"case_id": case_id, "decision": "route", "intent_id": "one"} for case_id in case_ids
    ])
    run["complete"] = complete

    with pytest.raises(ValueError, match="case_id"):
        summarize_repeats([run], group_ids=["lexical"], planned_repetitions=1)


@pytest.mark.parametrize(("completed_count", "selected_count", "total"), [
    (0, 2, 2), (2, 1, 2), (2, -1, 2), (True, 2, 2), (2, 2.0, 2), (2, 2, 0), (2, 2, True),
])
def test_rejects_inconsistent_result_counts(completed_count: int, selected_count: int, total: int):
    run = run_result(1, metrics(1.0, total=total), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
        {"case_id": "b", "decision": "route", "intent_id": "two"},
    ])
    run["completed_count"] = completed_count
    run["selected_count"] = selected_count

    with pytest.raises(ValueError, match="counts"):
        summarize_repeats([run], group_ids=["lexical"], planned_repetitions=1)


def test_rejects_changed_cohorts_instead_of_combining_new_observations():
    first = run_result(1, metrics(1.0, total=1), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
    ])
    second = run_result(2, metrics(1.0, total=1), [
        {"case_id": "b", "decision": "route", "intent_id": "one"},
    ])

    with pytest.raises(ValueError, match="cohort"):
        summarize_repeats([first, second], group_ids=["lexical"], planned_repetitions=2)


@pytest.mark.parametrize("errors", [-1, 3, True, 1])
def test_rejects_error_counts_that_do_not_match_records(errors: int):
    run = run_result(1, metrics(1.0, errors=errors), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
        {"case_id": "b", "decision": "route", "intent_id": "two"},
    ])

    with pytest.raises(ValueError, match="errors"):
        summarize_repeats([run], group_ids=["lexical"], planned_repetitions=1)


@pytest.mark.parametrize("accuracy", [math.nan, math.inf, -math.inf, True, -0.1, 1.1])
def test_rejects_invalid_metric_values_instead_of_exporting_non_json_statistics(accuracy: float):
    run = run_result(1, metrics(accuracy, total=1), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
    ])

    with pytest.raises(ValueError, match="metrics"):
        summarize_repeats([run], group_ids=["lexical"], planned_repetitions=1)


@pytest.mark.parametrize("p95", [math.nan, math.inf, -1, True])
def test_rejects_invalid_latency_values(p95: float):
    run = run_result(1, metrics(1.0, total=1, p95=p95), [
        {"case_id": "a", "decision": "route", "intent_id": "one"},
    ])

    with pytest.raises(ValueError, match="latency"):
        summarize_repeats([run], group_ids=["lexical"], planned_repetitions=1)
