---
name: python-external-client
description: |
  Use when wrapping an external HTTP API (CRM, payment gateway, notification
  service, LLM provider, etc.) into a typed Python client class. Triggers on
  edits to `app/clients/`; on imports of `httpx`, `tenacity`; on user questions
  about HTTP clients, retries, mocking external APIs, `MockTransport`, client
  lifecycle. Encodes: `BaseHTTPClient` with `httpx.AsyncClient` + tenacity retry
  (transient failures, repeat-safe requests only), one exception base per client
  mapped to 502/503, per-client `init_X_client` / `cleanup_X_client`, schemas know
  the wire shape via `from_X` / `to_X`, `httpx.MockTransport` for tests (no
  aiohttp dep), YAGNI on method surface.
  Do NOT use for: database access (use python-aggregate-and-repo); internal
  service-to-service in-process calls (just call the service).
license: MIT
compatibility: Python 3.12+ services using FastAPI, httpx, and tenacity.
metadata:
  tier: service
---

# External HTTP client pattern

Every external system your service talks to — an LLM provider, Stripe, Slack, a CRM — gets its own typed Python wrapper. The wrapper is a thin class with one method per API call your service actually needs. Inside, it uses a shared `httpx.AsyncClient` pool that lives for the app's lifetime and is torn down at shutdown.

This skill encodes the canonical shape: a `BaseHTTPClient` for shared concerns (retry policy, error handling), per-system subclasses with domain-shaped methods, and `httpx.MockTransport` for fast in-process tests.

**Bonus payoff: provider decoupling.** When you have multiple providers for the same role (OpenAI / Anthropic / Gemini for LLM, SendGrid / Postmark / SES for email), define a `Protocol` for the role and let each concrete client satisfy it. Services depend on the Protocol; swapping providers is one env var.

## When to use this skill

- Adding a new external client (`app/clients/<name>.py`)
- Adding a method to an existing client because a service needs one new call
- Writing tests for a client (or a service that uses one)
- Choosing a retry policy

## The rules

### 1. `BaseHTTPClient` carries the retry policy and the http pool

```python
# app/clients/base.py — shape; full version in examples/base.py
type HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class BaseHTTPClient:
    def __init__(self, *, http: httpx.AsyncClient, config: BaseHTTPClientConfig) -> None:
        self._http = http
        self._config = config

    @classmethod
    def from_config(cls, config: BaseHTTPClientConfig) -> Self:
        http = httpx.AsyncClient(
            base_url=config.BASE_URL,
            timeout=config.TIMEOUT,
            limits=httpx.Limits(
                max_keepalive_connections=config.KEEP_ALIVE_CONNECTIONS,
                max_connections=config.MAX_CONNECTIONS,
            ),
            headers=config.auth_headers(),     # per-system seam, see config below
        )
        return cls(http=http, config=config)

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: HTTPMethod,
        url: str,
        *,
        retry: bool | None = None,      # None → retry only GET/HEAD/OPTIONS (rule 8)
        **kwargs: Any,
    ) -> httpx.Response:
        # tenacity AsyncRetrying: up to 1 + config.MAX_RETRIES attempts with
        # wait_exponential, retrying only transient failures (transport errors,
        # 429, 5xx) and only when the request is safe to repeat.
        ...
```

Two seams:
- **`from_config`** (classmethod, returns `Self`) is the production constructor. Builds the `httpx.AsyncClient` from uniform fields on `BaseHTTPClientConfig`. Subclasses inherit it automatically.
- **`__init__`** is the testable injection point. Tests pass a mock-transport `httpx.AsyncClient` here directly, bypassing `from_config`.

`auth_headers()` is the per-system seam — overridden on each config subclass:

```python
# app/config.py — auth_headers is the per-system seam
class BaseHTTPClientConfig(BaseSettings):
    BASE_URL: str = ""
    TIMEOUT: float = 30.0
    KEEP_ALIVE_CONNECTIONS: int = 10
    MAX_CONNECTIONS: int = 20
    MAX_RETRIES: int = 2                       # retries after the first attempt

    def auth_headers(self) -> dict[str, str]:
        return {}                              # default: no auth

class OpenAIConfig(BaseHTTPClientConfig):
    API_KEY: str
    MODEL: str = "gpt-4o-mini"
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.API_KEY}"}
```

