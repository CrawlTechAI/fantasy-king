"""ChatGPT plan requests: the rules OpenAI sets, and how failures are reported."""

import httpx
import pytest
from helpers import CHATGPT_MODELS_URL, RESPONSES_URL, answer, api_error, save_account, sse

from fantasy_king.ai import chatgpt, chatgpt_auth, errors
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.selftest import make_test_image

MODEL = "test-chatgpt-model"


def ask(fake, store, waits=None, **options):
    record_wait = (lambda seconds: None) if waits is None else waits.append
    return chatgpt.ask(
        MODEL, "Be brief.", "Hello?", store=store, http_client=fake.http(), sleep=record_wait, **options
    )


# --- The shape of a request ---


def test_a_request_follows_the_plan_usage_rules():
    request = chatgpt.build_request(MODEL, "Be brief.", "Hello?")

    assert request == {
        "model": MODEL,
        "instructions": "Be brief.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hello?"}]}],
        "store": False,
        "stream": True,
    }
    assert not chatgpt.FORBIDDEN_FIELDS & request.keys()


def test_web_search_and_images_are_added_in_the_responses_api_format():
    image = make_test_image()
    request = chatgpt.build_request(MODEL, "", "What is this?", images=[image], web_search=True)

    assert request["tools"] == [{"type": "web_search"}]
    assert "instructions" not in request
    picture = request["input"][0]["content"][1]
    assert picture["type"] == "input_image"
    assert picture["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("field", sorted(chatgpt.FORBIDDEN_FIELDS))
def test_every_field_openai_prohibits_is_refused_before_sending(field):
    request = chatgpt.build_request(MODEL, "", "Hello?")
    with pytest.raises(ValueError, match=field):
        chatgpt.check_request({**request, field: 1})


def test_the_prohibited_list_matches_openais_docs():
    assert chatgpt.FORBIDDEN_FIELDS == {
        "background", "conversation", "max_output_tokens", "max_tool_calls", "metadata",
        "moderation", "multi_agent", "prompt", "prompt_cache_retention", "safety_identifier",
        "temperature", "top_logprobs", "top_p", "truncation", "user", "previous_response_id",
    }  # fmt: skip


@pytest.mark.parametrize(
    "change, complaint",
    [
        ({"store": True}, "store=False"),
        ({"stream": False}, "stream=True"),
        ({"input": "just a string"}, "list"),
        ({"input": [{"role": "system", "content": "rules"}]}, "instructions"),
    ],
)
def test_other_rule_breaks_are_refused_before_sending(change, complaint):
    request = chatgpt.build_request(MODEL, "", "Hello?")
    with pytest.raises(ValueError, match=complaint):
        chatgpt.check_request({**request, **change})


# --- Sending ---


def test_an_answer_is_streamed_from_the_responses_api_with_the_sign_in_token(fake, store):
    save_account(store)
    fake.ai_replies.append(answer("Fantasy King is connected."))

    result = ask(fake, store)

    assert result.text == "Fantasy King is connected."
    assert (result.provider, result.model, result.web_search_used) == ("chatgpt", MODEL, False)
    sent = fake.sent_to(RESPONSES_URL)[0]
    assert sent["method"] == "POST"
    assert sent["auth"] == "Bearer access-0"
    assert sent["body"]["store"] is False and sent["body"]["stream"] is True
    assert sent["body"]["instructions"] == "Be brief."


def test_web_sources_and_search_count_are_read_from_the_answer(fake, store):
    save_account(store)
    citation = {"type": "url_citation", "url": "https://example.com/news", "title": "Injury news"}
    output = [
        {"type": "web_search_call", "id": "ws_1", "status": "completed"},
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "He is out.", "annotations": [citation]}],
        },
    ]
    fake.ai_replies.append(answer("He is out.", output))

    result = ask(fake, store, web_search=True)

    assert fake.sent_to(RESPONSES_URL)[0]["body"]["tools"] == [{"type": "web_search"}]
    assert result.web_search_used and result.web_searches == 1
    assert result.sources == [{"title": "Injury news", "url": "https://example.com/news"}]


def test_an_answer_only_counts_once_openai_says_it_completed(fake, store):
    save_account(store)
    fake.ai_replies += [lambda: sse({"type": "response.output_text.delta", "delta": "Fan"})] * 3

    with pytest.raises(AIError, match="cut off"):
        ask(fake, store)


def test_no_model_chosen_is_explained_without_contacting_anyone(fake, store):
    save_account(store)
    with pytest.raises(AIError, match="No ChatGPT model") as raised:
        chatgpt.ask("", "", "Hello?", store=store, http_client=fake.http())
    assert raised.value.kind == errors.NOT_CONFIGURED
    assert fake.requests == []


def test_not_signed_in_is_explained_without_contacting_anyone(fake, store):
    with pytest.raises(AIError) as raised:
        ask(fake, store)
    assert raised.value.kind == errors.NOT_SIGNED_IN
    assert fake.requests == []


# --- Failures, using the codes on OpenAI's "Errors and recovery" page ---


@pytest.mark.parametrize(
    "status, code, kind",
    [
        (403, "subscription_sharing_user_not_eligible", errors.NOT_ELIGIBLE),
        (429, "subscription_sharing_usage_limit_exceeded", errors.USAGE_LIMIT),
        (400, "subscription_sharing_unsupported_capability", errors.UNSUPPORTED),
        (403, "subscription_sharing_route_not_supported", errors.UNKNOWN),
        (403, "chatpass_v2_scope_not_authorized", errors.PLAN_USAGE_OFF),
        (403, "chatpass_v2_invalid_authorization_context", errors.PLAN_USAGE_OFF),
        (403, None, errors.BLOCKED),
    ],
)
def test_permanent_failures_are_named_and_not_retried(fake, store, status, code, kind):
    save_account(store)
    fake.ai_replies.append(api_error(status, code))

    with pytest.raises(AIError) as raised:
        ask(fake, store)

    assert raised.value.kind == kind
    assert raised.value.code == code
    assert raised.value.request_id == "req_test_1"
    assert len(fake.sent_to(RESPONSES_URL)) == 1


