"""Observable coverage and separation guarantees of the airline preset."""
import json
from collections import Counter

from app.calibration import question_hash
from app.config import ROOT
from app.contracts import Intent


def read_preset(filename):
    return json.loads((ROOT / "data/presets/airline" / filename).read_text())


def test_airline_preset_has_200_workflows_and_complete_test_labels():
    catalog = read_preset("catalog.json")
    cases = read_preset("cases.json")
    ids = {intent["intent_id"] for intent in catalog}
    assert len(catalog) == len(ids) == 200
    assert len({intent["workflow_id"] for intent in catalog}) == 200
    assert len(cases) == 205
    assert Counter(case["expected_decision"] for case in cases) == {
        "route": 199, "handoff": 1, "clarify": 1, "out_of_scope": 4,
    }
    routed = {case["expected_intent_id"] for case in cases if case["expected_decision"] == "route"}
    assert routed | {"service.human"} == ids
    assert next(case for case in cases if case["expected_decision"] == "handoff")["expected_intent_id"] is None
    assert all(case["split"] == "test" and case["source"] == "seed" for case in cases)


def test_airline_operations_have_valid_boundaries_and_distinct_examples():
    catalog = [Intent.model_validate(item) for item in read_preset("catalog.json")]
    ids = {intent.intent_id for intent in catalog}
    assert len({intent.name for intent in catalog}) == len(catalog)
    assert len({intent.description for intent in catalog}) == len(catalog)
    for intent in catalog:
        assert len({question_hash(example) for example in intent.examples}) >= 2
        assert intent.exclusions and intent.selection_rule and intent.confusable_with
        assert set(intent.confusable_with) <= ids - {intent.intent_id}
        assert intent.workflow_id and intent.channels == ["chat", "voice"]


def test_airline_calibration_is_balanced_and_separate_from_test_and_examples():
    catalog = read_preset("catalog.json")
    cases = read_preset("cases.json")
    calibration = read_preset("calibration-cases.json")
    assert len(calibration) == 80
    assert Counter(case["expected_decision"] for case in calibration) == {
        "route": 40, "out_of_scope": 40,
    }
    all_cases = cases + calibration
    assert len({case["case_id"] for case in all_cases}) == len(all_cases)
    case_hashes = {question_hash(case["question"]) for case in all_cases}
    assert len(case_hashes) == len(all_cases)
    examples = {question_hash(example) for intent in catalog for example in intent["examples"]}
    assert not examples & case_hashes
    ids = {intent["intent_id"] for intent in catalog}
    for case in calibration:
        assert case["split"] == "calibration"
        if case["expected_decision"] == "route":
            assert case["expected_intent_id"] in ids
        else:
            assert case["expected_intent_id"] is None
        assert case["label_origin"].startswith("curated_synthetic")
