"""Public sample loading and export behavior, independent of model providers."""
import csv
import io
import json
import shutil
import subprocess
import sys
from collections import Counter

import pytest

from app.catalog_presets import workspace_preset
from app.config import ROOT
from app.importer import import_benchmark
from app.store import Store
from app.synthetic_samples import (
    SAMPLE_DIRECTORY, SyntheticSector, load_sample_pack, render_sample_csv, sample_cases,
    sample_metadata, validate_sample_sector,
)


@pytest.mark.parametrize("pack_id,workspace", [
    ("../../private", "demo"), ("synthetic-v1", "banking"),
    ("synthetic-v1", "../demo"), ("synthetic-v2", "demo"),
])
def test_loading_rejects_unknown_pack_or_workspace(pack_id, workspace):
    with pytest.raises(ValueError, match="Unsupported"):
        load_sample_pack(pack_id, workspace)


@pytest.mark.parametrize("workspace", ["demo", "airline", "insurance", "ecommerce"])
def test_published_sector_has_48_new_labelled_turns_with_required_coverage(workspace):
    pack = load_sample_pack("synthetic-v1", workspace)
    assert len(pack.cases) == 48
    assert pack.workspace == workspace
    assert all(case.split == "test" for case in pack.cases)
    challenges = Counter(case.challenge for case in pack.cases)
    assert challenges["context"] >= 10
    for challenge in ("paraphrase", "negation", "correction", "noisy_transcript", "near_neighbor",
                      "ambiguity", "multiple_intents", "out_of_scope", "handoff"):
        assert challenges[challenge] >= 2
    groups = Counter(case.conversation_id for case in pack.cases)
    assert sum(count > 1 for count in groups.values()) >= 3
    assert len({case.expected_intent_id for case in pack.cases if case.expected_decision == "route"}) >= 10


def test_export_check_validates_all_four_generated_files_without_writing():
    before = {path.name: path.read_bytes() for path in SAMPLE_DIRECTORY.glob("*.csv")}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/export_synthetic_samples.py"), "--check"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 CSV files are current" in result.stdout
    assert {path.name: path.read_bytes() for path in SAMPLE_DIRECTORY.glob("*.csv")} == before


def test_export_reports_missing_and_stale_csv_without_writing_and_regenerates(tmp_path):
    # Copy public inputs, leaving the actual checkout and private workspaces untouched.
    shutil.copytree(ROOT / "apps/api/app", tmp_path / "apps/api/app", ignore=shutil.ignore_patterns("__pycache__"))
    for directory in ("demo", "presets", "samples"):
        shutil.copytree(ROOT / "data" / directory, tmp_path / "data" / directory)
    (tmp_path / "scripts").mkdir()
    command = tmp_path / "scripts/export_synthetic_samples.py"
    shutil.copyfile(ROOT / "scripts/export_synthetic_samples.py", command)
    exported = tmp_path / "data/samples/synthetic-v1"
    path = exported / "airline.csv"
    path.unlink()
    missing = subprocess.run([sys.executable, str(command), "--check"], capture_output=True, text=True, check=False)
    assert missing.returncode == 1 and "airline.csv" in missing.stderr
    assert not path.exists()
    regenerated = subprocess.run([sys.executable, str(command)], capture_output=True, text=True, check=False)
    assert regenerated.returncode == 0, regenerated.stderr
    assert path.read_bytes() == (SAMPLE_DIRECTORY / "airline.csv").read_bytes()
    path.write_text("stale\n", encoding="utf-8")
    before = {item.name: item.read_bytes() for item in exported.glob("*.csv")}
    stale = subprocess.run([sys.executable, str(command), "--check"], capture_output=True, text=True, check=False)
    assert stale.returncode == 1 and "airline.csv" in stale.stderr
    assert {item.name: item.read_bytes() for item in exported.glob("*.csv")} == before


@pytest.mark.parametrize("workspace", ["demo", "airline", "insurance", "ecommerce"])
def test_csv_preserves_transcript_inputs_but_does_not_auto_review_annotations(workspace):
    pack = load_sample_pack("synthetic-v1", workspace)
    text = render_sample_csv(pack)
    assert text == render_sample_csv(pack)
    assert (SAMPLE_DIRECTORY / f"{pack.sector}.csv").read_bytes() == text.encode("utf-8")
    exported = list(csv.DictReader(io.StringIO(text)))
    imported, report = import_benchmark(text.encode("utf-8"), f"{pack.sector}.csv")
    assert report["imported"] == 48 and report["reviewed"] == 0 and report["duplicates"] == 0
    for original, row, restored in zip(pack.cases, exported, imported, strict=True):
        assert row["Answer"] == row["Message Flow"] == row["TRUE/FALSE"] == ""
        assert row["Question"] == original.question == restored["question"]
        assert json.loads(row["Context"]) == restored["context"] == original.context.as_data()
        assert restored["source_session_id"] == original.conversation_id
        assert restored["source_message_id"] == original.turn_id
        assert restored["source_dataset_id"] == f"intentbench-synthetic-v1-{pack.sector}"
        assert restored["reviewed"] is False and restored["expected_decision"] is None
        assert restored["expected_intent_id"] is None and restored["split"] == "test"
    replay, _ = import_benchmark(text.encode("utf-8"), "renamed.csv")
    assert [case["case_id"] for case in replay] == [case["case_id"] for case in imported]


