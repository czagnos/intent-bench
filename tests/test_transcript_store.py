"""Transcript persistence behavior through public Store methods and the real CSV parser."""
import csv
import io

import pytest

from app.importer import import_benchmark
from app.store import Store


def transcript_csv(*rows: dict[str, str]) -> bytes:
    stream = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def source_turn(**overrides: str) -> dict[str, str]:
    return {
        "SourceDatasetId": "synthetic-store-test",
        "BenchmarkSessionId": "conversation-one",
        "BenchmarkSessionMessageId": "turn-one",
        "Question": "Kart limitimi artırmak istiyorum",
        **overrides,
    }


def import_rows(store: Store, *rows: dict[str, str], workspace: str = "alpha"):
    cases, report = import_benchmark(transcript_csv(*rows), "synthetic.csv")
    return store.import_cases(workspace, cases, report)


def test_reimport_reports_actual_counts_and_preserves_reviewed_original_payload(tmp_path):
    store = Store(tmp_path)
    first = import_rows(store, source_turn(), source_turn())
    assert first.get("inserted") == 1
    assert first["imported"] == 1 and first["duplicates"] == 1
    assert first["already_present"] == 0
    initial = store.cases("alpha")[0]
    reviewed = store.review_case("alpha", initial["case_id"], {
        "expected_decision": "route", "expected_intent_id": "card.limit.change",
        "split": "dev", "review_notes": "Human label",
    })
    history = store.case_versions("alpha", initial["case_id"])
    second = import_rows(store, source_turn(), source_turn(BenchmarkSessionId="conversation-two"))
    assert second["inserted"] == 1 and second["already_present"] == 1
    assert second["imported"] == 2 and second["duplicates"] == 0
    assert store.cases("alpha")[0] == reviewed
    assert store.case_versions("alpha", initial["case_id"]) == history
    assert store.imports("alpha")[0] == second
    replay = import_rows(store, source_turn(), source_turn(BenchmarkSessionId="conversation-two"))
    assert replay["inserted"] == 0 and replay["already_present"] == 2
    assert len(store.cases("alpha")) == 2


@pytest.mark.parametrize("changed", [
    {"Question": "Changed immutable turn"},
    {"Answer": "Changed source answer"},
    {"Context": '{"messages":[]}'},
    {"TRUE/FALSE": "TRUE"},
    {"Message Flow": '{"steps":[{"step":"intent_detection","action":"changed"}]}'},
])
def test_conflicting_immutable_transcript_rejects_whole_import_and_report(tmp_path, changed):
    store = Store(tmp_path)
    import_rows(store, source_turn())
    before_cases, before_reports = store.cases("alpha"), store.imports("alpha")
    with pytest.raises(ValueError, match="Conflicting.*turn"):
        import_rows(store, source_turn(BenchmarkSessionId="new-conversation"), source_turn(**changed))
    assert store.cases("alpha") == before_cases
    assert store.imports("alpha") == before_reports
    assert store.case_versions("alpha", before_cases[0]["case_id"])["versions"] == []


@pytest.mark.parametrize("field", ["source_dataset_id", "source_session_id", "source_message_id", "conversation_id"])
def test_conflicting_stored_source_identity_is_never_silently_skipped(tmp_path, field):
    store = Store(tmp_path)
    cases, _ = import_benchmark(transcript_csv(source_turn()))
    cases[0][field] = "different-stored-identity"
    store.save_cases("alpha", cases)
    with pytest.raises(ValueError, match="Conflicting.*turn"):
        import_rows(store, source_turn())
    assert store.imports("alpha") == []


def test_new_conversation_implicit_peers_inherit_its_explicit_split(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn(), source_turn(BenchmarkSessionMessageId="two", Split="calibration"))
    assert {case["split"] for case in store.cases("alpha")} == {"calibration"}


def test_existing_conversation_new_implicit_turn_inherits_current_split(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn(Split="dev"))
    result = import_rows(store, source_turn(BenchmarkSessionMessageId="two"))
    assert result["inserted"] == 1
    assert {case["split"] for case in store.cases("alpha")} == {"dev"}


def test_explicit_conflicting_new_turn_rejects_whole_file_and_report(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn(Split="dev"))
    before_cases, before_reports = store.cases("alpha"), store.imports("alpha")
    with pytest.raises(ValueError, match="conversation.*split"):
        import_rows(store, source_turn(BenchmarkSessionId="independent"),
                    source_turn(BenchmarkSessionMessageId="two", Split="test"))
    assert store.cases("alpha") == before_cases
    assert store.imports("alpha") == before_reports


