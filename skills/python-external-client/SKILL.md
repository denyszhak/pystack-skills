---
name: python-external-client
description: |
  Use when wrapping an external HTTP API (CRM, payment gateway, notification
  service, LLM provider, etc.) into a typed Python client class. Triggers on
  edits to `app/clients/`; on imports of `httpx`, `tenacity`; on user questions
  about HTTP clients, retries, mocking external APIs, `MockTransport`, client
  lifecycle. Encodes: `BaseHTTPClient` with `httpx.AsyncClient` + tenacity retry,
  per-client `init_X_client` / `cleanup_X_client` async functions, schemas know
  the wire shape via `from_X` / `to_X`, `httpx.MockTransport` for tests (no
  aiohttp dep), YAGNI on method surface.
  Do NOT use for: database access (use python-aggregate-and-repo); internal
  service-to-service in-process calls (just call the service).
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

    async def _request(self, method: HTTPMethod, url: str, **kwargs: Any) -> httpx.Response:
        # tenacity AsyncRetrying with stop_after_attempt(config.MAX_RETRIES) +
        # wait_exponential, retrying on TransportError and HTTPStatusError.
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
    MAX_RETRIES: int = 3

    def auth_headers(self) -> dict[str, str]:
        return {}                              # default: no auth

class OpenAIConfig(BaseHTTPClientConfig):
    API_KEY: str
    MODEL: str = "gpt-4o-mini"
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.API_KEY}"}
```

Subclasses inherit this and call `self._request(...)`. Retry policy reads from `self._config`. The `Literal` on `method` makes typos a type error, not a runtime 405.

**URL composition note.** httpx joins the `base_url` set at `AsyncClient` construction with relative paths passed to `request()`. The gotcha: `base_url="https://api.com/v1"` + path `"/foo"` resolves to `https://api.com/foo`, **not** `https://api.com/v1/foo`. Ensure base_url ends with `/` and paths don't start with `/` if you want path-preserving composition. For complex versioned paths, override `_request` to call `urljoin(self._config.BASE_URL, path)` explicitly.

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
                json={
                    "model": model or self._config.MODEL,
                    "messages": [m.model_dump() for m in messages],
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_401_UNAUTHORIZED:
                raise OpenAIAuthException() from exc
            if exc.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise OpenAIRateLimitedException() from exc
            raise
        return response.json()["choices"][0]["message"]["content"]
```

YAGNI: implement only the methods a service actually calls — `chat` is enough for most agent code. Add `embed`, `stream_chat`, or function-calling variants only when a service needs them. Domain exceptions (`OpenAIAuthException`, `OpenAIRateLimitedException`) live in the client file (cohesion); they inherit from the cross-cutting bases in `app/common/exceptions.py`.

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
        raise ValueError(f"unknown LLM provider: {config.llm.PROVIDER}")
    app.state.llm_client = build(config)


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

### 5. Domain exceptions inherit from `app/common/exceptions.py` bases

`OpenAIAuthException` extends `NotAuthenticatedException`, which the global handler maps to 401. The client raises domain words; the HTTP layer translates.

```python
class OpenAIAuthException(NotAuthenticatedException): ...
class OpenAIRateLimitedException(RateLimitedException): ...
```

Concrete exception classes live in the client file (cohesion). Bases live in `app/common/exceptions.py`.

### 6. Test with `httpx.MockTransport` — no aiohttp, no extra deps

```python
# tests/doubles/openai.py — shape; full version in examples/openai_mock.py
class OpenAIMock:
    """Stateful httpx.MockTransport handler — supports per-test response setup."""

    def set_chat_response(self, response: dict[str, Any], *, http_status: int = 200) -> None: ...

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            return httpx.Response(self._chat_status, json=self._chat_response)
        return httpx.Response(status.HTTP_404_NOT_FOUND, json={"detail": "unmocked endpoint"})
```

In tests:

```python
# tests/integration/services/test_ai_assistant.py
@pytest.fixture
async def openai_mock_and_client() -> tuple[OpenAIMock, OpenAIClient]:
    mock = OpenAIMock()
    http = httpx.AsyncClient(transport=httpx.MockTransport(mock), base_url="https://api.openai.test")
    config = OpenAIConfig(API_KEY="test", BASE_URL="https://api.openai.test", MAX_RETRIES=1)
    return mock, OpenAIClient(http=http, config=config)


async def test_chat_returns_assistant_reply(openai_mock_and_client):
    mock, client = openai_mock_and_client
    mock.set_chat_response({"choices": [{"message": {"role": "assistant", "content": "hello"}}]})

    answer = await client.chat([ChatMessage(role="user", content="hi")])

    assert answer == "hello"
```

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

### 8. Retry policy: connect errors + 5xx; idempotent operations only

The default in `BaseHTTPClient._request` retries on `httpx.TransportError` (connection errors) and `httpx.HTTPStatusError` (any 4xx/5xx after `raise_for_status()`).

This is too eager for POST endpoints that aren't idempotent (you could double-create things on retry). For non-idempotent endpoints, override:

```python
class StripeClient(BaseHTTPClient):
    async def charge(self, *, amount: Decimal, customer_id: UUID) -> ChargeGet:
        # don't retry charges — could double-charge
        response = await self._http.post(
            "/v1/charges",
            json={"amount": int(amount * 100), "customer_id": str(customer_id)},
            headers={"Idempotency-Key": str(uuid4())},
        )
        response.raise_for_status()
        return ChargeGet.from_stripe(response.json())
```

Or pass an idempotency key and let retries through (Stripe-style).

The conservative default is: retry only `GET`. Other verbs need per-method consideration.

### 9. Errors are domain exceptions, not raw `httpx` exceptions

```python
try:
    response = await self._request("POST", "/v1/chat/completions", json={...})
except httpx.HTTPStatusError as exc:
    if exc.response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise OpenAIAuthException() from exc
    if exc.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        raise OpenAIRateLimitedException() from exc
    raise
```

`httpx.HTTPStatusError` escapes the client only when there's no domain-specific handling. Otherwise translate at the boundary — the rest of the app deals in `OpenAIAuthException`, not `httpx.HTTPStatusError`.

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
