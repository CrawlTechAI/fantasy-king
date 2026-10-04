"""AI calls paid for by your ChatGPT plan.

Requests go to OpenAI's Responses API with the access token from Sign in with
ChatGPT. Plan usage has stricter rules than a paid API key; they come from
https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
(read 2026-10-01) and are enforced by check_request() below.
"""

import time

import httpx
import openai

from fantasy_king.ai import chatgpt_auth, errors
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.token_store import TokenStore
from fantasy_king.ai.types import AIResult, image_data_url

BASE_URL = "https://api.openai.com/v1"
MODELS_URL = f"{BASE_URL}/models"
REQUEST_TIMEOUT_SECONDS = 180

# Plan usage rejects a request that contains any of these.
FORBIDDEN_FIELDS = frozenset(
    {
        "background",
        "conversation",
        "max_output_tokens",
        "max_tool_calls",
        "metadata",
        "moderation",
        "multi_agent",
        "prompt",
        "prompt_cache_retention",
        "safety_identifier",
        "temperature",
        "top_logprobs",
        "top_p",
        "truncation",
        "user",
        # Not allowed over HTTP: each request must carry its own history in "input".
        "previous_response_id",
    }
)

# Waits between tries when ChatGPT says the problem is temporary.
RETRY_WAITS = (1, 3)


def check_request(request: dict) -> None:
    """Refuse to send a request that breaks the plan-usage rules.

    Catching it here gives a clear message while developing, instead of a
    confusing rejection from ChatGPT later.
    """
    forbidden = FORBIDDEN_FIELDS & request.keys()
    if forbidden:
        raise ValueError(f"ChatGPT plan usage doesn't allow: {', '.join(sorted(forbidden))}")
    if request.get("store") is not False or request.get("stream") is not True:
        raise ValueError("ChatGPT plan usage requires store=False and stream=True")
    if not isinstance(request.get("input"), list):
        raise ValueError('ChatGPT plan usage requires "input" to be a list')
    if any(item.get("role") == "system" for item in request["input"]):
        raise ValueError('Use "instructions" instead of a system message')


def build_request(
    model: str,
    instructions: str,
    content: str,
    images: list[bytes] | tuple = (),
    web_search: bool = False,
) -> dict:
    parts = [{"type": "input_text", "text": content}]
    parts += [{"type": "input_image", "image_url": image_data_url(image)} for image in images]
    request = {
        "model": model,
        "input": [{"role": "user", "content": parts}],
        "store": False,
        "stream": True,
    }
    if instructions:
        request["instructions"] = instructions
    if web_search:
        # No limit on the number of searches can be sent: plan usage prohibits
        # max_tool_calls. MAX_WEB_SEARCHES_PER_RUN only switches search off (0) here.
        request["tools"] = [{"type": "web_search"}]
    check_request(request)
    return request


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(warnings=False)
    return {}


def _error_from_status(problem: openai.APIStatusError) -> AIError:
    body = _as_dict(problem.body)
    # The body is either {"code": ..., "message": ...} or, before a request
    # really starts, something looser such as {"detail": "..."}.
    body = _as_dict(body.get("error")) or body
    detail = body.get("message") or body.get("detail") or ""
    return errors.chatgpt_error(
        status=problem.status_code,
        code=body.get("code"),
        detail=detail if isinstance(detail, str) else "",
        param=body.get("param"),
        request_id=problem.request_id,
    )


def _read_answer(response: dict) -> tuple[list[dict], int]:
    """Web sources cited in the answer, and how many searches were run."""
    sources, searches = [], 0
    for item in response.get("output") or []:
        if item.get("type") == "web_search_call":
            searches += 1
        for part in item.get("content") or []:
            for note in part.get("annotations") or []:
                source = {"title": note.get("title") or note.get("url"), "url": note.get("url")}
                if note.get("type") == "url_citation" and source not in sources:
                    sources.append(source)
    return sources, searches


