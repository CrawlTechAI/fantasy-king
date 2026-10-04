"""ask_ai(): one function, two providers, and no switching behind your back."""

import pytest
from helpers import (
    OPENROUTER_CHAT_URL,
    RESPONSES_URL,
    answer,
    api_error,
    chat_answer,
    make_settings,
    save_account,
)

from fantasy_king.ai import AIError, ask_ai, errors, selftest
from fantasy_king.ai.client import NO_WEB_SEARCH_NOTE, WEB_SEARCH_OFF_NOTE, provider_status
from fantasy_king.ai.errors import switch_instructions


def ask(fake, store, settings, **options):
    return ask_ai(
        "Be brief.",
        "Hello?",
        settings=settings,
        store=store,
        http_client=fake.http(),
        sleep=lambda seconds: None,
        **options,
    )


# --- Routing ---


def test_the_chatgpt_setting_sends_requests_only_to_chatgpt(fake, store):
    save_account(store)
    fake.ai_replies.append(answer("From ChatGPT."))

    result = ask(fake, store, make_settings(ai_provider="chatgpt"))

    assert (result.text, result.provider) == ("From ChatGPT.", "chatgpt")
    assert result.model == "test-chatgpt-model"
    assert {request["host"] for request in fake.requests} == {"api.openai.com"}


def test_the_openrouter_setting_sends_requests_only_to_openrouter(fake, store):
    fake.chat_replies.append(chat_answer("From OpenRouter."))

    result = ask(fake, store, make_settings(ai_provider="openrouter"))

    assert (result.text, result.provider) == ("From OpenRouter.", "openrouter")
    assert result.model == "test/openrouter-model"
    assert {request["host"] for request in fake.requests} == {"openrouter.ai"}


# --- No automatic fallback to the provider that costs money ---


@pytest.mark.parametrize(
    "failure",
    [
        lambda: api_error(429, "subscription_sharing_usage_limit_exceeded"),
        lambda: api_error(403, "subscription_sharing_user_not_eligible"),
        lambda: api_error(503, "subscription_sharing_usage_unavailable"),
    ],
    ids=["usage limit", "not eligible", "outage"],
)
def test_a_chatgpt_failure_never_falls_back_to_openrouter_by_itself(fake, store, failure):
    save_account(store)
    fake.ai_replies += [failure] * 3
    fake.chat_replies.append(chat_answer("This must never be requested."))

    with pytest.raises(AIError) as raised:
        ask(fake, store, make_settings(ai_provider="chatgpt"))

    assert raised.value.provider == "chatgpt"
    assert fake.sent_to(OPENROUTER_CHAT_URL) == []


def test_not_being_signed_in_never_falls_back_to_openrouter_either(fake, store):
    with pytest.raises(AIError) as raised:
        ask(fake, store, make_settings(ai_provider="chatgpt"))
    assert raised.value.kind == errors.NOT_SIGNED_IN
    assert fake.requests == []


def test_an_openrouter_failure_never_falls_back_to_chatgpt(fake, store):
    save_account(store)
    fake.chat_replies.append(api_error(402))

    with pytest.raises(AIError) as raised:
        ask(fake, store, make_settings(ai_provider="openrouter"))

    assert raised.value.kind == errors.NO_CREDITS
    assert fake.sent_to(RESPONSES_URL) == []


def test_every_failure_can_explain_how_to_switch_providers():
    to_openrouter = switch_instructions("chatgpt")
    assert "AI_PROVIDER=openrouter" in to_openrouter and "credits" in to_openrouter
    assert "AI_PROVIDER=chatgpt" in switch_instructions("openrouter")


# --- Web search, and doing without it ---


def test_chatgpt_answers_without_web_search_when_the_account_or_model_cannot_search(fake, store):
    save_account(store)
    fake.ai_replies += [
        api_error(400, "subscription_sharing_unsupported_capability", param="tools[0]"),
        answer("Answered from what I already know."),
    ]

    result = ask(fake, store, make_settings(), web_search=True)

    first, second = (request["body"] for request in fake.sent_to(RESPONSES_URL))
    assert first["tools"] == [{"type": "web_search"}]
    assert "tools" not in second
    assert result.text == "Answered from what I already know."
    assert result.web_search_used is False
    assert result.notes == [NO_WEB_SEARCH_NOTE]