Subclasses inherit this and call `self._request(...)`. Retry policy reads from `self._config`. The `Literal` on `method` makes typos a type error, not a runtime 405.

**URL composition.** httpx *appends* a relative request path to `base_url`'s path. It adds a trailing `/` to `base_url` and strips the leading `/` from the path, so `base_url="https://api.example.com/v1"` + `"/charges"` → `https://api.example.com/v1/charges`, with or without slashes on either side. That is not `urllib.parse.urljoin`, which would drop the `/v1`, so don't rebuild URLs with `urljoin`. Put a version prefix either in `BASE_URL` or in every path, and pick one per client. An absolute URL passed to `request()` ignores `base_url` entirely.

Why a base class — once you have 3+ clients all needing identical retry + pool semantics, the base class earns its keep. Without it, you copy-paste the same `tenacity` + `httpx` setup into every file.

### 2. Per-client subclass: one method per API call your service needs

```python
# app/clients/openai.py — shape; full version in examples/openai_client.py
class OpenAIClient(BaseHTTPClient):
    async def chat(self, messages: list[ChatMessage], *, model: str | None = None) -> str:
        try:
            response = await self._request(
                "POST",
                "/v1/chat/completions",
                retry=True,     # a completion has no side effects beyond cost: safe to repeat
                json={
                    "model": model or self._config.MODEL,
                    "messages": [m.model_dump() for m in messages],
                },
            )
        except httpx.HTTPError as exc:
            raise OpenAIException.from_http_error(exc) from exc
        return response.json()["choices"][0]["message"]["content"]
```

YAGNI: implement only the methods a service actually calls — `chat` is enough for most agent code. Add `embed`, `stream_chat`, or function-calling variants only when a service needs them. The client's exceptions (`OpenAIException` and its subclasses) live in the client file (cohesion); rule 5 covers their hierarchy.

### 3. Each client module exports `init_X_client` and `cleanup_X_client`

```python
async def init_openai_client(app: FastAPI, config: OpenAIConfig) -> None:
    app.state.llm_client = OpenAIClient.from_config(config)


async def cleanup_openai_client(app: FastAPI) -> None:
    if hasattr(app.state, "llm_client"):
        await app.state.llm_client.close()
```

`lifespan` in `app/setup.py` calls these. The `httpx.AsyncClient` is constructed once inside `from_config` (sets up the connection pool), stored on `app.state`, and reused for every request.

Note: the client lives on `app.state.llm_client` (the *role*), not `app.state.openai_client` (the *provider*). Services depend on the role; the provider is an implementation detail.

### 4. Provider decoupling — `LLMClient` Protocol with dispatch

When multiple providers can play the same role, define a `Protocol` for the role and let each concrete class satisfy it. Services depend on the `Protocol`, never on the concrete client.

```python
# app/clients/llm.py — Protocol + dispatch; full version in examples/llm_dispatch.py
class LLMClient(Protocol):
    async def chat(self, messages: list[ChatMessage], *, model: str | None = None) -> str: ...
    async def close(self) -> None: ...


_BUILDERS: dict[str, Callable[[AppConfig], LLMClient]] = {
    "openai":    lambda c: OpenAIClient.from_config(c.openai),
    "anthropic": lambda c: AnthropicClient.from_config(c.anthropic),
    # add more providers here — services don't change
}


async def init_llm_client(app: FastAPI, config: AppConfig) -> None:
    try:
        build = _BUILDERS[config.llm.PROVIDER]
    except KeyError:
        raise ValueError(f"unknown LLM provider: {config.llm.PROVIDER}") from None
    app.state.llm_client = build(config)


async def cleanup_llm_client(app: FastAPI) -> None:
    if hasattr(app.state, "llm_client"):
        await app.state.llm_client.close()


# app/deps/clients.py
def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client
```

Service-side:

```python
# app/services/ai_assistant.py
class AIAssistantService:
    def __init__(self, *, llm: LLMClient) -> None:
        self._llm = llm

    async def answer(self, question: str) -> str:
        return await self._llm.chat([
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content=question),
        ])
```

`AIAssistantService` doesn't know it's talking to OpenAI. Set `LLM_PROVIDER=anthropic` in the environment and the dispatch swaps `OpenAIClient` for `AnthropicClient`. The service is unchanged. The Protocol is the only contract that matters.

