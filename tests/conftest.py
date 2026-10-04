"""Fixtures every test gets."""

import httpx
import pytest
from helpers import FakeServers

from fantasy_king.ai.token_store import HOME_ENV, TokenStore

SETTING_NAMES = (
    "LEAGUE_DATA_SOURCE",
    "AI_PROVIDER",
    "CHATGPT_MODEL",
    "OPENROUTER_MODEL",
    "OPENROUTER_API_KEY",
    "WEB_SEARCH_ENABLED",
    "MAX_WEB_SEARCHES_PER_RUN",
)


@pytest.fixture(autouse=True)
def isolated_from_this_computer(tmp_path, monkeypatch):
    """Keep tests away from the real saved sign-in, real settings, and the internet."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "saved_sign_in"))
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)

    def refuse(self, request):
        raise AssertionError(f"A test tried a real network call to {request.url.host}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def fake() -> FakeServers:
    return FakeServers()


@pytest.fixture
def store(tmp_path) -> TokenStore:
    """The same folder the app itself would use during this test."""
    return TokenStore(tmp_path / "saved_sign_in")
