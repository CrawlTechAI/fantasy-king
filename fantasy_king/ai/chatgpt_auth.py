"""Sign in with ChatGPT, so the app can use your ChatGPT plan.

This follows OpenAI's "ChatGPT plan usage for open-source apps" docs, starting
at https://developers.openai.com/siwc/token-sharing-open-source (read 2026-10-01):

  1. Pick a permanent ID for this computer and save it before the first sign-in.
  2. Open the browser at OpenAI's sign-in page. The first time, the app
     registers itself there; OpenAI hands back a client ID for later sign-ins.
  3. OpenAI sends the browser back to this computer with a one-time code.
  4. Swap the code for tokens, and check the ID token really came from OpenAI.
  5. Save the tokens, and refresh them shortly before they expire.

There is no client secret and no password. The app never sees your ChatGPT
password: you type it on OpenAI's page, not here.
"""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

from fantasy_king.ai import errors
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.token_store import TokenStore, TokenStoreError

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
DISCOVERY_URL = "https://auth.openai.com/.well-known/openid-configuration"
ISSUER = "https://auth.openai.com"
# The API these tokens are for. Sent with every authorization and token request.
RESOURCE = "https://api.openai.com/v1"

PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"

# Stands in for a client ID on the very first sign-in. OpenAI replaces it with a
# real one, which must be saved; this placeholder must never be saved.
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
# The name ChatGPT shows on its approval screen. The docs ask that it stay the same.
AGENT_NAME = "Fantasy King"

# OpenAI only accepts this exact address shape. Only the port may change between
# sign-ins, and "localhost" is not accepted in place of 127.0.0.1.
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PATH = "/auth/callback"
PREFERRED_PORT = 1455

REFRESH_MARGIN_SECONDS = 300  # refresh when the access token has under 5 minutes left
SIGN_IN_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 30

# Refresh failures that mean the saved sign-in is dead and you must sign in again.
SIGN_IN_AGAIN_CODES = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}

_SIGN_IN_AGAIN = "Open the AI connection page and click Continue with ChatGPT."


@dataclass(frozen=True)
class SignInAttempt:
    """One trip to OpenAI's sign-in page. Never reused."""

    url: str
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    client_id: str  # DYNAMIC_CLIENT_ID on a first sign-in, the saved ID afterwards


@contextmanager
def open_http(http_client: httpx.Client | None = None):
    """Use the given connection, or open one and close it afterwards."""
    if http_client is not None:
        yield http_client
    else:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            yield client


def _sign_in_error(message: str, how_to_fix: str = "Try signing in again.") -> AIError:
    return AIError(errors.SIGN_IN_FAILED, message, provider="chatgpt", how_to_fix=how_to_fix)


# --- Saved sign-in ---------------------------------------------------------


def load_state(store: TokenStore) -> dict:
    try:
        return store.load()
    except TokenStoreError as problem:
        raise AIError(
            errors.STORAGE,
            str(problem),
            provider="chatgpt",
            how_to_fix="Click Reset saved sign-in on the AI connection page, then sign in again.",
        ) from problem


def _save_state(store: TokenStore, state: dict) -> None:
    try:
        store.save(state)
    except TokenStoreError as problem:
        raise AIError(errors.STORAGE, str(problem), provider="chatgpt") from problem


def active_account(state: dict) -> dict | None:
    return state["accounts"].get(state.get("active") or "")


def is_signed_in(account: dict | None) -> bool:
    return bool(account and account.get("refresh_token"))


def ensure_host_id(store: TokenStore) -> str:
    """This computer's permanent ID, created and saved before the first sign-in."""
    with store.lock():
        state = load_state(store)
        if not state.get("host_id"):
            state["host_id"] = f"urn:uuid:{uuid.uuid4()}"
            _save_state(store, state)
        return state["host_id"]


def _forget_tokens(account: dict) -> None:
    """Drop the secrets but keep who the account is, so signing back in is quick."""
    for name in ("access_token", "refresh_token", "id_token", "expires_at", "earliest_refresh_at"):
        account.pop(name, None)


# --- Step 2: build the address of OpenAI's sign-in page ---------------------


