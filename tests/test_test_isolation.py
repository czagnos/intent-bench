"""Collecting tests must not initialize or harden a user's configured database."""

import os
from pathlib import Path
import subprocess
import sys


def test_collection_preserves_configured_user_storage(tmp_path):
    directory = tmp_path / "operator-data"
    directory.mkdir(mode=0o755)
    marker = directory / "keep.txt"
    marker.write_text("Existing operator files must stay untouched.")
    before_mode = directory.stat().st_mode
    environment = {
        **os.environ,
        "INTENT_DATA_DIR": str(directory),
        "INTENT_LLM_BASE_URL": "",
        "INTENT_LLM_API_KEY": "",
        "INTENT_OPENROUTER_API_KEY": "",
        "INTENT_LLM_PROTOCOL": "openai",
        "INTENT_EMBEDDING_MODE": "disabled",
        "INTENT_EMBEDDING_API_KEY": "",
        "INTENT_RERANKER_MODE": "disabled",
        "INTENT_RERANKER_API_KEY": "",
        "INTENT_MODEL_CREDENTIALS_FILE": str(tmp_path / "absent.env"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_request_security.py"],
        cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in directory.iterdir()) == ["keep.txt"]
    assert directory.stat().st_mode == before_mode
    assert marker.read_text() == "Existing operator files must stay untouched."
