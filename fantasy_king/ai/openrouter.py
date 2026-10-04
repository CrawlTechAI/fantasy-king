"""AI calls through OpenRouter, the backup provider. Each call costs OpenRouter credits.

Uses the OpenAI Python library pointed at OpenRouter. Web search uses
OpenRouter's "openrouter:web_search" server tool, described at
https://openrouter.ai/docs/guides/features/server-tools/web-search (read
2026-10-01). The older ":online" model suffix and "web" plugin are deprecated
and are not used.

How the number of searches is limited, and where that limit is weaker:

  max_tool_calls  A top-level request field. Each search uses one step of the
                  request's server-tool budget, and this field bounds that
                  budget. It is the limit that applies whichever search engine
                  runs. OpenRouter allows at most 30 (also its default).
  max_uses        A setting on the search tool itself. OpenRouter enforces it
                  for the engines it runs (Exa, Firecrawl, Parallel,
                  Perplexity). With a provider's own "native" search it is
                  passed on only to Anthropic; other native providers ignore it.
  max_results     Results per search. Ignored with native search.

The default engine, "auto", uses native search when the model's provider has
it. So for those models max_uses and max_results may do nothing, and
max_tool_calls is the limit that counts. OpenRouter's page does not say how a
native provider's own searches are counted against that budget, so treat the
limit as a firm cap for OpenRouter-run engines and a best effort for native
search. The number of searches actually billed is reported back in
usage.server_tool_use.web_search_requests and shown in AIResult.web_searches.
"""

import time

import httpx
import openai

from fantasy_king.ai import errors
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.types import AIResult, image_data_url

BASE_URL = "https://openrouter.ai/api/v1"
MODELS_URL = f"{BASE_URL}/models"
WEB_SEARCH_TOOL = "openrouter:web_search"
RESULTS_PER_SEARCH = 5
MAX_TOOL_CALLS_LIMIT = 30  # the most OpenRouter accepts for max_tool_calls
REQUEST_TIMEOUT_SECONDS = 180
RETRY_WAITS = (1, 3)

# Request fields OpenRouter understands but the OpenAI library has no argument for.
# send() passes these through the library's extra_body, which adds them to the request.
OPENROUTER_ONLY_FIELDS = ("max_tool_calls",)


def build_request(
    model: str,
    instructions: str,
    content: str,
    images: list[bytes] | tuple = (),
    web_search: bool = False,
    max_searches: int = 5,
) -> dict:
    """The request exactly as OpenRouter should receive it."""
    messages = [{"role": "system", "content": instructions}] if instructions else []
    if images:
        parts = [{"type": "text", "text": content}]
        parts += [{"type": "image_url", "image_url": {"url": image_data_url(i)}} for i in images]
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": content})
    request = {"model": model, "messages": messages}
    if web_search:
        limit = min(max(max_searches, 1), MAX_TOOL_CALLS_LIMIT)
        request["tools"] = [
            {
                "type": WEB_SEARCH_TOOL,
                # Honored by OpenRouter-run engines; mostly ignored by native search.
                "parameters": {"max_uses": limit, "max_results": RESULTS_PER_SEARCH},
            }
        ]
        # The overall budget, beside "tools" rather than inside the tool. See the top of this file.
        request["max_tool_calls"] = limit
    return request


def _error_from_body(error: dict, tool_sent: bool) -> AIError:
    code = error.get("code")
    return errors.openrouter_error(
        status=code if isinstance(code, int) else None,
        detail=str(error.get("message") or ""),
        tool_sent=tool_sent,
    )


def _read_sources(message: dict) -> list[dict]:
    sources = []
    for note in message.get("annotations") or []:
        citation = note.get("url_citation") or {}
        source = {"title": citation.get("title") or citation.get("url"), "url": citation.get("url")}
        if note.get("type") == "url_citation" and source["url"] and source not in sources:
            sources.append(source)
    return sources


