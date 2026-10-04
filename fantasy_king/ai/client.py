"""ask_ai(): the one function the rest of the app uses to talk to an AI.

AI_PROVIDER in .env decides who answers. If that provider fails, the error
explains what happened and how to switch. The app never switches to the other
provider by itself, because OpenRouter costs money per request.
"""

from fantasy_king.ai import chatgpt, chatgpt_auth, errors, openrouter
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.token_store import TokenStore
from fantasy_king.ai.types import AIResult
from fantasy_king.config import Settings, load_settings

NO_WEB_SEARCH_NOTE = (
    "Web search isn't available with this model or account, so this answer did not use it."
)
WEB_SEARCH_OFF_NOTE = (
    "Web search is turned off in .env (WEB_SEARCH_ENABLED=false or MAX_WEB_SEARCHES_PER_RUN=0)."
)


def _ask_provider(settings: Settings, instructions, content, images, web_search, deps) -> AIResult:
    if settings.ai_provider == "chatgpt":
        return chatgpt.ask(
            settings.chatgpt_model,
            instructions,
            content,
            images=images,
            web_search=web_search,
            **deps,
        )
    deps = {name: value for name, value in deps.items() if name != "store"}
    return openrouter.ask(
        settings.openrouter_model,
        settings.openrouter_api_key,
        instructions,
        content,
        images=images,
        web_search=web_search,
        max_searches=settings.max_web_searches_per_run,
        **deps,
    )


def _web_search_was_the_problem(problem: AIError) -> bool:
    if problem.kind != errors.UNSUPPORTED:
        return False
    # ChatGPT names the part it refused. Only retry if that part is the search tool.
    return not problem.param or "tool" in problem.param or "web_search" in problem.param


def ask_ai(
    instructions: str,
    content: str,
    *,
    images: list[bytes] | tuple = (),
    web_search: bool = False,
    settings: Settings | None = None,
    **deps,
) -> AIResult:
    """Ask the configured AI provider and return its answer.

    instructions: how the AI should behave (its role and rules).
    content:      the question or data for this request.
    images:       PNG, JPEG, GIF, or WebP files as bytes, such as screenshots.
    web_search:   let the AI search the web. If the model or account can't,
                  the answer comes back without it and says so in notes.

    Raises AIError with a plain-language message when the call can't be made.
    """
    settings = settings or load_settings()
    notes = []
    allowed = settings.web_search_enabled and settings.max_web_searches_per_run > 0
    if web_search and not allowed:
        web_search = False
        notes.append(WEB_SEARCH_OFF_NOTE)
    try:
        result = _ask_provider(settings, instructions, content, images, web_search, deps)
    except AIError as problem:
        if not (web_search and _web_search_was_the_problem(problem)):
            raise
        result = _ask_provider(settings, instructions, content, images, False, deps)
        notes.append(NO_WEB_SEARCH_NOTE)
    result.notes = notes + result.notes
    return result


def provider_status(settings: Settings, store: TokenStore | None = None) -> str:
    """One line describing the AI connection, for the dashboard. Makes no network calls."""
    if settings.ai_provider == "openrouter":
        if not settings.openrouter_api_key:
            return "no API key yet"
        return settings.openrouter_model or "no model chosen yet"
    try:
        account = chatgpt_auth.active_account(chatgpt_auth.load_state(store or TokenStore()))
    except AIError:
        return "saved sign-in can't be read"
    status = chatgpt_auth.describe(account)
    if chatgpt_auth.is_signed_in(account) and not settings.chatgpt_model:
        status += ", no model chosen yet"
    return status
