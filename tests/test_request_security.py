"""The local HTTP boundary rejects requests originating from unrelated websites."""

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("INTENT_TRUSTED_HOSTS")
    return Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled", llm_base_url="")


def test_untrusted_website_cannot_import_cases(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        response = client.post(
            "/v1/cases/import",
            headers={"Origin": "https://attacker.example"},
            files={"file": ("injected.csv", b"Question\nInjected benchmark question\n", "text/csv")},
        )
        assert response.status_code == 403
        assert client.get("/v1/status").json()["customer_case_count"] == 0


def test_untrusted_host_cannot_read_private_cases_after_dns_rebinding(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        imported = client.post(
            "/v1/cases/import",
            files={"file": ("local.csv", b"Question\nPrivate benchmark question\n", "text/csv")},
        )
        assert imported.status_code == 200
        response = client.get(
            "/v1/cases?source=customer",
            headers={"Host": "attacker.example:8002", "Origin": "http://attacker.example:8002"},
        )
        assert response.status_code == 400
        assert "Private benchmark question" not in response.text


def test_cross_site_browser_read_without_origin_is_rejected(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        response = client.get("/v1/status", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"})
        assert response.status_code == 403


@pytest.mark.parametrize("origin", [
    "null", "", "https://attacker.example", "http://127.0.0.1:8003",
    "http://127.0.0.1.attacker.example:8002", "http://localhost:5173@attacker.example",
    "http://localhost:5173/attacker", "http://localhost:5173?attacker=1",
    "http://localhost:5173#attacker", "http://localhost:5173\\attacker",
])
def test_untrusted_or_malformed_origins_cannot_read_data(settings, origin):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        assert client.get("/v1/status", headers={"Origin": origin}).status_code == 403


@pytest.mark.parametrize("host", [
    "attacker.example", "localhost.attacker.example", "127.0.0.1.attacker.example",
    "localhost@attacker.example", "localhost/path", "localhost:99999", "testserver",
])
def test_default_hosts_reject_unknown_and_malformed_hostnames(settings, host):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        assert client.get("/health", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("url", ["http://localhost:8002", "http://127.0.0.1:8002", "http://[::1]:8002"])
def test_local_ui_and_command_line_requests_remain_available(settings, url):
    # TestClient's transport cannot parse IPv6 netlocs; use the actual HTTP Host header.
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002", headers={"Host": url.split("://", 1)[1]}) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/v1/sessions", headers={"Origin": url}).status_code == 201


def test_explicit_development_origin_and_preflight_remain_available(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        headers = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "cross-site"}
        preflight = client.options("/v1/sessions", headers={**headers, "Access-Control-Request-Method": "POST"})
        assert preflight.status_code == 200
        assert preflight.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
        assert client.post("/v1/sessions", headers=headers).status_code == 201


@pytest.mark.parametrize("name,values,status", [
    ("Host", ["127.0.0.1:8002", "attacker.example"], 400),
    ("Origin", ["http://127.0.0.1:8002", "https://attacker.example"], 403),
])
def test_ambiguous_security_headers_are_rejected(settings, name, values, status):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8002") as client:
        assert client.get("/health", headers=[(name, value) for value in values]).status_code == status


def test_explicit_host_allowlist_can_support_an_operator_proxy(settings):
    settings.trusted_hosts = ["workbench.example"]
    with TestClient(create_app(settings), base_url="https://workbench.example") as client:
        assert client.post("/v1/sessions", headers={"Origin": "https://workbench.example"}).status_code == 201
        assert client.get("/health", headers={"Host": "localhost"}).status_code == 400
