# B2B Invoice Collection Service

Typed FastAPI service using Pydantic v2, SQLAlchemy 2.0 async, and Postgres.

## Run locally

```bash
docker compose up -d postgres
uv sync --dev
DB_HOST=localhost DB_PORT=5432 DB_USER=postgres DB_PASSWORD=postgres DB_NAME=invoices \
DB_AUTO_CREATE_TABLES=true uv run uvicorn app.setup:app --reload
```

The API is mounted under `/api/v1`. Health checks are available at `/health`.

## Main endpoints

- `POST /api/v1/customers`
- `POST /api/v1/invoices`
- `POST /api/v1/invoices/{invoice_id}/lines`
- `GET /api/v1/invoices/{invoice_id}/total`
- `POST /api/v1/invoices/{invoice_id}/issue`
- `POST /api/v1/invoices/{invoice_id}/payment-attempts`

Invoice issue and payment success events are written to the outbox table in the same
transaction as the invoice state change. The outbox dispatcher can then process those
events asynchronously and call the email provider.

## Tests

```bash
uv run pytest
```

Database-backed API tests require a dedicated Postgres database URL:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/invoices_test \
uv run pytest tests/api
```