def test_identical_explicit_replay_preserves_human_split_change(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn(Split="test"))
    case = store.cases("alpha")[0]
    reviewed = store.review_case("alpha", case["case_id"], {"split": "dev", "expected_decision": "handoff"})
    result = import_rows(store, source_turn(Split="test"))
    assert result["inserted"] == 0 and result["already_present"] == 1
    assert store.cases("alpha") == [reviewed]


def test_import_checks_related_legacy_split_conflicts_only_within_workspace(tmp_path):
    store = Store(tmp_path)
    cases, _ = import_benchmark(transcript_csv(source_turn(), source_turn(BenchmarkSessionMessageId="two")))
    cases[0]["split"], cases[1]["split"] = "dev", "test"
    store.save_cases("alpha", cases)
    with pytest.raises(ValueError, match="conversation.*split"):
        import_rows(store, source_turn(BenchmarkSessionMessageId="three"))
    assert store.imports("alpha") == []
    unrelated = import_rows(store, source_turn(BenchmarkSessionId="safe"))
    assert unrelated["inserted"] == 1
    isolated = import_rows(store, source_turn(BenchmarkSessionMessageId="three"), workspace="beta")
    assert isolated["inserted"] == 1
    assert store.cases("beta")[0]["split"] == "test"


def test_whole_conversation_split_preserves_labels_review_and_history_and_is_idempotent(tmp_path):
    store = Store(tmp_path)
    rows = [source_turn(Split="test"), source_turn(BenchmarkSessionMessageId="two", Split="test")]
    import_rows(store, *rows)
    import_rows(store, *rows, workspace="beta")
    cases = store.cases("alpha")
    store.review_case("alpha", cases[0]["case_id"], {"split": "test", "expected_decision": "route",
                                                    "expected_intent_id": "card.limit.change"})
    before, isolated = store.cases("alpha"), store.cases("beta")
    conversation_id = cases[0]["conversation_id"]
    result = store.update_conversation_split("alpha", conversation_id, "dev")
    assert result == {"conversation_id": conversation_id, "split": "dev", "updated_count": 2}
    assert store.cases("alpha") == [{**case, "split": "dev"} for case in before]
    assert store.cases("beta") == isolated
    versions = [store.case_versions("alpha", case["case_id"]) for case in cases]
    for version in versions:
        assert {entry["case"]["split"] for entry in version["versions"]} == {"test", "dev"}
    assert store.update_conversation_split("alpha", conversation_id, "dev")["updated_count"] == 0
    assert [store.case_versions("alpha", case["case_id"]) for case in cases] == versions
    replay = import_rows(store, *rows)
    assert replay["inserted"] == 0 and replay["already_present"] == 2
    assert store.cases("alpha") == [{**case, "split": "dev"} for case in before]
    assert [store.case_versions("alpha", case["case_id"]) for case in cases] == versions


def test_whole_conversation_split_missing_and_invalid_targets_leave_state_unchanged(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn())
    case = store.cases("alpha")[0]
    for workspace, conversation_id in [("beta", case["conversation_id"]), ("alpha", "absent")]:
        with pytest.raises(KeyError):
            store.update_conversation_split(workspace, conversation_id, "dev")
    with pytest.raises(ValueError, match="split"):
        store.update_conversation_split("alpha", case["conversation_id"], "invalid")
    assert store.cases("alpha") == [case]
    assert store.case_versions("alpha", case["case_id"])["versions"] == []


def test_row_review_rejects_splitting_siblings_without_partial_labels_or_history(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn(), source_turn(BenchmarkSessionMessageId="two"))
    before = store.cases("alpha")
    with pytest.raises(ValueError, match="whole-conversation split"):
        store.review_case("alpha", before[0]["case_id"], {
            "split": "dev", "expected_decision": "route", "expected_intent_id": "card.limit.change",
        })
    assert store.cases("alpha") == before
    assert all(store.case_versions("alpha", case["case_id"])["versions"] == [] for case in before)
    reviewed = store.review_case("alpha", before[0]["case_id"], {"expected_decision": "handoff", "split": "test"})
    assert reviewed["reviewed"] is True and reviewed["expected_decision"] == "handoff"
    assert store.cases("alpha")[1] == before[1]


