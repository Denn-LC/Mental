import pytest


@pytest.fixture(autouse=True)
def own_database(tmp_path, monkeypatch):
    """Every test gets an empty database of its own; the real ~/.mental is never touched."""
    monkeypatch.setenv("MENTAL_DB", str(tmp_path / "mental.db"))
