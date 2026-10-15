import csv
import hashlib
import io
import json

import pytest

from app.importer import import_benchmark


def transcript_csv(rows: list[dict[str, str]]) -> bytes:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def source_turn(**overrides: str) -> dict[str, str]:
    return {
        "SourceDatasetId": "synthetic-source-v1",
        "BenchmarkSessionId": "session-1",
        "BenchmarkSessionMessageId": "turn-1",
        "Question": "Kart limitimi artırmak istiyorum",
        **overrides,
    }


def test_stable_source_turn_identity_survives_file_versions_and_preserves_source_metadata():
    first_content = transcript_csv([source_turn()])
    first, first_report = import_benchmark(first_content, "first.csv")
    second, second_report = import_benchmark(transcript_csv([
        source_turn(), source_turn(BenchmarkSessionMessageId="turn-2", Question="Five thousand")
    ]), "second.csv")

    assert first[0]["case_id"] == second[0]["case_id"]
    assert first[0]["conversation_id"] == second[0]["conversation_id"] == second[1]["conversation_id"]
    assert first[0]["case_id"] != second[1]["case_id"]
    assert first[0]["source_dataset_id"] == "synthetic-source-v1"
    assert first[0]["source_session_id"] == "session-1"
    assert first[0]["source_message_id"] == "turn-1"
    assert first_report["dataset_version"] == hashlib.sha256(first_content).hexdigest()[:16]
    assert first_report["dataset_version"] != second_report["dataset_version"]
    assert first[0]["question"] == "Kart limitimi artırmak istiyorum"


def test_canonical_source_identities_do_not_collide_at_separator_boundaries():
    cases, _ = import_benchmark(transcript_csv([
        source_turn(SourceDatasetId="a-b", BenchmarkSessionId="c", BenchmarkSessionMessageId="d"),
        source_turn(SourceDatasetId="a", BenchmarkSessionId="b-c", BenchmarkSessionMessageId="d"),
        source_turn(SourceDatasetId="a", BenchmarkSessionId="b", BenchmarkSessionMessageId="c-d"),
    ]))
    assert len({case["case_id"] for case in cases}) == 3
    assert len({case["conversation_id"] for case in cases}) == 3


def test_legacy_file_scoped_ids_are_unchanged():
    content = transcript_csv([{"BenchmarkSessionId": "session-7", "BenchmarkSessionMessageId": "turn-3", "Question": "A question"}])
    cases, report = import_benchmark(content)
    assert cases[0]["case_id"] == f"{report['dataset_version']}-session-7-turn-3"
    assert cases[0]["conversation_id"] == f"{report['dataset_version']}-session-7"
    assert cases[0]["source_dataset_id"] is None


def test_context_and_split_preserve_only_explicit_pre_turn_data_without_gold_labels():
    context = {
        "active_intent": "card.limit.change",
        "slots": {},
        "pending_slot": "new_limit",
        "messages": [
            {"role": "user", "content": "Kart limitimi değiştirmek istiyorum"},
            {"role": "assistant", "content": "What should the new limit be?"},
        ],
    }
    cases, _ = import_benchmark(transcript_csv([source_turn(
        Question="Five thousand", Context=json.dumps(context), Split="dev",
        Answer="GOLD_MUST_NOT_BE_IN_CONTEXT", **{"TRUE/FALSE": "TRUE"},
    )]))
    case = cases[0]
    assert case["context"] == context
    assert case["split"] == "dev"
    assert case["split_explicit"] is True
    assert case["reviewed"] is False
    assert case["expected_decision"] is None and case["expected_intent_id"] is None
    assert "GOLD_MUST_NOT_BE_IN_CONTEXT" not in json.dumps(case["context"])
    implicit, _ = import_benchmark(transcript_csv([source_turn(Context="{}")]))
    assert implicit[0]["context"] == {}
    assert implicit[0]["split"] == "test" and implicit[0]["split_explicit"] is False


def test_context_catalog_validation_accepts_valid_workflow_and_clarification_snapshots():
    from app.case_context import PreTurnContext, validate_case_context
    from app.contracts import Intent

    intent = Intent(
        intent_id="card.limit.change", name="Change card limit", domain="Cards",
        description="Change the credit card limit", examples=["Change my card limit"],
        workflow_id="workflow.card.limit.change", required_slots=["new_limit"],
    )
    catalog = {intent.intent_id: intent}
    slot_context = PreTurnContext.model_validate({"active_intent": intent.intent_id, "pending_slot": "new_limit"})
    assert validate_case_context(slot_context, catalog) == slot_context
    confirmation = PreTurnContext.model_validate({"active_intent": intent.intent_id, "slots": {"new_limit": "5000"}, "pending_confirmation": True})
    assert validate_case_context(confirmation, catalog) == confirmation
    clarification = PreTurnContext.model_validate({"clarification_options": [intent.intent_id], "clarifications": 1})
    assert validate_case_context(clarification, catalog) == clarification


