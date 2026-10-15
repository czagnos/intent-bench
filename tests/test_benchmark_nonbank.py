"""Public corpus guarantees for the supplemental synthetic sector benchmarks."""
import json
from collections import Counter
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.calibration import question_hash
from app.config import ROOT
from app.contracts import Intent

SECTORS = ("airline", "insurance", "ecommerce")
HARD_CHALLENGES = {
    "negation", "correction", "noisy_transcript", "ambiguity", "out_of_scope", "handoff",
}


class CaseContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_intent: str | None = None
    clarification_options: list[str] = Field(default_factory=list)


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    conversation_id: str
    question: str = Field(min_length=1)
    source: Literal["seed"]
    dataset_version: str
    source_flag: None
    reviewed: Literal[True]
    split: Literal["test", "calibration"]
    expected_decision: Literal["route", "clarify", "out_of_scope", "handoff"]
    expected_intent_id: str | None
    context: CaseContext
    label_origin: str
    challenge: Literal[
        "paraphrase", "negation", "correction", "noisy_transcript", "ambiguity",
        "out_of_scope", "handoff", "context",
    ] | None = None


def read_cases(path: Path) -> list[BenchmarkCase]:
    return [BenchmarkCase.model_validate(row) for row in json.loads(path.read_text())]


@pytest.mark.parametrize("sector", SECTORS)
def test_supplement_covers_every_routable_intent_with_independent_questions(sector: str):
    directory = ROOT / "data/presets" / sector
    catalog = [Intent.model_validate(row) for row in json.loads((directory / "catalog.json").read_text())]
    base = read_cases(directory / "cases.json")
    supplement_path = directory / "benchmark-cases.json"
    supplement = read_cases(supplement_path) if supplement_path.exists() else []
    routable = {intent.intent_id for intent in catalog} - {"service.human"}
    counts = Counter(case.expected_intent_id for case in base + supplement if case.expected_decision == "route")
    insufficient = sorted(intent_id for intent_id in routable if counts[intent_id] < 2)
    assert not insufficient, f"Missing a second route question for {len(insufficient)} intents: {insufficient}"
    paraphrases = Counter(case.expected_intent_id for case in supplement if case.challenge == "paraphrase")
    assert set(paraphrases) == routable
    assert all(count == 1 for count in paraphrases.values())


@pytest.mark.parametrize("sector", SECTORS)
def test_supplement_has_explicit_labels_context_and_synthetic_challenges(sector: str):
    directory = ROOT / "data/presets" / sector
    path = directory / "benchmark-cases.json"
    cases = read_cases(path) if path.exists() else []
    counts = Counter(case.challenge for case in cases)
    assert sum(counts[category] for category in HARD_CHALLENGES) >= 24
    assert all(counts[category] >= 4 for category in HARD_CHALLENGES)
    assert counts["context"] >= 2
    ids = {row["intent_id"] for row in json.loads((directory / "catalog.json").read_text())}
    for case in cases:
        assert case.case_id.startswith(f"{sector}-depth-v1-")
        assert case.conversation_id == case.case_id
        assert case.dataset_version == f"{sector}-benchmark-depth-english-v1"
        assert case.label_origin == "curated_synthetic_benchmark_depth"
        assert case.split == "test" and case.challenge is not None
        if case.expected_decision == "route":
            assert case.expected_intent_id in ids - {"service.human"}
        else:
            assert case.expected_intent_id is None
        referenced = set(case.context.clarification_options)
        if case.context.active_intent:
            referenced.add(case.context.active_intent)
        assert referenced <= ids
        if case.challenge == "context":
            assert referenced
        if case.challenge in {"ambiguity", "out_of_scope", "handoff"}:
            assert case.expected_decision == {"ambiguity": "clarify", "out_of_scope": "out_of_scope", "handoff": "handoff"}[case.challenge]


@pytest.mark.parametrize("sector", SECTORS)
def test_test_calibration_and_catalog_questions_do_not_overlap(sector: str):
    directory = ROOT / "data/presets" / sector
    path = directory / "benchmark-cases.json"
    supplement = read_cases(path) if path.exists() else []
    cases = read_cases(directory / "cases.json") + read_cases(directory / "calibration-cases.json") + supplement
    assert len({case.case_id for case in cases}) == len(cases)
    hashes = [question_hash(case.question) for case in cases]
    assert len(set(hashes)) == len(hashes)
    example_hashes = {
        question_hash(example)
        for row in json.loads((directory / "catalog.json").read_text())
        for example in row["examples"]
    }
    assert not example_hashes.intersection(hashes)
