# Architecture and philosophy

The locked decisions behind every skill in this repo. Read this once; the individual skills are the practical applications.

## Target

A **typed Python backend service** — FastAPI HTTP API, SQLAlchemy 2.0 async, Pydantic v2, external HTTP clients (`httpx`), Postgres. Not libraries, scripts, CLIs, or notebooks.

## Tooling

- **Package manager:** `uv`
- **Formatter / linter:** `ruff`
- **Type checker:** `ty` (Astral's new type checker, not `mypy`)
- **Test runner:** `pytest` + `pytest-asyncio`

The skills are mindful of `ty`'s current capabilities — they don't rely on `mypy`-only syntax tricks.

## Layout

```
app/
  setup.py              # provide_app(config) -> FastAPI; bottom: app = provide_app(AppConfig())
  config.py             # AppConfig + sub-Config (DBConfig, OpenAIConfig, ...)
  common/
    exceptions.py       # AppException, NotFoundException, ConflictException, ...
  db/                   # init_db_pool, close_db_pool, provide_async_db_pool
  deps/                 # FastAPI Depends providers, one file per layer
    db.py               # get_session
    clients.py          # get_X_client
    repos.py            # get_X_repo
    services.py         # get_X_service
  models/               # SQLAlchemy ORM (one file per aggregate)
  repos/                # repositories (one file per aggregate)
  services/             # use cases (file per use case area, e.g. checkout.py)
  clients/              # external HTTP clients (BaseHTTPClient + per-system)
  schemas/              # Pydantic in/out: *Get, *Create, *Update, *Command
  api/                  # FastAPI routers, middleware, exception handlers
    system.py
    exception_handlers.py
    middleware/
    v1/

tests/
  conftest.py
  fixtures/             # pytest_plugins split files
  doubles/              # httpx.MockTransport handlers
  unit/                 # pure tests, no DB or HTTP
  integration/          # real DB and/or external doubles
    repos/
    services/
  api/                  # full app via httpx
```

## Principles

1. **Cohesion.** Every transformation of a class lives on the class as `@classmethod` (inbound: `OrderGet.from_model(order)`), `@property` (derived value), or method (outbound: `cmd.to_new_order()`). No `utils.py`, no `converters.py`, no free transform functions.

2. **YAGNI.** Repos, clients, schemas, and services implement only what's called now. No speculative completeness. Promote a one-off into a class/method only when used 3+ times or when it carries structured fields beyond a `detail` string.

3. **Init at startup, inject through.** App-lifetime resources (db pool, http pools, clients) are created once in `lifespan` and stored on `app.state`. Per-request resources (session, repos, services) are built via FastAPI `Depends` providers in `app/deps/`.

4. **Domain behavior on the SA model.** No separate `domain/` directory by default. The `Order` SA model carries methods (`order.place()`, `order.cancel(reason=...)`) that enforce invariants via precondition checks at the top of each method. For invariant-dense systems that justify the boilerplate, opt into `python-pure-domain-layer`.

5. **Application services orchestrate; pure domain services decide.** A service method may load repos, call clients, own a transaction, and return a schema. When a business decision is pure, spans multiple objects, and no longer belongs cleanly on one aggregate/value object, extract a small sync domain service or policy. It takes domain data in, returns domain data out, and knows nothing about FastAPI, Pydantic, `AsyncSession`, repos, or HTTP clients.

6. **One use case → one transaction owner.** A top-level service command method wraps writes in `async with session.begin()`. SQLAlchemy commits on success and rolls back on exception. Routes don't begin or commit. Repos don't begin or commit. Composable collaborators assume the caller already owns the transaction.

7. **Errors are typed and routed by base class.** Domain exceptions inherit from `AppException → NotFoundException / ConflictException / InvalidInputException / NotAuthenticatedException / NotAuthorizedException`. One `@app.exception_handler` per HTTP code, registered in `setup.py`. Routes never `try/except`.

8. **Real DB in tests, protocol-level doubles for external systems.** Postgres runs locally or in compose. Each test session creates and drops a fresh DB. Outbound HTTP is faked via `httpx.MockTransport`; non-HTTP external systems get purpose-built fakes in `tests/doubles/`. Avoid `unittest.mock`, `pytest-mock`, and ORM mocks by default.

## Why these choices

- **No separate domain layer (default).** For integration- and orchestration-heavy services (LLM agents, CRM integrations, fulfillment), the boilerplate of `from_domain` / `to_domain` translation rarely pays off. SA models with behavior cover the same ground with half the code. Cosmic Python's separate-domain pattern is excellent when invariants are dense; otherwise it's tax.

- **No UoW abstraction by default.** `AsyncSession` *is* the unit of work. A UoW class on top of it is ceremony unless it owns extra behavior such as outbox/event collection or multi-entrypoint wiring. The session lives one request; the top-level service owns the transaction boundary; FastAPI cleans up the session lifecycle.

- **No domain-service layer by default.** Domain services and policies are extraction tools, not mandatory architecture. Start with aggregate/value-object methods and application services. Extract pure decision logic only when keeping it inside the application service would create a god class or make a business rule hard to test.

- **Cohesion over DRY.** Transformations on a class belong to that class as methods. Free `convert_X_to_Y()` functions split knowledge across files; methods keep it together. The trade-off is that the file that defines `OrderGet` imports the model — accept the slight coupling for the cohesion win.

- **YAGNI over completeness.** A "complete" repo with 12 methods nobody calls is dead code. Each method exists because a service needs it; new methods are added when new services demand them.

- **`*Exception` suffix.** Not the most stdlib-aligned choice (`*Error` is shorter), but it's a wash; consistency matters more than brevity.

## Naming conventions

| Concept | Suffix | Example |
|---|---|---|
| Response schema (GET) | `*Get` | `OrderGet`, `LeadGet` |
| Create input (POST CRUD) | `*Create` | `CustomerCreate` |
| Update input (PATCH CRUD) | `*Update` | `CustomerUpdate` |
| Use case input (verb) | `*Command` | `PlaceOrderCommand`, `CancelOrderCommand` |
| Exception | `*Exception` | `OrderNotFoundException`, `UniqueViolationException` |
| Inbound transform classmethod | `from_<source>` | `OrderGet.from_model(order)`, `LeadGet.from_openai(json)` |
| Outbound transform method | `to_<target>` | `cmd.to_new_order()`, `cmd.to_openai()` |
| Lifecycle init/close | `init_X_<resource>` / `cleanup_X_<resource>` | `init_openai_client(app, config)` |
| Depends provider | `get_<thing>` | `get_order_repo`, `get_checkout_service` |
| DB table name | singular | `order`, `order_line`, `customer` (matches the class) |
| URL path | plural | `/orders/{id}`, `/customers` (REST convention) |

## What this repo does *not* prescribe

- Whether your app talks to Kafka, RabbitMQ, Redis, or none of them. The `python-message-bus-outbox` skill is opt-in; the default skill set is silent on async messaging.
- Whether you use Alembic, plain SQL migrations, or something else. Skills assume Alembic is available because it's a common choice in the FastAPI + SA ecosystem, but they don't require it.
- Whether you write OpenAPI specs by hand or auto-generate from FastAPI. FastAPI's auto-generation is the assumed default.
- Whether you deploy on AWS, GCP, fly.io, or bare metal. The skills are deployment-neutral.