def test_trusted_adapter_retains_synthetic_provenance_and_insertion_order(tmp_path):
    pack = load_sample_pack("synthetic-v1", "demo")
    cases = sample_cases(pack)
    store = Store(tmp_path / "samples")
    store.save_cases("demo", cases)
    stored = store.cases("demo", source="customer", reviewed=True, split="test")
    assert [case["case_id"] for case in stored] == [case.case_id for case in pack.cases]
    assert all(case["label_origin"] == "ai_assisted_synthetic" for case in stored)
    assert all("reviewed_at" not in case for case in stored)
    for original, case in zip(pack.cases, stored, strict=True):
        assert case["expected_decision"] == original.expected_decision
        assert case["expected_intent_id"] == original.expected_intent_id
        assert case["context"] == original.context.as_data()
        assert not store.case_versions("demo", case["case_id"])["versions"]


@pytest.mark.parametrize("limit", [1, 10, 48, 50])
def test_metadata_describes_selected_cohort_not_full_pack_or_repeats(limit):
    pack = load_sample_pack("synthetic-v1", "airline")
    metadata = sample_metadata(pack, limit)
    selected = pack.cases[:limit]
    assert metadata.available_count == 48
    assert metadata.selected_count == len(selected)
    assert metadata.selected_case_ids == [case.case_id for case in selected]
    assert metadata.selected_challenge_counts == Counter(case.challenge for case in selected)
    assert metadata.selected_decision_counts == Counter(case.expected_decision for case in selected)
    assert len(metadata.content_sha256) == 64
    assert metadata.content_sha256 == sample_metadata(pack, 48).content_sha256
    assert metadata.catalog_fingerprint == pack.catalog_fingerprint
    changed = pack.model_dump()
    changed["cases"][0]["rationale"] += " Additional author clarification."
    assert sample_metadata(SyntheticSector.model_validate(changed), limit).content_sha256 != metadata.content_sha256


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_metadata_rejects_invalid_selection_limit(limit):
    with pytest.raises(ValueError, match="positive integer"):
        sample_metadata(load_sample_pack("synthetic-v1", "demo"), limit)


@pytest.mark.parametrize("mutation,error", [
    ("catalog", "fingerprint"), ("identity", "Duplicate sample case"),
    ("turn", "Duplicate sample case"), ("question", "Duplicate sample question"),
    ("label", "outside the sample catalog"), ("nonroute_label", "Only route"),
    ("active_label", "must match the active intent"), ("slot", "outside the active intent"),
    ("split", "Input should be 'test'"), ("prefix", "prefix"),
    ("coverage", "coverage"), ("empty_context", "prior-message snapshot"),
    ("seed_overlap", "overlaps"), ("catalog_overlap", "overlaps"),
    ("unknown_field", "Extra inputs"),
])
def test_validator_rejects_invalid_authored_data(mutation, error):
    pack = load_sample_pack("synthetic-v1", "demo")
    data = pack.model_dump()
    cases = data["cases"]
    preset = workspace_preset("demo")
    catalog = preset.intents()
    exclusions = [json.loads(case.payload)["question"] for case in preset.cases() + preset.benchmark_cases()]
    if mutation == "catalog":
        data["catalog_fingerprint"] = "0" * 16
    elif mutation == "identity":
        cases[1]["case_id"] = cases[0]["case_id"]
    elif mutation == "turn":
        cases[1]["conversation_id"] = cases[0]["conversation_id"]
        cases[1]["turn_id"] = cases[0]["turn_id"]
    elif mutation == "question":
        cases[1]["question"] = cases[0]["question"]
        cases[1]["context"] = cases[0]["context"]
    elif mutation == "label":
        cases[0]["expected_decision"] = "route"
        cases[0]["expected_intent_id"] = "missing.intent"
    elif mutation == "nonroute_label":
        cases[0]["expected_decision"] = "clarify"
        cases[0]["expected_intent_id"] = catalog[0].intent_id
    elif mutation == "active_label":
        cases[0]["expected_decision"] = "cancel"
        cases[0]["expected_intent_id"] = "card.limit.change"
    elif mutation == "slot":
        cases[0]["context"] = {"active_intent": "card.limit.change", "pending_slot": "invented_slot"}
    elif mutation == "split":
        cases[0]["split"] = "dev"
    elif mutation == "prefix":
        cases[0]["case_id"] = "foreign-case"
    elif mutation == "coverage":
        for case in cases:
            if case["challenge"] == "handoff":
                case["challenge"] = "paraphrase"
    elif mutation == "empty_context":
        next(case for case in cases if case["challenge"] == "context"
             and case["expected_decision"] == "route")["context"] = {}
    elif mutation == "seed_overlap":
        cases[0]["question"] = exclusions[0]
        cases[0]["context"] = {}
    elif mutation == "catalog_overlap":
        cases[0]["question"] = catalog[0].examples[0]
        cases[0]["context"] = {}
    elif mutation == "unknown_field":
        cases[0]["trusted_label"] = True
    with pytest.raises(ValueError, match=error):
        validate_sample_sector(SyntheticSector.model_validate(data), catalog, exclusions)
