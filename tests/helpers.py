"""A fake OpenAI and OpenRouter for the tests, so no test touches the internet."""

import json
import time
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from fantasy_king.ai import chatgpt_auth
from fantasy_king.ai.token_store import TokenStore
from fantasy_king.config import Settings

ISSUED_CLIENT_ID = "oaiapp_test_client"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
REVOKE_URL = "https://auth.openai.com/api/accounts/oauth/revoke"
RESPONSES_URL = "https://api.openai.com/v1/responses"
CHATGPT_MODELS_URL = "https://api.openai.com/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def sse(*events: dict) -> httpx.Response:
    """A streamed Responses API reply made of the given events."""
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def answer(text: str, output: list | None = None) -> httpx.Response:
    """A complete, successful streamed reply saying `text`."""
    halves = [text[: len(text) // 2], text[len(text) // 2 :]]
    deltas = [{"type": "response.output_text.delta", "delta": half} for half in halves]
    done = {"type": "response.completed", "response": {"id": "resp_1", "output": output or []}}
    return sse(*deltas, done)


def api_error(status: int, code: str | None = None, **extra) -> httpx.Response:
    body = {"error": {"code": code, "message": "details from the server", **extra}}
    return httpx.Response(status, json=body, headers={"x-request-id": "req_test_1"})


def chat_answer(text: str, annotations: list | None = None, searches: int = 0) -> httpx.Response:
    """A successful OpenRouter chat completion saying `text`."""
    message = {"role": "assistant", "content": text, "annotations": annotations or []}
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    if searches:
        usage["server_tool_use"] = {"web_search_requests": searches}
    return httpx.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 0,
            "model": "test/model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": usage,
        },
    )


def _next(replies: list) -> httpx.Response:
    """The next queued reply. A queued function is called, to build a fresh reply each time."""
    reply = replies.pop(0)
    return reply() if callable(reply) else reply


class FakeServers:
    """Stands in for auth.openai.com, api.openai.com, and openrouter.ai."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.requests = []  # every request received, as dicts
        self.token_replies = []  # replies for the token endpoint, used in order
        self.ai_replies = []  # replies for POST /v1/responses, used in order
        self.chat_replies = []  # replies for OpenRouter chat completions, used in order
        self.revoke_replies = []  # replies for revocation; an empty 200 once these run out
        self.models_reply = httpx.Response(200, json={"models": []})
        self.catalog_reply = httpx.Response(200, json={"data": []})
        self.nonce = ""  # the nonce the next ID token should carry

    # --- things the fake OpenAI hands out ---

    def signing_keys(self, key=None) -> dict:
        public = (key or self.key).public_key()
        entry = jwt.algorithms.RSAAlgorithm.to_jwk(public, as_dict=True)
        return {"keys": [{**entry, "kid": "test-key", "use": "sig", "alg": "RS256"}]}

    def id_token(self, key=None, **claims) -> str:
        now = int(time.time())
        payload = {
            "iss": chatgpt_auth.ISSUER,
            "aud": ISSUED_CLIENT_ID,
            "sub": "user-123",
            "email": "fan@example.com",
            "nonce": self.nonce,
            "iat": now,
            "exp": now + 600,
            **claims,
        }
        return jwt.encode(payload, key or self.key, algorithm="RS256", headers={"kid": "test-key"})

    def tokens(self, number: int = 1, scope: str = chatgpt_auth.SCOPES, **extra) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": f"access-{number}",
                "refresh_token": f"refresh-{number}",
                "id_token": extra.pop("id_token", None) or self.id_token(),
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": scope,
                **extra,
            },
        )

    # --- routing ---

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = request.content.decode()
        if "json" in request.headers.get("content-type", ""):
            body = json.loads(body)
        elif body:
            body = {name: values[0] for name, values in parse_qs(body).items()}
        self.requests.append(
            {
                "method": request.method,
                "url": url,
                "host": request.url.host,
                "auth": request.headers.get("authorization"),
                "body": body,
            }
        )
        if url == chatgpt_auth.DISCOVERY_URL:
            return httpx.Response(
                200,
                json={
                    "issuer": chatgpt_auth.ISSUER,
                    "jwks_uri": JWKS_URL,
                    "revocation_endpoint": REVOKE_URL,
                },
            )
        if url == JWKS_URL:
            return httpx.Response(200, json=self.signing_keys())
        if url == chatgpt_auth.TOKEN_URL:
            return _next(self.token_replies)
        if url == REVOKE_URL:
            return _next(self.revoke_replies) if self.revoke_replies else httpx.Response(200)
        if url == RESPONSES_URL:
            return _next(self.ai_replies)
        if url == CHATGPT_MODELS_URL:
            return self.models_reply
        if url == OPENROUTER_CHAT_URL:
            return _next(self.chat_replies)
        if url == OPENROUTER_MODELS_URL:
            return self.catalog_reply
        raise AssertionError(f"Unexpected request to {url}")

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def sent_to(self, url: str) -> list[dict]:
        return [request for request in self.requests if request["url"] == url]


def save_account(store: TokenStore, **changes) -> dict:
    """Put a signed-in account straight into the store, as if sign-in already happened."""
    account = {
        "sub": "user-123",
        "client_id": ISSUED_CLIENT_ID,
        "email": "fan@example.com",
        "label": "fan@example.com",
        "scope": chatgpt_auth.SCOPES,
        "plan_usage_enabled": True,
        "callback_path": chatgpt_auth.CALLBACK_PATH,
        "welcome_seen": True,
        "access_token": "access-0",
        "refresh_token": "refresh-0",
        "id_token": "saved-id-token",
        "expires_at": time.time() + 3600,
        "earliest_refresh_at": None,
        **changes,
    }
    store.save(
        {"host_id": "urn:uuid:test-host", "accounts": {"user-123": account}, "active": "user-123"}
    )
    return account


def saved_account(store: TokenStore) -> dict:
    return chatgpt_auth.active_account(store.load())


def make_settings(**changes) -> Settings:
    values = {
        "league_data_source": "sample",
        "ai_provider": "chatgpt",
        "chatgpt_model": "test-chatgpt-model",
        "openrouter_model": "test/openrouter-model",
        "openrouter_api_key": "test-key-not-real",
        **changes,
    }
    return Settings(**values)