def test_single_case_review_split_ignores_same_conversation_in_another_workspace(tmp_path):
    store = Store(tmp_path)
    import_rows(store, source_turn())
    import_rows(store, source_turn(), source_turn(BenchmarkSessionMessageId="two"), workspace="beta")
    case = store.cases("alpha")[0]
    result = store.review_case("alpha", case["case_id"], {"split": "calibration", "expected_decision": "handoff"})
    assert result["reviewed"] is True and result["split"] == "calibration"
    assert {case["split"] for case in store.cases("beta")} == {"test"}


def test_selected_conversation_guard_checks_all_splits_and_legacy_rows_only_for_selected_cohort(tmp_path):
    store = Store(tmp_path)
    cases, _ = import_benchmark(transcript_csv(source_turn(), source_turn(BenchmarkSessionMessageId="two")))
    cases[0]["split"], cases[1]["split"] = "calibration", "test"
    for case in cases:
        case.pop("source_dataset_id")
        case.pop("source_session_id")
        case.pop("source_message_id")
    store.save_cases("alpha", cases)
    with pytest.raises(ValueError, match="conversation.*split"):
        store.validate_conversation_separation("alpha", [cases[0]["conversation_id"]])
    import_rows(store, source_turn(BenchmarkSessionId="independent"))
    safe = store.cases("alpha")[-1]
    assert store.validate_conversation_separation("alpha", [safe["conversation_id"], "absent", None, ""]) is None
    assert store.validate_conversation_separation("alpha", []) is None
    assert store.validate_conversation_separation("beta", [cases[0]["conversation_id"]]) is None
    before = store.cases("alpha")
    assert before[:2] == cases
    assert store.case_versions("alpha", cases[0]["case_id"])["versions"] == []


def test_selected_guard_ignores_cases_without_conversation_ids_and_whole_split_repairs_legacy_leakage(tmp_path):
    store = Store(tmp_path)
    cases, _ = import_benchmark(transcript_csv(source_turn(), source_turn(BenchmarkSessionMessageId="two")))
    cases[0]["split"], cases[1]["split"] = "dev", "test"
    conversation_id = "legacy/source/with/slashes"
    for case in cases:
        case["conversation_id"] = conversation_id
    store.save_cases("alpha", cases)
    result = store.update_conversation_split("alpha", conversation_id, "test")
    assert result["updated_count"] == 1
    assert store.validate_conversation_separation("alpha", [conversation_id]) is None
    assert store.case_versions("alpha", cases[1]["case_id"])["versions"] == []
    for case in cases:
        case.pop("conversation_id")
    store.save_cases("beta", cases)
    assert store.validate_conversation_separation("beta", [None, ""]) is None


def test_legacy_reimport_accepts_missing_new_metadata_and_preserves_original_payload(tmp_path):
    store = Store(tmp_path)
    row = source_turn(SourceDatasetId="")
    cases, _ = import_benchmark(transcript_csv(row))
    for key in ("source_dataset_id", "source_session_id", "source_message_id", "split_explicit"):
        cases[0].pop(key)
    store.save_cases("alpha", cases)
    reviewed = store.review_case("alpha", cases[0]["case_id"], {"split": "dev", "expected_decision": "handoff"})
    history = store.case_versions("alpha", cases[0]["case_id"])
    result = import_rows(store, row)
    assert result["inserted"] == 0 and result["already_present"] == 1
    assert store.cases("alpha") == [reviewed]
    assert store.case_versions("alpha", cases[0]["case_id"]) == history


def test_legacy_compatibility_never_ignores_present_conflicting_or_namespaced_identity(tmp_path):
    store = Store(tmp_path)
    legacy, _ = import_benchmark(transcript_csv(source_turn(SourceDatasetId="")))
    legacy[0]["source_message_id"] = "conflicting"
    store.save_cases("alpha", legacy)
    with pytest.raises(ValueError, match="Conflicting.*turn"):
        import_rows(store, source_turn(SourceDatasetId=""))
    namespaced, _ = import_benchmark(transcript_csv(source_turn()))
    for key in ("source_dataset_id", "source_session_id", "source_message_id"):
        namespaced[0].pop(key)
    store.save_cases("beta", namespaced)
    with pytest.raises(ValueError, match="Conflicting.*turn"):
        import_rows(store, source_turn(), workspace="beta")
