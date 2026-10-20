---
name: python-fastapi-sa-app-setup
description: |
  Use when scaffolding or modifying the structure of a FastAPI + SQLAlchemy backend
  service: `setup.py`, `config.py`, the `db/`, `deps/`, `common/`, `api/` directories,
  the FastAPI app factory, lifespan, middleware, exception handlers. Triggers on
  edits to those files; on a new repo that's becoming a FastAPI service; on user
  questions about app structure, dependency injection setup, lifespan, middleware,
  exception handling, project layout. Encodes: layered `app/` package, lifespan
  over event handlers, providers in `app/deps/`, exception handlers grouped by
  HTTP status, manual `app.state.*` setup in tests.
  Do NOT use for: scripts, CLIs, libraries, or codebases that aren't FastAPI services.
license: MIT
compatibility: Python 3.12+ services using FastAPI, Pydantic v2, SQLAlchemy 2.x (async), and PostgreSQL.
metadata:
  tier: service
---

# FastAPI + SQLAlchemy app setup

The skeleton of a typed Python backend service: where every file goes, what initializes when, and how requests flow from HTTP to database. Get this right once; the rest of the skills slot in cleanly.

## When to use this skill

- Starting a new FastAPI + SQLAlchemy service
- Refactoring an existing service toward a layered structure
- Adding a new client / middleware / exception handler to an existing service
- Wiring `app/deps/`, `app/db/`, or `app/api/` for the first time

## The canonical layout

```
app/
  setup.py              # provide_app(config) -> FastAPI factory + module-level app instance
  config.py             # AppConfig + sub-Config classes (DBConfig, OpenAIConfig, ...)
  common/
    exceptions.py       # AppException base + NotFoundException, ConflictException, ...
    logging.py          # configure_logging(env=...), contextvar correlation_id
    value_objects.py    # shared value objects (Money, EmailAddress) — see python-value-objects
  db/
    __init__.py         # init_db_pool, close_db_pool, provide_async_db_pool
  deps/
    db.py               # get_session
    clients.py          # get_X_client
    repos.py            # get_X_repo
    services.py         # get_X_service
  models/               # SA ORM (one file per aggregate)
  repos/                # repositories (one file per aggregate)
  services/             # use cases (one file per use case area: checkout.py, refunds.py)
  clients/              # external HTTP clients (BaseHTTPClient + per-system files)
  schemas/              # Pydantic in/out (one file per resource)
  api/
    system.py           # /health, /version
    exception_handlers.py
    middleware/
      __init__.py
      correlation.py    # CorrelationIDMiddleware
      logging.py        # logging_middleware
    v1/
      __init__.py       # provide_api_v1_router() factory
      order.py
      lead.py
```

`tests/` is adjacent to `app/`, not under it (see `python-test-pyramid`).

## Architecture — hexagonal-shaped, not strict

Inbound (`api/`, `consumers/`) and outbound (`clients/`, `repos/`) are separated at the root rather than nested under `adapters/inbound/` + `adapters/outbound/`. The directory names already communicate the role; nesting adds depth without semantic payoff and makes every import one level longer.

Two deliberate concessions to strict hexagonal:

1. **Domain behavior lives on the SA model.** `Order` inherits `Base` and carries methods (`place()`, `cancel()`, `@property total`). A framework-free domain layer requires `from_domain`/`to_domain` translation boilerplate for every aggregate — overkill for most services. Opt into `python-pure-domain-layer` when invariants are dense enough to justify it.

2. **Adapters are concrete classes by default.** `OrderRepo` and `StripeClient` aren't Protocol-typed. Defining a Port for a single-implementation adapter is ceremony without payoff. Promote to `Protocol` when 2+ implementations exist for the same role — see `LLMClient` in `python-external-client` for the canonical case.

You get the operational benefits of hexagonal (testable services, swappable adapters, framework-agnostic core logic) without the directory tax or the per-aggregate translation overhead.

## The rules

### 1. `provide_app(config)` factory + module-bottom `app` instance

`app/setup.py` exports `provide_app(config: AppConfig) -> FastAPI` as the canonical factory. The module also creates the actual ASGI `app` at the bottom, so `uvicorn app.setup:app` works.

```python
# app/setup.py — shape; full version in examples/setup.py
def provide_app(config: AppConfig) -> FastAPI:
    configure_logging(env=config.ENV)
    app = FastAPI(title=config.NAME, debug=config.DEBUG, lifespan=lifespan, ...)
    app.state.config = config
    _add_middleware(app, config)
    register_exception_handlers(app)           # from app/api/exception_handlers.py (rule 5)
    _include_routers(app)
    return app


app_config = AppConfig()
app = provide_app(app_config)         # ASGI handle at module level
```

