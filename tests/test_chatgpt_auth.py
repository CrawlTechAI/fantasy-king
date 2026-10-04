"""Sign in with ChatGPT, checked against a fake OpenAI. No real sign-in happens here."""

import base64
import hashlib
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from helpers import ISSUED_CLIENT_ID, REVOKE_URL, save_account, saved_account

from fantasy_king.ai import chatgpt_auth as auth
from fantasy_king.ai import errors
from fantasy_king.ai.errors import AIError

REDIRECT = "http://127.0.0.1:1455/auth/callback"
HOST_ID = "urn:uuid:test-host"


def query(url: str) -> dict:
    return {name: values[0] for name, values in parse_qs(urlsplit(url).query).items()}


def callback_for(attempt, **changes) -> dict:
    return {
        "code": "one-time-code",
        "state": attempt.state,
        "scope": auth.SCOPES,
        "client_id": ISSUED_CLIENT_ID,
        **changes,
    }


def first_sign_in(fake, store, **callback_changes):
    """Run a first sign-in against the fake OpenAI and return the attempt."""
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    fake.nonce = attempt.nonce
    if not fake.token_replies:
        fake.token_replies.append(fake.tokens())
    auth.complete_sign_in(store, fake.http(), attempt, callback_for(attempt, **callback_changes))
    return attempt


# --- Building the sign-in address ---


def test_first_sign_in_asks_openai_to_register_the_app():
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    sent = query(attempt.url)

    assert attempt.url.startswith("https://auth.openai.com/api/accounts/authorize?")
    assert sent == {
        "client_id": "dynamic_agent_client",
        "agent_name_hint": "Fantasy King",
        "ext_agent_host_id": HOST_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
        "resource": "https://api.openai.com/v1",
        "state": attempt.state,
        "nonce": attempt.nonce,
        "code_challenge_method": "S256",
        "code_challenge": sent["code_challenge"],
    }


