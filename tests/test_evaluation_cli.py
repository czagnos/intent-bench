"""CLI behavior through the real service, storage, and external boundaries."""
import json
import importlib.util
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import FrameType

import httpx
import pytest

from app.config import ROOT, Settings
from app.providers import OPENROUTER_BASE_URL
from app.store import Store


def isolated_environment(directory: Path) -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", "")}
    for name, field in Settings.model_fields.items():
        value = field.get_default(call_default_factory=True)
        if name == "data_dir":
            value = directory / "data"
        elif name == "model_credentials_file":
            value = directory / "absent.env"
        environment["INTENT_" + name.upper()] = json.dumps(value) if isinstance(value, (list, dict, bool)) else str(value)
    return environment


def test_cli_repeats_offline_and_preserves_all_execution_options(tmp_path):
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/evaluate.py"), "--limit", "1", "--repetitions", "2",
        "--max-provider-requests", "0", "--max-duration-seconds", "120",
        "--max-reported-cost-usd", "0.1",
    ], cwd=tmp_path, env=isolated_environment(tmp_path), text=True, capture_output=True, timeout=60)

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    artifact = json.loads((tmp_path / summary["file"]).read_text())
    assert summary["status"] == artifact["status"] == "completed"
    assert artifact["progress"] == artifact["total"] == 2
    assert artifact["options"]["repetitions"] == 2
    assert artifact["options"]["execution_limits"] == {
        "max_provider_requests": 0, "max_duration_seconds": 120, "max_reported_cost_usd": .1,
    }
    assert artifact["accounting"]["provider_requests"] == 0
    assert artifact["accounting"]["reported_cost_usd"] == 0
    assert {item["repeat_index"] for item in artifact["results"].values()} == {1, 2}
    assert artifact["group_summaries"][0]["complete_count"] == 2


def evaluate_script():
    spec = importlib.util.spec_from_file_location("evaluation_command", ROOT / "scripts/evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path / "data", model_credentials_file=tmp_path / "absent.env",
                    openrouter_api_key="synthetic-cli-key", embedding_mode="http",
                    embedding_base_url=OPENROUTER_BASE_URL, embedding_model="synthetic-embedding",
                    embedding_profile="plain", llm_base_url=OPENROUTER_BASE_URL, llm_model="synthetic-selector")


def test_cli_budget_stops_before_inference_and_exports_partial_result(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))

    code = evaluate_script().main([
        "--methods", "e5", "--semantic-rejection", "off", "--limit", "2", "--max-provider-requests", "0",
    ], settings=settings, transport=transport)

    assert code == 2
    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(summary["file"]).read_text())
    assert artifact["status"] == "stopped" and artifact["stop_reason"] == "request_limit"
    assert artifact["progress"] == 0 and artifact["total"] == 2
    assert requests == []
    partial = next(iter(artifact["results"].values()))
    assert partial["complete"] is False and partial["records"] == []


@pytest.mark.parametrize("arguments", [
    ["--repetitions", "0"], ["--repetitions", "6"], ["--repetitions", "1.5"],
    ["--max-provider-requests", "-1"], ["--max-provider-requests", "100001"],
    ["--max-duration-seconds", "0.9"], ["--max-duration-seconds", "86401"],
    ["--max-duration-seconds", "nan"], ["--max-reported-cost-usd", "0"],
    ["--max-reported-cost-usd", "10001"], ["--max-reported-cost-usd", "inf"],
])
def test_cli_rejects_invalid_controls_before_creating_job(settings, tmp_path, monkeypatch, capsys, arguments):
    monkeypatch.chdir(tmp_path)
    try:
        code = evaluate_script().main(arguments, settings=settings)
    except SystemExit as exc:
        code = exc.code
    assert code in (1, 2)
    assert capsys.readouterr().err
    assert Store(settings.data_dir).jobs("demo") == []
    assert not (tmp_path / "artifacts").exists()


