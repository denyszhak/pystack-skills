from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Invoice, InvoiceStatus, PaymentAttempt


async def create_customer(client) -> str:
    response = await client.post(
        "/customers",
        json={"name": "Acme Corp", "email": "ap@acme.example"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def create_invoice(client) -> str:
    customer_id = await create_customer(client)
    response = await client.post(f"/customers/{customer_id}/invoices")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    return body["id"]


async def add_standard_line(client, invoice_id: str) -> dict:
    response = await client.post(
        f"/invoices/{invoice_id}/lines",
        json={
            "description": "Implementation work",
            "quantity": "2.00",
            "unit_price": "100.00",
            "tax_rate": "0.1000",
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_invoice_draft_line_items_and_total(api_client) -> None:
    client, _, _ = api_client
    invoice_id = await create_invoice(client)

    invoice = await add_standard_line(client, invoice_id)

    assert invoice["status"] == "draft"
    assert invoice["subtotal"] == "200.00"
    assert invoice["tax_total"] == "20.00"
    assert invoice["total"] == "220.00"
    assert invoice["lines"][0]["line_total"] == "220.00"

    total_response = await client.get(f"/invoices/{invoice_id}/total")
    assert total_response.status_code == 200
    assert total_response.json() == {
        "subtotal": "200.00",
        "tax_total": "20.00",
        "total": "220.00",
    }


async def test_cannot_issue_empty_invoice(api_client) -> None:
    client, _, _ = api_client
    invoice_id = await create_invoice(client)

    response = await client.post(f"/invoices/{invoice_id}/issue")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "empty_invoice"


async def test_issuing_invoice_sends_email_records_event_and_locks_lines(
    api_client,
    db_session: AsyncSession,
) -> None:
    client, _, email_provider = api_client
    invoice_id = await create_invoice(client)
    await add_standard_line(client, invoice_id)

    issue_response = await client.post(f"/invoices/{invoice_id}/issue")

    assert issue_response.status_code == 200
    assert issue_response.json()["status"] == "issued"
    assert len(email_provider.calls) == 1

    events = (await db_session.scalars(select(Event))).all()
    assert [event.type for event in events] == ["invoice.issued"]

    line_response = await client.post(
        f"/invoices/{invoice_id}/lines",
        json={
            "description": "Late change",
            "quantity": "1.00",
            "unit_price": "1.00",
            "tax_rate": "0.0000",
        },
    )
    assert line_response.status_code == 409
    assert line_response.json()["error"]["code"] == "invoice_not_draft"


async def test_collect_payment_is_idempotent_and_marks_invoice_paid(
    api_client,
    db_session: AsyncSession,
) -> None:
    client, payment_provider, _ = api_client
    invoice_id = await create_invoice(client)
    await add_standard_line(client, invoice_id)
    await client.post(f"/invoices/{invoice_id}/issue")

    first_response = await client.post(
        f"/invoices/{invoice_id}/payment-attempts",
        headers={"Idempotency-Key": "collect-001"},
        json={"payment_method_token": "pm_card_visa"},
    )
    second_response = await client.post(
        f"/invoices/{invoice_id}/payment-attempts",
        headers={"Idempotency-Key": "collect-001"},
        json={"payment_method_token": "pm_card_visa"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["id"] == second_response.json()["id"]
    assert first_response.json()["status"] == "succeeded"
    assert first_response.json()["invoice_status"] == "paid"
    assert len(payment_provider.calls) == 1

    invoice = await db_session.get(Invoice, uuid.UUID(invoice_id))
    assert invoice is not None
    assert invoice.status == InvoiceStatus.PAID

    events = (await db_session.scalars(select(Event).order_by(Event.created_at))).all()
    assert [event.type for event in events] == ["invoice.issued", "invoice.paid"]

    new_key_response = await client.post(
        f"/invoices/{invoice_id}/payment-attempts",
        headers={"Idempotency-Key": "collect-002"},
        json={"payment_method_token": "pm_card_visa"},
    )
    assert new_key_response.status_code == 409
    assert new_key_response.json()["error"]["code"] == "invoice_already_paid"


async def test_payment_provider_errors_become_application_errors(
    api_client,
    db_session: AsyncSession,
) -> None:
    client, payment_provider, _ = api_client
    invoice_id = await create_invoice(client)
    await add_standard_line(client, invoice_id)
    await client.post(f"/invoices/{invoice_id}/issue")
    payment_provider.raise_error = True

    response = await client.post(
        f"/invoices/{invoice_id}/payment-attempts",
        headers={"Idempotency-Key": "collect-error"},
        json={"payment_method_token": "pm_card_visa"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "payment_provider_error"

    attempts = (await db_session.scalars(select(PaymentAttempt))).all()
    assert len(attempts) == 1
    assert attempts[0].status == "failed"
    assert attempts[0].error_code == "payment_provider_error"
