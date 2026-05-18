from fastapi import Request

from app.clients.email import EmailProviderClient
from app.clients.payment import PaymentProviderClient


def get_payment_provider_client(request: Request) -> PaymentProviderClient:
    return request.app.state.payment_provider_client


def get_email_provider_client(request: Request) -> EmailProviderClient:
    return request.app.state.email_provider_client
