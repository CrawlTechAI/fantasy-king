"""The OpenRouter backup provider, checked against a fake OpenRouter."""

import httpx
import openai
import pytest
from helpers import OPENROUTER_CHAT_URL, OPENROUTER_MODELS_URL, chat_answer

from fantasy_king.ai import errors, openrouter
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.selftest import make_test_image

MODEL = "test/openrouter-model"
KEY = "test-key-not-real"


def ask(fake, waits=None, **options):
    record_wait = (lambda seconds: None) if waits is None else waits.append
    return openrouter.ask(
        MODEL, KEY, "Be brief.", "Hello?", http_client=fake.http(), sleep=record_wait, **options
    )


def failure(status: int, message: str = "details from OpenRouter") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message}})


# --- The shape of a request ---


def test_a_plain_request_is_an_ordinary_chat_completion():
    assert openrouter.build_request(MODEL, "Be brief.", "Hello?") == {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hello?"},
        ],
    }


def test_web_search_uses_the_server_tool_with_two_limits_on_searches():
    request = openrouter.build_request(MODEL, "", "News?", web_search=True, max_searches=3)

    assert request["tools"] == [
        {"type": "openrouter:web_search", "parameters": {"max_uses": 3, "max_results": 5}}
    ]
    # The overall server-tool budget sits beside "tools", not inside the tool.
    assert request["max_tool_calls"] == 3
    assert "max_tool_calls" not in request["tools"][0]["parameters"]
    # The deprecated ways of turning search on are never used.
    assert not request["model"].endswith(":online")
    assert "plugins" not in request


def test_a_request_without_web_search_sets_no_tool_budget():
    assert "max_tool_calls" not in openrouter.build_request(MODEL, "", "Hello?")


@pytest.mark.parametrize("asked, sent", [(1, 1), (5, 5), (30, 30), (500, 30), (0, 1)])
def test_the_search_limit_stays_within_what_openrouter_accepts(asked, sent):
    request = openrouter.build_request(MODEL, "", "News?", web_search=True, max_searches=asked)
    assert request["max_tool_calls"] == sent
    assert request["tools"][0]["parameters"]["max_uses"] == sent


def test_images_are_sent_as_image_url_parts():
    request = openrouter.build_request(MODEL, "", "What is this?", images=[make_test_image()])
    text, picture = request["messages"][0]["content"]
    assert text == {"type": "text", "text": "What is this?"}
    assert picture["image_url"]["url"].startswith("data:image/png;base64,")


# --- Sending ---


def test_requests_go_to_openrouter_through_the_openai_library_with_your_key(fake):
    fake.chat_replies.append(chat_answer("Fantasy King is connected."))

    result = ask(fake)

    assert result.text == "Fantasy King is connected."
    assert (result.provider, result.model, result.web_search_used) == ("openrouter", MODEL, False)
    sent = fake.sent_to(OPENROUTER_CHAT_URL)[0]
    assert sent["method"] == "POST"
    assert sent["auth"] == f"Bearer {KEY}"
    assert sent["body"]["model"] == MODEL
    assert "tools" not in sent["body"]


def test_web_search_results_are_read_from_citations_and_usage(fake):
    citation = {
        "type": "url_citation",
        "url_citation": {"url": "https://example.com/news", "title": "Injury news"},
    }
    fake.chat_replies.append(chat_answer("He is out.", [citation], searches=2))

    result = ask(fake, web_search=True, max_searches=4)

    tool = fake.sent_to(OPENROUTER_CHAT_URL)[0]["body"]["tools"][0]
    assert tool == {"type": "openrouter:web_search", "parameters": {"max_uses": 4, "max_results": 5}}
    assert result.web_search_used and result.web_searches == 2
    assert result.sources == [{"title": "Injury news", "url": "https://example.com/news"}]


def test_the_tool_budget_reaches_openrouter_as_a_top_level_field(fake):
    """What OpenRouter actually receives over HTTP, after the OpenAI library builds it."""
    fake.chat_replies.append(chat_answer("Searched.", searches=1))

    ask(fake, web_search=True, max_searches=4)

    body = fake.sent_to(OPENROUTER_CHAT_URL)[0]["body"]
    assert body["max_tool_calls"] == 4  # a sibling of "messages" and "tools"
    assert set(body) == {"model", "messages", "tools", "max_tool_calls"}
    assert "extra_body" not in body  # extra_body is the library's way in, not a field
    assert body["tools"][0]["parameters"] == {"max_uses": 4, "max_results": 5}


