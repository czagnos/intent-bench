"""The import command shares validation and atomic persistence with the API."""
import csv
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import ROOT, Settings
from app.store import Store
from test_evaluation_cli import isolated_environment


def test_cli_synthetic_template_replay_reports_actual_insertions(tmp_path):
    command = [sys.executable, str(ROOT / "scripts/import_benchmark.py"),
               str(ROOT / "data/demo/transcript-example.csv"), "--workspace", "demo"]
    first = subprocess.run(command, cwd=tmp_path, env=isolated_environment(tmp_path),
                           text=True, capture_output=True, timeout=60)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout).get("inserted") == 4
    second = subprocess.run(command, cwd=tmp_path, env=isolated_environment(tmp_path),
                            text=True, capture_output=True, timeout=60)
    assert second.returncode == 0, second.stderr
    report = json.loads(second.stdout)
    assert report["inserted"] == 0 and report["already_present"] == report["imported"] == 4
    cases = Store(tmp_path / "data").cases("demo", "customer")
    assert len(cases) == 4 and all(not case["reviewed"] for case in cases)
    assert any(case["context"].get("pending_confirmation") for case in cases)


def import_script():
    spec = importlib.util.spec_from_file_location("import_command", ROOT / "scripts/import_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path / "data", model_credentials_file=tmp_path / "absent.env",
                    openrouter_api_key="", embedding_api_key="", llm_api_key="", reranker_api_key="",
                    embedding_mode="disabled", llm_base_url="", reranker_mode="disabled")


def template_rows() -> list[list[str]]:
    return list(csv.reader(io.StringIO((ROOT / "data/demo/transcript-example.csv").read_text())))


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)


@pytest.mark.parametrize("context", [
    '{"active_intent":"missing.intent"}',
    '{"active_intent":"card.limit.change","pending_slot":"invalid_slot"}',
    '{"messages":[{"role":"system","content":"Unsupported prior role"}]}',
    '{"future_context":true}',
    'not-json',
])
def test_cli_rejects_entire_import_on_context_error(settings, tmp_path, capsys, context):
    rows = template_rows()
    rows[2][rows[0].index("Context")] = context
    source = tmp_path / "invalid-context.csv"
    write_csv(source, rows)
    assert import_script().main([str(source)], settings=settings) == 1
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]
    store = Store(settings.data_dir)
    assert store.cases("demo", "customer") == [] and store.imports("demo") == []
    # Reusing the same database after failure succeeds without retained locks or partial rows.
    assert import_script().main([str(ROOT / "data/demo/transcript-example.csv")], settings=settings) == 0
    assert json.loads(capsys.readouterr().out)["inserted"] == 4


def test_cli_replay_preserves_review_and_moved_split_but_new_conflicts_are_atomic(settings, tmp_path, capsys):
    command = import_script()
    source = tmp_path / "transcript.csv"
    rows = template_rows()
    write_csv(source, rows)
    assert command.main([str(source)], settings=settings) == 0
    capsys.readouterr()
    store = Store(settings.data_dir)
    case = next(case for case in store.cases("demo", "customer") if case["source_session_id"] == "standalone-balance")
    store.review_case("demo", case["case_id"], {
        "expected_decision": "route", "expected_intent_id": "account.balance", "split": "test",
    })
    store.update_conversation_split("demo", case["conversation_id"], "dev")
    reviewed = next(item for item in store.cases("demo", "customer") if item["case_id"] == case["case_id"])
    history = store.case_versions("demo", case["case_id"])

    assert command.main([str(source)], settings=settings) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["inserted"] == 0 and replay["already_present"] == 4
    assert next(item for item in store.cases("demo", "customer") if item["case_id"] == case["case_id"]) == reviewed
    assert store.case_versions("demo", case["case_id"]) == history

    new_turn = rows[1].copy()
    new_turn[rows[0].index("BenchmarkSessionMessageId")] = "new"
    rows.append(new_turn)  # Explicit test conflicts with the persisted dev conversation.
    write_csv(source, rows)
    assert command.main([str(source)], settings=settings) == 1
    assert "split" in json.loads(capsys.readouterr().err)["error"].lower()
    assert len(store.cases("demo", "customer")) == 4 and len(store.imports("demo")) == 1

    rows[-1][rows[0].index("Split")] = ""
    write_csv(source, rows)
    assert command.main([str(source)], settings=settings) == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["inserted"] == 1 and appended["already_present"] == 4
    assert all(item["split"] == "dev" for item in store.cases("demo", "customer")
               if item["conversation_id"] == case["conversation_id"])


@pytest.mark.parametrize("content", [b"not a CSV", b"Question\n\xff"])
def test_cli_malformed_input_returns_error_then_database_remains_usable(settings, tmp_path, capsys, content):
    source = tmp_path / "bad.csv"
    source.write_bytes(content)
    assert import_script().main([str(source)], settings=settings) == 1
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]
    assert "Traceback" not in output.err
    assert Store(settings.data_dir).cases("demo", "customer") == []
    assert import_script().main([str(ROOT / "data/demo/transcript-example.csv")], settings=settings) == 0
    assert json.loads(capsys.readouterr().out)["inserted"] == 4