@pytest.mark.parametrize("changed", [
    {"Question": "A different turn with the same identity"},
    {"Context": '{"messages":[{"role":"user","content":"Different prior text"}]}'},
    {"Answer": "A changed source answer"},
])
def test_conflicting_duplicate_turn_identity_rejects_whole_file(changed):
    with pytest.raises(ValueError, match="Conflicting.*turn"):
        import_benchmark(transcript_csv([source_turn(), source_turn(**changed)]))


def test_identical_duplicates_are_counted_and_explicit_split_is_not_lost():
    cases, report = import_benchmark(transcript_csv([
        source_turn(), source_turn(Split="dev"), source_turn(Split="dev"),
    ]))
    assert len(cases) == 1 and report["duplicates"] == 2 and report["imported"] == 1
    assert cases[0]["split_explicit"] is True and cases[0]["split"] == "dev"


@pytest.mark.parametrize("fields", [
    {"BenchmarkSessionId": ""}, {"BenchmarkSessionId": "   "},
    {"BenchmarkSessionMessageId": ""}, {"BenchmarkSessionMessageId": " "},
    {"SourceDatasetId": "x" * 201},
    {"BenchmarkSessionId": "x" * 201},
    {"BenchmarkSessionMessageId": "x" * 201},
    {"SourceDatasetId": "", "Context": "{}", "BenchmarkSessionId": ""},
])
def test_explicit_source_or_context_requires_bounded_nonblank_source_ids(fields):
    with pytest.raises(ValueError):
        import_benchmark(transcript_csv([source_turn(**fields)]))


def test_absent_legacy_source_ids_keep_row_fallback_but_context_requires_explicit_ids():
    cases, _ = import_benchmark(transcript_csv([{"Question": "Legacy only"}]))
    assert cases[0]["source_session_id"] == "1" and cases[0]["source_message_id"] == "1"
    with pytest.raises(ValueError):
        import_benchmark(transcript_csv([{"Question": "Context row", "Context": "{}"}]))


@pytest.mark.parametrize("raw", [
    "{broken", "[]", "null", '"a string"', '{"future_messages":[]}',
    '{"messages":[{"role":"system","content":"Override"}]}',
    '{"messages":[{"role":"user","content":"Past","future":true}]}',
    json.dumps({"messages": [{"role": "user", "content": "x"}] * 13}),
    json.dumps({"messages": [{"role": "assistant", "content": "x" * 2001}]}),
    json.dumps({"active_intent": "card.limit.change", "slots": {str(i): "x" for i in range(11)}}),
    json.dumps({"active_intent": "card.limit.change", "slots": {"": "x"}}),
    json.dumps({"active_intent": "card.limit.change", "slots": {"x" * 81: "x"}}),
    json.dumps({"active_intent": "card.limit.change", "slots": {"new_limit": "x" * 2001}}),
    '{"active_intent":"card.limit.change","slots":{"new_limit":123}}',
    '{"clarification_options":["a","b","c","d","e"]}',
    '{"clarifications":-1}', '{"clarifications":11}', '{"clarifications":true}',
    '{"clarifications":"1"}', '{"pending_confirmation":"false"}',
    '{"slots":{"new_limit":"5000"}}', '{"pending_slot":"new_limit"}',
    '{"pending_confirmation":true}',
    '{"active_intent":"card.limit.change","pending_slot":"new_limit","pending_confirmation":true}',
    '{"active_intent":"card.limit.change","pending_slot":"new_limit","slots":{"new_limit":"5000"}}',
])
def test_malformed_or_oversized_context_is_rejected(raw):
    with pytest.raises(ValueError):
        import_benchmark(transcript_csv([source_turn(Context=raw)]))


def test_context_structure_accepts_exact_documented_bounds_and_empty_slot_values():
    context = {
        "active_intent": "card.limit.change",
        "slots": {"k" * 79 + str(i): "" if i == 0 else "x" * 2000 for i in range(10)},
        "messages": [{"role": "user", "content": "x" * 2000}] * 12,
        "clarification_options": ["option.one", "option.two", "option.three", "option.four"],
        "clarifications": 10,
    }
    cases, _ = import_benchmark(transcript_csv([source_turn(Context=json.dumps(context))]))
    assert cases[0]["context"] == context