def test_the_openai_library_has_no_argument_for_the_budget_so_extra_body_is_required(fake):
    """Guards the reason send() uses extra_body: passing it directly is a programming error."""
    client = openai.OpenAI(api_key=KEY, base_url=openrouter.BASE_URL, http_client=fake.http())
    request = openrouter.build_request(MODEL, "", "News?", web_search=True)
    with pytest.raises(TypeError, match="max_tool_calls"):
        client.chat.completions.create(**request)
    assert fake.requests == []


def test_a_plain_request_sends_no_tool_budget(fake):
    fake.chat_replies.append(chat_answer("Hello."))
    ask(fake)
    assert set(fake.sent_to(OPENROUTER_CHAT_URL)[0]["body"]) == {"model", "messages"}


# --- Settings problems, caught before anything is sent ---


@pytest.mark.parametrize(
    "model, key, complaint",
    [
        (MODEL, "", "No OpenRouter API key"),
        ("", KEY, "No OpenRouter model"),
        ("openai/some-model:online", KEY, "deprecated"),
    ],
)
def test_settings_problems_are_explained_without_contacting_anyone(fake, model, key, complaint):
    with pytest.raises(AIError, match=complaint) as raised:
        openrouter.ask(model, key, "", "Hello?", http_client=fake.http())
    assert raised.value.kind == errors.NOT_CONFIGURED
    assert raised.value.how_to_fix
    assert fake.requests == []


# --- Failures, using the statuses on OpenRouter's errors page ---


@pytest.mark.parametrize(
    "status, kind",
    [
        (401, errors.BAD_KEY),
        (402, errors.NO_CREDITS),
        (403, errors.BLOCKED),
        (404, errors.MODEL_PROBLEM),
    ],
)
def test_permanent_failures_are_named_and_not_retried(fake, status, kind):
    fake.chat_replies.append(failure(status))

    with pytest.raises(AIError) as raised:
        ask(fake)

    assert raised.value.kind == kind
    assert raised.value.provider == "openrouter"
    assert len(fake.sent_to(OPENROUTER_CHAT_URL)) == 1


def test_an_error_message_never_contains_the_api_key(fake):
    fake.chat_replies.append(failure(401))
    with pytest.raises(AIError) as raised:
        ask(fake)
    assert KEY not in raised.value.message + raised.value.how_to_fix


@pytest.mark.parametrize("status", [408, 429, 502, 503])
def test_temporary_failures_are_retried_with_a_short_bounded_wait(fake, status):
    fake.chat_replies += [lambda: failure(status), lambda: failure(status), chat_answer("Back.")]
    waits = []

    assert ask(fake, waits=waits).text == "Back."
    assert waits == [1, 3]


def test_retries_stop_after_two(fake):
    fake.chat_replies += [lambda: failure(429)] * 3
    with pytest.raises(AIError) as raised:
        ask(fake)
    assert raised.value.kind == errors.RATE_LIMITED
    assert len(fake.sent_to(OPENROUTER_CHAT_URL)) == 3


def test_an_error_hidden_inside_a_200_reply_is_still_caught(fake):
    fake.chat_replies.append(
        httpx.Response(200, json={"error": {"code": 402, "message": "Insufficient credits"}})
    )
    with pytest.raises(AIError) as raised:
        ask(fake)
    assert raised.value.kind == errors.NO_CREDITS


def test_a_model_that_cannot_use_tools_is_reported_as_unsupported(fake):
    fake.chat_replies.append(failure(404, "No endpoints found that support tool use"))
    with pytest.raises(AIError) as raised:
        ask(fake, web_search=True)
    assert raised.value.kind == errors.UNSUPPORTED


def test_an_empty_answer_is_an_error_not_a_blank_result(fake):
    fake.chat_replies += [lambda: chat_answer("")] * 3
    with pytest.raises(AIError, match="empty answer"):
        ask(fake)


# --- The model list ---


def test_the_model_list_is_public_and_says_what_each_model_can_do(fake):
    fake.catalog_reply = httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "maker/model-a",
                    "name": "Model A",
                    "supported_parameters": ["tools", "temperature"],
                    "architecture": {"input_modalities": ["text", "image"]},
                    "pricing": {"prompt": "0.00000025", "completion": "0.000002"},
                },
                {"id": "maker/model-b", "supported_parameters": []},
                {"id": "maker/model-a:batch", "supported_parameters": ["tools"]},
            ]
        },
    )

    assert openrouter.list_models(fake.http()) == [
        {
            "id": "maker/model-a",
            "name": "Model A",
            "tools": True,
            "images": True,
            "price": "$0.25 in / $2.00 out per million tokens",
        },
        {"id": "maker/model-b", "name": "maker/model-b", "tools": False, "images": False, "price": ""},
    ]  # the ":batch" variant is left out
    assert fake.sent_to(OPENROUTER_MODELS_URL)[0]["auth"] is None  # no key is sent
