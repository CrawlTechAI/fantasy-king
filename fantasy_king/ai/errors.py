"""AI failures, turned into messages a person can act on.

Every failure from either provider becomes an AIError. Its message says what
happened, how_to_fix says what to do, and switch_instructions() says how to
use the other provider. Nothing here ever switches providers on its own.
"""

# The page OpenAI's UI guidelines name as the destination for "Manage usage".
MANAGE_USAGE_URL = "https://chatgpt.com/settings/usage"

PROVIDER_LABELS = {"chatgpt": "ChatGPT plan", "openrouter": "OpenRouter"}

# What went wrong, in broad terms. The dashboard uses these to pick a layout.
NOT_SIGNED_IN = "not_signed_in"
SIGN_IN_EXPIRED = "sign_in_expired"
SIGN_IN_FAILED = "sign_in_failed"
PLAN_USAGE_OFF = "plan_usage_off"
NOT_ELIGIBLE = "not_eligible"
USAGE_LIMIT = "usage_limit"
UNAVAILABLE = "unavailable"
UNSUPPORTED = "unsupported"
BLOCKED = "blocked"
NOT_CONFIGURED = "not_configured"
BAD_KEY = "bad_key"
NO_CREDITS = "no_credits"
RATE_LIMITED = "rate_limited"
MODEL_PROBLEM = "model_problem"
NETWORK = "network"
STORAGE = "storage"
UNKNOWN = "unknown"


