"""Consumer-facing insurance preset coverage and evaluation data contracts."""
import json
from collections import Counter

from app.calibration import question_hash
from app.config import ROOT
from app.contracts import Intent


PRESET = ROOT / "data/presets/insurance"


def read(name):
    return json.loads((PRESET / f"{name}.json").read_text())


def test_insurance_has_two_hundred_distinct_bounded_operations():
    intents = [Intent.model_validate(item) for item in read("catalog")]
    ids = {intent.intent_id for intent in intents}
    assert len(intents) == len(ids) == 200
    assert len({intent.workflow_id for intent in intents}) == 200
    assert len({intent.name.casefold() for intent in intents}) == 200
    assert len({intent.description.casefold() for intent in intents}) == 200
    assert "service.human" in ids
    for intent in intents:
        assert len(intent.examples) == 2
        assert intent.exclusions and intent.selection_rule
        assert intent.confusable_with
        assert set(intent.confusable_with) <= ids - {intent.intent_id}
        assert all(text.strip() for text in intent.examples + intent.exclusions)


def test_insurance_test_cohort_covers_every_routing_operation():
    intents = read("catalog")
    cases = read("cases")
    assert len(cases) == 205
    assert Counter(case["expected_decision"] for case in cases) == {
        "route": 199, "handoff": 1, "clarify": 1, "out_of_scope": 4,
    }
    covered = {case["expected_intent_id"] for case in cases if case["expected_decision"] == "route"}
    assert covered | {"service.human"} == {intent["intent_id"] for intent in intents}
    assert all(case["split"] == "test" for case in cases)
    assert len({case["case_id"] for case in cases}) == len(cases)
    added = [case for case in cases if "-v2-" in case["case_id"]]
    assert len(added) == 181
    assert all(case["label_origin"] == "curated_synthetic_expansion" for case in added)


def test_insurance_calibration_is_balanced_and_all_text_splits_are_independent():
    catalog = read("catalog")
    cases = read("cases")
    calibration = read("calibration-cases")
    assert len(calibration) == 80
    assert Counter(case["expected_decision"] for case in calibration) == {"route": 40, "out_of_scope": 40}
    ids = {intent["intent_id"] for intent in catalog}
    assert all(case["expected_intent_id"] in ids for case in calibration if case["expected_decision"] == "route")
    assert all(case["split"] == "calibration" for case in calibration)
    texts = [example for intent in catalog for example in intent["examples"]]
    texts += [case["question"] for case in cases + calibration]
    assert len({question_hash(text) for text in texts}) == len(texts)
    assert len({case["case_id"] for case in cases + calibration}) == len(cases + calibration)
    assert not any(character in json.dumps(catalog + cases + calibration, ensure_ascii=False) for character in "ğşİıçüöĞŞÇÜÖ")


def test_original_insurance_case_identifiers_and_labels_remain_available():
    cases = read("cases")
    calibration = read("calibration-cases")
    assert {f"insurance-test-v1-{index:03}" for index in range(1, 25)} <= {case["case_id"] for case in cases}
    assert {f"insurance-calibration-v1-{index:03}" for index in range(1, 25)} <= {case["case_id"] for case in calibration}
    by_id = {case["case_id"]: case for case in cases + calibration}
    assert by_id["insurance-test-v1-020"]["question"] == "Transfer me to a human insurance service adviser."
    assert by_id["insurance-test-v1-020"]["expected_intent_id"] is None
    assert by_id["insurance-calibration-v1-024"]["question"] == "How do I grow basil on my balcony?"
