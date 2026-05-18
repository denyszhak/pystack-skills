# PyStack Eval Runs

This directory stores generated code samples used to evaluate whether PyStack skills change the quality of AI-written Python backend code.

The goal is not to prove anything from one run. Run 1 is a smoke test: same task, same stack, one output without PyStack and one output with PyStack.

## Run 1

Directory layout:

```text
run 1/
  control/  # baseline: no PyStack skills requested
  test/     # treatment: PyStack skills explicitly requested
```

Both outputs implement the same B2B invoice collection service.

## Prompt

The control run used this prompt exactly:

```text
Build a small typed Python backend service for B2B invoice collection.

Use FastAPI, Pydantic v2, SQLAlchemy 2.0 async, and Postgres.

The service should support:

- creating a customer
- creating an invoice for a customer
- adding invoice line items while the invoice is draft
- calculating invoice total
- issuing an invoice
- recording a payment attempt
- marking an invoice as paid after payment succeeds
- exposing HTTP endpoints for those operations
- persisting customers, invoices, invoice lines, and payment attempts in Postgres
- calling an external payment provider HTTP API when collecting payment
- calling an external email provider HTTP API when an invoice is issued
- recording events so invoice issued / invoice paid work can be processed asynchronously
- tests for the main behavior

Domain rules:

- an invoice starts as draft
- line items can only be added while the invoice is draft
- issuing an empty invoice is not allowed
- once issued, an invoice cannot be modified
- a paid invoice cannot be paid again
- each line has description, quantity, unit price, and tax rate
- quantity must be positive
- unit price cannot be negative
- tax rate must be between 0 and 1
- invoice total is subtotal plus tax
- payment collection must be idempotent using an idempotency key
- external client errors should become application-level errors, not raw HTTP exceptions
```

The PyStack run used the same prompt plus this final instruction:

```text
Before implementing, load and follow the relevant installed PyStack skills:
python-fastapi-sa-app-setup, python-aggregate-and-repo,
python-service-and-schema-cohesion, python-external-client,
python-test-pyramid, python-message-bus-outbox, python-typing-idioms,
python-value-objects, python-structlog-logging, python-stdlib-idioms,
and python-antipatterns-cheatsheet.
```

## Checks

Commands for reproducing the checks from a fresh source-only checkout:

```bash
cd "run 1/test"
uv sync
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run pytest -q
RUFF_CACHE_DIR=/tmp/pystack-eval-test-ruff-cache uv run ruff check .

cd "../control"
uv sync
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run pytest -q
RUFF_CACHE_DIR=/tmp/pystack-eval-control-ruff-cache uv run ruff check .
```

Results:

| Condition | Tests | Ruff |
|---|---:|---|
| `test/` with PyStack | 7 passed, 2 skipped | passed |
| `control/` without PyStack | 5 passed | passed |

The two skipped PyStack tests are Postgres-backed tests skipped when `TEST_DATABASE_URL` is not set. The control run used in-memory SQLite for tests even though the prompt requested Postgres.

## First-Pass Comparison

Manual first-pass score:

| Condition | Score | Summary |
|---|---:|---|
| `test/` with PyStack | 8/10 | Stronger production shape. Better boundaries, domain model, client structure, outbox, and test posture. |
| `control/` without PyStack | 6/10 | Working small app, but already compressed into a service-script shape and weaker production parity. |

This is a qualitative score for one run, not a statistical result.

## What PyStack Improved

### Architecture Boundaries

The PyStack output separates the app into conventional backend layers:

- `app/api/`
- `app/models/`
- `app/repos/`
- `app/services/`
- `app/clients/`
- `app/events/`
- `app/outbox/`
- `app/deps/`

The control output is much flatter:

- `app/api.py`
- `app/models.py`
- `app/services.py`
- `app/clients.py`
- `app/totals.py`

The flat version is readable at this size, but it has fewer places for future behavior to land cleanly.

### Domain Rules

The PyStack output places core invoice behavior on the SQLAlchemy aggregate:

- `Invoice.add_line(...)`
- `Invoice.issue()`
- `Invoice.start_payment_attempt(...)`
- `Invoice.mark_paid()`
- `Invoice.total`

The control output keeps most business decisions in `InvoiceCollectionService`. That works initially, but it pushes the service toward becoming the place where every rule, query, side effect, and response mapping accumulates.

### Transactions

The PyStack output uses service-level transaction blocks:

```python
async with self._session.begin():
    ...
```

Repos flush/load data but do not own commits.

The control output manually commits throughout service methods:

```python
await self._session.commit()
```

That is not immediately broken, but it makes composition harder and increases the chance of partial side effects as the service grows.

### External Clients

The PyStack output has a reusable HTTP client base with:

- configured timeout
- connection limits
- explicit close lifecycle
- retry policy limited to transport errors and 5xx
- explicit opt-in for retrying non-idempotent requests
- typed provider errors

The control output creates a new `httpx.AsyncClient` per external call and has no retry policy.

### Events And Outbox

The PyStack output implements a real outbox shape:

- event dataclasses
- JSON-safe payload conversion
- `outbox_entries` table
- outbox repo
- dispatcher
- message bus
- email handlers

The control output records `Event` rows, but there is no dispatcher or processing path. It also sends the invoice-issued email synchronously inside the issue operation, before the final database commit.

### Tests

The PyStack output uses:

- API tests through `httpx.ASGITransport`
- real Postgres requirement for DB-backed tests
- `httpx.MockTransport` for external HTTP providers
- unit tests for invoice model behavior
- no generic mock/patch usage

The control output has useful API-level tests, but the DB fixture uses in-memory SQLite. That misses production-parity risks for UUIDs, enums, JSON, numeric behavior, constraints, and transaction semantics.

## Issues Found

### PyStack Output

The PyStack output is not perfect.

The main correctness issue is payment error handling. The service catches only `PaymentProviderException`, but the payment client can raise sibling exceptions such as `PaymentProviderRejectedException` and `PaymentProviderRateLimitedException`. Those errors still become API-level errors through the global exception handler, but the payment attempt may remain pending instead of being marked failed.

This is a local fix: catch the shared payment/client exception base in the payment collection flow and update the attempt state consistently.

### Control Output

The control output passes its own tests, but the tests do not enforce the requested production constraints.

Main issues:

- uses SQLite tests for a Postgres service
- no repository boundary
- no real asynchronous event processor
- synchronous email side effect inside invoice issuing
- manual commits across service methods
- most domain rules live in one service class
- creates external HTTP clients per request
- no retry policy

None of these makes the small generated app unusable immediately. The concern is iteration: adding partial payments, credit notes, reminders, webhooks, audit logs, and retryable outbox handling would likely concentrate more responsibilities in the same service file.

## Takeaway

Run 1 supports the working hypothesis:

> PyStack does not make the first draft perfect. It biases the first draft toward a codebase shape that is easier to review, fix, and extend.

The baseline produced green tests, but with production-shape gaps visible immediately. The PyStack output also had a bug, but the bug was localized inside a stronger architecture.

Future runs should measure this at scale with repeated tasks, blind scoring, static checks for critical failures, and follow-up feature iterations.