`_add_middleware` and `_include_routers` are private helpers in the same module; `register_exception_handlers` lives with the handlers it registers. They keep `provide_app` short and let each concern be tested or extended independently.

The factory makes tests trivial: build a `FastAPI` with a custom `AppConfig`, set `app.state.*` manually for mocked deps.

### 2. Lifespan, not `add_event_handler`

`add_event_handler("startup"/"shutdown", ...)` is deprecated in modern FastAPI. Use `lifespan`.

```python
from contextlib import AsyncExitStack, asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: AppConfig = app.state.config
    async with AsyncExitStack() as stack:
        await init_db_pool(app, config.db)
        stack.push_async_callback(close_db_pool, app)

        await init_stripe_client(app, config.stripe)
        stack.push_async_callback(cleanup_stripe_client, app)

        await init_llm_client(app, config)              # provider chosen by config.llm.PROVIDER
        stack.push_async_callback(cleanup_llm_client, app)

        # ... each resource: init, then register its cleanup
        yield
```

**Why `AsyncExitStack` over a plain `try/finally`:** if any `init_X(...)` raises *after* an earlier init succeeded, a plain `try/finally` block doesn't run — the exception escaped before `yield`. Resources opened by the earlier inits leak.

`AsyncExitStack` registers each cleanup *after* its init succeeds. If the next init fails, the stack unwinds in reverse order — exactly the partial-failure recovery the naive pattern misses. If everything succeeds and the app runs to shutdown, the same stack runs all cleanups on exit. One pattern covers both paths.

Each `init_X_client` / `cleanup_X_client` lives in its client's own module (see `python-external-client`). They're plain `async def`, not factory-returning-closures — `lifespan` awaits them and registers the cleanup callback.

### 3. `AppConfig` aggregates sub-configs; env-prefix per sub-config

```python
# app/config.py — shape; full version in examples/config.py
BASE_SETTINGS_CONFIG = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class DBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", **BASE_SETTINGS_CONFIG)
    HOST: str = "localhost"
    NAME: str = "postgres"
    # ... DRIVER, PORT, USER, PASSWORD, POOL_SIZE, POOL_OVERFLOW, POOL_RECYCLE, ECHO

    @property
    def url(self) -> URL: ...                       # URL.create(...) — derived values are properties


class OpenAIConfig(BaseHTTPClientConfig):           # shares pool / retry / timeout knobs with other clients
    model_config = SettingsConfigDict(env_prefix="OPENAI_", **BASE_SETTINGS_CONFIG)
    API_KEY: str

    def auth_headers(self) -> dict[str, str]: ...


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", **BASE_SETTINGS_CONFIG)
    ENV: Literal["local", "test", "dev", "staging", "production"] = "local"
    CORS_ORIGINS: list[str] = []                    # exact browser origins; empty = no CORS (rule 6)
    db: DBConfig = Field(default_factory=DBConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    # ... NAME, VERSION, DEBUG, more sub-configs
```

Rules:
- One `*Config` class per external system or concern, each with its own `env_prefix`.
- Fields in SCREAMING_SNAKE_CASE.
- Derived values (DSNs, computed flags) as `@property`.
- `AppConfig` holds sub-configs as `Field(default_factory=...)` so they auto-load from env vars.
- HTTP client configs inherit `BaseHTTPClientConfig` for shared pool/retry knobs.

### 4. Providers live in `app/deps/`, one file per layer

Not co-located with the class — separated out for clarity and to keep class files focused on what the class *is*.

```python
# app/deps/db.py
from collections.abc import AsyncIterator
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
```

```python
# app/deps/clients.py
from fastapi import Request
from app.clients.llm import LLMClient
from app.clients.stripe import StripeClient


def get_stripe_client(request: Request) -> StripeClient:
    return request.app.state.stripe_client


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client
```

A provider returns the type the service depends on. For a single-provider client that's the concrete class (`StripeClient`). For a role with several interchangeable providers it's the role's `Protocol` (`LLMClient`, see `python-external-client` rule 4) — never the concrete `OpenAIClient`, or swapping `LLM_PROVIDER` would leave services typed against the wrong class.

```python
# app/deps/repos.py
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.deps.db import get_session
from app.repos.order import OrderRepo


def get_order_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderRepo:
    return OrderRepo(session)
```

