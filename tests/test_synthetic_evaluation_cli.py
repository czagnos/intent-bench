"""Run authored samples through the public command and real evaluation lifecycle."""
import importlib.util
import json
import signal
import tempfile
from collections import Counter
from pathlib import Path

import httpx
import pytest

from app.config import ROOT, Settings
from app.model_registry import ModelRegistry, Registration
from app.providers import OPENROUTER_BASE_URL
from app.store import Store
from app.synthetic_samples import load_sample_pack, sample_cases, sample_metadata


def evaluate_script():
    spec = importlib.util.spec_from_file_location("synthetic_evaluation_command", ROOT / "scripts/evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def settings(tmp_path):
    defaults = {name: field.get_default(call_default_factory=True) for name, field in Settings.model_fields.items()}
    defaults.update(data_dir=tmp_path / "private", model_credentials_file=tmp_path / "absent.env",
                    openrouter_api_key="synthetic-cli-key", embedding_mode="http",
                    embedding_base_url=OPENROUTER_BASE_URL, embedding_model="synthetic-embedding",
                    embedding_profile="plain", llm_base_url=OPENROUTER_BASE_URL, llm_model="synthetic-selector")
    return Settings(_env_file=None, **defaults)


def files(directory: Path) -> dict[str, bytes]:
    return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def test_sample_cli_runs_exact_public_cohort_without_touching_private_data(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    pack = load_sample_pack("synthetic-v1", "airline")
    private = Store(settings.data_dir)
    private.save_cases("airline", [dict(sample_cases(pack)[0], case_id="private-case", question="Private wording")])
    ModelRegistry(settings, private).save("airline", Registration(
        kind="embedding", name="Private embedding", model="private-model", connection="onprem",
        base_url="https://private.example/v1", auth="none"))
    before = files(settings.data_dir)
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))

    code = evaluate_script().main(["--sample-pack", "synthetic-v1", "--workspace", "airline"],
                                  settings=settings, transport=transport)

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(summary["file"]).read_text())
    assert summary["status"] == artifact["status"] == "completed"
    assert artifact["progress"] == artifact["total"] == 48
    assert artifact["options"]["source"] == "customer"
    assert artifact["accounting"]["provider_requests"] == 0 and requests == []
    metadata = sample_metadata(pack, 100).model_dump()
    assert summary["sample_pack"] == artifact["sample_pack"] == metadata
    records = artifact["results"]["lexical"]["records"]
    assert [record["case_id"] for record in records] == metadata["selected_case_ids"]
    assert len(records) == 48 and all(record["decision"] != "error" for record in records)
    assert files(settings.data_dir) == before
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("source", ["seed", "customer", "all"])
def test_sample_source_is_unambiguous_and_conflicts_fail_before_writes(settings, tmp_path, monkeypatch, capsys, source):
    monkeypatch.chdir(tmp_path)
    before = files(tmp_path)
    try:
        code = evaluate_script().main(["--sample-pack", "synthetic-v1", "--source", source, "--limit", "1"],
                                      settings=settings)
    except SystemExit as exc:
        code = exc.code
    assert code in (1, 2)
    assert "--source" in capsys.readouterr().err
    assert files(tmp_path) == before
    assert not settings.data_dir.exists() and not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("workspace", ["private-workspace", "banking", "../airline"])
def test_sample_cli_rejects_unsupported_workspace_before_writes(settings, tmp_path, monkeypatch, capsys, workspace):
    monkeypatch.chdir(tmp_path)
    before = files(tmp_path)

    code = evaluate_script().main(["--sample-pack", "synthetic-v1", "--workspace", workspace], settings=settings)

    assert code == 1
    assert "Unsupported sample pack or workspace" in capsys.readouterr().err
    assert files(tmp_path) == before
    assert not settings.data_dir.exists() and not (tmp_path / "artifacts").exists()


def test_sample_limit_metadata_describes_each_ordered_repeat_without_expanding_counts(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pack = load_sample_pack("synthetic-v1", "insurance")

    code = evaluate_script().main([
        "--sample-pack", "synthetic-v1", "--workspace", "insurance", "--limit", "17", "--repetitions", "2",
        "--max-provider-requests", "0", "--max-duration-seconds", "120", "--max-reported-cost-usd", "0.1",
    ], settings=settings)

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(summary["file"]).read_text())
    metadata = artifact["sample_pack"]
    assert summary["sample_pack"] == metadata
    assert metadata["available_count"] == 48 and metadata["selected_count"] == 17
    assert artifact["selected_count"] == 17 and artifact["progress"] == artifact["total"] == 34
    assert len(artifact["results"]) == 2
    assert {result["repeat_index"] for result in artifact["results"].values()} == {1, 2}
    assert artifact["group_summaries"][0]["complete_count"] == 2
    expected = pack.cases[:17]
    assert metadata["selected_challenge_counts"] == Counter(case.challenge for case in expected)
    assert metadata["selected_decision_counts"] == Counter(case.expected_decision for case in expected)
    for result in artifact["results"].values():
        assert result["selected_count"] == result["completed_count"] == 17
        assert [record["case_id"] for record in result["records"]] == metadata["selected_case_ids"]
    assert metadata["selected_case_ids"] == [case.case_id for case in expected]
    assert artifact["options"]["execution_limits"] == {
        "max_provider_requests": 0, "max_duration_seconds": 120, "max_reported_cost_usd": .1,
    }
    assert artifact["accounting"]["provider_requests"] == 0
    assert not settings.data_dir.exists()


