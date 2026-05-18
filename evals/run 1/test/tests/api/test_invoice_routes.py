from decimal import Decimal

import httpx
from fastapi import FastAPI

from app.outbox.dispatcher import dispatch_once
from tests.doubles.email import EmailProviderMock
from tests.doubles.payment import PaymentProviderMock


async def test_invoice_collection_flow(
    app: FastAPI,
    client: httpx.AsyncClient,
    payment_mock: PaymentProviderMock,
    email_mock: EmailProviderMock,
) -> None:
    customer_response = await client.post(
        "/api/v1/customers",
        json={"name": "Acme Corp", "email": "ap@example.com"},
    )
    assert customer_response.status_code == 201
    customer_id = customer_response.json()["id"]

    invoice_response = await client.post(
        "/api/v1/invoices",
        json={"customer_id": customer_id, "currency": "USD"},
    )
    assert invoice_response.status_code == 201
    invoice_id = invoice_response.json()["id"]
    assert invoice_response.json()["status"] == "draft"

    line_response = await client.post(
        f"/api/v1/invoices/{invoice_id}/lines",
        json={
            "description": "Implementation",
            "quantity": 2,
            "unit_price": "100.00",
            "tax_rate": "0.20",
        },
    )
    assert line_response.status_code == 200
    assert Decimal(line_response.json()["total"]) == Decimal("240.00")

    total_response = await client.get(f"/api/v1/invoices/{invoice_id}/total")
    assert total_response.status_code == 200
    assert Decimal(total_response.json()["subtotal"]) == Decimal("200.00")
    assert Decimal(total_response.json()["tax"]) == Decimal("40.00")
    assert Decimal(total_response.json()["total"]) == Decimal("240.00")

    issued_response = await client.post(f"/api/v1/invoices/{invoice_id}/issue")
    assert issued_response.status_code == 200
    assert issued_response.json()["status"] == "issued"

    dispatched = await dispatch_once(
        session_factory=app.state.db_session_factory,
        bus=app.state.bus,
        batch_size=100,
    )
    assert dispatched == 1
    assert "/emails/invoice-issued" in email_mock.sent_paths

    payment_mock.set_collect_response({"payment_id": "pay_123", "status": "succeeded"})
    payment_response = await client.post(
        f"/api/v1/invoices/{invoice_id}/payment-attempts",
        json={"idempotency_key": "idem-1", "payment_method_token": "pm_test"},
    )
    assert payment_response.status_code == 200
    body = payment_response.json()
    assert body["invoice"]["status"] == "paid"
    assert body["payment_attempt"]["status"] == "succeeded"

    repeat_response = await client.post(
        f"/api/v1/invoices/{invoice_id}/payment-attempts",
        json={"idempotency_key": "idem-1", "payment_method_token": "pm_test"},
    )
    assert repeat_response.status_code == 200
    assert payment_mock.collect_count == 1

    dispatched = await dispatch_once(
        session_factory=app.state.db_session_factory,
        bus=app.state.bus,
        batch_size=100,
    )
    assert dispatched == 1
    assert "/emails/invoice-paid" in email_mock.sent_paths


async def test_invoice_rejects_line_after_issue(client: httpx.AsyncClient) -> None:
    customer_response = await client.post(
        "/api/v1/customers",
        json={"name": "Beta LLC", "email": "ap@beta.example"},
    )
    customer_id = customer_response.json()["id"]
    invoice_response = await client.post(
        "/api/v1/invoices",
        json={"customer_id": customer_id, "currency": "USD"},
    )
    invoice_id = invoice_response.json()["id"]
    await client.post(
        f"/api/v1/invoices/{invoice_id}/lines",
        json={
            "description": "Implementation",
            "quantity": 1,
            "unit_price": "100.00",
            "tax_rate": "0.20",
        },
    )
    await client.post(f"/api/v1/invoices/{invoice_id}/issue")

    response = await client.post(
        f"/api/v1/invoices/{invoice_id}/lines",
        json={
            "description": "Extra",
            "quantity": 1,
            "unit_price": "25.00",
            "tax_rate": "0.20",
        },
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "invoice_not_draft"