def test_cli_failed_worker_saves_artifact_and_returns_one(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("external transport failed with sensitive detail")

    code = evaluate_script().main(["--methods", "e5", "--semantic-rejection", "off", "--limit", "2"],
                                  settings=settings, transport=httpx.MockTransport(unavailable))
    assert code == 1
    output = capsys.readouterr()
    summary = json.loads(output.out)
    saved = Path(summary["file"]).read_text()
    artifact = json.loads(saved)
    assert artifact["status"] == "failed" and artifact["progress"] == 0
    assert artifact["accounting"]["provider_requests"] == 1
    assert artifact["accounting"]["reported_cost_usd"] is None
    assert "sensitive detail" not in saved + output.out + output.err


def test_repeated_sigint_waits_for_inflight_work_and_saves_finished_records(tmp_path):
    child = tmp_path / "run_cli.py"
    child.write_text('''import importlib.util
import json
import time
from pathlib import Path
import httpx

spec = importlib.util.spec_from_file_location("evaluate", SCRIPT)
evaluate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate)

def respond(request):
    Path("inflight").write_text("started")
    deadline = time.monotonic() + 30
    while not Path("release").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("HTTP gate was not released")
        time.sleep(.02)
    body = json.loads(request.content)
    return httpx.Response(200, json={"data": [
        {"index": n, "embedding": [1., 0.]} for n in range(len(body["input"]))],
        "usage": {"prompt_tokens": 5, "total_tokens": 5, "cost": .01}})

raise SystemExit(evaluate.main(["--methods", "lexical", "e5", "--semantic-rejection", "off", "--limit", "2"],
                              transport=httpx.MockTransport(respond)))
'''.replace("SCRIPT", repr(str(ROOT / "scripts/evaluate.py"))))
    environment = isolated_environment(tmp_path)
    environment.update(INTENT_EMBEDDING_MODE="http", INTENT_EMBEDDING_BASE_URL=OPENROUTER_BASE_URL,
                       INTENT_OPENROUTER_API_KEY="synthetic-cli-key", INTENT_EMBEDDING_MODEL="synthetic-embedding")
    process = subprocess.Popen([sys.executable, str(child)], cwd=tmp_path, env=environment,
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while not (tmp_path / "inflight").exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert (tmp_path / "inflight").exists(), "CLI did not reach its HTTP boundary"
        before = Store(tmp_path / "data").jobs("demo")[0]
        assert before["progress"] == 2 and before["status"] == "running"
        process.send_signal(signal.SIGINT)
        time.sleep(.3)
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        time.sleep(.3)
        waiting = process.poll() is None
    finally:
        (tmp_path / "release").write_text("finish the in-flight request")
        stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 130, stderr
    assert waiting, "Cancellation must wait for the in-flight request"
    artifact = json.loads((tmp_path / json.loads(stdout)["file"]).read_text())
    assert artifact["status"] == "cancelled" and artifact["stop_reason"] == "user_cancelled"
    assert artifact["progress"] == 2 and artifact["total"] == 4
    assert len(artifact["results"]["lexical"]["records"]) == 2
    assert artifact["results"]["e5"]["complete"] is False
    assert artifact["accounting"]["provider_requests"] == 1
    assert artifact["accounting"]["reported_cost_usd"] == .01
    assert "KeyboardInterrupt" not in stderr


@pytest.mark.parametrize(("arguments", "status", "progress"), [
    (["--methods", "lexical", "--limit", "1"], "completed", 1),
    (["--methods", "e5", "--semantic-rejection", "off", "--limit", "1", "--max-provider-requests", "0"],
     "stopped", 0),
])
def test_sigint_during_shutdown_returns_130_after_preserving_artifact_and_handler(
    settings, tmp_path, monkeypatch, capsys, arguments, status, progress,
):
    monkeypatch.chdir(tmp_path)
    prior_handler = signal.getsignal(signal.SIGINT)
    prior_profile = sys.getprofile()
    signal_sent = False

    def interrupt_at_shutdown(frame: FrameType, event: str, argument: object) -> None:
        nonlocal signal_sent
        # Observe real cleanup timing without replacing any service or executor operation.
        if event == "call" and frame.f_code is ThreadPoolExecutor.shutdown.__code__ and not signal_sent:
            signal_sent = True
            os.kill(os.getpid(), signal.SIGINT)
            os.kill(os.getpid(), signal.SIGINT)

    try:
        sys.setprofile(interrupt_at_shutdown)
        code = evaluate_script().main(arguments, settings=settings)
    finally:
        sys.setprofile(prior_profile)

    assert signal_sent, "The test must deliver SIGINT during real resource cleanup"
    assert signal.getsignal(signal.SIGINT) is prior_handler
    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(summary["file"]).read_text())
    assert artifact["status"] == status
    assert artifact["progress"] == progress and artifact["total"] == 1
    assert artifact["accounting"]["provider_requests"] == 0
    assert code == 130
