from dataclasses import dataclass


@dataclass(slots=True)
class ApplicationError(Exception):
    code: str
    message: str
    status_code: int = 400


@dataclass(slots=True)
class ExternalProviderError(Exception):
    provider: str
    message: str
    status_code: int | None = None

