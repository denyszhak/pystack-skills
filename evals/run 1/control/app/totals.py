from decimal import ROUND_HALF_UP, Decimal

from app.models import InvoiceLine
from app.schemas import InvoiceLineRead, InvoiceRead, InvoiceTotals

CENT = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_totals(lines: list[InvoiceLine]) -> InvoiceTotals:
    subtotal = sum((line.quantity * line.unit_price for line in lines), Decimal("0"))
    tax_total = sum(
        (line.quantity * line.unit_price * line.tax_rate for line in lines),
        Decimal("0"),
    )
    return InvoiceTotals(
        subtotal=quantize_money(subtotal),
        tax_total=quantize_money(tax_total),
        total=quantize_money(subtotal + tax_total),
    )


def line_to_read(line: InvoiceLine) -> InvoiceLineRead:
    line_subtotal = quantize_money(line.quantity * line.unit_price)
    tax_amount = quantize_money(line.quantity * line.unit_price * line.tax_rate)
    return InvoiceLineRead(
        id=line.id,
        invoice_id=line.invoice_id,
        description=line.description,
        quantity=line.quantity,
        unit_price=line.unit_price,
        tax_rate=line.tax_rate,
        line_subtotal=line_subtotal,
        tax_amount=tax_amount,
        line_total=quantize_money(line_subtotal + tax_amount),
        created_at=line.created_at,
    )


def invoice_to_read(invoice) -> InvoiceRead:
    lines = [line_to_read(line) for line in invoice.lines]
    totals = calculate_totals(invoice.lines)
    return InvoiceRead(
        id=invoice.id,
        customer_id=invoice.customer_id,
        status=invoice.status,
        created_at=invoice.created_at,
        issued_at=invoice.issued_at,
        paid_at=invoice.paid_at,
        lines=lines,
        subtotal=totals.subtotal,
        tax_total=totals.tax_total,
        total=totals.total,
    )

