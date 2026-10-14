import json
import runpy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from app.config import ROOT, Settings
from app.providers import OPENROUTER_BASE_URL, ModelUnavailable, response_json, retry_after_seconds
from app.retrieval import Embeddings

CHECK_SCRIPT = runpy.run_path(str(ROOT / "scripts/check_models.py"))


def rate_response(code=429, *, headers=None, metadata=None, path="embeddings"):
    return httpx.Response(code, request=httpx.Request("POST", OPENROUTER_BASE_URL + "/" + path),
        headers=headers, json={"error": {"code": 429, "message": "private-input-secret", "metadata": metadata or {}}})


def test_upstream_rate_limit_exposes_only_diagnostic_fields():
    response = rate_response(headers={"Retry-After": "60", "Authorization": "Bearer header-secret"}, metadata={
        "provider_name": "DeepInfra", "provider_code": "rate_limited", "error_type": "rate_limit_exceeded",
        "raw": "api-key-and-prompt", "flagged_input": "private-input", "request": {"secret": "hidden"},
    })
    with pytest.raises(ModelUnavailable) as exc:
        response_json(response, "Embedding")
    assert exc.value.diagnostics == {
        "http_status": 429, "error_code": 429, "provider_name": "DeepInfra",
        "provider_code": "rate_limited", "error_type": "rate_limit_exceeded",
        "retry_after_seconds": 60, "rate_limit_source": "upstream_provider",
    }
    output = str(exc.value) + json.dumps(exc.value.diagnostics)
    assert all(secret not in output for secret in ("private-input", "api-key-and-prompt", "header-secret", "hidden"))


@pytest.mark.parametrize("path", ["embeddings", "chat/completions"])
def test_platform_headers_distinguish_openrouter_limit(path):
    response = rate_response(path=path, headers={"X-RateLimit-Limit": "10", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000000"})
    with pytest.raises(ModelUnavailable) as exc:
        response_json(response, "Model")
    assert exc.value.diagnostics["rate_limit_source"] == "openrouter"
    assert exc.value.diagnostics["rate_limit_remaining"] == "0"


@pytest.mark.parametrize("metadata", [{}, {"provider_name": None, "provider_code": None, "error_type": None}])
def test_missing_hints_do_not_invent_provider_or_wait_time(metadata):
    with pytest.raises(ModelUnavailable) as exc:
        response_json(rate_response(metadata=metadata), "Embedding")
    assert exc.value.diagnostics == {"http_status": 429, "error_code": 429, "rate_limit_source": "unknown"}


def test_html_error_preserves_status_and_retry_after_without_leaking_body():
    response = httpx.Response(429, text="<html>private-error-body</html>", headers={"Retry-After": "2"})
    with pytest.raises(ModelUnavailable) as exc:
        response_json(response, "Embedding")
    assert exc.value.diagnostics["retry_after_seconds"] == 2
    assert "private-error-body" not in str(exc.value)


def test_upstream_http200_error_keeps_original_rate_limit_code():
    with pytest.raises(ModelUnavailable) as exc:
        response_json(rate_response(200, metadata={"provider_code": "429"}), "Embedding")
    assert exc.value.diagnostics["http_status"] == 200
    assert exc.value.diagnostics["error_code"] == 429
    assert exc.value.diagnostics["rate_limit_source"] == "upstream_provider"


def test_retry_after_accepts_delta_seconds_and_http_date():
    assert retry_after_seconds("1.5") == 1.5
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60), usegmt=True)
    assert 58 <= retry_after_seconds(future) <= 60
    for value in (None, "", "not-a-date", "-10", "nan", "inf"):
        assert retry_after_seconds(value) is None


def test_opt_in_retry_waits_then_returns_success():
    failures, waits = [], []
    def operation():
        if not failures:
            failures.append(True)
            raise ModelUnavailable("limited", diagnostics={"http_status": 429, "retry_after_seconds": 2})
        return "ok"
    state = {"wait_seconds": 0, "retry_count": 0}
    result = CHECK_SCRIPT["call_with_rate_limit_retry"](operation, 2, state, sleep=waits.append)
    assert result == "ok" and waits == [2]
    assert state == {"wait_seconds": 2, "retry_count": 1}


@pytest.mark.parametrize("code,retry_after,retries", [(429, 60, 2), (429, 1, 0), (402, 1, 2), (401, 1, 2)])
def test_no_early_or_unrequested_retries(code, retry_after, retries):
    waits, calls = [], []
    def operation():
        calls.append(True)
        raise ModelUnavailable("error", diagnostics={"http_status": code, "retry_after_seconds": retry_after})
    with pytest.raises(ModelUnavailable):
        CHECK_SCRIPT["call_with_rate_limit_retry"](operation, retries, {"wait_seconds": 0, "retry_count": 0}, sleep=waits.append)
    assert len(calls) == 1 and waits == []


def test_retry_budget_is_total_and_http200_rate_limit_is_retryable():
    calls, waits = [], []
    def operation():
        calls.append(True)
        raise ModelUnavailable("error", diagnostics={"http_status": 200, "error_code": 429, "retry_after_seconds": 3})
    state = {"wait_seconds": 0, "retry_count": 0}
    with pytest.raises(ModelUnavailable):
        CHECK_SCRIPT["call_with_rate_limit_retry"](operation, 2, state, sleep=waits.append)
    assert len(calls) == 2 and waits == [3] and state["wait_seconds"] == 3


def test_diagnostic_script_identifies_the_failed_phase_and_does_not_call_llm(monkeypatch):
    settings = Settings(_env_file=None)
    class ProbeEmbeddings:
        def __init__(self, settings):
            pass
        def encode(self, texts, query=False):
            if query:
                raise ModelUnavailable("limited", diagnostics={"http_status": 429, "retry_after_seconds": 60})
            return __import__("numpy").array([[1., 0.]])
    check = CHECK_SCRIPT["check_models"]
    monkeypatch.setitem(check.__globals__, "Embeddings", ProbeEmbeddings)
    checks = check(settings, embedding=True, llm=False, retry_429=2)
    assert len(checks) == 1 and checks[0]["failed_phase"] == "query"
    assert checks[0]["diagnostics"]["retry_after_seconds"] == 60
    assert checks[0]["retry_count"] == 0


@pytest.mark.parametrize("base_url,expected_provider", [(OPENROUTER_BASE_URL, {"only": ["nebius"]}), ("https://onprem.example/v1", None)])
def test_embedding_provider_selection_is_scoped_to_openrouter(base_url, expected_provider):
    settings = Settings(_env_file=None, embedding_mode="http", embedding_base_url=base_url,
        embedding_model="qwen/qwen3-embedding-8b", openrouter_api_key="test-key", embedding_provider_only=["nebius"])
    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == "qwen/qwen3-embedding-8b"
        assert payload.get("provider") == expected_provider
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1., 0.]}]})
    embeddings = Embeddings(settings, httpx.MockTransport(respond))
    assert embeddings.encode(["Kart limiti"], query=True).shape == (1, 2)
    assert embeddings.metadata["provider_only"] == (["nebius"] if expected_provider else [])
