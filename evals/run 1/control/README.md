# B2B Invoice Collection Service

Small typed FastAPI service for creating customers, drafting invoices, issuing them,
collecting payment idempotently, and recording invoice events.

## Stack

- FastAPI
- Pydantic v2
- SQLAlchemy 2.0 async
- Postgres via `asyncpg`
- `httpx` external payment and email clients

## Run locally

Start Postgres:

```bash
docker compose up -d postgres
```

Create tables and run the API:

```bash
CREATE_TABLES_ON_STARTUP=true uv run uvicorn app.main:app --reload
```

Default database URL:

```text
postgresql+asyncpg://postgres:postgres@localhost:5432/invoice_collection
```

## Main endpoints

- `POST /customers`
- `POST /customers/{customer_id}/invoices`
- `POST /invoices/{invoice_id}/lines`
- `GET /invoices/{invoice_id}`
- `GET /invoices/{invoice_id}/total`
- `POST /invoices/{invoice_id}/issue`
- `POST /invoices/{invoice_id}/payment-attempts` with `Idempotency-Key`

## Tests

```bash
uv run pytest
```

Tests use an async SQLite database with the same SQLAlchemy model metadata, while
the application configuration and Docker setup target Postgres.