**When the Protocol earns its keep:** 2+ providers for the same role. For single-provider clients (Stripe, your CRM), skip the Protocol — just inject the concrete class directly.

### 5. One exception base per client; upstream failures map to 502/503

```python
# app/common/exceptions.py
class UpstreamException(AppException): ...                    # → 502: a system we call failed
class UpstreamUnavailableException(UpstreamException): ...    # → 503: it's down or throttling us; retry later


# app/clients/openai.py — full version in examples/openai_client.py
class OpenAIException(UpstreamException): ...                                          # → 502
class OpenAIAuthException(OpenAIException): ...                                        # → 502
class OpenAIUnavailableException(OpenAIException, UpstreamUnavailableException): ...   # → 503
class OpenAIRateLimitedException(OpenAIUnavailableException): ...                      # → 503
```

Two rules:

- **Every exception a client raises inherits that client's base.** A service that has to react to *any* OpenAI failure — mark a payment attempt failed, fall back to another provider — catches one class: `except OpenAIException`. Without the shared base, the service catches the one subclass its author thought of; a sibling (rejected, rate limited) slips past and leaves state half-updated.
- **Upstream failures surface as 502/503, never as the upstream's own status.** OpenAI answering 401 means *our* API key is wrong — the end user is authenticated fine. Mapping it to `NotAuthenticatedException` would tell the caller to log in again; a 502 tells them, and your alerting, that a dependency failed. Only "down, timing out, or throttling us" (`UpstreamUnavailableException`) becomes 503.

The exception handlers find the status by walking the exception's MRO (`python-fastapi-sa-app-setup` rule 5), so `OpenAIRateLimitedException` resolves to 503 through `UpstreamUnavailableException` before it reaches `UpstreamException`. Concrete classes live in the client file (cohesion); the bases live in `app/common/exceptions.py`.

### 6. Test with `httpx.MockTransport` — no aiohttp, no extra deps

```python
# tests/doubles/openai.py — shape; full version in examples/openai_mock.py
class OpenAIMock:
    requests: list[httpx.Request]            # every request it served, for assertions

    def reset(self) -> None: ...             # back to defaults — called between tests
    def set_chat_response(self, response: dict[str, Any], *, http_status: int = 200) -> None: ...
    def queue_chat_responses(self, *responses: tuple[int, dict[str, Any]]) -> None: ...  # e.g. 503 then 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            ...                              # serve the next configured response
        return httpx.Response(status.HTTP_404_NOT_FOUND, json={"detail": "unmocked endpoint"})
```

In tests:

```python
# tests/integration/services/test_ai_assistant.py
@pytest.fixture
async def openai_mock_and_client() -> tuple[OpenAIMock, OpenAIClient]:
    mock = OpenAIMock()
    http = httpx.AsyncClient(transport=httpx.MockTransport(mock), base_url="https://api.openai.test")
    config = OpenAIConfig(API_KEY="test", BASE_URL="https://api.openai.test", MAX_RETRIES=0)
    return mock, OpenAIClient(http=http, config=config)


async def test_chat_returns_assistant_reply(openai_mock_and_client):
    mock, client = openai_mock_and_client
    mock.set_chat_response({"choices": [{"message": {"role": "assistant", "content": "hello"}}]})

    answer = await client.chat([ChatMessage(role="user", content="hi")])

    assert answer == "hello"


async def test_rejected_api_key_is_an_upstream_failure(openai_mock_and_client):
    mock, client = openai_mock_and_client
    mock.set_chat_response({"error": "invalid key"}, http_status=401)

    with pytest.raises(OpenAIAuthException):
        await client.chat([ChatMessage(role="user", content="hi")])
```

`MAX_RETRIES=0` keeps failure tests fast: one attempt, no backoff sleeps. To test the retry policy itself, set it to 1 or more, queue `(503, ...)` then `(200, ...)` with `queue_chat_responses`, and assert on `len(mock.requests)`.

The mock is a callable class: `__call__(self, request: httpx.Request) -> httpx.Response`. `httpx.MockTransport(mock)` plugs it into the client. No HTTP socket, no port allocation, no aiohttp dep — fastest possible test loop.

### 7. Auth + headers in `init_X_client`, not on every request

```python
http = httpx.AsyncClient(
    base_url=config.BASE_URL,
    headers={"Authorization": f"Bearer {config.API_KEY}"},
    # ...
)
```

