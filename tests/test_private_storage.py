"""Local datasets and routing history are readable only by their owner."""

from stat import S_IMODE

import pytest

from app.store import Store


def test_private_storage_uses_owner_only_permissions(tmp_path):
    directory = tmp_path / "private"
    store = Store(directory)
    store.create_session("demo")
    assert S_IMODE(directory.stat().st_mode) == 0o700
    assert S_IMODE((directory / "studio.db").stat().st_mode) == 0o600


def test_storage_refuses_a_symlinked_data_directory(tmp_path):
    target = tmp_path / "shared"
    target.mkdir(mode=0o755)
    directory = tmp_path / "private"
    directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        Store(directory)
    assert S_IMODE(target.stat().st_mode) == 0o755
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("filename", ["studio.db", "studio.db-wal", "studio.db-shm"])
def test_storage_refuses_a_symlinked_database_file(tmp_path, filename):
    target = tmp_path / "unrelated.db"
    target.touch(mode=0o644)
    directory = tmp_path / "private"
    directory.mkdir()
    (directory / filename).symlink_to(target)
    with pytest.raises(OSError):
        Store(directory)
    assert S_IMODE(target.stat().st_mode) == 0o644
    assert target.read_bytes() == b""


def test_existing_private_storage_is_hardened_without_losing_data(tmp_path):
    directory = tmp_path / "private"
    store = Store(directory)
    session = store.create_session("demo")
    directory.chmod(0o755)
    (directory / "studio.db").chmod(0o644)

    reopened = Store(directory)
    assert reopened.claim_turn("demo", session["session_id"], 1)["session_id"] == session["session_id"]
    assert S_IMODE(directory.stat().st_mode) == 0o700
    assert S_IMODE((directory / "studio.db").stat().st_mode) == 0o600
