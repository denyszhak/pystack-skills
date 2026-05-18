from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.invoice import (
    EmptyInvoiceException,
    Invoice,
    InvoiceAlreadyPaidException,
    InvoiceNotDraftException,
    InvoiceStatus,
)


def test_invoice_starts_as_draft() -> None:
    invoice = Invoice.new(customer_id=uuid4(), currency="usd")

    assert invoice.status is InvoiceStatus.DRAFT
    assert invoice.currency == "USD"
    assert invoice.total == Decimal("0.00")


def test_invoice_total_is_subtotal_plus_tax() -> None:
    invoice = Invoice.new(customer_id=uuid4(), currency="USD")

    invoice.add_line(
        description="Implementation",
        quantity=2,
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("0.20"),
    )

    assert invoice.subtotal == Decimal("200.00")
    assert invoice.tax == Decimal("40.00")
    assert invoice.total == Decimal("240.00")


def test_empty_invoice_cannot_be_issued() -> None:
    invoice = Invoice.new(customer_id=uuid4(), currency="USD")

    with pytest.raises(EmptyInvoiceException):
        invoice.issue()


def test_issued_invoice_cannot_be_modified() -> None:
    invoice = Invoice.new(customer_id=uuid4(), currency="USD")
    invoice.add_line(
        description="Implementation",
        quantity=1,
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("0.20"),
    )
    invoice.issue()

    with pytest.raises(InvoiceNotDraftException):
        invoice.add_line(
            description="Extra work",
            quantity=1,
            unit_price=Decimal("50.00"),
            tax_rate=Decimal("0.20"),
        )


def test_paid_invoice_cannot_be_paid_again() -> None:
    invoice = Invoice.new(customer_id=uuid4(), currency="USD")
    invoice.add_line(
        description="Implementation",
        quantity=1,
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("0.20"),
    )
    invoice.issue()
    invoice.mark_paid()

    with pytest.raises(InvoiceAlreadyPaidException):
        invoice.mark_paid()
