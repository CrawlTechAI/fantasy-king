"""Smoke tests: the dashboard pages run and show the right things.

These use Streamlit's own test runner. Nothing here signs in or calls an AI.
"""

import pytest
from helpers import save_account
from streamlit.testing.v1 import AppTest

from fantasy_king.ai import errors, selftest
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.types import AIResult
from fantasy_king.config import PROJECT_ROOT

HOME_PAGE = str(PROJECT_ROOT / "app.py")
AI_PAGE = str(PROJECT_ROOT / "pages" / "1_AI_connection.py")


@pytest.fixture(autouse=True)
def known_settings(monkeypatch):
    """Use fixed settings, whatever the real .env on this computer says."""
    monkeypatch.setenv("LEAGUE_DATA_SOURCE", "sample")
    monkeypatch.setenv("AI_PROVIDER", "chatgpt")
    monkeypatch.setenv("CHATGPT_MODEL", "test-chatgpt-model")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")


def run(page: str) -> AppTest:
    app = AppTest.from_file(page, default_timeout=30).run()
    assert not app.exception, [problem.value for problem in app.exception]
    return app


def all_text(app: AppTest) -> str:
    kinds = (app.markdown, app.caption, app.info, app.success, app.warning, app.error)
    return "\n".join(str(element.value) for kind in kinds for element in kind)


def labels(app: AppTest) -> list[str]:
    return [button.label for button in app.button]


# --- The home page still works, and now reports the AI connection ---


def test_the_sample_league_still_shows_on_the_home_page():
    app = run(HOME_PAGE)
    assert app.title[0].value == "Fantasy King"
    assert [tab.label for tab in app.tabs] == ["My team", "Matchup", "League", "Free agents"]
    assert len(app.dataframe) >= 5
    assert "Fantasy data provided by Yahoo Fantasy" in all_text(app)


def test_the_home_page_sidebar_reports_the_ai_connection(store):
    assert "ChatGPT plan (not signed in yet)" in all_text(run(HOME_PAGE))
    save_account(store)
    assert "ChatGPT plan (signed in as fan@example.com)" in all_text(run(HOME_PAGE))


# --- The AI connection page ---


def test_signed_out_shows_the_sign_in_button_with_openais_wording():
    app = run(AI_PAGE)
    assert "Continue with ChatGPT" in labels(app)
    text = all_text(app)
    assert "Use your ChatGPT plan in this app" in text
    assert "In use now:** ChatGPT plan" in text
    assert "AI_PROVIDER=openrouter" in text  # how to switch is always on the page


def test_signed_in_shows_the_plan_indicator_and_account_options(store):
    save_account(store)
    app = run(AI_PAGE)
    text = all_text(app)
    assert "Signed in as fan@example.com" in text
    assert "Using ChatGPT plan" in text
    assert "Continue with ChatGPT" not in labels(app)
    assert {"Sign out", "Sign in with a different account"} <= set(labels(app))
    assert "access-0" not in text and "refresh-0" not in text


def test_the_welcome_notice_appears_once_after_the_first_sign_in(store):
    save_account(store, welcome_seen=False)
    first = run(AI_PAGE)
    assert "Eligible usage in this app uses your ChatGPT plan" in all_text(first)
    assert "Got it" in labels(first)

    second = run(AI_PAGE)
    assert "Got it" not in labels(second)


def test_signed_in_without_plan_approval_offers_to_approve_it(store):
    save_account(store, plan_usage_enabled=False)
    app = run(AI_PAGE)
    assert "plan usage wasn't approved" in all_text(app)
    assert "Continue with ChatGPT" in labels(app)


def test_an_unreadable_saved_sign_in_offers_a_reset(store):
    store.directory.mkdir(parents=True)
    store.path.write_bytes(b"damaged")
    app = run(AI_PAGE)
    assert "couldn't be read" in all_text(app)
    assert "Reset saved sign-in" in labels(app)

    app.button[labels(app).index("Reset saved sign-in")].click().run()
    assert not app.exception
    assert "Continue with ChatGPT" in labels(app)


def test_openrouter_shows_whether_a_key_is_set_but_never_the_key(monkeypatch):
    assert "**API key:** not set" in all_text(run(AI_PAGE))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    text = all_text(run(AI_PAGE))
    assert "**API key:** set" in text
    assert "test-key-not-real" not in text


# --- The test buttons, with the AI call replaced ---


def click_test(monkeypatch, name: str, outcome) -> AppTest:
    def fake_test(**options):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(selftest, f"{name}_test", fake_test)
    app = run(AI_PAGE)
    app.button(key="test_search" if name == "web_search" else f"test_{name}").click().run()
    assert not app.exception
    return app


def test_a_working_test_shows_the_answer(monkeypatch):
    result = AIResult("Fantasy King is connected.", "chatgpt", "test-chatgpt-model")
    text = all_text(click_test(monkeypatch, "plain", result))
    assert "It worked." in text
    assert "Fantasy King is connected." in text
    assert "Answered by ChatGPT plan, model test-chatgpt-model." in text


def test_the_web_search_test_says_when_search_was_not_used(monkeypatch):
    note = "Web search isn't available with this model or account, so this answer did not use it."
    result = AIResult("An answer.", "chatgpt", "test-chatgpt-model", notes=[note])
    assert note in all_text(click_test(monkeypatch, "web_search", result))


def test_the_web_search_test_lists_sources_when_search_was_used(monkeypatch):
    result = AIResult(
        "An answer.",
        "openrouter",
        "maker/model",
        web_search_used=True,
        web_searches=2,
        sources=[{"title": "NFL schedule", "url": "https://example.com/schedule"}],
    )
    text = all_text(click_test(monkeypatch, "web_search", result))
    assert "Web search was used (2 searches)." in text
    assert "[NFL schedule](https://example.com/schedule)" in text


def test_a_usage_limit_uses_openais_wording_and_says_how_to_switch(monkeypatch):
    problem = AIError(errors.USAGE_LIMIT, "Usage limit reached.", provider="chatgpt")
    app = click_test(monkeypatch, "plain", problem)
    text = all_text(app)
    assert "Usage limit reached" in text
    assert "Review your plan or this app's limit in ChatGPT settings." in text
    assert "AI_PROVIDER=openrouter" in text
    manage = [link.proto for link in app.get("link_button")]
    assert ("Manage usage", "https://chatgpt.com/settings/usage") in [
        (link.label, link.url) for link in manage
    ]


def test_any_other_failure_says_what_happened_what_to_do_and_how_to_switch(monkeypatch):
    problem = AIError(
        errors.SIGN_IN_EXPIRED,
        "Your ChatGPT sign-in has expired or was disconnected.",
        provider="chatgpt",
        how_to_fix="Open the AI connection page and click Continue with ChatGPT.",
    )
    text = all_text(click_test(monkeypatch, "image", problem))
    assert "Your ChatGPT sign-in has expired or was disconnected." in text
    assert "**What to do:**" in text
    assert "AI_PROVIDER=openrouter" in text


def test_the_tests_run_against_the_provider_picked_on_the_page(monkeypatch):
    used = []
    monkeypatch.setattr(
        selftest,
        "plain_test",
        lambda settings: used.append(settings.ai_provider) or AIResult("ok", "openrouter", "m"),
    )
    app = run(AI_PAGE)
    app.radio[0].set_value("openrouter").run()
    app.button(key="test_plain").click().run()
    assert used == ["openrouter"]
