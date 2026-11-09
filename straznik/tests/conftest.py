import pytest


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAZNIK_STATE_DIR", str(tmp_path))
    return tmp_path
