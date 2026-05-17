---
name: python-test-pyramid
description: |
  Use when writing or organizing tests for a FastAPI + SQLAlchemy backend service.
  Triggers on edits to `tests/`, `conftest.py`, files in `tests/fixtures/`,
  `tests/doubles/`, `tests/unit/`, `tests/integration/`, `tests/api/`; on imports of
  `pytest_asyncio`, `httpx.ASGITransport`, `httpx.MockTransport`; on user
  questions about test fixtures, real-DB tests, external doubles, test
  layout, pytest setup. Encodes: real Postgres (no testcontainers), session-
  scoped DB + app, function-scoped session + client, ASGITransport, manual
  app.state setup in fixtures, httpx.MockTransport for external clients, no
  unittest.mock / pytest-mock, no factory libs, unit/integration/api split.
  Do NOT use for: testing libraries, scripts, or non-FastAPI Python.
---

# Test pyramid for FastAPI + SQLAlchemy

The testing strategy for an opinionated FastAPI + SQLAlchemy service. The core trade-off: **real Postgres, protocol-level doubles for external systems**. The DB is the part most likely to surprise you in production (constraints, transactions, types); external systems are where you want speed and determinism.

This skill encodes the canonical conftest, fixture organization, and test layout.

## When to use this skill

- Setting up `tests/conftest.py` and fixtures for a new service
- Adding a new test for a service, repo, route, or client
- Restructuring an existing test suite into unit / integration
- Diagnosing flaky tests, missing fixture wiring, or session lifetime issues

## The layout

```
tests/
  conftest.py           # session-scoped: settings, db setup, app, db_pool. function-scoped: session, client.
  fixtures/             # split fixture modules (pytest_plugins)
    models.py
    services.py
    clients.py
    repos.py
  doubles/              # httpx.MockTransport handlers (one class per external client)
    openai.py
    stripe.py
  unit/                 # no DB, no HTTP — fast
    schemas/            # cohesion methods (from_X, to_X)
    common/             # exceptions, utilities, value objects
  integration/          # real DB and/or external doubles
    repos/              # exercises real DB
    services/           # real DB + fake clients
  api/                  # full app via httpx ASGITransport
```

## The rules

### 1. `conftest.py` at `tests/` root, fixtures split by topic via `pytest_plugins`

```python
# tests/conftest.py — shape; full version in examples/conftest.py
pytest_plugins = [
    "tests.fixtures.models",
    "tests.fixtures.services",
    "tests.fixtures.clients",
    "tests.fixtures.repos",
]

@pytest.fixture(scope="session")
def config() -> AppConfig:
    return AppConfig()
```

Splitting fixtures into `tests/fixtures/*.py` keeps `conftest.py` short and lets you find a fixture by topic.

### 2. Real Postgres, set up once per test session

```python
@pytest.fixture(scope="session")
def setup_database(config: AppConfig) -> Iterator[None]:
    # Connect to admin DB (sync) → DROP IF EXISTS → CREATE DATABASE → run Alembic to head.
    # On teardown: terminate connections, DROP DATABASE.
    bootstrap_url = config.db.sync_url().set(database="postgres")
    engine = create_engine(bootstrap_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    ...
```

- Use `config.db.sync_url()` to get a sync URL (Alembic + admin connections need sync)
- Connect to the `postgres` admin DB via `.set(database="postgres")` — no string-replace needed
- `DROP DATABASE IF EXISTS` to clean up any leftover, then `CREATE DATABASE` fresh
- Run Alembic migrations to head (Alembic gets `config.db.sync_url()` too)
- Test session runs against this DB; teardown drops again

**No testcontainers.** Assume a Postgres is reachable (docker-compose, local install, RDS).

### 3. Session-scoped `app` fixture, manual `app.state` setup

```python
@pytest_asyncio.fixture(scope="session")
async def app(config: AppConfig, setup_database: None, openai_client, ...) -> FastAPI:
    app = provide_app(config)
    # Skip lifespan; set app.state manually so fake clients stay fake.
    app.state.db_pool = await provide_async_db_pool(config.db)
    app.state.db_session_factory = async_sessionmaker(app.state.db_pool, expire_on_commit=False)
    app.state.openai_client = openai_client
    return app
```