def test_the_pkce_challenge_is_the_sha256_of_the_verifier():
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    digest = hashlib.sha256(attempt.code_verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert query(attempt.url)["code_challenge"] == expected


def test_every_attempt_uses_fresh_one_time_values():
    first, second = auth.start_attempt(HOST_ID, REDIRECT), auth.start_attempt(HOST_ID, REDIRECT)
    assert first.state != second.state
    assert first.nonce != second.nonce
    assert first.code_verifier != second.code_verifier


def test_later_sign_ins_use_the_saved_client_and_leave_the_app_name_out():
    account = {"client_id": ISSUED_CLIENT_ID, "id_token": "saved-id-token", "email": "a@b.co"}
    sent = query(auth.start_attempt(HOST_ID, REDIRECT, account).url)

    assert sent["client_id"] == ISSUED_CLIENT_ID
    assert sent["id_token_hint"] == "saved-id-token"
    assert sent["login_hint"] == "a@b.co"
    assert sent["ext_agent_host_id"] == HOST_ID
    assert "agent_name_hint" not in sent
    assert "prompt" not in sent


def test_consent_is_asked_again_only_when_requested():
    account = {"client_id": ISSUED_CLIENT_ID}
    sent = query(auth.start_attempt(HOST_ID, REDIRECT, account, ask_consent=True).url)
    assert sent["prompt"] == "consent"


def test_this_computers_id_is_created_once_and_kept(store):
    host_id = auth.ensure_host_id(store)
    assert host_id.startswith("urn:uuid:")
    assert auth.ensure_host_id(store) == host_id


# --- Handling the browser coming back ---


def test_a_callback_from_some_other_attempt_is_refused():
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    with pytest.raises(AIError, match="didn't match"):
        auth.read_callback(callback_for(attempt, state="someone-elses-state"), attempt)


def test_declining_on_chatgpts_page_is_explained(fake, store):
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    declined = {"error": "access_denied", "state": attempt.state}

    with pytest.raises(AIError, match="declined") as raised:
        auth.complete_sign_in(store, fake.http(), attempt, declined)

    assert "OpenRouter" in raised.value.how_to_fix
    assert fake.requests == []  # no code, so nothing is exchanged
    assert saved_account(store) is None


def test_a_callback_without_a_code_fails(fake, store):
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    with pytest.raises(AIError, match="sign-in failed"):
        auth.complete_sign_in(store, fake.http(), attempt, {"state": attempt.state})


# --- Completing a first sign-in ---


def test_first_sign_in_saves_the_issued_client_and_tokens(fake, store):
    attempt = first_sign_in(fake, store)
    account = saved_account(store)

    assert account["client_id"] == ISSUED_CLIENT_ID  # never the placeholder
    assert account["access_token"] == "access-1"
    assert account["refresh_token"] == "refresh-1"
    assert account["email"] == account["label"] == "fan@example.com"
    assert account["sub"] == "user-123"
    assert account["plan_usage_enabled"] is True
    assert account["callback_path"] == "/auth/callback"
    assert account["expires_at"] > time.time() + 3000

    exchange = fake.sent_to(auth.TOKEN_URL)[0]
    assert exchange["method"] == "POST"
    assert exchange["body"] == {
        "grant_type": "authorization_code",
        "client_id": ISSUED_CLIENT_ID,
        "code": "one-time-code",
        "code_verifier": attempt.code_verifier,
        "redirect_uri": REDIRECT,
        "resource": "https://api.openai.com/v1",
    }


def test_first_sign_in_fails_if_openai_issues_no_client(fake, store):
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    callback = callback_for(attempt)
    del callback["client_id"]
    with pytest.raises(AIError, match="didn't register"):
        auth.complete_sign_in(store, fake.http(), attempt, callback)
    assert fake.requests == []


def test_signing_in_without_approving_plan_usage_keeps_the_sign_in_but_turns_ai_off(fake, store):
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    fake.nonce = attempt.nonce
    fake.token_replies.append(fake.tokens(scope="openid profile email offline_access"))
    auth.complete_sign_in(
        store, fake.http(), attempt, callback_for(attempt, scope="openid profile email")
    )

    account = saved_account(store)
    assert auth.is_signed_in(account)
    assert account["plan_usage_enabled"] is False
    with pytest.raises(AIError) as raised:
        auth.get_access_token(store, fake.http())
    assert raised.value.kind == errors.PLAN_USAGE_OFF


def test_openai_rejecting_the_code_is_reported(fake, store):
    fake.token_replies.append(httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(AIError, match="invalid_grant"):
        first_sign_in(fake, store)
    assert saved_account(store) is None


@pytest.mark.parametrize(
    "bad_claims",
    [
        {"nonce": "a-different-attempt"},
        {"aud": "oaiapp_some_other_app"},
        {"iss": "https://not-openai.example"},
        {"exp": int(time.time()) - 3600},
    ],
    ids=["wrong nonce", "wrong audience", "wrong issuer", "expired"],
)
def test_an_id_token_that_fails_any_check_is_not_saved(fake, store, bad_claims):
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    fake.nonce = attempt.nonce
    fake.token_replies.append(fake.tokens(id_token=fake.id_token(**bad_claims)))

    with pytest.raises(AIError) as raised:
        auth.complete_sign_in(store, fake.http(), attempt, callback_for(attempt))

    assert raised.value.kind == errors.SIGN_IN_FAILED
    assert saved_account(store) is None


def test_an_id_token_signed_by_someone_else_is_not_saved(fake, store):
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attempt = auth.start_attempt(HOST_ID, REDIRECT)
    fake.nonce = attempt.nonce
    fake.token_replies.append(fake.tokens(id_token=fake.id_token(key=attacker)))

    with pytest.raises(AIError, match="couldn't be verified"):
        auth.complete_sign_in(store, fake.http(), attempt, callback_for(attempt))
    assert saved_account(store) is None


def test_an_unsigned_id_token_is_not_saved(fake):
    unsigned = jwt.encode({"iss": auth.ISSUER, "aud": ISSUED_CLIENT_ID}, None, algorithm="none")
    with pytest.raises(AIError, match="couldn't be verified"):
        auth.validate_id_token(
            unsigned, client_id=ISSUED_CLIENT_ID, nonce="n", signing_keys=fake.signing_keys()
        )


def test_signing_back_in_as_someone_else_with_a_saved_client_is_refused(fake, store):
    save_account(store)
    attempt = auth.start_attempt(HOST_ID, REDIRECT, saved_account(store))
    fake.nonce = attempt.nonce
    fake.token_replies.append(fake.tokens(id_token=fake.id_token(sub="a-different-user")))

    with pytest.raises(AIError, match="different ChatGPT account"):
        auth.complete_sign_in(store, fake.http(), attempt, callback_for(attempt))
    assert saved_account(store)["access_token"] == "access-0"


# --- Signing back in: the callback's client ID must be the saved one, or absent ---


def test_a_returning_callback_naming_a_different_client_is_rejected_before_any_exchange(
    fake, store
):
    save_account(store)
    on_disk = store.path.read_bytes()
    attempt = auth.start_attempt(HOST_ID, REDIRECT, saved_account(store))
    fake.nonce = attempt.nonce
    fake.token_replies.append(fake.tokens(9))  # would be used if an exchange were attempted

    with pytest.raises(AIError, match="different app registration") as raised:
        auth.complete_sign_in(
            store, fake.http(), attempt, callback_for(attempt, client_id="oaiapp_someone_else")
        )

    assert raised.value.kind == errors.SIGN_IN_FAILED
    assert fake.requests == []  # no token exchange, no key download, nothing
    assert len(fake.token_replies) == 1  # the queued reply was never asked for
    assert store.path.read_bytes() == on_disk  # the saved sign-in was not rewritten
    account = saved_account(store)
    assert account["client_id"] == ISSUED_CLIENT_ID
    assert (account["access_token"], account["refresh_token"]) == ("access-0", "refresh-0")


def test_the_placeholder_client_is_also_rejected_on_a_returning_callback(fake, store):
    save_account(store)
    attempt = auth.start_attempt(HOST_ID, REDIRECT, saved_account(store))
    with pytest.raises(AIError, match="different app registration"):
        auth.complete_sign_in(
            store, fake.http(), attempt, callback_for(attempt, client_id=auth.DYNAMIC_CLIENT_ID)
        )
    assert fake.requests == []


@pytest.mark.parametrize("callback_client", [None, ISSUED_CLIENT_ID], ids=["omitted", "the same"])
def test_a_returning_callback_exchanges_with_the_saved_client(fake, store, callback_client):
    save_account(store)
    attempt = auth.start_attempt(HOST_ID, REDIRECT, saved_account(store))
    fake.nonce = attempt.nonce
    fake.token_replies.append(fake.tokens(2))
    callback = callback_for(attempt)
    del callback["client_id"]
    if callback_client:
        callback["client_id"] = callback_client

    auth.complete_sign_in(store, fake.http(), attempt, callback)

    assert fake.sent_to(auth.TOKEN_URL)[0]["body"]["client_id"] == ISSUED_CLIENT_ID
    account = saved_account(store)
    assert account["client_id"] == ISSUED_CLIENT_ID
    assert account["access_token"] == "access-2"


def test_the_mismatch_is_also_caught_through_the_real_browser_callback(fake, store):
    save_account(store)
    on_disk = store.path.read_bytes()

    with pytest.raises(AIError, match="different app registration"):
        auth.sign_in_with_browser(
            store,
            fake.http(),
            open_browser=pretend_browser(fake, client_id="oaiapp_someone_else"),
            timeout=10,
        )

    assert fake.requests == []
    assert store.path.read_bytes() == on_disk


# --- The whole flow, with a pretend browser ---


def pretend_browser(fake, **callback_changes):
    """Stands in for the browser: 'visits' the sign-in address and comes straight back."""

    def open_browser(url: str) -> None:
        sent = query(url)
        fake.nonce = sent["nonce"]
        params = {
            "code": "one-time-code",
            "state": sent["state"],
            "scope": sent["scope"],
            "client_id": ISSUED_CLIENT_ID,
            **callback_changes,
        }
        fake.redirect_uri = sent["redirect_uri"]
        fake.token_replies.append(fake.tokens())
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        callback_url = f"{sent['redirect_uri']}?{urlencode(params)}"
        threading.Thread(target=lambda: direct.open(callback_url, timeout=10).read()).start()

    return open_browser


def test_the_whole_sign_in_from_button_to_saved_account(fake, store):
    shown = []
    account = auth.sign_in_with_browser(
        store, fake.http(), open_browser=pretend_browser(fake), on_ready=shown.append, timeout=10
    )

    redirect = urlsplit(fake.redirect_uri)
    assert (redirect.scheme, redirect.hostname, redirect.path) == ("http", "127.0.0.1", "/auth/callback")
    assert account["client_id"] == ISSUED_CLIENT_ID
    assert saved_account(store)["refresh_token"] == "refresh-1"
    assert store.load()["host_id"].startswith("urn:uuid:")
    assert shown and shown[0].startswith(auth.AUTHORIZE_URL)


def test_sign_in_gives_up_politely_if_the_browser_never_comes_back(fake, store):
    with pytest.raises(AIError, match="wasn't finished"):
        auth.sign_in_with_browser(store, fake.http(), open_browser=lambda url: None, timeout=0.3)
    assert saved_account(store) is None


def test_the_listener_ignores_other_addresses_and_takes_a_free_port_if_1455_is_busy():
    first = auth.open_listener()
    second = auth.open_listener(first.server_address[1])  # that port is now taken
    try:
        assert first.server_address[0] == second.server_address[0] == "127.0.0.1"
        assert second.server_address[1] != first.server_address[1]

        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{second.server_address[1]}"

        def visit():
            try:
                direct.open(f"{base}/somewhere-else?code=x", timeout=10)
            except urllib.error.HTTPError:
                pass
            direct.open(f"{base}/auth/callback?code=abc&state=xyz", timeout=10).read()

        threading.Thread(target=visit).start()
        assert auth.wait_for_callback(second, timeout=10) == {"code": "abc", "state": "xyz"}
    finally:
        first.server_close()
        second.server_close()


def test_an_idle_browser_connection_does_not_block_the_real_callback():
    server = auth.open_listener()
    port = server.server_address[1]
    idle = socket.create_connection(("127.0.0.1", port))  # connects, then sends nothing
    try:
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f"http://127.0.0.1:{port}/auth/callback?code=abc&state=xyz"
        threading.Thread(target=lambda: direct.open(url, timeout=10).read()).start()
        started = time.monotonic()
        assert auth.wait_for_callback(server, timeout=10) == {"code": "abc", "state": "xyz"}
        assert time.monotonic() - started < 4  # did not wait for the idle one to time out
    finally:
        idle.close()
        server.server_close()


# --- Keeping the sign-in fresh ---


def test_a_fresh_token_is_used_without_contacting_openai(fake, store):
    save_account(store)
    assert auth.get_access_token(store, fake.http()) == "access-0"
    assert fake.requests == []


def test_not_signed_in_is_reported_clearly(fake, store):
    with pytest.raises(AIError) as raised:
        auth.get_access_token(store, fake.http())
    assert raised.value.kind == errors.NOT_SIGNED_IN
    assert "Continue with ChatGPT" in raised.value.how_to_fix


def test_a_token_about_to_expire_is_refreshed_and_the_new_refresh_token_kept(fake, store):
    save_account(store, expires_at=time.time() + 60)
    fake.token_replies.append(fake.tokens(2))

    assert auth.get_access_token(store, fake.http()) == "access-2"

    refresh = fake.sent_to(auth.TOKEN_URL)[0]
    assert refresh["body"] == {
        "grant_type": "refresh_token",
        "client_id": ISSUED_CLIENT_ID,
        "refresh_token": "refresh-0",
        "resource": "https://api.openai.com/v1",
    }  # and no "scope", which keeps the permissions already granted
    account = saved_account(store)
    assert account["refresh_token"] == "refresh-2"
    assert account["expires_at"] > time.time() + 3000


def test_openais_earliest_refresh_time_is_respected(fake, store):
    now = time.time()
    save_account(store, expires_at=now + 60, earliest_refresh_at=now + 30)
    assert auth.get_access_token(store, fake.http(), now=now) == "access-0"
    assert fake.requests == []

    fake.token_replies.append(fake.tokens(2))
    assert auth.get_access_token(store, fake.http(), now=now + 45) == "access-2"


@pytest.mark.parametrize("code", sorted(auth.SIGN_IN_AGAIN_CODES))
def test_a_dead_refresh_token_means_sign_in_again(fake, store, code):
    save_account(store, expires_at=0)
    fake.token_replies.append(httpx.Response(400, json={"error": code}))

    with pytest.raises(AIError) as raised:
        auth.get_access_token(store, fake.http())

    assert raised.value.kind == errors.SIGN_IN_EXPIRED
    assert "Continue with ChatGPT" in raised.value.how_to_fix
    account = saved_account(store)
    assert "refresh_token" not in account and "access_token" not in account
    assert account["client_id"] == ISSUED_CLIENT_ID  # kept, so signing back in is quick


def test_a_temporary_refresh_failure_keeps_the_sign_in(fake, store):
    save_account(store, expires_at=0)
    fake.token_replies.append(httpx.Response(503, text="try later"))

    with pytest.raises(AIError) as raised:
        auth.get_access_token(store, fake.http())

    assert raised.value.kind == errors.UNAVAILABLE and raised.value.retryable
    assert saved_account(store)["refresh_token"] == "refresh-0"


def test_a_garbled_refresh_reply_keeps_the_sign_in(fake, store):
    save_account(store, expires_at=0)
    fake.token_replies.append(httpx.Response(200, text="<html>not what was expected</html>"))

    with pytest.raises(AIError) as raised:
        auth.get_access_token(store, fake.http())

    assert raised.value.kind == errors.UNAVAILABLE
    assert saved_account(store)["refresh_token"] == "refresh-0"


def test_no_internet_during_refresh_keeps_the_sign_in(store):
    def offline(request):
        raise httpx.ConnectError("no internet")

    save_account(store, expires_at=0)
    with pytest.raises(AIError) as raised:
        auth.get_access_token(store, httpx.Client(transport=httpx.MockTransport(offline)))
    assert raised.value.kind == errors.NETWORK
    assert saved_account(store)["refresh_token"] == "refresh-0"


def test_a_rejected_token_forces_a_refresh(fake, store):
    save_account(store)
    fake.token_replies.append(fake.tokens(2))
    assert auth.get_access_token(store, fake.http(), rejected_token="access-0") == "access-2"


def test_no_second_refresh_if_another_process_already_refreshed(fake, store):
    save_account(store, access_token="access-from-other-process")
    token = auth.get_access_token(store, fake.http(), rejected_token="access-0")
    assert token == "access-from-other-process"
    assert fake.requests == []


# --- Signing out ---


def test_sign_out_tells_openai_and_forgets_the_tokens(fake, store):
    save_account(store)
    assert auth.sign_out(store, fake.http(), sleep=lambda seconds: None) is True

    revoke = fake.sent_to(REVOKE_URL)[0]
    assert revoke["method"] == "POST"
    assert revoke["body"] == {
        "token": "refresh-0",
        "token_type_hint": "refresh_token",
        "client_id": ISSUED_CLIENT_ID,
    }
    account = saved_account(store)
    assert not auth.is_signed_in(account)
    assert not {"access_token", "refresh_token", "id_token"} & account.keys()
    assert account["client_id"] == ISSUED_CLIENT_ID and account["label"] == "fan@example.com"
    assert store.load()["host_id"] == "urn:uuid:test-host"


def test_sign_out_still_forgets_the_tokens_when_openai_cannot_be_reached(fake, store):
    save_account(store)
    fake.revoke_replies += [lambda: httpx.Response(503)] * 3
    waits = []

    assert auth.sign_out(store, fake.http(), sleep=waits.append) is False
    assert waits == [0, 1, 3]
    assert not auth.is_signed_in(saved_account(store))


def test_the_one_line_status_never_contains_a_token(store):
    account = save_account(store)
    for text in (auth.describe(account), auth.describe(None), auth.describe({"label": "x"})):
        assert "access-0" not in text and "refresh-0" not in text
    assert auth.describe(account) == "signed in as fan@example.com"
