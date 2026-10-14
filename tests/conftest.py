import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Isolate app.main's eager default app before test-module collection imports it."""
    from app.config import Settings

    directory = TemporaryDirectory(prefix="intent-tests-default-app-")
    config.add_cleanup(directory.cleanup)
    overrides = {"data_dir": Path(directory.name), "model_credentials_file": Path(directory.name) / "absent.env"}
    with pytest.MonkeyPatch.context() as environment:
        # Fill every setting from schema defaults so neither .env nor the caller's
        # provider keys, model paths, or private data directory initialize this app.
        for name, field in Settings.model_fields.items():
            value = overrides.get(name, field.get_default(call_default_factory=True))
            encoded = json.dumps(value) if isinstance(value, (list, dict, bool)) else str(value)
            environment.setenv("INTENT_" + name.upper(), encoded)
        from app.main import app

    config.add_cleanup(app.state.studio.close)


@pytest.fixture(autouse=True)
def allow_test_client_host(monkeypatch):
    """httpx TestClient uses testserver; this allowance must never ship as a default."""
    monkeypatch.setenv("INTENT_TRUSTED_HOSTS", '["localhost", "127.0.0.1", "::1", "testserver"]')