```python
# app/deps/services.py
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.clients.llm import LLMClient
from app.clients.stripe import StripeClient
from app.deps.clients import get_llm_client, get_stripe_client
from app.deps.db import get_session
from app.deps.repos import get_order_repo
from app.repos.order import OrderRepo
from app.services.ai_assistant import AIAssistantService
from app.services.checkout import CheckoutService


def get_checkout_service(
    orders: Annotated[OrderRepo, Depends(get_order_repo)],
    stripe: Annotated[StripeClient, Depends(get_stripe_client)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CheckoutService:
    return CheckoutService(orders=orders, stripe=stripe, session=session)


def get_ai_assistant_service(
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> AIAssistantService:
    return AIAssistantService(llm=llm)
```

Layer dependency flow: routers import only from `deps/services`; `deps/services` builds on `deps/repos` + `deps/clients` + `deps/db`. Lower layers never import higher.

### 5. One status table for every exception base, in `api/exception_handlers.py`

The exception hierarchy lives in `app/common/exceptions.py`:

```python
# app/common/exceptions.py
class AppException(Exception): ...
class InvalidInputException(AppException): ...       # → 400
class NotAuthenticatedException(AppException): ...   # → 401
class NotAuthorizedException(AppException): ...      # → 403
class NotFoundException(AppException): ...           # → 404
class ConflictException(AppException): ...           # → 409
class UniqueViolationException(ConflictException): ...
class UpstreamException(AppException): ...           # → 502: a system we call failed
class UpstreamUnavailableException(UpstreamException): ...  # → 503: it's down or throttling us
class AsyncDBPoolProvisionException(AppException): ...
```

```python
# app/api/exception_handlers.py
from typing import Final

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.common.exceptions import (
    AppException,
    ConflictException,
    InvalidInputException,
    NotAuthenticatedException,
    NotAuthorizedException,
    NotFoundException,
    UpstreamException,
    UpstreamUnavailableException,
)


log = structlog.get_logger(__name__)

# One HTTP status per exception base. An exception gets the status of the first
# class in its MRO that appears here; anything else is a 500.
_STATUS_BY_EXCEPTION: Final[dict[type[AppException], int]] = {
    InvalidInputException: status.HTTP_400_BAD_REQUEST,
    NotAuthenticatedException: status.HTTP_401_UNAUTHORIZED,
    NotAuthorizedException: status.HTTP_403_FORBIDDEN,
    NotFoundException: status.HTTP_404_NOT_FOUND,
    ConflictException: status.HTTP_409_CONFLICT,
    UpstreamException: status.HTTP_502_BAD_GATEWAY,
    UpstreamUnavailableException: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _status_for(exc: AppException) -> int:
    return next(
        (_STATUS_BY_EXCEPTION[cls] for cls in type(exc).__mro__ if cls in _STATUS_BY_EXCEPTION),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    status_code = _status_for(exc)
    emit = log.error if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR else log.warning
    emit("request.failed", status=status_code, exception=type(exc).__name__, detail=str(exc))
    return JSONResponse(status_code=status_code, content={"errors": [str(exc)]})


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    emit = log.error if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR else log.warning
    emit("request.http_error", status=exc.status_code, detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"errors": [exc.detail]},
        headers=exc.headers,                       # keep WWW-Authenticate, Retry-After, ...
    )


async def request_validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Log where validation failed, not the offending input — it may contain PII.
    log.warning("request.invalid", locations=[error["loc"] for error in exc.errors()])
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"errors": jsonable_encoder(exc.errors())},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(AppException, app_exception_handler)
```

How it routes:

- **`AppException` is registered once.** Starlette sends each raised exception to the closest registered class in its MRO, so every domain exception reaches `app_exception_handler`. `_status_for` then walks the same MRO through the table: `OrderNotFoundException` → 404, and `OpenAIRateLimitedException` → 503 (it hits `UpstreamUnavailableException` before `UpstreamException`). Adding a base means adding one table line. You can't declare a base and forget to register its handler, which used to turn 400/401/403 into 500s.
- **Only `RequestValidationError` is a 422.** That is FastAPI rejecting the *request*. A bare pydantic `ValidationError` raised inside your own code — a schema that doesn't fit the model it's built from, or a provider payload that changed shape — is a server bug or an upstream failure. It isn't the caller's fault, so it is not registered here and surfaces as a 500. A client parsing a provider response translates it to that client's exception instead, which gives a 502.
- **`starlette.exceptions.HTTPException`, not FastAPI's.** FastAPI's `HTTPException` subclasses it, so this one handler also catches Starlette's own 404/405 for unknown routes, and every error response has the same `{"errors": [...]}` shape.

