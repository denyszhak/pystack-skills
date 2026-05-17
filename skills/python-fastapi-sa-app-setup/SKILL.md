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
    _add_middleware(app)
    _register_exception_handlers(app)
    _include_routers(app)
    return app


app_config = AppConfig()
app = provide_app(app_config)         # ASGI handle at module level
```

`_add_middleware`, `_register_exception_handlers`, `_include_routers` are private helpers in the same module. They keep `provide_app` short and let each concern be tested or extended independently.

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

        await init_openai_client(app, config.openai)
        stack.push_async_callback(cleanup_openai_client, app)

        # ... each resource: init, then register its cleanup
        yield
```

**Why `AsyncExitStack` over a plain `try/finally`:** if any `init_X(...)` raises *after* an earlier init succeeded, a plain `try/finally` block doesn't run — the exception escaped before `yield`. Resources opened by the earlier inits leak.

`AsyncExitStack` registers each cleanup *after* its init succeeds. If the next init fails, the stack unwinds in reverse order — exactly the partial-failure recovery the naive pattern misses. If everything succeeds and the app runs to shutdown, the same stack runs all cleanups on exit. One pattern covers both paths.

Each `init_X_client` / `cleanup_X_client` lives in its client's own module (see `python-external-client`). They're plain `async def`, not factory-returning-closures — `lifespan` awaits them and registers the cleanup callback.

### 3. `AppConfig` aggregates sub-configs; env-prefix per sub-config

```python
# app/config.py
import os
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


class BaseHTTPClientConfig(BaseSettings):
    BASE_URL: str = ""
    KEEP_ALIVE_CONNECTIONS: int = 10
    MAX_CONNECTIONS: int = 20
    MAX_RETRIES: int = 3
    TIMEOUT: float = 30.0

    def auth_headers(self) -> dict[str, str]:
        return {}                                   # subclasses override per system


class DBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", **BASE_SETTINGS_CONFIG)
    DRIVER: str = "postgresql+asyncpg"           # async driver by default
    HOST: str = "localhost"
    PORT: int = 5432
    USER: str = "postgres"
    PASSWORD: str = "password"
    NAME: str = "postgres"
    POOL_SIZE: int = 5
    POOL_OVERFLOW: int = 10
    POOL_RECYCLE: int = 3600
    ECHO: bool = False

    @property
    def url(self) -> URL:
        return URL.create(
            drivername=self.DRIVER,
            username=self.USER,
            password=self.PASSWORD,
            host=self.HOST,
            port=self.PORT,
            database=self.NAME,
        )

    def sync_url(self, driver: str = "postgresql") -> URL:
        return self.url.set(drivername=driver)   # for Alembic + test bootstrap

    @property
    def PATH(self) -> str:
        return f"{self.HOST}:{self.PORT}/{self.NAME}"


class OpenAIConfig(BaseHTTPClientConfig):
    model_config = SettingsConfigDict(env_prefix="OPENAI_", **BASE_SETTINGS_CONFIG)
    BASE_URL: str = "https://api.openai.com"
    API_KEY: str
    MODEL: str = "gpt-4o-mini"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.API_KEY}"}


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", **BASE_SETTINGS_CONFIG)
    ENV: Literal["local", "dev", "staging", "production"] = "local"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    NAME: str = "My Service"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    db: DBConfig = Field(default_factory=DBConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    # ... more
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
from app.clients.openai import OpenAIClient


def get_openai_client(request: Request) -> OpenAIClient:
    return request.app.state.llm_client
```

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
from app.clients.openai import OpenAIClient
from app.deps.clients import get_openai_client
from app.deps.db import get_session
from app.deps.repos import get_order_repo
from app.repos.order import OrderRepo
from app.services.checkout import CheckoutService


def get_checkout_service(
    orders: Annotated[OrderRepo, Depends(get_order_repo)],
    llm: Annotated[OpenAIClient, Depends(get_openai_client)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CheckoutService:
    return CheckoutService(orders=orders, llm=llm, session=session)
```

Layer dependency flow: routers import only from `deps/services`; `deps/services` builds on `deps/repos` + `deps/clients` + `deps/db`. Lower layers never import higher.

### 5. Exception handlers grouped by HTTP status, one per file in `api/exception_handlers.py`

```python
# app/api/exception_handlers.py
import logging
from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from pydantic import ValidationError
from app.common.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    UniqueViolationException,
)


logger = logging.getLogger(__name__)


async def http_exception_handler(_: Request, exc: HTTPException) -> ORJSONResponse:
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error(f"internal error: status_code={exc.status_code}, detail={exc.detail}")
    else:
        logger.warning(f"client error: status_code={exc.status_code}, detail={exc.detail}")
    return ORJSONResponse(status_code=exc.status_code, content={"errors": [exc.detail]})


async def request_validation_exception_handler(
    _: Request,
    exc: RequestValidationError | ValidationError,
) -> ORJSONResponse:
    logger.warning(f"validation error: {exc.errors()}")
    return ORJSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"errors": list(exc.errors())},
    )


async def not_found_exception_handler(_: Request, exc: NotFoundException) -> ORJSONResponse:
    logger.warning(f"not found: {exc}")
    return ORJSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"errors": [str(exc)]},
    )


async def conflict_exception_handler(_: Request, exc: ConflictException) -> ORJSONResponse:
    logger.warning(f"conflict: {exc}")
    return ORJSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"errors": [str(exc)]},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(ValidationError, request_validation_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(NotFoundException, not_found_exception_handler)
    app.add_exception_handler(ConflictException, conflict_exception_handler)
```

The exception hierarchy lives in `app/common/exceptions.py`:

```python
# app/common/exceptions.py
class AppException(Exception): ...
class NotFoundException(AppException): ...           # → 404
class ConflictException(AppException): ...           # → 409
class InvalidInputException(AppException): ...       # → 400
class NotAuthenticatedException(AppException): ...   # → 401
class NotAuthorizedException(AppException): ...      # → 403
class UniqueViolationException(ConflictException): ...
class AsyncDBPoolProvisionException(AppException): ...
```

Concrete domain exceptions (e.g. `OrderNotFoundException`) inherit from these and live next to the model they describe (see `python-aggregate-and-repo`).

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
def _add_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(logging_middleware)
    app.add_middleware(CorrelationIDMiddleware)
```

Note: middleware execution order is *reverse* of registration. `CorrelationIDMiddleware` runs first (sets the contextvar) so `logging_middleware` can read it.

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
# app/db/__init__.py
import asyncio
from collections.abc import AsyncIterator
from typing import Final
from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)

from app.common.exceptions import AsyncDBPoolProvisionException
from app.config import DBConfig

_HEALTHCHECK: Final = text("SELECT 1;")


async def provide_async_db_pool(
    config: DBConfig,
    *,
    max_retries: int = 3,
    retry_interval: float = 2.0,
) -> AsyncEngine:
    for attempt in range(max_retries + 1):
        try:
            pool = create_async_engine(
                config.ASYNC_DSN,
                echo=config.ECHO,
                pool_size=config.POOL_SIZE,
                max_overflow=config.POOL_OVERFLOW,
                pool_recycle=config.POOL_RECYCLE,
                pool_pre_ping=True,
            )
            async with pool.begin() as conn:
                await conn.execute(_HEALTHCHECK)
            return pool
        except Exception as exc:
            if attempt < max_retries:
                await asyncio.sleep(retry_interval)
                continue
            raise AsyncDBPoolProvisionException(
                f"failed to connect to db at {config.PATH}",
            ) from exc


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