def send(request: dict, api_key: str, http_client: httpx.Client | None = None) -> AIResult:
    client = openai.OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        max_retries=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
        http_client=http_client,
    )
    tool_sent = "tools" in request
    extra = {name: request[name] for name in OPENROUTER_ONLY_FIELDS if name in request}
    standard = {name: value for name, value in request.items() if name not in extra}
    try:
        completion = client.chat.completions.create(**standard, extra_body=extra or None)
        completion = completion.model_dump(warnings=False)
    except openai.APIStatusError as problem:
        body = problem.body if isinstance(problem.body, dict) else {}
        raise errors.openrouter_error(
            status=problem.status_code, detail=str(body.get("message") or ""), tool_sent=tool_sent
        ) from problem
    except openai.APIConnectionError as problem:  # includes timeouts
        raise AIError(
            errors.NETWORK,
            "Couldn't reach OpenRouter.",
            provider="openrouter",
            how_to_fix="Check your internet connection and try again.",
            retryable=True,
        ) from problem

    # OpenRouter can answer "200 OK" and still put an error in the body.
    choice = (completion.get("choices") or [{}])[0]
    failure = completion.get("error") or choice.get("error")
    if failure:
        raise _error_from_body(failure, tool_sent)
    message = choice.get("message") or {}
    if not message.get("content"):
        raise AIError(
            errors.UNKNOWN,
            "OpenRouter returned an empty answer.",
            provider="openrouter",
            how_to_fix="Try again, or pick a different model on the AI connection page.",
            retryable=True,
        )
    sources = _read_sources(message)
    usage = completion.get("usage") or {}
    searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
    return AIResult(
        text=message["content"],
        provider="openrouter",
        model=request["model"],
        web_search_used=searches > 0 or bool(sources),
        web_searches=searches,
        sources=sources,
    )


def ask(
    model: str,
    api_key: str,
    instructions: str,
    content: str,
    *,
    images: list[bytes] | tuple = (),
    web_search: bool = False,
    max_searches: int = 5,
    http_client: httpx.Client | None = None,
    sleep=time.sleep,
) -> AIResult:
    if not api_key:
        raise AIError(
            errors.NOT_CONFIGURED,
            "No OpenRouter API key is set.",
            provider="openrouter",
            how_to_fix="Create a key at openrouter.ai/keys and put it after "
            "OPENROUTER_API_KEY= in your .env file.",
        )
    if not model:
        raise AIError(
            errors.NOT_CONFIGURED,
            "No OpenRouter model has been chosen yet.",
            provider="openrouter",
            how_to_fix="Open the AI connection page, load the model list, and save one.",
        )
    if model.endswith(":online"):
        raise AIError(
            errors.NOT_CONFIGURED,
            'OPENROUTER_MODEL ends in ":online", which OpenRouter has deprecated.',
            provider="openrouter",
            how_to_fix='Remove ":online" from OPENROUTER_MODEL in your .env file. '
            "The app turns web search on by itself when it needs it.",
        )
    request = build_request(model, instructions, content, images, web_search, max_searches)
    waits = list(RETRY_WAITS)
    while True:
        try:
            return send(request, api_key, http_client)
        except AIError as problem:
            if not (problem.retryable and waits):
                raise
            sleep(waits.pop(0))


def _price(model: dict) -> str:
    """The model's price per million tokens, or "" if the catalog doesn't give one."""
    pricing = model.get("pricing") or {}
    try:
        question = float(pricing["prompt"]) * 1_000_000
        reply = float(pricing["completion"]) * 1_000_000
    except (KeyError, TypeError, ValueError):
        return ""
    return f"${question:.2f} in / ${reply:.2f} out per million tokens"


def list_models(http_client: httpx.Client | None = None) -> list[dict]:
    """OpenRouter's current models. Public information: no key is needed or sent.

    Returns [{"id": ..., "name": ..., "tools": bool, "images": bool, "price": str}].
    Batch variants are left out: they are for bulk jobs, not for live requests.
    """
    try:
        if http_client is not None:
            response = http_client.get(MODELS_URL)
        else:
            response = httpx.get(MODELS_URL, timeout=30)
        response.raise_for_status()
        catalog = response.json().get("data", [])
    except (httpx.HTTPError, ValueError) as problem:
        raise AIError(
            errors.NETWORK,
            "Couldn't download OpenRouter's model list.",
            provider="openrouter",
            how_to_fix="Check your internet connection and try again.",
            retryable=True,
        ) from problem
    return [
        {
            "id": model["id"],
            "name": model.get("name") or model["id"],
            "tools": "tools" in (model.get("supported_parameters") or []),
            "images": "image" in ((model.get("architecture") or {}).get("input_modalities") or []),
            "price": _price(model),
        }
        for model in catalog
        if not model["id"].endswith(":batch")
    ]