def test_sample_remote_budget_preserves_finished_records_and_metadata_without_a_request(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))

    code = evaluate_script().main([
        "--sample-pack", "synthetic-v1", "--workspace", "ecommerce", "--limit", "2",
        "--methods", "lexical", "e5", "--semantic-rejection", "off", "--max-provider-requests", "0",
    ], settings=settings, transport=transport)

    assert code == 2
    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(summary["file"]).read_text())
    assert artifact["status"] == "stopped" and artifact["stop_reason"] == "request_limit"
    assert artifact["progress"] == 2 and artifact["total"] == 4
    assert artifact["accounting"]["provider_requests"] == 0 and requests == []
    assert summary["sample_pack"] == artifact["sample_pack"]
    assert artifact["sample_pack"]["selected_count"] == 2
    assert [record["case_id"] for record in artifact["results"]["lexical"]["records"]] == artifact["sample_pack"]["selected_case_ids"]
    assert artifact["results"]["e5"]["complete"] is False
    assert artifact["results"]["e5"]["records"] == []
    assert list(scratch.iterdir()) == [] and not settings.data_dir.exists()


def test_sample_cleanup_after_export_failure_restores_signal_handler(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    (tmp_path / "artifacts").write_text("An existing file prevents writing the export directory.")
    before = files(tmp_path)
    previous_handler = signal.getsignal(signal.SIGINT)

    code = evaluate_script().main(["--sample-pack", "synthetic-v1", "--workspace", "airline", "--limit", "1"],
                                  settings=settings)

    assert code == 1
    assert "output unavailable" in capsys.readouterr().err
    assert signal.getsignal(signal.SIGINT) is previous_handler
    assert list(scratch.iterdir()) == [] and not settings.data_dir.exists()
    assert files(tmp_path) == before


def test_ordinary_cli_still_selects_seed_cases_without_sample_metadata(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = evaluate_script().main(["--workspace", "airline", "--limit", "1"], settings=settings)

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(summary["file"]).read_text())
    assert "sample_pack" not in summary and "sample_pack" not in artifact
    assert artifact["options"]["source"] == "seed"
    assert artifact["selected_count"] == artifact["progress"] == artifact["total"] == 1
    stored = Store(settings.data_dir)
    seed_ids = {case["case_id"] for case in stored.cases("airline", "seed", split="test")}
    assert artifact["results"]["lexical"]["records"][0]["case_id"] in seed_ids
    assert stored.jobs("airline")[0]["id"] == artifact["id"]


def test_sample_remote_run_uses_default_connection_and_cleans_up_after_worker_failure(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    requests: list[httpx.Request] = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise RuntimeError("External failure containing sensitive provider details")

    code = evaluate_script().main([
        "--sample-pack", "synthetic-v1", "--workspace", "airline", "--limit", "2",
        "--methods", "e5", "--semantic-rejection", "off",
    ], settings=settings, transport=httpx.MockTransport(unavailable))

    assert code == 1
    output = capsys.readouterr()
    summary = json.loads(output.out)
    saved = Path(summary["file"]).read_text()
    artifact = json.loads(saved)
    assert artifact["status"] == "failed" and artifact["progress"] == 0
    assert artifact["accounting"]["provider_requests"] == len(requests) == 1
    assert str(requests[0].url) == OPENROUTER_BASE_URL + "/embeddings"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-cli-key"
    assert json.loads(requests[0].content)["model"] == settings.embedding_model
    assert summary["sample_pack"] == artifact["sample_pack"]
    assert artifact["sample_pack"]["selected_count"] == artifact["total"] == 2
    assert "sensitive provider details" not in saved + output.out + output.err
    assert list(scratch.iterdir()) == [] and not settings.data_dir.exists()


def test_sample_cannot_select_private_registered_models_and_cleans_up_before_job(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    private = Store(settings.data_dir)
    registered = ModelRegistry(settings, private).save("airline", Registration(
        kind="embedding", name="Private embedding", model="private-model", connection="onprem",
        base_url="https://private.example/v1", auth="none"))
    before = files(settings.data_dir)
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))

    code = evaluate_script().main([
        "--sample-pack", "synthetic-v1", "--workspace", "airline", "--limit", "1",
        "--methods", "e5", "--semantic-rejection", "off", "--embedding-ids", registered["id"],
    ], settings=settings, transport=transport)

    assert code == 1
    assert "Unknown embedding model selection" in capsys.readouterr().err
    assert requests == [] and not (tmp_path / "artifacts").exists()
    assert list(scratch.iterdir()) == [] and files(settings.data_dir) == before