def _random_token() -> str:
    return secrets.token_urlsafe(32)


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def start_attempt(
    host_id: str, redirect_uri: str, account: dict | None = None, ask_consent: bool = False
) -> SignInAttempt:
    """Build a sign-in address with fresh one-time values.

    Pass a saved account to sign back in with its client ID; pass none to
    register this app with a ChatGPT account for the first time. ask_consent
    makes ChatGPT show its approval screen again, for an account that signed in
    earlier without approving plan usage.
    """
    state, nonce, code_verifier = _random_token(), _random_token(), _random_token()
    client_id = account["client_id"] if account else DYNAMIC_CLIENT_ID
    params = {
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": _pkce_challenge(code_verifier),
    }
    if account:
        # Sign-ins after the first leave the app name out and say who is expected.
        if account.get("id_token"):
            params["id_token_hint"] = account["id_token"]
        if account.get("email"):
            params["login_hint"] = account["email"]
        if ask_consent:
            params["prompt"] = "consent"
    else:
        params["agent_name_hint"] = AGENT_NAME
    return SignInAttempt(
        url=f"{AUTHORIZE_URL}?{urlencode(params)}",
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        client_id=client_id,
    )


# --- Step 3: catch the browser coming back -----------------------------------

_DONE_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>Fantasy King</title>"
    "<body style='font-family:sans-serif;margin:3rem'>"
    "<h2>You can close this tab</h2><p>Go back to Fantasy King to finish.</p></body>"
).encode("utf-8")


class _CallbackHandler(BaseHTTPRequestHandler):
    # Browsers sometimes open a connection and send nothing. Give up on those quickly.
    timeout = 5

    def do_GET(self):  # noqa: N802 (name required by BaseHTTPRequestHandler)
        address = urlsplit(self.path)
        if address.path != CALLBACK_PATH:
            self.send_error(404)
            return
        self.server.callback = {key: values[0] for key, values in parse_qs(address.query).items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_DONE_PAGE)))
        self.end_headers()
        self.wfile.write(_DONE_PAGE)

    def log_message(self, *args):
        # The default would print the address, which contains the one-time code.
        pass


class _CallbackServer(ThreadingHTTPServer):
    # Each connection gets its own thread, so an idle one can't hold up the real callback.
    # Off, so a port another program is already using is refused rather than shared.
    allow_reuse_address = False
    block_on_close = False
    callback: dict | None = None


def open_listener(preferred_port: int = PREFERRED_PORT) -> HTTPServer:
    """Listen on this computer only. Falls back to any free port if 1455 is taken."""
    try:
        return _CallbackServer((CALLBACK_HOST, preferred_port), _CallbackHandler)
    except OSError:
        return _CallbackServer((CALLBACK_HOST, 0), _CallbackHandler)


def wait_for_callback(server: HTTPServer, timeout: float) -> dict | None:
    """Wait for the browser to come back. Returns None if it never does."""
    deadline = time.monotonic() + timeout
    while server.callback is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        server.timeout = min(remaining, 1.0)
        server.handle_request()
    return server.callback


def read_callback(params: dict, attempt: SignInAttempt) -> dict:
    """Check the browser came back from our own attempt, and with a code."""
    if not hmac.compare_digest(params.get("state", ""), attempt.state):
        raise _sign_in_error("The sign-in response didn't match this sign-in attempt.")
    if params.get("error") == "access_denied":
        raise _sign_in_error(
            "You declined the request on ChatGPT's page, so nothing was connected.",
            "Click Continue with ChatGPT again and approve it, or use OpenRouter instead.",
        )
    if params.get("error") or not params.get("code"):
        raise _sign_in_error(f"ChatGPT sign-in failed ({params.get('error', 'no code returned')}).")
    return params


# --- Step 4: swap the code for tokens and check them ------------------------


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _oauth_error_code(response: httpx.Response) -> str:
    """The error name from a token-endpoint failure, in either common JSON shape."""
    error = _json(response).get("error")
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or "")
    return str(error or "")


def _post_form(http: httpx.Client, url: str, form: dict) -> httpx.Response:
    try:
        return http.post(url, data=form)
    except httpx.HTTPError as problem:
        raise AIError(
            errors.NETWORK,
            "Couldn't reach OpenAI's sign-in service.",
            provider="chatgpt",
            how_to_fix="Check your internet connection and try again.",
            retryable=True,
        ) from problem


def exchange_code(http: httpx.Client, attempt: SignInAttempt, client_id: str, code: str) -> dict:
    response = _post_form(
        http,
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": attempt.code_verifier,
            "redirect_uri": attempt.redirect_uri,
            "resource": RESOURCE,
        },
    )
    if response.status_code != 200:
        detail = _oauth_error_code(response) or f"HTTP {response.status_code}"
        raise _sign_in_error(f"OpenAI didn't accept the sign-in ({detail}).")
    return _json(response)