def test_the_usage_limit_message_uses_openais_wording(fake, store):
    save_account(store)
    fake.ai_replies.append(api_error(429, "subscription_sharing_usage_limit_exceeded"))
    with pytest.raises(AIError) as raised:
        ask(fake, store)
    assert raised.value.message.startswith("Usage limit reached.")


def test_an_unsupported_capability_names_the_part_that_was_refused(fake, store):
    save_account(store)
    fake.ai_replies.append(
        api_error(400, "subscription_sharing_unsupported_capability", param="tools")
    )
    with pytest.raises(AIError, match="tools") as raised:
        ask(fake, store)
    assert raised.value.param == "tools"


def test_a_failure_reported_inside_the_stream_is_handled_too(fake, store):
    save_account(store)
    failed = {
        "type": "response.failed",
        "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded", "message": ""}},
    }
    fake.ai_replies.append(sse(failed))

    with pytest.raises(AIError) as raised:
        ask(fake, store)
    assert raised.value.kind == errors.USAGE_LIMIT


@pytest.mark.parametrize(
    "temporary",
    [
        lambda: api_error(503, "subscription_sharing_usage_unavailable"),
        lambda: api_error(503, "subscription_sharing_user_unavailable"),
        lambda: httpx.Response(503, json={"detail": "Direct routing is unavailable"}),
    ],
    ids=["usage unavailable", "user unavailable", "no error code"],
)
def test_temporary_failures_are_retried_with_a_short_bounded_wait(fake, store, temporary):
    save_account(store)
    fake.ai_replies += [temporary, temporary, answer("Back again.")]
    waits = []

    assert ask(fake, store, waits=waits).text == "Back again."
    assert waits == [1, 3]


def test_retries_stop_after_two_and_the_sign_in_is_kept(fake, store):
    save_account(store)
    fake.ai_replies += [lambda: api_error(503, "subscription_sharing_usage_unavailable")] * 3
    waits = []

    with pytest.raises(AIError) as raised:
        ask(fake, store, waits=waits)

    assert raised.value.kind == errors.UNAVAILABLE
    assert waits == [1, 3]
    assert chatgpt_auth.is_signed_in(chatgpt_auth.active_account(store.load()))


def test_no_internet_is_reported_as_a_network_problem(store):
    def offline(request):
        raise httpx.ConnectError("no internet")

    save_account(store)
    http = httpx.Client(transport=httpx.MockTransport(offline))
    with pytest.raises(AIError) as raised:
        chatgpt.ask(MODEL, "", "Hello?", store=store, http_client=http, sleep=lambda seconds: None)
    assert raised.value.kind == errors.NETWORK


# --- A refused sign-in token ---


def test_a_refused_token_is_refreshed_once_and_the_request_repeated(fake, store):
    save_account(store)
    fake.ai_replies += [api_error(401, "subscription_sharing_invalid_user"), answer("Hi.")]
    fake.token_replies.append(fake.tokens(2))

    assert ask(fake, store).text == "Hi."

    used = [request["auth"] for request in fake.sent_to(RESPONSES_URL)]
    assert used == ["Bearer access-0", "Bearer access-2"]
    assert len(fake.sent_to(chatgpt_auth.TOKEN_URL)) == 1


def test_a_token_refused_twice_asks_you_to_sign_in_again(fake, store):
    save_account(store)
    fake.ai_replies += [lambda: httpx.Response(401, json={"detail": "nope"})] * 2
    fake.token_replies.append(fake.tokens(2))

    with pytest.raises(AIError) as raised:
        ask(fake, store)

    assert raised.value.kind == errors.SIGN_IN_EXPIRED
    assert "Continue with ChatGPT" in raised.value.how_to_fix
    assert len(fake.sent_to(RESPONSES_URL)) == 2


def test_a_disconnected_app_is_noticed_when_the_refresh_fails(fake, store):
    save_account(store)
    fake.ai_replies.append(httpx.Response(401, json={"detail": "nope"}))
    fake.token_replies.append(httpx.Response(400, json={"error": "refresh_token_invalidated"}))

    with pytest.raises(AIError) as raised:
        ask(fake, store)

    assert raised.value.kind == errors.SIGN_IN_EXPIRED
    assert not chatgpt_auth.is_signed_in(chatgpt_auth.active_account(store.load()))


# --- The model list ---


def test_the_model_list_shows_only_models_meant_to_be_listed(fake, store):
    save_account(store)
    fake.models_reply = httpx.Response(
        200,
        json={
            "models": [
                {"slug": "model-a", "display_name": "Model A", "visibility": "list"},
                {"slug": "model-hidden", "display_name": "Hidden", "visibility": "hide"},
            ]
        },
    )

    assert chatgpt.list_models(store, fake.http()) == [{"id": "model-a", "name": "Model A"}]
    request = fake.sent_to(CHATGPT_MODELS_URL)[0]
    assert (request["method"], request["auth"]) == ("GET", "Bearer access-0")


def test_a_failed_model_list_is_explained(fake, store):
    save_account(store)
    fake.models_reply = api_error(403, "subscription_sharing_user_not_eligible")
    with pytest.raises(AIError) as raised:
        chatgpt.list_models(store, fake.http())
    assert raised.value.kind == errors.NOT_ELIGIBLE
