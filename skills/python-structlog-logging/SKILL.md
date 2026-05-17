---
name: python-structlog-logging
description: |
  Use when setting up logging or writing log calls in a Python service. Triggers
  on `import logging`, `import structlog`, edits to `app/common/logging.py` or
  `app/api/middleware/`, on user questions about logging, JSON logs, correlation
  IDs, structured logging, log levels. Encodes: structlog as the canonical
  logger, contextvar-based correlation_id propagation, env-driven console-vs-JSON
  renderer, stdlib bridge so library logs flow through structlog, key=value
  fields not f-strings.
  Do NOT use for: print-debugging in scripts; CLI output (use rich or stdout
  directly).
---

# Logging with structlog

Logs are the cheapest observability. With `structlog`, every log line is a structured event with key=value fields — searchable in Loki, Datadog, CloudWatch without regex acrobatics. Per-request context (correlation_id, user_id) propagates automatically via `contextvars`, so call sites stay focused on what just happened rather than on plumbing.

This skill encodes the canonical setup: structlog primary, stdlib bridge for libraries, env-driven console renderer for local dev and JSON for everywhere else.

## When to use this skill

- Setting up logging in a new service (`app/common/logging.py`, middleware)
- Writing log calls in any code (`log.info("order.placed", order_id=...)`)
- Adding fields to a per-request context (user_id, tenant_id)
- Diagnosing why library logs (SQLAlchemy, httpx) aren't appearing in the structured stream

## The rules

### 1. Configure structlog once, in `configure_logging(env=...)`

```python
# app/common/logging.py — shape; full version in examples/logging_setup.py
correlation_id_var: Final[contextvars.ContextVar[str]] = contextvars.ContextVar(
    "correlation_id", default="-",
)


def configure_logging(*, env: str) -> None:
    is_local = env == "local"
    renderer = (
        structlog.dev.ConsoleRenderer(colors=True) if is_local
        else structlog.processors.JSONRenderer()
    )
    # Configure structlog with: contextvars merge, correlation_id, ISO timestamp,
    # log level, exc_info, then the renderer.
    # Bridge stdlib logging through structlog.stdlib.ProcessorFormatter so
    # library logs (SQLAlchemy, httpx, uvicorn) join the structured stream.
    ...
```

Called once in `provide_app(config)`:

```python
def provide_app(config: AppConfig) -> FastAPI:
    configure_logging(env=config.ENV)
    ...
```

### 2. `correlation_id_var` is a module-level `ContextVar`

Why ContextVar: it's the only way to propagate per-request data through async code without passing it as an arg. Async tasks inherit the contextvar from their parent task automatically.

```python
import contextvars

correlation_id_var: Final[contextvars.ContextVar[str]] = contextvars.ContextVar(
    "correlation_id",
    default="-",
)
```

`default="-"` makes log lines outside any HTTP request still have a sensible value.

### 3. `CorrelationIDMiddleware` sets the contextvar per request

```python
# app/api/middleware/correlation.py — full version in examples/middleware.py
class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_var.reset(token)
```

The middleware:
- Reads `X-Correlation-ID` from upstream (or generates one)
- Sets the contextvar
- Echoes it back in the response header (so clients can correlate)
- Resets at the end so it doesn't leak between requests

Register it FIRST (so other middleware can read the value):

```python
app.middleware("http")(logging_middleware)
app.add_middleware(CorrelationIDMiddleware)
```

(Middleware order is the reverse of registration — `CorrelationIDMiddleware` runs first because added last.)

### 4. `logging_middleware` logs request start/end as structured events

```python
# app/api/middleware/logging.py
import time

import structlog
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger("app.request")


async def logging_middleware(request: Request, call_next) -> Response:
    started = time.perf_counter()
    log.info("request.start", method=request.method, path=request.url.path)

    response = await call_next(request)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "request.end",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    return response
```

`structlog.get_logger("app.request")` gives a named logger for the request stream — useful when you want to filter HTTP request logs separately from app logs in your aggregator.

### 5. Every log call uses key=value fields, never f-strings

