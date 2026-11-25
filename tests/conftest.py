import pytest

from tests.support.replay import Replay
from utility_agents import model
from utility_agents.config import settings


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No test reaches the real API or the real log directory: the key and the kill switch
    are unset, and the logs go to the test's own directory."""
    monkeypatch.delenv(model.API_KEY_VARIABLE, raising=False)
    monkeypatch.delenv(model.KILL_SWITCH_VARIABLE, raising=False)
    monkeypatch.setitem(settings, "log_directory", str(tmp_path / "logs"))


@pytest.fixture
def replay(monkeypatch):
    """Answers every API request of the test from a local server, with no retry delay."""
    server = Replay()
    monkeypatch.setenv(model.API_KEY_VARIABLE, "replayed")
    monkeypatch.setitem(settings["anthropic"], "url", server.url)
    monkeypatch.setitem(settings["anthropic"], "retry_delay_seconds", 0)

    yield server

    server.close()