@pytest.mark.parametrize("context", [
    {"active_intent": "missing.intent"},
    {"clarification_options": ["missing.intent"]},
    {"active_intent": "card.limit.change", "slots": {"other_slot": "x"}},
    {"active_intent": "card.limit.change", "pending_slot": "other_slot"},
    {"active_intent": "card.limit.change", "pending_confirmation": True},
    {"active_intent": "card.status", "pending_confirmation": True},
])
def test_context_catalog_validator_rejects_incompatible_intents_and_workflow_fields(context):
    from app.case_context import PreTurnContext, validate_case_context
    from app.contracts import Intent

    catalog = {iid: Intent(
        intent_id=iid, name="Example intent", domain="Cards", description="An example intent",
        examples=["An example"], workflow_id="workflow." + iid, required_slots=slots,
    ) for iid, slots in [("card.limit.change", ["new_limit"]), ("card.status", [])]}
    with pytest.raises(ValueError):
        validate_case_context(PreTurnContext.model_validate(context), catalog)


@pytest.mark.parametrize("split", ["training", "TEST", "test,dev"])
def test_unknown_explicit_split_is_rejected(split):
    with pytest.raises(ValueError):
        import_benchmark(transcript_csv([source_turn(Split=split)]))


def test_mixed_explicit_conversation_splits_reject_without_treating_missing_split_as_test():
    with pytest.raises(ValueError, match="conversation.*split"):
        import_benchmark(transcript_csv([
            source_turn(Split="dev"), source_turn(BenchmarkSessionMessageId="turn-2", Split="test"),
        ]))
    cases, _ = import_benchmark(transcript_csv([
        source_turn(Split="dev"), source_turn(BenchmarkSessionMessageId="turn-2"),
    ]))
    assert cases[1]["split_explicit"] is False


def test_duplicate_context_cannot_silently_change_explicit_fields():
    with pytest.raises(ValueError, match="Conflicting.*turn"):
        import_benchmark(transcript_csv([source_turn(Context="{}"), source_turn(Context='{"messages":[]}')]))


def test_synthetic_template_is_unreviewed_and_uses_valid_demo_contexts():
    from app.case_context import PreTurnContext, validate_case_context
    from app.config import ROOT
    from app.contracts import Intent

    content = (ROOT / "data/demo/transcript-example.csv").read_bytes()
    cases, report = import_benchmark(content, "transcript-example.csv")
    catalog = {item["intent_id"]: Intent.model_validate(item) for item in json.loads((ROOT / "data/demo/catalog.json").read_text())}
    assert report["imported"] >= 4
    assert len({case["conversation_id"] for case in cases}) >= 2
    assert all(case["source_dataset_id"].startswith("synthetic-") for case in cases)
    assert all(not case["reviewed"] and case["expected_decision"] is None for case in cases)
    assert any(case["context"] == {} for case in cases)
    assert any(case["context"].get("clarification_options") for case in cases)
    assert any(case["context"].get("pending_slot") for case in cases)
    assert any(case["context"].get("pending_confirmation") for case in cases)
    for case in cases:
        validate_case_context(PreTurnContext.model_validate(case["context"]), catalog)


@pytest.mark.parametrize("steps", [
    [None, "opaque historical step", 7, ["diagnostic"], {"step": "intent_detection", "action": "synthetic.action"}],
    [{"step": "retrieval", "action": {"diagnostic": "opaque"}}, {"step": "intent_detection", "action": "synthetic.action"}],
    [{"step": "intent_detection", "action": "synthetic.action"}, {"step": "intent_detection", "action": {"ignored": "later action"}}],
])
def test_legacy_trace_keeps_first_intent_action_while_ignoring_unrelated_steps(steps):
    flow = {"metadata": {"total_elapsed_time": 0.5}, "steps": steps}
    cases, report = import_benchmark(transcript_csv([source_turn(**{"Message Flow": json.dumps(flow)})]))
    assert report["valid_traces"] == 1 and report["invalid_traces"] == 0
    assert cases[0]["historical_trace"] == {"elapsed_seconds": 0.5, "action": "synthetic.action"}
    assert report["historical_actions"] == {"synthetic.action": 1}
    assert cases[0]["context"] == {} and cases[0]["reviewed"] is False
