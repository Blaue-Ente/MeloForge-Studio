import pytest


@pytest.fixture(autouse=True)
def _isolated_library(monkeypatch, tmp_path):
    """Never let tests write into the user's real Music folder."""
    monkeypatch.setenv("MELOFORGE_LIBRARY_DIR", str(tmp_path / "library"))


@pytest.fixture(autouse=True)
def _no_real_ollama(monkeypatch):
    """Tests must not depend on (or auto-enable) a locally running Ollama."""
    from app.services import local_llm

    monkeypatch.setattr(local_llm, "list_models", lambda *args, **kwargs: None)