def test_the_retry_only_happens_when_web_search_was_the_part_refused(fake, store):
    save_account(store)
    fake.ai_replies.append(
        api_error(400, "subscription_sharing_unsupported_capability", param="model")
    )

    with pytest.raises(AIError) as raised:
        ask(fake, store, make_settings(), web_search=True)

    assert raised.value.kind == errors.UNSUPPORTED
    assert len(fake.sent_to(RESPONSES_URL)) == 1


def test_an_unsupported_request_without_web_search_is_not_retried(fake, store):
    save_account(store)
    fake.ai_replies.append(api_error(400, "subscription_sharing_unsupported_capability"))
    with pytest.raises(AIError):
        ask(fake, store, make_settings())
    assert len(fake.sent_to(RESPONSES_URL)) == 1


def test_openrouter_answers_without_web_search_when_the_model_cannot_use_tools(fake, store):
    fake.chat_replies += [
        api_error(404, message="No endpoints found that support tool use"),
        chat_answer("Answered without searching."),
    ]

    result = ask(fake, store, make_settings(ai_provider="openrouter"), web_search=True)

    first, second = (request["body"] for request in fake.sent_to(OPENROUTER_CHAT_URL))
    assert first["tools"][0]["type"] == "openrouter:web_search"
    assert "tools" not in second and "max_tool_calls" not in second
    assert result.notes == [NO_WEB_SEARCH_NOTE]


def test_web_search_turned_off_in_settings_is_never_sent(fake, store):
    save_account(store)
    fake.ai_replies.append(answer("No search."))

    result = ask(fake, store, make_settings(web_search_enabled=False), web_search=True)

    assert "tools" not in fake.sent_to(RESPONSES_URL)[0]["body"]
    assert result.notes == [WEB_SEARCH_OFF_NOTE]


def test_the_search_limit_from_settings_reaches_openrouter(fake, store):
    fake.chat_replies.append(chat_answer("Searched.", searches=1))
    settings = make_settings(ai_provider="openrouter", max_web_searches_per_run=2)

    ask(fake, store, settings, web_search=True)

    body = fake.sent_to(OPENROUTER_CHAT_URL)[0]["body"]
    assert body["max_tool_calls"] == 2  # the overall budget, whichever search engine runs
    assert body["tools"][0]["parameters"]["max_uses"] == 2


@pytest.mark.parametrize("provider", ["chatgpt", "openrouter"])
def test_a_search_limit_of_zero_means_no_web_search_at_all(fake, store, provider):
    save_account(store)
    fake.ai_replies.append(answer("No search."))
    fake.chat_replies.append(chat_answer("No search."))
    settings = make_settings(ai_provider=provider, max_web_searches_per_run=0)

    result = ask(fake, store, settings, web_search=True)

    body = fake.requests[-1]["body"]
    assert "tools" not in body and "max_tool_calls" not in body
    assert result.notes == [WEB_SEARCH_OFF_NOTE]


# --- The three connection tests on the AI connection page ---


def test_the_connection_tests_send_what_they_say(fake, store):
    save_account(store)
    fake.ai_replies += [answer(selftest.EXPECTED_REPLY), answer("Two teams."), answer("KING 42")]
    options = {"settings": make_settings(), "store": store, "http_client": fake.http()}

    assert selftest.plain_test(**options).text == selftest.EXPECTED_REPLY
    selftest.web_search_test(**options)
    selftest.image_test(**options)

    plain, search, image = (request["body"] for request in fake.sent_to(RESPONSES_URL))
    assert "tools" not in plain
    assert search["tools"] == [{"type": "web_search"}]
    assert image["input"][0]["content"][1]["type"] == "input_image"


# --- The one-line status in the dashboard sidebar ---


def test_the_status_line_describes_the_connection_without_any_network_call(store):
    assert provider_status(make_settings(), store) == "not signed in yet"
    save_account(store)
    assert provider_status(make_settings(), store) == "signed in as fan@example.com"
    assert provider_status(make_settings(chatgpt_model=""), store).endswith("no model chosen yet")

    openrouter = make_settings(ai_provider="openrouter")
    no_key = make_settings(ai_provider="openrouter", openrouter_api_key="")
    assert provider_status(openrouter, store) == "test/openrouter-model"
    assert provider_status(no_key, store) == "no API key yet"
