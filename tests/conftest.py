import pytest

from app import llm


class NoKeyClient:
    api_key = None
    auth_token = None
    credentials = None


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch):
    """Tests never reach the real API, even with a key in .env. Tests that need AI output
    install their own fake client or fake call_json on top of this."""
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.anthropic, "Anthropic", lambda *args, **kwargs: NoKeyClient())
    monkeypatch.delenv("KRDICT_API_KEY", raising=False)