def fetch_discovery(http: httpx.Client) -> dict:
    """OpenAI's published list of sign-in addresses (where its keys are, and so on)."""
    try:
        response = http.get(DISCOVERY_URL)
        response.raise_for_status()
        discovery = response.json()
    except (httpx.HTTPError, ValueError) as problem:
        raise AIError(
            errors.NETWORK,
            "Couldn't reach OpenAI's sign-in service.",
            provider="chatgpt",
            how_to_fix="Check your internet connection and try again.",
            retryable=True,
        ) from problem
    if discovery.get("issuer") != ISSUER:
        raise _sign_in_error("OpenAI's sign-in service identified itself unexpectedly.")
    return discovery


def _openai_url(discovery: dict, name: str) -> str:
    """An address from discovery, accepted only if it is on OpenAI's sign-in host."""
    url = discovery.get(name) or ""
    address = urlsplit(url)
    if address.scheme != "https" or address.netloc != urlsplit(ISSUER).netloc:
        raise _sign_in_error("OpenAI's sign-in service listed an unexpected address.")
    return url


def fetch_signing_keys(http: httpx.Client, discovery: dict) -> dict:
    try:
        response = http.get(_openai_url(discovery, "jwks_uri"))
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as problem:
        raise AIError(
            errors.NETWORK,
            "Couldn't download OpenAI's signing keys.",
            provider="chatgpt",
            how_to_fix="Check your internet connection and try again.",
            retryable=True,
        ) from problem


