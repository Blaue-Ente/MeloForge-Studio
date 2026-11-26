import pytest


@pytest.fixture(autouse=True)
def _isolated_library(monkeypatch, tmp_path):
    """Never let tests write into the user's real Music folder."""
    monkeypatch.setenv("MELOFORGE_LIBRARY_DIR", str(tmp_path / "library"))