class AIError(Exception):
    """An AI call or sign-in failed. The text is written for the user."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        provider: str,
        how_to_fix: str = "",
        code: str | None = None,
        param: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.provider = provider
        self.how_to_fix = how_to_fix
        self.code = code
        self.param = param
        self.request_id = request_id
        self.retryable = retryable


def switch_instructions(provider: str) -> str:
    """How to use the other provider instead of the one that just failed."""
    if provider == "chatgpt":
        return (
            "To use OpenRouter instead: open your .env file, set AI_PROVIDER=openrouter, "
            "make sure OPENROUTER_API_KEY and OPENROUTER_MODEL are filled in, save, and "
            "refresh this page. OpenRouter charges your OpenRouter credits for each request."
        )
    return (
        "To use your ChatGPT plan instead: open your .env file, set AI_PROVIDER=chatgpt, "
        "save, refresh this page, and sign in on the AI connection page."
    )


_SIGN_IN_AGAIN = "Open the AI connection page and click Continue with ChatGPT."
_TRY_LATER = "Nothing is wrong with your sign-in. Wait a few minutes and try again."

# Error codes from OpenAI's "Errors and recovery" page for ChatGPT plan usage.
_CHATGPT_CODES = {
    "subscription_sharing_user_not_eligible": (
        NOT_ELIGIBLE,
        "ChatGPT plan usage isn't available for this ChatGPT account, workspace, or region.",
        "Signing in again will not change this. Use OpenRouter for now.",
        False,
    ),
    "subscription_sharing_usage_limit_exceeded": (
        USAGE_LIMIT,
        "Usage limit reached. Review your plan or this app's limit in ChatGPT settings.",
        "Wait for the limit to reset, or raise this app's limit in ChatGPT settings.",
        False,
    ),
    "subscription_sharing_usage_unavailable": (
        UNAVAILABLE,
        "ChatGPT couldn't check your plan usage just now.",
        _TRY_LATER,
        True,
    ),
    "subscription_sharing_user_unavailable": (
        UNAVAILABLE,
        "ChatGPT couldn't look up your account just now.",
        _TRY_LATER,
        True,
    ),
    "subscription_sharing_unsupported_capability": (
        UNSUPPORTED,
        "This request used something ChatGPT plan usage doesn't support with your model.",
        "Pick a different model on the AI connection page, or use OpenRouter.",
        False,
    ),
    "subscription_sharing_route_not_supported": (
        UNKNOWN,
        "The app called ChatGPT in a way plan usage doesn't allow. This is a bug in the app.",
        "Use OpenRouter for now and report this.",
        False,
    ),
    "subscription_sharing_invalid_user": (
        SIGN_IN_EXPIRED,
        "ChatGPT couldn't confirm your sign-in.",
        _SIGN_IN_AGAIN,
        False,
    ),
    "chatpass_v2_scope_not_authorized": (
        PLAN_USAGE_OFF,
        "This sign-in doesn't include permission to use your ChatGPT plan.",
        _SIGN_IN_AGAIN + " Approve plan usage when ChatGPT asks.",
        False,
    ),
    "chatpass_v2_invalid_authorization_context": (
        PLAN_USAGE_OFF,
        "ChatGPT rejected this app's permission to use your plan.",
        _SIGN_IN_AGAIN + " If it keeps happening, choose Sign in with a different account.",
        False,
    ),
}

# Used when ChatGPT answers with only an HTTP status and no error code.
_CHATGPT_STATUSES = {
    401: (SIGN_IN_EXPIRED, "ChatGPT didn't accept your sign-in.", _SIGN_IN_AGAIN, False),
    403: (
        BLOCKED,
        "ChatGPT blocked this request (a policy, permission, or region restriction).",
        "Signing in again is unlikely to help. Use OpenRouter for now.",
        False,
    ),
    429: (
        RATE_LIMITED,
        "ChatGPT is receiving requests too quickly from this app.",
        "Wait a minute and try again.",
        True,
    ),
    503: (
        UNAVAILABLE,
        "ChatGPT plan usage is unavailable right now, or isn't switched on for your account.",
        "Wait a few minutes and try again. If it never works, use OpenRouter.",
        True,
    ),
}

_OPENROUTER_STATUSES = {
    400: (UNKNOWN, "OpenRouter couldn't understand the request.", "", False),
    401: (
        BAD_KEY,
        "OpenRouter didn't accept your API key.",
        "Check OPENROUTER_API_KEY in your .env file. Create a new key at "
        "openrouter.ai/keys if needed.",
        False,
    ),
    402: (
        NO_CREDITS,
        "Your OpenRouter account is out of credits.",
        "Add credits at openrouter.ai/credits, or raise the limit on this key.",
        False,
    ),
    403: (
        BLOCKED,
        "OpenRouter blocked this request (permissions, a guardrail, or moderation).",
        "",
        False,
    ),
    404: (
        MODEL_PROBLEM,
        "OpenRouter doesn't have the model named in OPENROUTER_MODEL.",
        "Pick a model from the list on the AI connection page.",
        False,
    ),
    408: (UNAVAILABLE, "OpenRouter timed out.", "Try again.", True),
    429: (RATE_LIMITED, "OpenRouter is rate limiting you.", "Wait a minute and try again.", True),
    502: (
        MODEL_PROBLEM,
        "The model you chose is down or returned an invalid answer.",
        "Try again, or pick a different model on the AI connection page.",
        True,
    ),
    503: (
        MODEL_PROBLEM,
        "No provider is available for the model you chose right now.",
        "Try again, or pick a different model on the AI connection page.",
        True,
    ),
}


def chatgpt_error(
    *,
    status: int | None = None,
    code: str | None = None,
    detail: str = "",
    param: str | None = None,
    request_id: str | None = None,
) -> AIError:
    """Build the right AIError for a ChatGPT plan failure."""
    known = _CHATGPT_CODES.get(code or "") or _CHATGPT_STATUSES.get(status or 0)
    if known:
        kind, message, how_to_fix, retryable = known
    elif status and status >= 500:
        kind, message, how_to_fix, retryable = (
            UNAVAILABLE,
            "ChatGPT had a problem on its side.",
            _TRY_LATER,
            True,
        )
    else:
        kind, how_to_fix, retryable = UNKNOWN, "", False
        message = "ChatGPT returned an error the app doesn't recognize."
    if kind == UNSUPPORTED and param:
        message += f" (The part it refused: {param}.)"
    if kind == UNKNOWN and (code or detail):
        message += f" Details: {code or detail}"
    return AIError(
        kind,
        message,
        provider="chatgpt",
        how_to_fix=how_to_fix,
        code=code,
        param=param,
        request_id=request_id,
        retryable=retryable,
    )


def openrouter_error(
    *, status: int | None = None, detail: str = "", tool_sent: bool = False
) -> AIError:
    """Build the right AIError for an OpenRouter failure."""
    kind, message, how_to_fix, retryable = _OPENROUTER_STATUSES.get(
        status or 0,
        (UNKNOWN, "OpenRouter returned an error the app doesn't recognize.", "", False),
    )
    # A model that can't use tools rejects the web search tool. ask_ai() retries without it.
    if tool_sent and status in (400, 404) and "tool" in detail.lower():
        kind, retryable = UNSUPPORTED, False
        message = "The OpenRouter model you chose can't use web search."
        how_to_fix = "Pick a model that supports tools on the AI connection page."
    elif detail and kind in (UNKNOWN, BLOCKED, MODEL_PROBLEM):
        message += f" Details: {detail}"
    return AIError(
        kind,
        message,
        provider="openrouter",
        how_to_fix=how_to_fix,
        code=str(status) if status else None,
        retryable=retryable,
    )