`provide_app(config)` builds the FastAPI app but `lifespan` doesn't run in this fixture — so you set `app.state.*` manually, with fake clients in place of real ones. Precise control over what's real (DB) vs doubled (external systems).

If you need lifespan to run (testing the lifespan itself), use `asgi-lifespan.LifespanManager`. For everyday tests, manual `app.state` is simpler.

### 4. Function-scoped `client` and `session` fixtures

```python
@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c

@pytest_asyncio.fixture
async def session(app: FastAPI) -> AsyncSession:
    async with AsyncSession(app.state.db_pool, expire_on_commit=False) as s:
        yield s
```

- `client` — function-scoped because tests may set custom headers per case
- `session` — function-scoped because each test should get a fresh transactional state

Note: this is *not* the outer-transaction-rollback pattern. Each test reads/writes the same shared DB (the one set up at session scope). Test isolation comes from:
- Each test creating its data with unique UUIDs (`id=uuid4()`)
- Tests cleaning up only if they care (most don't)

This is faster than outer-transaction-rollback at the cost of tests not being fully order-independent. Acceptable if you discipline yourself to write tests that don't rely on starting from empty.

### 5. `httpx.AsyncClient` with `ASGITransport`, not `TestClient`

```python
from httpx import AsyncClient, ASGITransport

async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
    response = await client.post("/api/v1/orders", json={...})
```

Why not `TestClient`: it's synchronous (uses `anyio.from_thread` under the hood) and spawns its own event loop, which conflicts with `pytest_asyncio`'s loop and creates lifespan/fixture timing issues. `AsyncClient + ASGITransport` shares the test event loop — clean and predictable.

### 6. External HTTP via `httpx.MockTransport`, never real network

In `tests/fixtures/clients.py`:

```python
import pytest_asyncio
import httpx

from app.clients.openai import OpenAIClient
from app.config import OpenAIConfig
from tests.doubles.openai import OpenAIMock


@pytest_asyncio.fixture
async def openai_mock() -> OpenAIMock:
    return OpenAIMock()


@pytest_asyncio.fixture
async def openai_client(openai_mock: OpenAIMock) -> OpenAIClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(openai_mock),
        base_url="https://api.openai.test",
    )
    config = OpenAIConfig(WEBHOOK="test", BASE_URL="https://api.openai.test", MAX_RETRIES=1)
    return OpenAIClient(http=http, config=config)
```

The mock is a callable class (`tests/doubles/openai.py`); tests interact with it to set responses per-case:

```python
async def test_chat_returns_response(openai_mock, openai_client):
    openai_mock.set_chat_response({"choices": [{"message": {"content": "Hello!"}}]})

    answer = await openai_client.chat([ChatMessage(role="user", content="Hi")])

    assert answer == "Hello!"
```

### 7. No pytest mocks or unittest mocks

Don't use `unittest.mock.Mock`, `AsyncMock`, `patch`, the `mocker` fixture from `pytest-mock`, or monkeypatching as the default testing style.

- **Database**: use real Postgres. Never mock `AsyncSession`, SQLAlchemy result objects, or repos when testing persistence behavior.
- **External HTTP**: test clients against `httpx.MockTransport` / fake server handlers in `tests/doubles/`.
- **External non-HTTP systems**: write a small purpose-built fake in `tests/doubles/` that implements the same public methods your service calls.

```python
class FakePublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)
```

Purpose-built fakes are typed, readable, and assert against behavior. Generic mocks assert against implementation details and drift as call order changes.

### 8. Unit vs integration split — by what they touch, not by what they test

```
tests/
  unit/                 # no DB, no HTTP — milliseconds per test
    schemas/
      test_order_cohesion.py     # OrderGet.from_model, cmd.to_new_order
      test_chat_openai.py        # ChatGet.from_openai, cmd.to_openai
    common/
      test_exceptions.py
      test_value_objects.py      # Money invariants, EmailAddress validation

  integration/          # real DB and/or external doubles — tens of milliseconds
    repos/
      test_order_repo.py         # OrderRepo against real Postgres
    services/
      test_checkout_service.py   # service + real DB + fake OpenAI

  api/                  # full app through ASGITransport — fewer, broader tests
    test_orders_routes.py        # routes + deps + service + real DB + fake clients
```

"Service tests" aren't a category — they're either unit (no DB) or integration (with DB). In this style, services always use the DB, so they're always integration.

### 9. Test data: construct directly, no factory libraries

```python
async def test_place_order_creates_order(client: AsyncClient):
    cmd = PlaceOrderCommand(
        customer_id=uuid4(),
        currency="USD",
        lines=[
            OrderLineInput(product_id=uuid4(), quantity=2, unit_price=Decimal("10")),
        ],
    )

    response = await client.post("/api/v1/orders", json=cmd.model_dump(mode="json"))

    assert response.status_code == 201
    order = OrderGet.model_validate(response.json())
    assert order.total == Decimal("20")
```

`factory_boy` is solving a problem you don't have here — Pydantic's constructor, your `to_X` cohesion methods, and `model_dump`/`model_validate` are enough. If you find yourself building the same complex command in 5 tests, extract a `_make_place_order_cmd(...)` helper in the test file. Not a library.

### 10. Test file names mirror source files: `test_<source_filename>.py`

`app/repos/order.py` → `tests/integration/repos/test_order.py`
`app/services/checkout.py` → `tests/integration/services/test_checkout.py`
`app/api/v1/order.py` → `tests/api/test_order_routes.py`
`app/schemas/order.py` → `tests/unit/schemas/test_order_cohesion.py`

Mirror means "find the source file's tests fast." Pytest doesn't require this — it's a discipline.

### 11. `pytest-asyncio` mode = `auto`, mark only when overriding

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

This makes `async def test_...` work without `@pytest.mark.asyncio` on every test. Use the mark only to override scope (`@pytest.mark.asyncio(scope="session")` on a session-scoped async fixture).

## When to break these rules

- **Real Postgres** — if your CI doesn't have Postgres available and adding it would slow PRs significantly, testcontainers-python is a reasonable upgrade. The skill defaults to local Postgres for simplicity.
- **Outer-transaction-rollback** — if test pollution causes flakes, switch to the SAVEPOINT + rollback pattern. Slower per-test but order-independent.
- **`AsyncClient`** — for very simple route tests, `TestClient` is fine. Reach for `AsyncClient` when you hit a lifespan or async-fixture issue.
- **`pytest-asyncio` strict mode** — strict gives explicit per-test marking; auto is friendlier. Pick one and stay consistent.

## Anti-patterns this displaces

- **In-memory SQLite as a "fast Postgres"** — SQLite's dialect differs in constraint enforcement, type coercion, full-text search, JSON ops, and concurrency. Tests pass against SQLite, prod breaks against Postgres. Always real Postgres.
- **Mocking the ORM** — never `Mock(spec=AsyncSession)`. Mocking the ORM tests your understanding of SA, not your code. Real DB or no test.
- **Generic mocks** — no `Mock`, `AsyncMock`, `patch`, `mocker`, or monkeypatching by default. Use real dependencies where cheap, protocol-level fakes where not.
- **Shared mutable fixtures across tests** — every fixture should be either immutable (config) or re-created per test (session, client). Shared mutable state is how flakes are born.
- **End-to-end-only test suite** — if every test is full-app httpx-through-routes, your test suite is slow and your failures are unspecific. The pyramid: lots of unit + some integration + few API tests.

## See also

- `python-fastapi-sa-app-setup` — `provide_app(config)` factory used in `app` fixture
- `python-aggregate-and-repo` — what's being tested in `tests/integration/repos/`
- `python-service-and-schema-cohesion` — what's being tested in `tests/integration/services/` and `tests/unit/schemas/`
- `python-external-client` — `httpx.MockTransport` pattern for `tests/doubles/`
