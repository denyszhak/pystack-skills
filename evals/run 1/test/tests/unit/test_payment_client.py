from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status

from app.clients.payment import PaymentProviderRejectedException
from tests.doubles.payment import PaymentProviderMock


async def test_payment_client_collects_with_idempotency_key(
    payment_mock: PaymentProviderMock,
    payment_provider_client,
) -> None:
    payment_mock.set_collect_response({"payment_id": "pay_123", "status": "succeeded"})

    result = await payment_provider_client.collect_payment(
        invoice_id=uuid4(),
        amount=Decimal("120.00"),
        currency="USD",
        payment_method_token="pm_test",
        idempotency_key="idem-1",
    )

    assert result.succeeded is True
    assert result.provider_payment_id == "pay_123"
    assert payment_mock.requests[0].headers["Idempotency-Key"] == "idem-1"


async def test_payment_client_maps_provider_client_errors(
    payment_mock: PaymentProviderMock,
    payment_provider_client,
) -> None:
    payment_mock.set_collect_response(
        {"error": "bad request"},
        status_code=status.HTTP_400_BAD_REQUEST,
    )

    with pytest.raises(PaymentProviderRejectedException):
        await payment_provider_client.collect_payment(
            invoice_id=uuid4(),
            amount=Decimal("120.00"),
            currency="USD",
            payment_method_token="pm_test",
            idempotency_key="idem-1",
        )