def send(request: dict, access_token: str, http_client: httpx.Client | None = None) -> AIResult:
    """Send one request and collect the streamed answer."""
    check_request(request)
    client = openai.OpenAI(
        api_key=access_token,
        base_url=BASE_URL,
        max_retries=0,  # retries are handled in ask(), with the rules from OpenAI's docs
        timeout=REQUEST_TIMEOUT_SECONDS,
        http_client=http_client,
    )
    text, completed = [], None
    try:
        with client.responses.create(**request) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    text.append(event.delta)
                elif event.type == "response.failed":
                    failure = _as_dict(_as_dict(event.response).get("error"))
                    raise errors.chatgpt_error(
                        code=failure.get("code"), detail=failure.get("message") or ""
                    )
                elif event.type == "response.incomplete":
                    raise AIError(
                        errors.UNKNOWN,
                        "ChatGPT stopped before finishing its answer.",
                        provider="chatgpt",
                        how_to_fix="Try again.",
                        retryable=True,
                    )
                elif event.type == "response.completed":
                    completed = _as_dict(event.response)
    except openai.APIStatusError as problem:
        raise _error_from_status(problem) from problem
    except openai.APIConnectionError as problem:  # includes timeouts
        raise AIError(
            errors.NETWORK,
            "Couldn't reach ChatGPT.",
            provider="chatgpt",
            how_to_fix="Check your internet connection and try again.",
            retryable=True,
        ) from problem
    except openai.APIError as problem:  # an error reported in the middle of the stream
        failure = _as_dict(problem.body)
        raise errors.chatgpt_error(
            code=failure.get("code"), detail=failure.get("message") or str(problem)
        ) from problem

    # The docs say an answer only counts once "response.completed" has arrived.
    if completed is None:
        raise AIError(
            errors.UNKNOWN,
            "ChatGPT's answer was cut off before it finished.",
            provider="chatgpt",
            how_to_fix="Try again.",
            retryable=True,
        )
    sources, searches = _read_answer(completed)
    return AIResult(
        text="".join(text),
        provider="chatgpt",
        model=request["model"],
        web_search_used=searches > 0 or bool(sources),
        web_searches=searches,
        sources=sources,
    )


def ask(
    model: str,
    instructions: str,
    content: str,
    *,
    images: list[bytes] | tuple = (),
    web_search: bool = False,
    store: TokenStore | None = None,
    http_client: httpx.Client | None = None,
    sleep=time.sleep,
) -> AIResult:
    """Ask ChatGPT, signing in with the saved account and refreshing it if needed."""
    if not model:
        raise AIError(
            errors.NOT_CONFIGURED,
            "No ChatGPT model has been chosen yet.",
            provider="chatgpt",
            how_to_fix="Open the AI connection page, load the model list, and save one.",
        )
    store = store or TokenStore()
    request = build_request(model, instructions, content, images, web_search)
    refreshed = False
    waits = list(RETRY_WAITS)
    with chatgpt_auth.open_http(http_client) as auth_http:
        token = chatgpt_auth.get_access_token(store, auth_http)
        while True:
            try:
                return send(request, token, http_client)
            except AIError as problem:
                # A refused token may just be stale: refresh once, then give up.
                if problem.kind == errors.SIGN_IN_EXPIRED and not refreshed:
                    refreshed = True
                    token = chatgpt_auth.get_access_token(store, auth_http, rejected_token=token)
                elif problem.retryable and waits:
                    sleep(waits.pop(0))
                else:
                    raise


def list_models(
    store: TokenStore | None = None, http_client: httpx.Client | None = None
) -> list[dict]:
    """The models your ChatGPT account may use: [{"id": ..., "name": ...}]."""
    with chatgpt_auth.open_http(http_client) as http:
        token = chatgpt_auth.get_access_token(store or TokenStore(), http)
        try:
            response = http.get(MODELS_URL, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as problem:
            raise AIError(
                errors.NETWORK,
                "Couldn't reach ChatGPT.",
                provider="chatgpt",
                how_to_fix="Check your internet connection and try again.",
                retryable=True,
            ) from problem
    if response.status_code != 200:
        try:
            body = _as_dict(response.json())
        except ValueError:
            body = {}
        body = _as_dict(body.get("error")) or body
        raise errors.chatgpt_error(status=response.status_code, code=body.get("code"))
    return [
        {"id": model["slug"], "name": model.get("display_name") or model["slug"]}
        for model in response.json().get("models", [])
        if model.get("visibility") == "list"
    ]