```python
log = structlog.get_logger(__name__)

# good — fields are queryable
log.info("order.placed", order_id=order.id, total=order.total, currency=order.currency)
log.warning("payment.declined", order_id=order.id, reason=exc.reason)
log.error("client.error", client="openai", status=response.status_code)

# bad — opaque string, hard to filter/aggregate
log.info(f"Order {order.id} placed for {order.total} {order.currency}")
```

The event name (`"order.placed"`) is a *type* of log line; fields are the data on that line. This is the whole reason for using structlog — your log aggregator can group by event name, filter by field, aggregate counts. F-strings throw all that away.

Naming: lowercase, dot-separated, past tense for things that happened (`order.placed`, `payment.declined`). Imperative or noun for ongoing states (`request.start`, `db.query`).

### 6. Bind context with `log.bind(...)` to add fields across multiple lines

```python
async def place_order(cmd: PlaceOrderCommand) -> OrderGet:
    log = structlog.get_logger(__name__).bind(
        customer_id=cmd.customer_id,
        order_id=order.id,
    )
    log.info("checkout.start")
    await stripe.charge(...)
    log.info("checkout.charged")
    await orders.add(order)
    log.info("checkout.persisted")
```

Every log line from this bound logger includes `customer_id` and `order_id`. Cleaner than repeating those fields.

Alternative: `structlog.contextvars.bind_contextvars(customer_id=...)` binds at the contextvar level — propagates through all log calls in the request, including ones inside other functions. Use this in middleware for per-request fields like `user_id`.

### 7. Library logs (SQLAlchemy, httpx, uvicorn) flow through structlog automatically

The stdlib bridge in `configure_logging` does this. Without the bridge, library logs use their own formatter and bypass structlog — you lose half your observability.

After the bridge is configured, `sqlalchemy.engine` logs appear in the same JSON stream as your app logs, with the same correlation_id.

To control library log levels:

```python
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # noisy by default
```

Put these in `configure_logging` after the bridge is set up.

### 8. JSON renderer in prod, ConsoleRenderer in local

```python
if env == "local":
    renderer = structlog.dev.ConsoleRenderer(colors=True)
else:
    renderer = structlog.processors.JSONRenderer()
```

`ConsoleRenderer` gives colored, multi-line, human-readable output for development. `JSONRenderer` gives one-line JSON for production log shippers (Vector, Fluentd, etc.).

`env` is `AppConfig.ENV: Literal["local", "dev", "staging", "production"]`. Default `"local"` means the dev experience is good out of the box; CI and prod set it explicitly.

### 9. Don't log secrets, full request bodies, or PII

```python
# bad
log.info("user.login", email=user.email, password=password)
log.info("api.request", body=request_body)        # may contain PII

# good
log.info("user.login", user_id=user.id)
log.info("api.request", body_size=len(request_body))
```

If a field might be sensitive, hash it (`sha256(email).hexdigest()`) or omit. Once a secret hits your log aggregator, it's there forever. There's no `redact` command on a log shipper.

### 10. Don't log inside hot loops

```python
# bad — millions of log lines, all useless individually
for item in big_list:
    log.info("processing.item", item_id=item.id)
    process(item)

# good — summarize
log.info("processing.start", count=len(big_list))
processed = 0
for item in big_list:
    process(item)
    processed += 1
log.info("processing.done", count=processed)
```

Log boundaries (start/end of a batch, errors), not individual items. Log shippers charge per byte; structured logs are still bytes.

## When to break these rules

- **structlog dep** — for a one-file script, stdlib `logging` is fine; structlog is overkill. Promote to structlog when the script becomes a service.
- **JSON in prod** — if your log aggregator only accepts a specific format (logfmt, GELF), swap the renderer. structlog has renderers for most.
- **f-strings in log calls** — fine for one-off `log.debug(f"computed value: {x}")` during local debugging; remove before commit. In committed code, fields > f-strings.
- **Library log levels** — for actual debugging of a library bug, temporarily set its logger to DEBUG.

## See also

- `python-fastapi-sa-app-setup` — `configure_logging(env=config.ENV)` is called in `provide_app`
- `python-typing-idioms` — `Final`, `ContextVar`