Per-request `headers={...}` adds noise to every method. Put the auth in `init`; per-request headers are for overrides.

For OAuth flows that need refresh, write an `httpx.Auth` subclass and pass it as `auth=` to the `AsyncClient`.

### 8. Retry policy: transient failures only, and only requests that are safe to repeat

`_request` retries only when **both** conditions hold:

- **The failure is transient:** `httpx.TransportError` (connect, read, timeout), 429, or 5xx. Other 4xx responses are never retried — a 400, 401, 404, or 422 fails the same way every time, so retrying only adds latency and load.
- **The request is safe to repeat:** by default that means `GET`, `HEAD`, and `OPTIONS` only. Any other method is sent once unless the client method passes `retry=True`. That flag is a per-endpoint claim *you* make: the request carries an idempotency key, or it has no side effects (an LLM completion costs money but changes nothing).

A timeout on a `POST` is the dangerous case: the server may already have done the work. That's why non-idempotent requests aren't retried by default.

```python
class StripeClient(BaseHTTPClient):
    async def charge(self, *, amount: Decimal, customer_id: UUID, idempotency_key: str) -> ChargeGet:
        response = await self._request(
            "POST",
            "/v1/charges",
            retry=True,                                   # safe: Stripe dedupes on the key
            headers={"Idempotency-Key": idempotency_key},
            json={"amount": int(amount * 100), "customer_id": str(customer_id)},
        )
        return ChargeGet.from_stripe(response.json())
```

The idempotency key comes from the caller and names the **business operation**, e.g. `f"order-{order.id}-charge"`. It stays the same across HTTP retries, across outbox redeliveries, and across a user double-clicking "pay". A fresh `uuid4()` per call protects nothing, because every retry then looks like a new charge.

### 9. Errors are domain exceptions, not raw `httpx` exceptions

```python
class OpenAIException(UpstreamException):
    @classmethod
    def from_http_error(cls, exc: httpx.HTTPError) -> OpenAIException:
        if not isinstance(exc, httpx.HTTPStatusError):
            return OpenAIUnavailableException(f"openai unreachable: {exc!r}")   # transport error
        match exc.response.status_code:
            case status.HTTP_401_UNAUTHORIZED | status.HTTP_403_FORBIDDEN:
                return OpenAIAuthException()
            case status.HTTP_429_TOO_MANY_REQUESTS:
                return OpenAIRateLimitedException()
            case code if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                return OpenAIUnavailableException(f"openai returned {code}")
            case code:
                return OpenAIException(f"openai returned {code}")


# every client method
try:
    response = await self._request("POST", "/v1/chat/completions", retry=True, json={...})
except httpx.HTTPError as exc:
    raise OpenAIException.from_http_error(exc) from exc
```

Catch `httpx.HTTPError` (the parent of both status and transport errors) and translate everything. The translation is one `from_http_error` classmethod on the client's base exception, so every method maps errors the same way. No `httpx` exception escapes the client; the rest of the app deals in `OpenAIException` and its subclasses.

### 10. `BaseHTTPClient.close()` is idempotent

Calling `close` on an already-closed client should not error. `httpx.AsyncClient.aclose()` is itself idempotent, so a thin `await self._http.aclose()` is enough.

This matters because tests may call cleanup multiple times via fixtures, and lifespan exception paths may double-cleanup.

## When to break these rules

- **`BaseHTTPClient`** — if you have one external client total, the base class is overhead. Drop it; put the `_request` helper directly on the one client. Add the base when you hit 3+.
- **Per-client init/cleanup** — fine to inline both in one `app/clients/__init__.py` if you have 2–3 clients. The per-file split shines at 5+.
- **`httpx.MockTransport`** — for clients that exercise real HTTP semantics (chunked transfer, multipart uploads, server-sent events), a local `aiohttp` server is more faithful. Use MockTransport as the default; switch when you find a test that MockTransport can't express.
- **Retry policy** — if your external API has its own per-endpoint retry guidance (Stripe, AWS), follow that instead.

## See also

- `python-fastapi-sa-app-setup` — `lifespan` calls `init_X_client` / `cleanup_X_client`
- `python-service-and-schema-cohesion` — services depend on clients via `Annotated[X, Depends(get_X_client)]`
- `python-test-pyramid` — testing clients and the services that use them
- `python-typing-idioms` — `Annotated`, `Protocol`