Concrete domain exceptions (e.g. `OrderNotFoundException`) inherit from these bases and live next to the model they describe (see `python-aggregate-and-repo`). Client exceptions inherit `UpstreamException` (see `python-external-client` rule 5).

### 6. Middleware in `api/middleware/`, registered in `provide_app`

```python
# app/api/middleware/correlation.py
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.common.logging import correlation_id_var


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_var.reset(token)
```

Register in `provide_app`:

```python
def _add_middleware(app: FastAPI, config: AppConfig) -> None:
    if config.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.CORS_ORIGINS,          # exact origins, never "*" with credentials
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.middleware("http")(logging_middleware)
    app.add_middleware(CorrelationIDMiddleware)
```

Note: middleware execution order is *reverse* of registration. `CorrelationIDMiddleware` runs first (sets the contextvar) so `logging_middleware` can read it.

**CORS is opt-in, with explicit origins.** `allow_origins=["*"]` together with `allow_credentials=True` doesn't mean "public API". Starlette answers a cookie-carrying request by echoing back whatever `Origin` the browser sent, along with `Access-Control-Allow-Credentials: true`. Any website could then make authenticated requests to your API from a logged-in user's browser and read the responses. List the exact front-end origins in `APP_CORS_ORIGINS`, a JSON list such as `'["https://app.example.com"]'`. With none configured, no CORS middleware is added and browsers keep same-origin rules; a server-to-server API needs nothing more.

### 7. Routers under `api/`, versioned via subpackages

```python
# app/api/v1/__init__.py
from fastapi import APIRouter
from app.api.v1 import customer, lead, order


def provide_api_v1_router() -> APIRouter:
    router = APIRouter()
    router.include_router(order.router, prefix="/orders", tags=["orders"])
    router.include_router(lead.router, prefix="/leads", tags=["leads"])
    router.include_router(customer.router, prefix="/customers", tags=["customers"])
    return router
```

Each resource file is singular (`order.py`), defines a `router = APIRouter()`, and contains route handlers that import services from `app/deps/services.py`. URL prefixes are plural (`/orders`).

```python
# app/setup.py — include routers
def _include_routers(app: FastAPI) -> None:
    app.include_router(system.router)
    app.include_router(provide_api_v1_router(), prefix="/api/v1")
```

### 8. DB pool init with retry; sessionmaker on `app.state`

```python
# app/db/__init__.py — shape; full version in examples/db.py
async def provide_async_db_pool(
    config: DBConfig,
    *,
    max_retries: int = 3,
    retry_interval: float = 2.0,
) -> AsyncEngine:
    # Per attempt: create_async_engine(config.url, pool_pre_ping=True, ...) and run SELECT 1.
    # On failure: dispose that engine (don't leak one per attempt), sleep, retry; after
    # max_retries raise AsyncDBPoolProvisionException from the last error.
    ...


async def init_db_pool(app: FastAPI, config: DBConfig) -> None:
    pool = await provide_async_db_pool(config)
    app.state.db_pool = pool
    app.state.db_session_factory = async_sessionmaker(pool, expire_on_commit=False)


async def close_db_pool(app: FastAPI) -> None:
    if hasattr(app.state, "db_pool"):
        await app.state.db_pool.dispose()
```

Two non-obvious choices:
- **`pool_pre_ping=True`** — catches dead connections silently dropped by Postgres/LB. Tiny cost; eliminates a whole class of flakes.
- **`expire_on_commit=False`** on the sessionmaker — required by the cohesion methods that access SA attributes after commit (`OrderGet.from_model(order)` doesn't trigger lazy reload).

### 9. `setup.py` filename note

The entry file is `app/setup.py` — yes, the same name as setuptools' historical `setup.py`. The collision doesn't bite because this `setup.py` is *inside* a package, not at the project root; pip and setuptools never touch it. The file name is a deliberate signal: "this module sets up the app."

If you'd rather avoid the historical association, rename to `app/main.py` or `app/app.py`. The skill is naming-agnostic; just stay consistent within a repo.

## When to break these rules

- **Per-system `*Config`** — if all your config comes from a single source with no per-system envs, one `AppConfig` is fine. The split pays off once you have 4+ external systems.

## See also

- `python-external-client` — `init_X_client` / `cleanup_X_client` pattern
- `python-aggregate-and-repo` — what goes in `app/models/` and `app/repos/`
- `python-service-and-schema-cohesion` — what goes in `app/services/` and `app/schemas/`
- `python-structlog-logging` — `configure_logging`, `correlation_id_var`
- `python-test-pyramid` — how to test all of this
