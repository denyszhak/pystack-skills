from typing import ClassVar


class AppException(Exception):
    code: ClassVar[str] = "app_error"
    default_message: ClassVar[str] = "application error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class InvalidInputException(AppException):
    code = "invalid_input"
    default_message = "invalid input"


class NotFoundException(AppException):
    code = "not_found"
    default_message = "not found"


class ConflictException(AppException):
    code = "conflict"
    default_message = "conflict"


class UniqueViolationException(ConflictException):
    code = "unique_violation"
    default_message = "unique constraint violated"


class ExternalServiceException(AppException):
    code = "external_service_error"
    default_message = "external service error"


class RateLimitedException(ExternalServiceException):
    code = "rate_limited"
    default_message = "external service rate limited"