def validate_id_token(id_token: str, *, client_id: str, nonce: str, signing_keys: dict) -> dict:
    """Prove the ID token was issued by OpenAI, for this app, for this attempt."""
    try:
        key_id = jwt.get_unverified_header(id_token).get("kid")
        keys = jwt.PyJWKSet.from_dict(signing_keys).keys
        matching = [key for key in keys if key.key_id == key_id] or (keys if not key_id else [])
        if not matching:
            raise jwt.InvalidTokenError("signed with an unknown key")
        claims = jwt.decode(
            id_token,
            matching[0].key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            leeway=60,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as problem:
        raise _sign_in_error(
            "The sign-in couldn't be verified as coming from OpenAI, so it was not saved."
        ) from problem
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise _sign_in_error("The sign-in response didn't match this sign-in attempt.")
    return claims


def _token_claim(token: str, name: str):
    """Read one field from a token without verifying it. Only for non-security hints."""
    try:
        return jwt.decode(token, options={"verify_signature": False}).get(name)
    except jwt.PyJWTError:
        return None


def _to_timestamp(value) -> float | None:
    """earliest_refresh_at is documented without a format, so accept the likely ones."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _apply_tokens(account: dict, tokens: dict, now: float) -> None:
    account["access_token"] = tokens["access_token"]
    # Each refresh returns a replacement refresh token. Keep the newest one.
    if tokens.get("refresh_token"):
        account["refresh_token"] = tokens["refresh_token"]
    if tokens.get("id_token"):
        account["id_token"] = tokens["id_token"]
    account["expires_at"] = now + float(tokens.get("expires_in") or 3600)
    account["earliest_refresh_at"] = _to_timestamp(tokens.get("earliest_refresh_at"))


def complete_sign_in(
    store: TokenStore,
    http: httpx.Client,
    attempt: SignInAttempt,
    params: dict,
    *,
    now: float | None = None,
) -> dict:
    """Steps 3 to 5: read the callback, get tokens, verify them, save the account."""
    now = time.time() if now is None else now
    callback = read_callback(params, attempt)
    client_id = attempt.client_id
    if client_id == DYNAMIC_CLIENT_ID:
        # A first sign-in. OpenAI issues the real client ID in the callback.
        client_id = callback.get("client_id") or ""
        if not client_id or client_id == DYNAMIC_CLIENT_ID:
            raise _sign_in_error("ChatGPT didn't register this app, so sign-in couldn't finish.")
    elif callback.get("client_id", client_id) != client_id:
        # Signing back in: the callback may leave the client ID out, but if it names a
        # different one the docs say to reject it, not to replace the saved registration.
        raise _sign_in_error(
            "ChatGPT answered for a different app registration than the one saved here, "
            "so nothing was changed.",
            "Try again. If it keeps happening, click Sign in with a different account.",
        )

    tokens = exchange_code(http, attempt, client_id, callback["code"])
    if not tokens.get("access_token") or not tokens.get("id_token"):
        raise _sign_in_error("OpenAI's sign-in response was incomplete.")
    signing_keys = fetch_signing_keys(http, fetch_discovery(http))
    claims = validate_id_token(
        tokens["id_token"], client_id=client_id, nonce=attempt.nonce, signing_keys=signing_keys
    )
    granted = (
        tokens.get("scope")
        or callback.get("scope")
        or _token_claim(tokens["access_token"], "scope")
        or ""
    )

    with store.lock():
        state = load_state(store)
        previous = active_account(state)
        if (
            attempt.client_id != DYNAMIC_CLIENT_ID
            and previous
            and previous.get("sub") != claims["sub"]
        ):
            raise _sign_in_error(
                "You signed in with a different ChatGPT account than the one saved here.",
                "Click Sign in with a different account instead.",
            )
        account = state["accounts"].get(claims["sub"], {})
        account.update(
            sub=claims["sub"],
            client_id=client_id,
            email=claims.get("email") or "",
            label=claims.get("email") or claims.get("name") or "your ChatGPT account",
            scope=granted,
            # Signing in without approving plan usage is allowed; AI calls just stay off.
            plan_usage_enabled=PLAN_SCOPE in granted.split(),
            callback_path=urlsplit(attempt.redirect_uri).path,
        )
        account.setdefault("registered_at", now)
        account.setdefault("welcome_seen", False)
        _apply_tokens(account, tokens, now)
        state["accounts"][claims["sub"]] = account
        state["active"] = claims["sub"]
        _save_state(store, state)
    return account


def sign_in_with_browser(
    store: TokenStore,
    http: httpx.Client,
    *,
    different_account: bool = False,
    timeout: float = SIGN_IN_TIMEOUT_SECONDS,
    open_browser=webbrowser.open,
    on_ready=None,
) -> dict:
    """Run the whole sign-in: open the browser, wait for you, save the result.

    on_ready(url) is called just before the browser opens, so the dashboard can
    show a fallback link in case the browser doesn't open by itself.
    """
    host_id = ensure_host_id(store)
    saved = None if different_account else active_account(load_state(store))
    if saved and not saved.get("client_id"):
        saved = None
    server = open_listener()
    try:
        path = (saved or {}).get("callback_path") or CALLBACK_PATH
        redirect_uri = f"http://{CALLBACK_HOST}:{server.server_address[1]}{path}"
        ask_consent = bool(saved) and not saved.get("plan_usage_enabled")
        attempt = start_attempt(host_id, redirect_uri, saved, ask_consent)
        if on_ready:
            on_ready(attempt.url)
        open_browser(attempt.url)
        params = wait_for_callback(server, timeout)
    finally:
        server.server_close()
    if params is None:
        raise _sign_in_error(
            f"Sign-in wasn't finished within {int(timeout // 60)} minutes.",
            "Click Continue with ChatGPT again and finish in the browser tab that opens.",
        )
    return complete_sign_in(store, http, attempt, params)


# --- Step 5: keep the sign-in fresh ----------------------------------------


def _needs_refresh(account: dict, now: float) -> bool:
    expires_at = account.get("expires_at") or 0
    if now >= expires_at:
        return True
    if now < expires_at - REFRESH_MARGIN_SECONDS:
        return False
    # Inside the last few minutes: refresh, unless OpenAI said it is too early.
    return now >= (account.get("earliest_refresh_at") or 0)


def _refresh(store: TokenStore, http: httpx.Client, state: dict, account: dict, now: float):
    response = _post_form(
        http,
        TOKEN_URL,
        {
            # No "scope": leaving it out keeps the permissions already granted.
            "grant_type": "refresh_token",
            "client_id": account["client_id"],
            "refresh_token": account["refresh_token"],
            "resource": RESOURCE,
        },
    )
    tokens = _json(response) if response.status_code == 200 else {}
    if tokens.get("access_token"):
        _apply_tokens(account, tokens, now)
        if tokens.get("scope"):
            account["scope"] = tokens["scope"]
            account["plan_usage_enabled"] = PLAN_SCOPE in tokens["scope"].split()
        _save_state(store, state)
        return

    code = _oauth_error_code(response)
    if code in SIGN_IN_AGAIN_CODES:
        _forget_tokens(account)
        _save_state(store, state)
        raise AIError(
            errors.SIGN_IN_EXPIRED,
            "Your ChatGPT sign-in has expired or was disconnected.",
            provider="chatgpt",
            how_to_fix=_SIGN_IN_AGAIN,
            code=code,
        )
    if code == "invalid_client":
        raise AIError(
            errors.SIGN_IN_EXPIRED,
            "ChatGPT no longer recognizes this app's registration.",
            provider="chatgpt",
            how_to_fix="On the AI connection page, click Sign in with a different account "
            "and choose your account again. That registers the app afresh.",
            code=code,
        )
    # Anything else is treated as temporary, so the saved sign-in is kept.
    raise AIError(
        errors.UNAVAILABLE,
        "OpenAI's sign-in service couldn't refresh your sign-in just now.",
        provider="chatgpt",
        how_to_fix="Nothing is wrong with your sign-in. Wait a few minutes and try again.",
        code=code or str(response.status_code),
        retryable=True,
    )


def get_access_token(
    store: TokenStore,
    http: httpx.Client,
    *,
    rejected_token: str | None = None,
    now: float | None = None,
) -> str:
    """A valid access token for AI calls, refreshed first if it is about to expire.

    Pass rejected_token after ChatGPT refuses a token, to force a refresh.
    """
    now = time.time() if now is None else now
    account = active_account(load_state(store))
    _require_usable(account)
    if rejected_token is None and not _needs_refresh(account, now):
        return account["access_token"]

    with store.lock():
        # Read again inside the lock: another process may have refreshed already.
        state = load_state(store)
        account = active_account(state)
        _require_usable(account)
        current = account.get("access_token")
        refreshed_elsewhere = (
            current != rejected_token
            if rejected_token is not None
            else not _needs_refresh(account, now)
        )
        if not refreshed_elsewhere:
            _refresh(store, http, state, account, now)
        return account["access_token"]


def _require_usable(account: dict | None) -> None:
    if not is_signed_in(account):
        raise AIError(
            errors.NOT_SIGNED_IN,
            "You aren't signed in with ChatGPT yet.",
            provider="chatgpt",
            how_to_fix=_SIGN_IN_AGAIN,
        )
    if not account.get("plan_usage_enabled"):
        raise AIError(
            errors.PLAN_USAGE_OFF,
            "You're signed in, but ChatGPT plan usage wasn't approved for this app.",
            provider="chatgpt",
            how_to_fix=_SIGN_IN_AGAIN + " Approve plan usage when ChatGPT asks.",
        )


# --- Signing out -------------------------------------------------------------


def sign_out(store: TokenStore, http: httpx.Client, *, sleep=time.sleep) -> bool:
    """Tell OpenAI to cancel the sign-in, then forget the tokens on this computer.

    Returns False if OpenAI couldn't be told. The tokens are forgotten here
    either way; in that case also disconnect the app in ChatGPT settings.
    """
    account = active_account(load_state(store))
    revoked = True
    if is_signed_in(account):
        revoked = _revoke(http, account, sleep)
    with store.lock():
        state = load_state(store)
        account = active_account(state)
        if account:
            _forget_tokens(account)
            _save_state(store, state)
    return revoked


def _revoke(http: httpx.Client, account: dict, sleep) -> bool:
    form = {
        "token": account["refresh_token"],
        "token_type_hint": "refresh_token",
        "client_id": account["client_id"],
    }
    for wait in (0, 1, 3):
        sleep(wait)
        try:
            url = _openai_url(fetch_discovery(http), "revocation_endpoint")
            response = _post_form(http, url, form)
        except AIError:
            continue
        if response.status_code == 200:
            return True
        if response.status_code < 500:
            return False
    return False


def mark_welcome_seen(store: TokenStore) -> None:
    """Remember that the one-time "You're using your ChatGPT plan" notice was shown."""
    with store.lock():
        state = load_state(store)
        account = active_account(state)
        if account:
            account["welcome_seen"] = True
            _save_state(store, state)


def describe(account: dict | None) -> str:
    """One line for the dashboard. Never includes a token."""
    if not account:
        return "not signed in yet"
    if not is_signed_in(account):
        return f"signed out ({account.get('label', 'saved account')})"
    if not account.get("plan_usage_enabled"):
        return f"signed in as {account.get('label')}, plan usage not approved"
    return f"signed in as {account.get('label')}"
